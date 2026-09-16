$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-B FIX2"
Write-Host "PROVIDER IDENTITY LAYER / ADR & CROSS-LISTING MAPPING"
Write-Host "NO V13 / SHEETS / WEB / PRODUCT STATE MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $REC)) { throw "No existe Recovery V1: $REC" }
if (-not (Test-Path $V13)) { throw "No existe V13: $V13" }

Set-Location $ROOT
$before = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"


@'
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ProviderIdentity:
    canonical_ticker: str
    market_symbol: str
    fundamentals_symbol: str
    sec_ticker: str
    listing_type: str = "primary"
    conversion_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# IMPORTANT:
# canonical_ticker = internal Alpha Engine identity.
# Provider symbols are NEVER inferred from the canonical ticker when a known
# cross-listing / ADR / local listing relationship exists.
KNOWN_IDENTITIES: dict[str, ProviderIdentity] = {
    "PAMP": ProviderIdentity(
        canonical_ticker="PAMP",
        market_symbol="PAMP.BA",
        fundamentals_symbol="PAM",
        sec_ticker="PAM",
        listing_type="BYMA ordinary / NYSE ADS cross-listing",
        conversion_note="Pampa Energia: NYSE PAM ADS; 1 ADS = 25 ordinary shares.",
    ),
}


def resolve_identity(ticker: str) -> ProviderIdentity:
    canonical = ticker.strip().upper()
    if not canonical:
        raise ValueError("empty ticker")

    known = KNOWN_IDENTITIES.get(canonical)
    if known is not None:
        return known

    return ProviderIdentity(
        canonical_ticker=canonical,
        market_symbol=canonical,
        fundamentals_symbol=canonical,
        sec_ticker=canonical,
        listing_type="provider-default",
        conversion_note="",
    )
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\provider_identity.py") -Encoding UTF8

@'
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
'@ | Set-Content -Path (Join-Path $REC "scripts\run_fundamentals_recovery.py") -Encoding UTF8

@'
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.provider_identity import resolve_identity


class TestProviderIdentity(unittest.TestCase):
    def test_pamp_provider_mapping(self):
        x = resolve_identity("PAMP")
        self.assertEqual(x.canonical_ticker, "PAMP")
        self.assertEqual(x.market_symbol, "PAMP.BA")
        self.assertEqual(x.fundamentals_symbol, "PAM")
        self.assertEqual(x.sec_ticker, "PAM")
        self.assertIn("25", x.conversion_note)

    def test_default_identity_is_not_mutated(self):
        x = resolve_identity("NVDA")
        self.assertEqual(x.canonical_ticker, "NVDA")
        self.assertEqual(x.market_symbol, "NVDA")
        self.assertEqual(x.fundamentals_symbol, "NVDA")
        self.assertEqual(x.sec_ticker, "NVDA")

    def test_mapping_is_case_normalized(self):
        x = resolve_identity("pamp")
        self.assertEqual(x.canonical_ticker, "PAMP")
        self.assertEqual(x.fundamentals_symbol, "PAM")


if __name__ == "__main__":
    unittest.main()
'@ | Set-Content -Path (Join-Path $REC "tests\test_provider_identity.py") -Encoding UTF8

Write-Host ""
Write-Host "[1/6] Unit tests"
Set-Location $REC
python -m unittest discover -s tests -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "Tests DR1-B FIX2 fallaron." }

Write-Host ""
Write-Host "[2/6] Identity contract"
python -c "import sys; sys.path.insert(0,'src'); from alpha_data_recovery.provider_identity import resolve_identity; x=resolve_identity('PAMP'); print('IDENTITY_OK', x.canonical_ticker, x.market_symbol, x.fundamentals_symbol, x.sec_ticker, x.conversion_note)"
if ($LASTEXITCODE -ne 0) { throw "Provider identity smoke falló." }

Write-Host ""
Write-Host "[3/6] SEC provider-symbol smoke"
python -c "import sys; sys.path.insert(0,'src'); from alpha_data_recovery.sec_companyfacts import fetch_ticker_map; m=fetch_ticker_map(); print('SEC_MAP_OK', len(m), 'NVDA' in m, 'MSFT' in m, 'YPF' in m, 'PAM' in m)"
if ($LASTEXITCODE -ne 0) { throw "SEC map smoke falló." }

Write-Host ""
Write-Host "[4/6] Live fundamentals sentinels"
python scripts\run_fundamentals_recovery.py --symbols NVDA MSFT YPF PAMP
if ($LASTEXITCODE -ne 0) {
    throw "DR1-B FIX2 live recovery quedó INCOMPLETE."
}

Write-Host ""
Write-Host "[5/6] Identity + audit gate"
$audit = Import-Csv (Join-Path $REC "outputs\data_recovery_v1\fundamentals_audit_latest.csv")
$ids   = Import-Csv (Join-Path $REC "outputs\data_recovery_v1\provider_identity_latest.csv")

$pamp = $ids | Where-Object { $_.canonical_ticker -eq "PAMP" } | Select-Object -First 1
if (-not $pamp) { throw "IDENTITY GATE: falta PAMP." }
if ($pamp.fundamentals_symbol -ne "PAM") { throw "IDENTITY GATE: PAMP Yahoo fundamental != PAM." }
if ($pamp.sec_ticker -ne "PAM") { throw "IDENTITY GATE: PAMP SEC != PAM." }
if ($pamp.market_symbol -ne "PAMP.BA") { throw "IDENTITY GATE: PAMP market != PAMP.BA." }

Write-Host "  [OK] PAMP canonical -> Market=PAMP.BA | YahooFund=PAM | SEC=PAM"

$required = @("roe","debt_equity","net_margin","revenue_growth","free_cash_flow")
foreach ($ticker in @("NVDA","MSFT","YPF","PAMP")) {
    foreach ($field in $required) {
        $row = $audit |
            Where-Object { $_.ticker -eq $ticker -and $_.field -eq $field } |
            Select-Object -First 1

        if (-not $row) { throw "AUDIT GATE: falta $ticker/$field" }
        if (-not $row.source) { throw "AUDIT GATE: source vacío $ticker/$field" }
        if (-not $row.status) { throw "AUDIT GATE: status vacío $ticker/$field" }

        if ($row.status -eq "MISSING") {
            Write-Host "  [WARN] $ticker/$field MISSING source=$($row.source)"
        } else {
            Write-Host "  [OK]   $ticker/$field source=$($row.source) status=$($row.status) fallback=$($row.fallback)"
        }
    }
}

Write-Host ""
Write-Host "[6/6] V13 immutability"
Set-Location $ROOT
$after = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
if (($before | Out-String) -ne ($after | Out-String)) {
    throw "GUARDRAIL: cambió V13 durante DR1-B FIX2."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "DR1-B FIX2 COMPLETE"
Write-Host "PROVIDER IDENTITY: ACTIVE"
Write-Host "PAMP CANONICAL: PRESERVED"
Write-Host "PAMP FUNDAMENTALS/SEC: PAM"
Write-Host "PAMP MARKET: PAMP.BA"
Write-Host "V8/V10 SCORES: NOT IMPORTED"
Write-Host "V13: UNCHANGED"
Write-Host "SHEETS: UNCHANGED"
Write-Host "WEB: UNCHANGED"
Write-Host "PRODUCT STATE: NOT REGENERATED"
Write-Host "============================================================"
Write-Host ""
Write-Host "Pegame la salida completa."
