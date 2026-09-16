$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-B FIX1"
Write-Host "SEC GZIP + AUDITVALUE CONSOLE FIX"
Write-Host "NO V13 / SHEETS / WEB / PRODUCT STATE MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $REC)) { throw "No existe Recovery V1: $REC" }
if (-not (Test-Path $V13)) { throw "No existe V13: $V13" }

Set-Location $ROOT
$before = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"


@'
from __future__ import annotations

import gzip
import json
import os
import time
import zlib
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK"


def _ua() -> str:
    return os.getenv(
        "SEC_USER_AGENT",
        "AlphaEngine-Data-Recovery local-research",
    )


def _decode_http_body(raw: bytes, content_encoding: str | None = None) -> str:
    """Decode SEC response bodies safely.

    SEC may return gzip-compressed payloads even when urllib does not
    transparently decompress them. We support both the HTTP header and
    gzip magic bytes to avoid treating compressed bytes as UTF-8.
    """
    encoding = (content_encoding or "").lower().strip()

    if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        raw = zlib.decompress(raw)

    return raw.decode("utf-8")


def _get_json(url: str, attempts: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": _ua(),
                    "Accept": "application/json",
                    # Allow compression, but decode it explicitly below.
                    "Accept-Encoding": "gzip, deflate",
                },
            )
            with urlopen(req, timeout=25) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                raw = resp.read()
                content_encoding = resp.headers.get("Content-Encoding")
                text = _decode_http_body(raw, content_encoding)
                return json.loads(text)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            RuntimeError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            OSError,
            zlib.error,
        ) as exc:
            last_error = exc
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"SEC request failed: {url}: {last_error}")


def fetch_ticker_map() -> dict[str, str]:
    payload = _get_json(SEC_TICKERS)
    out: dict[str, str] = {}
    for item in payload.values():
        ticker = str(item.get("ticker") or "").upper().strip()
        cik = item.get("cik_str")
        if ticker and cik is not None:
            out[ticker] = str(cik).zfill(10)
    return out


def fetch_companyfacts(cik: str) -> dict[str, Any]:
    return _get_json(f"{SEC_FACTS}{str(cik).zfill(10)}.json")


def annual_series(
    facts: dict[str, Any],
    names: list[str],
) -> list[dict[str, Any]]:
    for namespace in ("us-gaap", "ifrs-full"):
        block = (facts or {}).get(namespace) or {}
        for name in names:
            concept = block.get(name)
            if not concept or not concept.get("units"):
                continue
            for unit, values in concept["units"].items():
                annual = []
                for x in values or []:
                    if x.get("form") not in {"10-K", "20-F", "40-F"}:
                        continue
                    if x.get("fp") not in {None, "", "FY"}:
                        continue
                    if x.get("fy") is None or x.get("val") is None:
                        continue
                    annual.append({
                        "fy": int(x["fy"]),
                        "val": float(x["val"]),
                        "end": x.get("end"),
                        "filed": x.get("filed"),
                        "form": x.get("form"),
                        "unit": unit,
                        "concept": name,
                        "namespace": namespace,
                    })
                if annual:
                    by_year: dict[int, dict[str, Any]] = {}
                    for x in annual:
                        old = by_year.get(x["fy"])
                        if old is None or str(x.get("filed") or "") >= str(old.get("filed") or ""):
                            by_year[x["fy"]] = x
                    return [by_year[y] for y in sorted(by_year)]
    return []


def sec_raw_fundamentals(companyfacts: dict[str, Any]) -> dict[str, Any]:
    facts = companyfacts.get("facts") or {}

    concept_map = {
        "revenue": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "Revenue",
        ],
        "net_income": ["NetIncomeLoss", "ProfitLoss"],
        "assets": ["Assets"],
        "equity": [
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            "Equity",
        ],
        "debt": [
            "LongTermDebtAndFinanceLeaseObligationsCurrent",
            "LongTermDebtCurrent",
            "LongTermDebtNoncurrent",
            "LongTermDebt",
            "Borrowings",
        ],
        "eps_diluted": [
            "EarningsPerShareDiluted",
            "DilutedEarningsLossPerShare",
            "BasicEarningsLossPerShare",
        ],
        "cash_from_operations": [
            "NetCashProvidedByUsedInOperatingActivities",
            "CashFlowsFromUsedInOperatingActivities",
        ],
        "capex": [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PurchaseOfPropertyPlantAndEquipment",
        ],
        "current_assets": ["AssetsCurrent"],
        "current_liabilities": ["LiabilitiesCurrent"],
    }

    series = {k: annual_series(facts, v) for k, v in concept_map.items()}

    def latest(name: str) -> dict[str, Any] | None:
        arr = series[name]
        return arr[-1] if arr else None

    def previous(name: str) -> dict[str, Any] | None:
        arr = series[name]
        return arr[-2] if len(arr) >= 2 else None

    return {
        "entity_name": companyfacts.get("entityName"),
        "series": series,
        "latest": {k: latest(k) for k in series},
        "previous": {k: previous(k) for k in series},
    }


