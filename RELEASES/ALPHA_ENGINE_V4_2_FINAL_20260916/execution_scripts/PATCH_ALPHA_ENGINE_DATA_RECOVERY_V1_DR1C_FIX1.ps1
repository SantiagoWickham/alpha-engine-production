$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-C FIX1"
Write-Host "TEST FIX ONLY: UNIQUE SYNTHETIC DATES FOR BETA/CORRELATION"
Write-Host "NO PRODUCTION MARKET LOGIC CHANGE"
Write-Host "NO V13 / SHEETS / WEB / PRODUCT STATE MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $REC)) { throw "No existe Recovery V1: $REC" }
if (-not (Test-Path $V13)) { throw "No existe V13: $V13" }

Set-Location $ROOT
$before = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"


@'
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.market_sheet_metrics import compute_sheet_market_metrics
from alpha_data_recovery.sheet_payloads import (
    FUND_HEADERS, MKT_HEADERS,
    FUND_SCORE_COLUMNS, MKT_SCORE_COLUMNS,
)
from alpha_data_recovery.universe_registry import load_universe


class TestDR1C(unittest.TestCase):
    def test_exact_legacy_payload_widths(self):
        self.assertEqual(len(FUND_HEADERS), 29)
        self.assertEqual(len(MKT_HEADERS), 41)

    def test_score_columns_are_explicitly_identified(self):
        self.assertEqual(len(FUND_SCORE_COLUMNS), 3)
        self.assertEqual(len(MKT_SCORE_COLUMNS), 9)
        self.assertIn("RISK SCORE", MKT_SCORE_COLUMNS)

    def test_market_extra_metrics(self):
        # Use unique, strictly increasing daily timestamps.
        # The previous synthetic test accidentally recycled only 28 calendar
        # dates, which is incompatible with date-aligned beta/correlation.
        rows = []
        start = datetime(2025, 1, 1, 20, 0, tzinfo=timezone.utc)
        for i in range(300):
            dt = start + timedelta(days=i)
            rows.append({
                "timestamp": dt.isoformat(),
                "epoch": int(dt.timestamp()),
                "adj_close": 100.0 + i,
                "close": 100.0 + i,
                "volume": 1000.0 + i,
            })

        self.assertEqual(
            len({r["timestamp"][:10] for r in rows}),
            300,
        )

        m = compute_sheet_market_metrics(rows, rows)
        self.assertIsNotNone(m["dist_sma20"])
        self.assertIsNotNone(m["avg_vol_20d"])
        self.assertAlmostEqual(m["rs_3m"], 0.0)
        self.assertAlmostEqual(m["beta_6m"], 1.0)
        self.assertAlmostEqual(m["corr_6m"], 1.0)

    def test_universe_loader(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "u.csv"
            p.write_text(
                "canonical_ticker,asset_class,motor,sector,benchmark,market_symbol,"
                "fundamentals_symbol,sec_ticker,country,active,note\n"
                "PAMP,Acción,Fundamental,Energia,^MERV,PAMP.BA,PAM,PAM,Argentina,SI,test\n",
                encoding="utf-8",
            )
            u = load_universe(p)[0]
            self.assertEqual(u.canonical_ticker, "PAMP")
            self.assertEqual(u.market_symbol, "PAMP.BA")
            self.assertEqual(u.fundamentals_symbol, "PAM")
            self.assertEqual(u.sec_ticker, "PAM")


if __name__ == "__main__":
    unittest.main()
'@ | Set-Content -Path (Join-Path $REC "tests\test_dr1c_staging.py") -Encoding UTF8

Write-Host ""
Write-Host "[1/6] Full unit tests"
Set-Location $REC
python -m unittest discover -s tests -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "Tests DR1-C FIX1 fallaron." }

Write-Host ""
Write-Host "[2/6] Full recovered-universe staging"
python scripts\run_dr1c_staging.py
if ($LASTEXITCODE -ne 0) { throw "DR1-C FIX1 structural staging failed." }

Write-Host ""
Write-Host "[3/6] Payload structural gate"
$STG = Join-Path $REC "outputs\data_recovery_v1\staging"
$fund = Import-Csv (Join-Path $STG "fundamentales_payload_latest.csv")
$mkt  = Import-Csv (Join-Path $STG "mercado_riesgo_payload_latest.csv")

if ($fund.Count -ne 187) { throw "FUND ROW GATE: $($fund.Count) != 187" }
if ($mkt.Count -ne 200) { throw "MKT ROW GATE: $($mkt.Count) != 200" }

if ($fund[0].PSObject.Properties.Count -ne 29) {
    throw "FUND WIDTH GATE: $($fund[0].PSObject.Properties.Count) != 29"
}
if ($mkt[0].PSObject.Properties.Count -ne 41) {
    throw "MKT WIDTH GATE: $($mkt[0].PSObject.Properties.Count) != 41"
}

Write-Host "  [OK] Fundamentales rows=187 cols=29"
Write-Host "  [OK] Mercado & Riesgo rows=200 cols=41"

Write-Host ""
Write-Host "[4/6] Forbidden-score blank gate"
$badFund = $fund | Where-Object {
    $_.'Score Calidad (Shrink)' -or
    $_.'Score Crecimiento (Shrink)' -or
    $_.'Score Valuación (Shrink)'
}
if ($badFund) { throw "FORBIDDEN SCORE GATE: DR1-C populated old fundamental scores." }

$badMkt = $mkt | Where-Object {
    $_.'Score Tendencia' -or
    $_.'Score RS' -or
    $_.'Score Participación' -or
    $_.'Score Mercado' -or
    $_.'Score Volatilidad' -or
    $_.'Score Tail Risk' -or
    $_.'Score Liquidez' -or
    $_.'Beta/Corr Info Score' -or
    $_.'RISK SCORE'
}
if ($badMkt) { throw "FORBIDDEN SCORE GATE: DR1-C populated old market/risk scores." }

Write-Host "  [OK] All V8/V10 score columns are blank"

Write-Host ""
Write-Host "[5/6] Coverage summary"
Get-Content (Join-Path $STG "recovery_coverage_summary.json")

Write-Host ""
Write-Host "[6/6] V13 immutability"
Set-Location $ROOT
$after = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
if (($before | Out-String) -ne ($after | Out-String)) {
    throw "GUARDRAIL: cambió V13 durante DR1-C FIX1."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "DR1-C FIX1 COMPLETE"
Write-Host "SYNTHETIC TEST DATES: FIXED"
Write-Host "PRODUCTION MARKET LOGIC: UNCHANGED"
Write-Host "V8 UNIVERSE: RECOVERED"
Write-Host "OLD SCORE COLUMNS: BLANK"
Write-Host "V13: UNCHANGED"
Write-Host "SHEETS: UNCHANGED"
Write-Host "WEB: UNCHANGED"
Write-Host "PRODUCT STATE: NOT REGENERATED"
Write-Host "============================================================"
Write-Host ""
Write-Host "Pegame desde [2/6] Full recovered-universe staging hasta el final."
