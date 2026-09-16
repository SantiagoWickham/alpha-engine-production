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

from alpha_data_recovery.fundamentals import recover_fundamentals
from alpha_data_recovery.provider_identity import resolve_identity
from alpha_data_recovery.sec_companyfacts import fetch_ticker_map
from alpha_data_recovery.yahoo_fundamentals import YahooSession


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["NVDA", "MSFT", "YPF", "PAMP"],
    )
    args = parser.parse_args()

    output_dir = ROOT / "outputs" / "data_recovery_v1"
    output_dir.mkdir(parents=True, exist_ok=True)

    yf = YahooSession()
    try:
        yf.bootstrap()
        print("[OK] Yahoo session")
    except Exception as exc:
        print(f"[WARN] Yahoo session bootstrap failed: {exc}")

    try:
        sec_map = fetch_ticker_map()
        print(f"[OK] SEC ticker map: {len(sec_map)} tickers")
    except Exception as exc:
        sec_map = {}
        print(f"[WARN] SEC ticker map failed: {exc}")

    records = []
    identities = []

    for symbol in args.symbols:
        ident = resolve_identity(symbol)
        identities.append(ident.to_dict())

        if (
            ident.canonical_ticker != ident.fundamentals_symbol
            or ident.canonical_ticker != ident.sec_ticker
        ):
            print(
                f"[MAP] {ident.canonical_ticker} -> "
                f"YahooFund={ident.fundamentals_symbol} "
                f"SEC={ident.sec_ticker} "
                f"Market={ident.market_symbol}"
            )

        snap = recover_fundamentals(
            ticker=ident.canonical_ticker,
            yahoo_symbol=ident.fundamentals_symbol,
            sec_ticker=ident.sec_ticker,
            yahoo_session=yf,
            sec_map=sec_map,
        )
        record = snap.to_dict()
        record["provider_identity"] = ident.to_dict()
        records.append(record)

        f = record["fields"]

        def val(name: str):
            return (f.get(name) or {}).get("value")

        def src(name: str):
            return (f.get(name) or {}).get("source")

        def stat(name: str):
            return (f.get(name) or {}).get("status")

        print(
            f"[{record['overall_status']}] {ident.canonical_ticker:<6} "
            f"yf={ident.fundamentals_symbol:<6} "
            f"sec={ident.sec_ticker:<6} "
            f"mcap={val('market_cap')} "
            f"pe={val('pe')} "
            f"roe={val('roe')} "
            f"rev_growth={val('revenue_growth')} "
            f"coverage={record['coverage']:.0%}"
        )
        print(
            f"       roe_source={src('roe')} status={stat('roe')} | "
            f"revenue_growth_source={src('revenue_growth')} "
            f"status={stat('revenue_growth')}"
        )
        if val("_yahoo_error"):
            print(f"       yahoo_error={val('_yahoo_error')}")
        if val("_sec_error"):
            print(f"       sec_error={val('_sec_error')}")

    payload = {
        "stage": "ALPHA_ENGINE_DATA_RECOVERY_V1_DR1B_FIX2",
        "identity_policy": (
            "canonical Alpha ticker is separate from provider-specific "
            "market/fundamentals/SEC symbols"
        ),
        "mutation_policy": {
            "v13_model": False,
            "v13_policy": False,
            "v13_outputs": False,
            "sheets": False,
            "web": False,
            "product_state": False,
        },
        "identities": identities,
        "records": records,
    }

    json_path = output_dir / "fundamentals_snapshot_latest.json"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    canonical = [
        "company_name", "sector", "industry", "price", "market_cap",
        "pe", "fwd_pe", "peg", "roe", "roa", "debt_equity",
        "net_margin", "eps_growth", "revenue_growth", "free_cash_flow",
        "fcf_yield", "ev_ebitda", "current_ratio", "quick_ratio",
        "dividend_yield", "beta", "target_mean_price", "target_upside",
        "recommendation_mean", "price_book", "shares_outstanding",
    ]

    wide_path = output_dir / "fundamentals_snapshot_latest.csv"
    with wide_path.open("w", newline="", encoding="utf-8-sig") as fh:
        headers = [
            "ticker",
            "fundamentals_symbol",
            "sec_ticker",
            "market_symbol",
            "status",
            "coverage",
        ] + canonical
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()

        for r in records:
            ident = r["provider_identity"]
            row = {
                "ticker": r["ticker"],
                "fundamentals_symbol": ident["fundamentals_symbol"],
                "sec_ticker": ident["sec_ticker"],
                "market_symbol": ident["market_symbol"],
                "status": r["overall_status"],
                "coverage": r["coverage"],
            }
            for name in canonical:
                row[name] = (r["fields"].get(name) or {}).get("value")
            writer.writerow(row)

    audit_path = output_dir / "fundamentals_audit_latest.csv"
    with audit_path.open("w", newline="", encoding="utf-8-sig") as fh:
        headers = [
            "ticker",
            "fundamentals_symbol",
            "sec_ticker",
            "field",
            "value",
            "source",
            "asof",
            "status",
            "fallback",
            "detail",
        ]
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()

        for r in records:
            ident = r["provider_identity"]
            for field, audit in r["fields"].items():
                writer.writerow({
                    "ticker": r["ticker"],
                    "fundamentals_symbol": ident["fundamentals_symbol"],
                    "sec_ticker": ident["sec_ticker"],
                    "field": field,
                    **audit,
                })

    identity_path = output_dir / "provider_identity_latest.csv"
    with identity_path.open("w", newline="", encoding="utf-8-sig") as fh:
        headers = [
            "canonical_ticker",
            "market_symbol",
            "fundamentals_symbol",
            "sec_ticker",
            "listing_type",
            "conversion_note",
        ]
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerows(identities)

    print("")
    print("WROTE:")
    print(f"  {json_path}")
    print(f"  {wide_path}")
    print(f"  {audit_path}")
    print(f"  {identity_path}")
    print("")

    incomplete = [
        r["ticker"]
        for r in records
        if r["overall_status"] == "INCOMPLETE"
    ]
    print(f"records={len(records)} incomplete={len(incomplete)} {incomplete}")

    return 2 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
