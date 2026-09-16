from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone
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


def post_json(url: str, payload: dict, timeout: int = 90) -> dict:
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
        raise RuntimeError(f"HTTP {exc.code}: {text[:1000]}") from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc}") from exc

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Non-JSON response: {text[:1000]}") from exc

    if not obj.get("ok"):
        raise RuntimeError(json.dumps(obj, ensure_ascii=False))
    return obj


def load_all():
    fh, fr = read_csv_matrix(STAGING / "fundamentales_payload_latest.csv")
    mh, mr = read_csv_matrix(STAGING / "mercado_riesgo_payload_latest.csv")
    ah, ar = read_csv_matrix(STAGING / "data_audit_long_latest.csv")
    ph, pr = read_csv_matrix(STAGING / "provider_failures_latest.csv")
    summary = json.loads(
        (STAGING / "recovery_coverage_summary.json").read_text(encoding="utf-8")
    )
    return fh, fr, mh, mr, ah, ar, ph, pr, summary


def auth_args():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.getenv("ALPHA_SHEETS_API_URL", ""))
    p.add_argument("--token", default=os.getenv("ALPHA_SHEETS_API_TOKEN", ""))
    p.add_argument("--inspect", action="store_true")
    p.add_argument("--commit-safe", action="store_true")
    return p.parse_args()


def main() -> int:
    args = auth_args()
    if not args.url or not args.token:
        raise RuntimeError("Missing URL/token")

    if args.inspect:
        print("[REMOTE INSPECT - READ ONLY]")
        obj = post_json(
            args.url,
            {"token": args.token, "action": "dr1d_inspect"},
        )
        print(json.dumps(obj, indent=2, ensure_ascii=False))
        print("")
        print("INSPECT COMPLETE. NO SHEETS MUTATION.")
        return 0

    if not args.commit_safe:
        raise RuntimeError("Use --inspect or --commit-safe")

    fh, fr, mh, mr, ah, ar, ph, pr, summary = load_all()

    if len(fr) != 187 or len(fh) != 29:
        raise RuntimeError("Fund local gate failed")
    if len(mr) != 200 or len(mh) != 41:
        raise RuntimeError("Market local gate failed")

    base = {
        "token": args.token,
        "fundamentals": {"headers": fh, "rows": fr},
        "market": {"headers": mh, "rows": mr},
    }

    print("[1/9] REMOTE DRY RUN")
    print(json.dumps(post_json(
        args.url,
        {**base, "action": "dr1d_dry_run"},
    ), indent=2, ensure_ascii=False))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("")
    print("[2/9] BACKUP FUNDAMENTALS")
    print(json.dumps(post_json(args.url, {
        "token": args.token,
        "action": "dr1d_backup_sheet",
        "module": "fundamentals",
        "run_id": run_id,
    }), indent=2, ensure_ascii=False))

    print("")
    print("[3/9] BACKUP MARKET")
    print(json.dumps(post_json(args.url, {
        "token": args.token,
        "action": "dr1d_backup_sheet",
        "module": "market",
        "run_id": run_id,
    }), indent=2, ensure_ascii=False))

    print("")
    print("[4/9] CLEAR TARGETS")
    for module in ("fundamentals", "market"):
        print(json.dumps(post_json(args.url, {
            "token": args.token,
            "action": "dr1d_clear_target",
            "module": module,
        }), indent=2, ensure_ascii=False))

    print("")
    print("[5/9] WRITE FUNDAMENTALS IN 40-ROW CHUNKS")
    for start in range(0, len(fr), 40):
        chunk = fr[start:start + 40]
        r = post_json(args.url, {
            "token": args.token,
            "action": "dr1d_write_chunk",
            "module": "fundamentals",
            "start_index": start,
            "rows": chunk,
        })
        print(f"  fundamentals {start + len(chunk)}/{len(fr)} OK")
        time.sleep(0.15)

    print("")
    print("[6/9] WRITE MARKET IN 40-ROW CHUNKS")
    for start in range(0, len(mr), 40):
        chunk = mr[start:start + 40]
        r = post_json(args.url, {
            "token": args.token,
            "action": "dr1d_write_chunk",
            "module": "market",
            "start_index": start,
            "rows": chunk,
        })
        print(f"  market {start + len(chunk)}/{len(mr)} OK")
        time.sleep(0.15)

    print("")
    print("[7/9] VERIFY CORE TARGETS")
    for module, rows in (("fundamentals", fr), ("market", mr)):
        v = post_json(args.url, {
            "token": args.token,
            "action": "dr1d_verify_target",
            "module": module,
            "expected_first_ticker": str(rows[0][0]),
            "expected_last_ticker": str(rows[-1][0]),
        })
        print(json.dumps(v, indent=2, ensure_ascii=False))
        if not v.get("pass"):
            raise RuntimeError(f"Remote verification failed for {module}")

    print("")
    print("[8/9] WRITE AUDIT + FAILURES")
    for start in range(0, len(ar), 500):
        chunk = ar[start:start + 500]
        r = post_json(args.url, {
            "token": args.token,
            "action": "dr1d_write_audit_chunk",
            "reset": start == 0,
            "rows": chunk,
        })
        print(f"  audit {start + len(chunk)}/{len(ar)} OK")
        time.sleep(0.10)

    print(json.dumps(post_json(args.url, {
        "token": args.token,
        "action": "dr1d_write_failures",
        "rows": pr,
    }), indent=2, ensure_ascii=False))

    print("")
    print("[9/9] FINALIZE")
    print(json.dumps(post_json(args.url, {
        "token": args.token,
        "action": "dr1d_finalize",
        "summary": summary,
    }), indent=2, ensure_ascii=False))

    print("")
    print("DR1-D SAFE CHUNKED COMMIT COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