def age_days(asof: str | None) -> float | None:
    if not asof:
        return None
    try:
        dt = datetime.fromisoformat(asof).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\sec_companyfacts.py") -Encoding UTF8

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

    for symbol in args.symbols:
        snap = recover_fundamentals(
            ticker=symbol,
            yahoo_symbol=symbol,
            sec_ticker=symbol,
            yahoo_session=yf,
            sec_map=sec_map,
        )
        record = snap.to_dict()
        records.append(record)

        # IMPORTANT: print from serialized audit contract, not dataclass objects.
        f = record["fields"]

        def val(name: str):
            return (f.get(name) or {}).get("value")

        def src(name: str):
            return (f.get(name) or {}).get("source")

        def stat(name: str):
            return (f.get(name) or {}).get("status")

        print(
            f"[{record['overall_status']}] {symbol:<6} "
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
        "stage": "ALPHA_ENGINE_DATA_RECOVERY_V1_DR1B_FIX1",
        "mutation_policy": {
            "v13_model": False,
            "v13_policy": False,
            "v13_outputs": False,
            "sheets": False,
            "web": False,
            "product_state": False,
        },
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
        headers = ["ticker", "status", "coverage"] + canonical
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()

        for r in records:
            row = {
                "ticker": r["ticker"],
                "status": r["overall_status"],
                "coverage": r["coverage"],
            }
            for name in canonical:
                row[name] = (r["fields"].get(name) or {}).get("value")
            writer.writerow(row)

    audit_path = output_dir / "fundamentals_audit_latest.csv"
    with audit_path.open("w", newline="", encoding="utf-8-sig") as fh:
        headers = [
            "ticker", "field", "value", "source", "asof",
            "status", "fallback", "detail",
        ]
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()

        for r in records:
            for field, audit in r["fields"].items():
                writer.writerow({
                    "ticker": r["ticker"],
                    "field": field,
                    **audit,
                })

    print("")
    print("WROTE:")
    print(f"  {json_path}")
    print(f"  {wide_path}")
    print(f"  {audit_path}")
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

import gzip
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.fundamentals import sec_derived
from alpha_data_recovery.sec_companyfacts import _decode_http_body


class TestDataRecoveryDR1B(unittest.TestCase):
    def test_sec_derived_metrics(self):
        raw = {
            "latest": {
                "revenue": {"val": 120.0, "end": "2025-12-31"},
                "net_income": {"val": 12.0, "end": "2025-12-31"},
                "assets": {"val": 100.0, "end": "2025-12-31"},
                "equity": {"val": 60.0, "end": "2025-12-31"},
                "debt": {"val": 30.0, "end": "2025-12-31"},
                "eps_diluted": {"val": 6.0, "end": "2025-12-31"},
                "cash_from_operations": {"val": 18.0, "end": "2025-12-31"},
                "capex": {"val": 5.0, "end": "2025-12-31"},
                "current_assets": {"val": 40.0, "end": "2025-12-31"},
                "current_liabilities": {"val": 20.0, "end": "2025-12-31"},
            },
            "previous": {
                "revenue": {"val": 100.0, "end": "2024-12-31"},
                "net_income": {"val": 10.0, "end": "2024-12-31"},
                "assets": {"val": 90.0, "end": "2024-12-31"},
                "equity": {"val": 50.0, "end": "2024-12-31"},
                "debt": {"val": 25.0, "end": "2024-12-31"},
                "eps_diluted": {"val": 5.0, "end": "2024-12-31"},
                "cash_from_operations": {"val": 15.0, "end": "2024-12-31"},
                "capex": {"val": 4.0, "end": "2024-12-31"},
                "current_assets": {"val": 35.0, "end": "2024-12-31"},
                "current_liabilities": {"val": 20.0, "end": "2024-12-31"},
            },
        }
        d = sec_derived(raw)
        self.assertAlmostEqual(d["roe"][0], 0.2)
        self.assertAlmostEqual(d["roa"][0], 0.12)
        self.assertAlmostEqual(d["debt_equity"][0], 50.0)
        self.assertAlmostEqual(d["net_margin"][0], 0.1)
        self.assertAlmostEqual(d["eps_growth"][0], 0.2)
        self.assertAlmostEqual(d["revenue_growth"][0], 0.2)
        self.assertAlmostEqual(d["free_cash_flow"][0], 13.0)
        self.assertAlmostEqual(d["current_ratio"][0], 2.0)

    def test_sec_gzip_decode_by_header(self):
        original = b'{"ok": true}'
        compressed = gzip.compress(original)
        self.assertEqual(
            _decode_http_body(compressed, "gzip"),
            original.decode("utf-8"),
        )

    def test_sec_gzip_decode_by_magic_bytes(self):
        original = b'{"tickers": 1}'
        compressed = gzip.compress(original)
        self.assertEqual(
            _decode_http_body(compressed, None),
            original.decode("utf-8"),
        )

    def test_no_v8_scores_in_fundamental_contract(self):
        forbidden = {
            "quality", "growth_score", "value_score",
            "alpha", "market_score", "risk_score",
        }
        expected = {
            "roe", "roa", "debt_equity", "net_margin",
            "eps_growth", "revenue_growth", "free_cash_flow",
        }
        self.assertTrue(forbidden.isdisjoint(expected))


if __name__ == "__main__":
    unittest.main()
'@ | Set-Content -Path (Join-Path $REC "tests\test_data_recovery_dr1b.py") -Encoding UTF8

Write-Host ""
Write-Host "[1/5] Unit tests"
Set-Location $REC
python -m unittest discover -s tests -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "Tests DR1-B FIX1 fallaron." }

