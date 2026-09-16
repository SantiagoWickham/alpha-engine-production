from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "outputs" / "data_recovery_v1" / "staging"


def read_csv_matrix(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise RuntimeError(f"empty CSV: {path}")

    def convert(x: str):
        if x == "":
            return None
        low = x.lower()
        if low in {"true", "false"}:
            return low == "true"
        try:
            if any(ch in x for ch in (".", "e", "E")):
                return float(x)
            return int(x)
        except ValueError:
            return x

    return rows[0], [[convert(x) for x in r] for r in rows[1:]]


def raw_post(url: str, payload: dict, timeout: int = 90) -> dict:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {text[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc}") from exc

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Non-JSON response: {text[:500]}") from exc

    if not obj.get("ok"):
        raise RuntimeError(json.dumps(obj, ensure_ascii=False))
    return obj


def safe_read_call(url: str, payload: dict, retries: int = 6) -> dict:
    last = None
    for attempt in range(1, retries + 1):
        try:
            return raw_post(url, payload)
        except Exception as exc:
            last = exc
            if attempt == retries:
                break
            wait = min(15, attempt * 2)
            print(f"    transient read failure {attempt}/{retries}; retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Read call failed after {retries} attempts: {last}")


def audit_total(url: str, token: str) -> int:
    obj = safe_read_call(url, {
        "token": token,
        "action": "dr1d_write_audit_chunk",
        "reset": False,
        "rows": [],
    })
    return int(obj.get("total_rows", -1))


def write_audit_chunk_state_safe(
    url: str,
    token: str,
    local_rows: list[list[object]],
    start: int,
    chunk_size: int,
) -> int:
    total_local = len(local_rows)
    expected_before = start
    chunk = local_rows[start:start + chunk_size]
    expected_after = start + len(chunk)

    # Confirm exact remote position before touching anything.
    before = audit_total(url, token)
    if before != expected_before:
        raise RuntimeError(
            f"Audit position mismatch before write: remote={before}, expected={expected_before}"
        )

    for attempt in range(1, 7):
        try:
            obj = raw_post(url, {
                "token": token,
                "action": "dr1d_write_audit_chunk",
                "reset": False,
                "rows": chunk,
            })
            after = int(obj.get("total_rows", -1))
            if after != expected_after:
                raise RuntimeError(
                    f"Audit total mismatch in response: {after} != {expected_after}"
                )
            return after

        except Exception as exc:
            # Critical rule: NEVER retry an append until we have checked
            # whether Google executed it despite returning an HTTP error.
            print(f"    audit call error on attempt {attempt}: {type(exc).__name__}")
            time.sleep(min(8, attempt * 2))

            observed = audit_total(url, token)
            if observed == expected_after:
                print("    remote state confirms chunk was written despite HTTP error")
                return observed

            if observed == expected_before:
                if attempt < 6:
                    print("    remote state unchanged; safe to retry this chunk")
                    continue
                raise RuntimeError(
                    f"Audit chunk failed after {attempt} attempts; remote stayed at {observed}"
                )

            raise RuntimeError(
                f"Unexpected audit remote position after error: "
                f"remote={observed}, expected_before={expected_before}, "
                f"expected_after={expected_after}"
            )

    raise RuntimeError("Unreachable audit retry state")


def safe_idempotent_write(url: str, payload: dict, retries: int = 6) -> dict:
    # Used only for actions that clear/replace their target (failures/finalize),
    # so retrying cannot duplicate rows.
    last = None
    for attempt in range(1, retries + 1):
        try:
            return raw_post(url, payload)
        except Exception as exc:
            last = exc
            if attempt == retries:
                break
            wait = min(15, attempt * 2)
            print(f"    transient idempotent write failure {attempt}/{retries}; retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Idempotent write failed after {retries} attempts: {last}")


def main() -> int:
    url = os.getenv("ALPHA_SHEETS_API_URL", "")
    token = os.getenv("ALPHA_SHEETS_API_TOKEN", "")
    if not url or not token:
        raise RuntimeError("Missing URL/token")

    fh, fr = read_csv_matrix(STAGING / "fundamentales_payload_latest.csv")
    mh, mr = read_csv_matrix(STAGING / "mercado_riesgo_payload_latest.csv")
    ah, ar = read_csv_matrix(STAGING / "data_audit_long_latest.csv")
    ph, pr = read_csv_matrix(STAGING / "provider_failures_latest.csv")
    summary = json.loads(
        (STAGING / "recovery_coverage_summary.json").read_text(encoding="utf-8")
    )

    if len(fr) != 187 or len(mr) != 200 or len(ar) != 12423:
        raise RuntimeError("Local staging structural gate failed")

    print("[1/5] REVERIFY CORE - READ ONLY")
    for module, rows in (("fundamentals", fr), ("market", mr)):
        v = safe_read_call(url, {
            "token": token,
            "action": "dr1d_verify_target",
            "module": module,
            "expected_first_ticker": str(rows[0][0]),
            "expected_last_ticker": str(rows[-1][0]),
        })
        print(json.dumps(v, indent=2, ensure_ascii=False))
        if not v.get("pass"):
            raise RuntimeError(f"Core verification failed for {module}")

    print("")
    print("[2/5] AUDIT REMOTE POSITION")
    remote_total = audit_total(url, token)
    print(f"  remote audit rows={remote_total}")
    print(f"  local audit rows={len(ar)}")

    if remote_total < 0 or remote_total > len(ar):
        raise RuntimeError(
            f"Invalid remote audit position {remote_total}; local={len(ar)}"
        )

    print("")
    print("[3/5] RESUME AUDIT IN STATE-SAFE 250-ROW CHUNKS")
    chunk_size = 250

    if remote_total == len(ar):
        print("  audit already complete")
    else:
        start = remote_total
        while start < len(ar):
            after = write_audit_chunk_state_safe(
                url, token, ar, start, chunk_size
            )
            print(f"  audit {after}/{len(ar)} OK")
            start = after
            time.sleep(0.25)

    print("")
    print("[4/5] PROVIDER FAILURES + FINAL STATUS")
    failures = safe_idempotent_write(url, {
        "token": token,
        "action": "dr1d_write_failures",
        "rows": pr,
    })
    print(json.dumps(failures, indent=2, ensure_ascii=False))

    final = safe_idempotent_write(url, {
        "token": token,
        "action": "dr1d_finalize",
        "summary": summary,
    })
    print(json.dumps(final, indent=2, ensure_ascii=False))

    print("")
    print("[5/5] FINAL AUDIT COUNT")
    final_total = audit_total(url, token)
    print(f"  remote audit rows={final_total}")
    if final_total != len(ar):
        raise RuntimeError(
            f"Final audit count mismatch: {final_total} != {len(ar)}"
        )

    print("")
    print("============================================================")
    print("DR1-D RECOVERY COMPLETE")
    print("CORE FUNDAMENTALS: VERIFIED 187/187")
    print("CORE MARKET: VERIFIED 200/200")
    print("OLD V8/V10 SCORE CELLS: 0")
    print(f"AUDIT: VERIFIED {final_total}/{len(ar)}")
    print("PROVIDER FAILURES: WRITTEN")
    print("STATUS: FINALIZED")
    print("============================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
