from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.yahoo_chart import recover_market


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["NVDA", "MSFT", "SPY"],
        help="Yahoo market symbols for smoke recovery",
    )
    args = parser.parse_args()

    output_dir = ROOT / "outputs" / "data_recovery_v1"
    ohlcv_dir = output_dir / "ohlcv"
    output_dir.mkdir(parents=True, exist_ok=True)
    ohlcv_dir.mkdir(parents=True, exist_ok=True)

    records = []
    failures = []

    for symbol in args.symbols:
        ticker = symbol.upper()
        try:
            snap, rows = recover_market(ticker=ticker, market_symbol=ticker)
            records.append(snap.to_dict())
            with (ohlcv_dir / f"{ticker.replace('^', '_')}.jsonl").open(
                "w", encoding="utf-8"
            ) as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")

            f = snap.fields
            print(
                f"[{snap.overall_status}] {ticker:<8} "
                f"price={f['price'].value} "
                f"prev={f['previous_close'].value} "
                f"var_1d={f['var_1d'].value} "
                f"chartPrev_DIAG={f['meta_chart_previous_close'].value} "
                f"fallback={f['price'].fallback}"
            )
        except Exception as exc:
            failures.append({"ticker": ticker, "error": str(exc)})
            print(f"[ERROR] {ticker}: {exc}")

    payload = {
        "stage": "ALPHA_ENGINE_DATA_RECOVERY_V1_DR1A_FIX1",
        "var_1d_contract": "regular_market_price / immediately_preceding_raw_daily_close - 1",
        "forbidden_var_1d_input": "Yahoo meta.chartPreviousClose",
        "mutation_policy": {
            "v13_model": False,
            "v13_policy": False,
            "v13_outputs": False,
            "sheets": False,
            "web": False,
        },
        "records": records,
        "failures": failures,
    }
    (output_dir / "market_snapshot_latest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    csv_path = output_dir / "market_snapshot_latest.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        headers = [
            "ticker", "market_symbol", "price", "previous_close", "var_1d",
            "latest_daily_close", "close_to_close_1d",
            "ret_1m", "ret_3m", "ret_6m", "ret_12m",
            "vol_20d", "vol_60d", "vol_1y", "max_drawdown_1y",
            "dollar_volume_20d", "relative_volume_20v60",
            "source", "asof", "status", "fallback", "coverage",
            "meta_regular_previous_close_DIAGNOSTIC",
            "meta_chart_previous_close_DIAGNOSTIC",
        ]
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for r in records:
            f = r["fields"]
            m = r["metrics"]
            writer.writerow({
                "ticker": r["ticker"],
                "market_symbol": r["market_symbol"],
                "price": f["price"]["value"],
                "previous_close": f["previous_close"]["value"],
                "var_1d": f["var_1d"]["value"],
                "latest_daily_close": f["latest_daily_close"]["value"],
                "close_to_close_1d": m["close_to_close_1d"]["value"],
                "ret_1m": m["ret_1m"]["value"],
                "ret_3m": m["ret_3m"]["value"],
                "ret_6m": m["ret_6m"]["value"],
                "ret_12m": m["ret_12m"]["value"],
                "vol_20d": m["vol_20d"]["value"],
                "vol_60d": m["vol_60d"]["value"],
                "vol_1y": m["vol_1y"]["value"],
                "max_drawdown_1y": m["max_drawdown_1y"]["value"],
                "dollar_volume_20d": m["dollar_volume_20d"]["value"],
                "relative_volume_20v60": m["relative_volume_20v60"]["value"],
                "source": f["price"]["source"],
                "asof": f["price"]["asof"],
                "status": r["overall_status"],
                "fallback": f["price"]["fallback"],
                "coverage": r["coverage"],
                "meta_regular_previous_close_DIAGNOSTIC":
                    f["meta_regular_previous_close"]["value"],
                "meta_chart_previous_close_DIAGNOSTIC":
                    f["meta_chart_previous_close"]["value"],
            })

    print("")
    print("WROTE:")
    print(f"  {output_dir / 'market_snapshot_latest.json'}")
    print(f"  {csv_path}")
    print("")
    print(f"records={len(records)} failures={len(failures)}")
    return 0 if records and not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
