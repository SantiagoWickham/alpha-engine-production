from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.fundamentals import recover_fundamentals
from alpha_data_recovery.market_sheet_metrics import compute_sheet_market_metrics
from alpha_data_recovery.sec_companyfacts import fetch_ticker_map
from alpha_data_recovery.sheet_payloads import (
    FUND_HEADERS, MKT_HEADERS,
    FUND_SCORE_COLUMNS, MKT_SCORE_COLUMNS,
    fundamental_payload_row, market_payload_row,
)
from alpha_data_recovery.universe_registry import load_universe
from alpha_data_recovery.yahoo_chart import recover_market
from alpha_data_recovery.yahoo_fundamentals import YahooSession


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def market_worker(symbol: str):
    snap, rows = recover_market(symbol, symbol)
    return snap.to_dict(), rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-workers", type=int, default=6)
    args = parser.parse_args()

    universe_path = ROOT / "config" / "universe_v8_recovered.csv"
    universe = [u for u in load_universe(universe_path) if u.active]
    fundamentals_u = [u for u in universe if u.motor == "Fundamental"]
    market_u = [u for u in universe if u.motor != "Renta Fija"]
    rf_u = [u for u in universe if u.motor == "Renta Fija"]

    print(
        f"UNIVERSE total={len(universe)} "
        f"fundamental={len(fundamentals_u)} "
        f"market={len(market_u)} rf={len(rf_u)}"
    )

    if len(universe) != 228:
        raise RuntimeError(f"Universe structural mismatch: {len(universe)} != 228")
    if len(fundamentals_u) != 187:
        raise RuntimeError(f"Fundamental universe mismatch: {len(fundamentals_u)} != 187")
    if len(market_u) != 200:
        raise RuntimeError(f"Market universe mismatch: {len(market_u)} != 200")
    if len(rf_u) != 28:
        raise RuntimeError(f"RF universe mismatch: {len(rf_u)} != 28")

    staging = ROOT / "outputs" / "data_recovery_v1" / "staging"
    staging.mkdir(parents=True, exist_ok=True)

    symbols = sorted({
        s
        for u in market_u
        for s in (u.market_symbol, u.benchmark)
        if s
    })

    print(f"[MARKET] unique provider symbols={len(symbols)}")
    market_results: dict[str, tuple[dict, list[dict]]] = {}
    market_errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max(1, min(args.market_workers, 8))) as ex:
        futs = {ex.submit(market_worker, s): s for s in symbols}
        done = 0
        for fut in as_completed(futs):
            symbol = futs[fut]
            try:
                market_results[symbol] = fut.result()
            except Exception as exc:
                market_errors[symbol] = str(exc)
            done += 1
            if done % 25 == 0 or done == len(symbols):
                print(
                    f"  market {done}/{len(symbols)} "
                    f"ok={len(market_results)} errors={len(market_errors)}"
                )

    yf = YahooSession()
    yahoo_bootstrap_error = None
    try:
        yf.bootstrap()
        print("[FUND] Yahoo session OK")
    except Exception as exc:
        yahoo_bootstrap_error = str(exc)
        print(f"[FUND] Yahoo session WARN: {exc}")

    try:
        sec_map = fetch_ticker_map()
        print(f"[FUND] SEC map OK tickers={len(sec_map)}")
    except Exception as exc:
        sec_map = {}
        print(f"[FUND] SEC map WARN: {exc}")

    fund_records: dict[str, dict] = {}
    for i, u in enumerate(fundamentals_u, start=1):
        try:
            snap = recover_fundamentals(
                ticker=u.canonical_ticker,
                yahoo_symbol=u.fundamentals_symbol,
                sec_ticker=u.sec_ticker,
                yahoo_session=yf,
                sec_map=sec_map,
            )
            fund_records[u.canonical_ticker] = snap.to_dict()
        except Exception as exc:
            fund_records[u.canonical_ticker] = {
                "ticker": u.canonical_ticker,
                "yahoo_symbol": u.fundamentals_symbol,
                "sec_ticker": u.sec_ticker,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "overall_status": "INCOMPLETE",
                "coverage": 0.0,
                "fields": {
                    "_orchestrator_error": {
                        "value": str(exc),
                        "source": "DR1-C orchestrator",
                        "asof": datetime.now(timezone.utc).isoformat(),
                        "status": "ERROR",
                        "fallback": "none",
                        "detail": "",
                    }
                },
            }
        if i % 25 == 0 or i == len(fundamentals_u):
            c = Counter(r["overall_status"] for r in fund_records.values())
            print(f"  fundamentals {i}/{len(fundamentals_u)} status={dict(c)}")
        time.sleep(0.08)

    fund_payload = [
        fundamental_payload_row(u, fund_records[u.canonical_ticker])
        for u in fundamentals_u
    ]

    market_payload = []
    audit_rows = []
    failures = []

    for u in market_u:
        asset = market_results.get(u.market_symbol)
        bench = market_results.get(u.benchmark) if u.benchmark else None

        if asset:
            snap, rows = asset
            b_rows = bench[1] if bench else None
            market_payload.append(
                market_payload_row(u, snap, rows, b_rows)
            )

            for field, a in (snap.get("fields") or {}).items():
                audit_rows.append({
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
                audit_rows.append({
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

            extra = compute_sheet_market_metrics(rows, b_rows)
            for field, value in extra.items():
                audit_rows.append({
                    "ticker": u.canonical_ticker,
                    "module": "market",
                    "provider_symbol": u.market_symbol,
                    "field": field,
                    "value": value,
                    "source": "derived: Yahoo OHLCV aligned",
                    "asof": (snap.get("fields", {}).get("latest_daily_close", {}) or {}).get("asof"),
                    "status": "OK" if value is not None else "MISSING",
                    "fallback": "none",
                    "detail": "DR1-C raw market metric; no V8 score.",
                })
        else:
            err = market_errors.get(u.market_symbol, "market symbol not recovered")
            market_payload.append(
                market_payload_row(u, None, None, None, err)
            )
            failures.append({
                "ticker": u.canonical_ticker,
                "module": "market",
                "provider_symbol": u.market_symbol,
                "error": err,
            })

    for u in fundamentals_u:
        rec = fund_records[u.canonical_ticker]
        for field, a in (rec.get("fields") or {}).items():
            audit_rows.append({
                "ticker": u.canonical_ticker,
                "module": "fundamentals",
                "provider_symbol": u.fundamentals_symbol,
                "field": field,
                "value": a.get("value"),
                "source": a.get("source"),
                "asof": a.get("asof"),
                "status": a.get("status"),
                "fallback": a.get("fallback"),
                "detail": a.get("detail"),
            })

        if rec["overall_status"] == "INCOMPLETE":
            failures.append({
                "ticker": u.canonical_ticker,
                "module": "fundamentals",
                "provider_symbol": u.fundamentals_symbol,
                "error": (
                    ((rec.get("fields") or {}).get("_yahoo_error") or {}).get("value")
                    or ((rec.get("fields") or {}).get("_orchestrator_error") or {}).get("value")
                    or "incomplete coverage"
                ),
            })

    fund_path = staging / "fundamentales_payload_latest.csv"
    mkt_path = staging / "mercado_riesgo_payload_latest.csv"
    audit_path = staging / "data_audit_long_latest.csv"
    fail_path = staging / "provider_failures_latest.csv"
    uni_path = staging / "universe_registry_latest.csv"

    write_csv(fund_path, FUND_HEADERS, fund_payload)
    write_csv(mkt_path, MKT_HEADERS, market_payload)
    write_csv(
        audit_path,
        ["ticker","module","provider_symbol","field","value","source","asof","status","fallback","detail"],
        audit_rows,
    )
    write_csv(
        fail_path,
        ["ticker","module","provider_symbol","error"],
        failures,
    )

    with universe_path.open("r", encoding="utf-8-sig") as src:
        uni_path.write_text(src.read(), encoding="utf-8-sig")

    fund_status = Counter(r["overall_status"] for r in fund_records.values())
    market_ok = sum(
        1 for u in market_u if u.market_symbol in market_results
    )

    summary = {
        "stage": "ALPHA_ENGINE_DATA_RECOVERY_V1_DR1C",
        "asof": datetime.now(timezone.utc).isoformat(),
        "universe": {
            "total": len(universe),
            "fundamental": len(fundamentals_u),
            "market_non_rf": len(market_u),
            "renta_fija": len(rf_u),
        },
        "market": {
            "asset_rows": len(market_payload),
            "asset_symbols_recovered": market_ok,
            "asset_symbols_missing": len(market_u) - market_ok,
            "unique_provider_symbols_requested": len(symbols),
            "provider_symbols_failed": len(market_errors),
        },
        "fundamentals": {
            "rows": len(fund_payload),
            "status_counts": dict(fund_status),
            "yahoo_bootstrap_error": yahoo_bootstrap_error,
        },
        "audit_rows": len(audit_rows),
        "provider_failures": len(failures),
        "score_columns_policy": {
            "fundamental_scores_blank": True,
            "market_scores_blank": True,
            "v8_v10_scores_imported": False,
        },
        "mutation_policy": {
            "v13_model": False,
            "v13_policy": False,
            "v13_outputs": False,
            "sheets": False,
            "web": False,
            "product_state": False,
        },
    }

    summary_path = staging / "recovery_coverage_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("")
    print("DR1-C STAGING WRITTEN")
    print(f"  {fund_path}")
    print(f"  {mkt_path}")
    print(f"  {audit_path}")
    print(f"  {fail_path}")
    print(f"  {summary_path}")
    print("")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    # Provider gaps are NOT structural failures. They are audited.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
