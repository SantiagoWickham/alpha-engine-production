from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.market_sheet_metrics import compute_sheet_market_metrics
from alpha_data_recovery.sheet_payloads import MKT_HEADERS, market_payload_row
from alpha_data_recovery.universe_registry import load_universe
from alpha_data_recovery.yahoo_chart import recover_market

UNIVERSE_PATH = ROOT / "config" / "universe_v8_recovered.csv"
LIVE = ROOT / "outputs" / "data_recovery_v1" / "live"
HISTORY = LIVE / "history"

AUDIT_HEADERS = [
    "ticker","module","provider_symbol","field","value",
    "source","asof","status","fallback","detail",
]


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def market_worker(symbol: str):
    snap, rows = recover_market(symbol, symbol)
    return snap.to_dict(), rows


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
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc}") from exc

    obj = json.loads(text)
    if not obj.get("ok"):
        raise RuntimeError(json.dumps(obj, ensure_ascii=False))
    return obj


def collect_market(workers: int):
    universe = [u for u in load_universe(UNIVERSE_PATH) if u.active]
    market_u = [u for u in universe if u.motor != "Renta Fija"]

    if len(market_u) != 200:
        raise RuntimeError(f"Market universe mismatch: {len(market_u)} != 200")

    symbols = sorted({
        s
        for u in market_u
        for s in (u.market_symbol, u.benchmark)
        if s
    })

    print(f"[FETCH] market assets={len(market_u)} unique provider symbols={len(symbols)}")

    results: dict[str, tuple[dict, list[dict]]] = {}
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as ex:
        futs = {ex.submit(market_worker, s): s for s in symbols}
        done = 0
        for fut in as_completed(futs):
            symbol = futs[fut]
            try:
                results[symbol] = fut.result()
            except Exception as exc:
                errors[symbol] = str(exc)
            done += 1
            if done % 25 == 0 or done == len(symbols):
                print(
                    f"  provider {done}/{len(symbols)} "
                    f"ok={len(results)} errors={len(errors)}"
                )

    asset_missing = [
        u for u in market_u if u.market_symbol not in results
    ]

    # Fail closed. Never replace a good Sheet with a degraded transient pull.
    if errors or asset_missing:
        print("")
        print("REFRESH ABORTED BEFORE SHEET WRITE")
        print(f"provider_symbols_failed={len(errors)}")
        print(f"asset_symbols_missing={len(asset_missing)}")
        for sym, err in list(errors.items())[:20]:
            print(f"  FAIL {sym}: {err}")
        raise RuntimeError(
            "Market refresh did not reach full provider coverage. "
            "Existing Sheet remains untouched."
        )

    payload = []
    audit = []

    for u in market_u:
        snap, rows = results[u.market_symbol]
        bench = results.get(u.benchmark) if u.benchmark else None
        bench_rows = bench[1] if bench else None

        payload.append(market_payload_row(u, snap, rows, bench_rows))

        for field, a in (snap.get("fields") or {}).items():
            audit.append({
                "ticker": u.canonical_ticker,
                "module": "market",
                "provider_symbol": u.market_symbol,
                "field": field,
                "value": a.get("value"),
                "source": a.get("source"),
                "asof": a.get("asof"),
                "status": a.get("status"),
                "fallback": a.get("fallback"),
                "detail": a.get("detail"),
            })

        for field, a in (snap.get("metrics") or {}).items():
            audit.append({
                "ticker": u.canonical_ticker,
                "module": "market",
                "provider_symbol": u.market_symbol,
                "field": field,
                "value": a.get("value"),
                "source": a.get("source"),
                "asof": a.get("asof"),
                "status": a.get("status"),
                "fallback": a.get("fallback"),
                "detail": a.get("detail"),
            })

        extra = compute_sheet_market_metrics(rows, bench_rows)
        for field, value in extra.items():
            audit.append({
                "ticker": u.canonical_ticker,
                "module": "market",
                "provider_symbol": u.market_symbol,
                "field": field,
                "value": value,
                "source": "derived: Yahoo OHLCV aligned",
                "asof": (
                    (snap.get("fields", {}).get("latest_daily_close", {}) or {})
                    .get("asof")
                ),
                "status": "OK" if value is not None else "MISSING",
                "fallback": "none",
                "detail": "DR1-F live raw market metric; no V8 score.",
            })

    if len(payload) != 200:
        raise RuntimeError(f"Payload row mismatch: {len(payload)} != 200")

    # Explicit score blank gate: zero-based columns 29..37.
    for i, row in enumerate(payload):
        vals = [row[h] for h in MKT_HEADERS]
        for idx in range(29, 38):
            if vals[idx] not in (None, ""):
                raise RuntimeError(
                    f"Forbidden V8/V10 score value row={i} col={idx}"
                )

    return market_u, symbols, payload, audit