Write-Host ""
Write-Host "[2/5] Direct SEC map smoke"
python -c "import sys; sys.path.insert(0,'src'); from alpha_data_recovery.sec_companyfacts import fetch_ticker_map; m=fetch_ticker_map(); print('SEC_MAP_OK', len(m), 'NVDA' in m, 'MSFT' in m, 'YPF' in m, 'PAMP' in m)"
if ($LASTEXITCODE -ne 0) { throw "SEC map smoke falló." }

Write-Host ""
Write-Host "[3/5] Live fundamentals sentinels"
python scripts\run_fundamentals_recovery.py --symbols NVDA MSFT YPF PAMP
if ($LASTEXITCODE -ne 0) {
    throw "DR1-B FIX1 live recovery quedó INCOMPLETE en al menos un sentinel."
}

Write-Host ""
Write-Host "[4/5] Audit gate"
$audit = Import-Csv (Join-Path $REC "outputs\data_recovery_v1\fundamentals_audit_latest.csv")
$required = @("roe","debt_equity","net_margin","revenue_growth","free_cash_flow")

foreach ($ticker in @("NVDA","MSFT","YPF","PAMP")) {
    foreach ($field in $required) {
        $row = $audit |
            Where-Object { $_.ticker -eq $ticker -and $_.field -eq $field } |
            Select-Object -First 1

        if (-not $row) {
            throw "AUDIT GATE: falta $ticker/$field"
        }
        if (-not $row.source) {
            throw "AUDIT GATE: source vacío $ticker/$field"
        }
        if (-not $row.status) {
            throw "AUDIT GATE: status vacío $ticker/$field"
        }

        if ($row.status -eq "MISSING") {
            Write-Host "  [WARN] $ticker/$field MISSING source=$($row.source)"
        } else {
            Write-Host "  [OK]   $ticker/$field source=$($row.source) status=$($row.status) fallback=$($row.fallback)"
        }
    }
}

Write-Host ""
Write-Host "[5/5] V13 immutability"
Set-Location $ROOT
$after = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
if (($before | Out-String) -ne ($after | Out-String)) {
    throw "GUARDRAIL: cambió V13 durante DR1-B FIX1."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "DR1-B FIX1 COMPLETE"
Write-Host "SEC GZIP: HANDLED"
Write-Host "FIELD AUDIT: ACTIVE"
Write-Host "V8/V10 SCORES: NOT IMPORTED"
Write-Host "V13: UNCHANGED"
Write-Host "SHEETS: UNCHANGED"
Write-Host "WEB: UNCHANGED"
Write-Host "PRODUCT STATE: NOT REGENERATED"
Write-Host "============================================================"
Write-Host ""
Write-Host "Pegame la salida completa."