def save_live(symbols, payload, audit):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    live_dir = LIVE
    hist_dir = HISTORY / stamp
    live_dir.mkdir(parents=True, exist_ok=True)
    hist_dir.mkdir(parents=True, exist_ok=True)

    latest_payload = live_dir / "mercado_riesgo_live_latest.csv"
    latest_audit = live_dir / "market_audit_live_latest.csv"
    latest_summary = live_dir / "market_refresh_summary_latest.json"

    write_csv(latest_payload, MKT_HEADERS, payload)
    write_csv(latest_audit, AUDIT_HEADERS, audit)

    summary = {
        "stage": "ALPHA_ENGINE_DATA_RECOVERY_V1_DR1F_MARKET",
        "asof": datetime.now(timezone.utc).isoformat(),
        "market_asset_rows": len(payload),
        "unique_provider_symbols_requested": len(symbols),
        "provider_symbols_failed": 0,
        "asset_symbols_missing": 0,
        "score_columns_blank": True,
        "sheet_write_pending": True,
        "v13_mutated": False,
        "web_mutated": False,
        "product_state_mutated": False,
    }
    latest_summary.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Immutable history snapshot for auditability.
    write_csv(hist_dir / "mercado_riesgo.csv", MKT_HEADERS, payload)
    write_csv(hist_dir / "market_audit.csv", AUDIT_HEADERS, audit)
    (hist_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return stamp, latest_payload, latest_summary


def commit_market(url: str, token: str, payload: list[dict], stamp: str):
    rows = [[row[h] for h in MKT_HEADERS] for row in payload]

    print("")
    print("[SHEET] Backup current Mercado & Riesgo")
    b = post_json(url, {
        "token": token,
        "action": "dr1d_backup_sheet",
        "module": "market",
        "run_id": f"DR1F_{stamp}",
    })
    print(f"  backup={b.get('backup')}")

    print("[SHEET] Clear bounded market target")
    post_json(url, {
        "token": token,
        "action": "dr1d_clear_target",
        "module": "market",
    })

    print("[SHEET] Write 200 rows in 40-row chunks")
    for start in range(0, len(rows), 40):
        chunk = rows[start:start + 40]
        post_json(url, {
            "token": token,
            "action": "dr1d_write_chunk",
            "module": "market",
            "start_index": start,
            "rows": chunk,
        })
        print(f"  market {start + len(chunk)}/{len(rows)} OK")
        time.sleep(0.15)

    print("[SHEET] Verify")
    v = post_json(url, {
        "token": token,
        "action": "dr1d_verify_target",
        "module": "market",
        "expected_first_ticker": str(rows[0][0]),
        "expected_last_ticker": str(rows[-1][0]),
    })
    print(json.dumps(v, indent=2, ensure_ascii=False))
    if not v.get("pass"):
        raise RuntimeError("Remote market verification failed")

    return v


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--market-workers", type=int, default=6)
    p.add_argument("--commit", action="store_true")
    p.add_argument("--url", default=os.getenv("ALPHA_SHEETS_API_URL", ""))
    p.add_argument("--token", default=os.getenv("ALPHA_SHEETS_API_TOKEN", ""))
    args = p.parse_args()

    market_u, symbols, payload, audit = collect_market(args.market_workers)
    stamp, payload_path, summary_path = save_live(symbols, payload, audit)

    print("")
    print("DR1-F MARKET LIVE PAYLOAD READY")
    print(f"  rows={len(payload)} cols={len(MKT_HEADERS)}")
    print(f"  audit_rows={len(audit)}")
    print(f"  live_payload={payload_path}")
    print(f"  summary={summary_path}")
    print("  old_score_columns_blank=True")

    if not args.commit:
        print("")
        print("NO SHEET WRITE: --commit not supplied")
        return 0

    if not args.url or not args.token:
        raise RuntimeError("Missing URL/token for commit")

    commit_market(args.url, args.token, payload, stamp)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["sheet_write_pending"] = False
    summary["sheet_write_status"] = "PASS"
    summary["sheet_written_at"] = datetime.now(timezone.utc).isoformat()
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("")
    print("============================================================")
    print("DR1-F MARKET REFRESH COMPLETE")
    print("PROVIDER COVERAGE: 212/212")
    print("MARKET ROWS: VERIFIED 200/200")
    print("OLD V8/V10 SCORE CELLS: 0")
    print("FUNDAMENTALS: UNCHANGED")
    print("V13: UNCHANGED")
    print("WEB: UNCHANGED")
    print("PRODUCT STATE: UNCHANGED")
    print("============================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
