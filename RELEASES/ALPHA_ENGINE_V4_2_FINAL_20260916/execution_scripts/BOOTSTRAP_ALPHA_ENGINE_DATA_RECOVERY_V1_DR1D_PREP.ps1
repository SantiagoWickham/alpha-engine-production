$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"
$STG  = Join-Path $REC "outputs\data_recovery_v1\staging"
$SEAL = Join-Path $REC "outputs\data_recovery_v1\seals"
$BRG  = Join-Path $REC "sheets_bridge"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-D PREP"
Write-Host "SEAL DR1-C + PREPARE SAFE SHEETS WRITE BRIDGE"
Write-Host "NO GOOGLE SHEETS MUTATION IN THIS SCRIPT"
Write-Host "NO V13 / WEB / PRODUCT STATE MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $REC)) { throw "No existe Recovery V1: $REC" }
if (-not (Test-Path $V13)) { throw "No existe V13: $V13" }
if (-not (Test-Path $STG)) { throw "No existe staging DR1-C: $STG" }

New-Item -ItemType Directory -Force -Path $SEAL | Out-Null
New-Item -ItemType Directory -Force -Path $BRG | Out-Null

Set-Location $ROOT
$before = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"

Write-Host ""
Write-Host "[1/4] Revalidate DR1-C staging"

$fundPath = Join-Path $STG "fundamentales_payload_latest.csv"
$mktPath  = Join-Path $STG "mercado_riesgo_payload_latest.csv"
$audPath  = Join-Path $STG "data_audit_long_latest.csv"
$failPath = Join-Path $STG "provider_failures_latest.csv"
$sumPath  = Join-Path $STG "recovery_coverage_summary.json"

$fund = Import-Csv $fundPath
$mkt = Import-Csv $mktPath

$fundCols = @($fund[0].PSObject.Properties).Count
$mktCols = @($mkt[0].PSObject.Properties).Count

if ($fund.Count -ne 187 -or $fundCols -ne 29) {
    throw "DR1-C FUND structural gate failed."
}
if ($mkt.Count -ne 200 -or $mktCols -ne 41) {
    throw "DR1-C MARKET structural gate failed."
}

$badFund = @($fund | Where-Object {
    $_.'Score Calidad (Shrink)' -or
    $_.'Score Crecimiento (Shrink)' -or
    $_.'Score Valuación (Shrink)'
})
if ($badFund.Count -gt 0) {
    throw "Old fundamental scores are not blank."
}

$badMkt = @($mkt | Where-Object {
    $_.'Score Tendencia' -or $_.'Score RS' -or
    $_.'Score Participación' -or $_.'Score Mercado' -or
    $_.'Score Volatilidad' -or $_.'Score Tail Risk' -or
    $_.'Score Liquidez' -or $_.'Beta/Corr Info Score' -or
    $_.'RISK SCORE'
})
if ($badMkt.Count -gt 0) {
    throw "Old market/risk scores are not blank."
}

Write-Host "  [OK] 187x29 fundamentals"
Write-Host "  [OK] 200x41 market/risk"
Write-Host "  [OK] old score columns blank"

Write-Host ""
Write-Host "[2/4] Seal DR1-C"

$summary = Get-Content $sumPath -Raw | ConvertFrom-Json

$hashes = [ordered]@{}
foreach ($p in @($fundPath,$mktPath,$audPath,$failPath,$sumPath)) {
    $hashes[[IO.Path]::GetFileName($p)] = (Get-FileHash $p -Algorithm SHA256).Hash.ToLower()
}

$manifest = [ordered]@{
    seal_id = "ALPHA_ENGINE_DATA_RECOVERY_V1_DR1C"
    sealed_at = (Get-Date).ToUniversalTime().ToString("o")
    structural_status = "PASS"
    market_asset_rows = 200
    market_missing = 0
    fundamental_rows = 187
    fundamental_ok = 185
    accepted_exceptions = @(
        [ordered]@{
            ticker = "ECOG"
            status = "INCOMPLETE"
            coverage = 0.50
            reason = "Provider-native limitation: Yahoo ECOG.BA lacks several required ratios; no SEC ticker configured."
            policy = "Keep missing fields blank and audited. No silent imputation."
        },
        [ordered]@{
            ticker = "SPCX"
            status = "PARTIAL"
            coverage = 0.75
            reason = "Provider-native limitation: several profitability/cash-flow ratios unavailable."
            policy = "Keep missing fields blank and audited. No silent imputation."
        }
    )
    v8_v10_scores_imported = $false
    per_datum_audit = $true
    files_sha256 = $hashes
    mutation_policy = [ordered]@{
        v13 = $false
        sheets = $false
        web = $false
        product_state = $false
    }
}

$sealPath = Join-Path $SEAL "dr1c_seal_manifest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content $sealPath -Encoding UTF8

Write-Host "  [OK] $sealPath"

Write-Host ""
Write-Host "[3/4] Install local DR1-D bridge assets"


@'
/**
 * ALPHA ENGINE - DATA RECOVERY V1 - DR1-D SHEETS BRIDGE
 *
 * PURPOSE
 * - Write ONLY recovered raw data to:
 *     Fundamentales
 *     Mercado & Riesgo
 * - Write per-datum audit to hidden sheet:
 *     _DATA_AUDIT_V1
 * - Write provider failures to hidden sheet:
 *     _PROVIDER_FAILURES_V1
 *
 * HARD GUARDRAILS
 * - Never calls recalcularV8 / actualizarCarteraMotorV8 / actualizarPortfolioV8.
 * - Never writes V8/V10 score values.
 * - Requires existing MMM_API_TOKEN_V8 from V8.2 API bridge.
 * - Requires dry-run before commit in the local sender.
 * - Creates data-only backups before core write.
 */

const DR1D = Object.freeze({
  EXPECTED_SPREADSHEET_ID: '1hcpEptfvm7fVMXZuuUnAdmY5eH0jv6nRPxtlaSe1-aI',
  TOKEN_PROPERTY: 'MMM_API_TOKEN_V8',

  FUND_SHEET: 'Fundamentales',
  MKT_SHEET: 'Mercado & Riesgo',
  AUDIT_SHEET: '_DATA_AUDIT_V1',
  FAIL_SHEET: '_PROVIDER_FAILURES_V1',
  STATUS_SHEET: '_DATA_RECOVERY_STATUS_V1',

  HEADER_ROW: 5,
  DATA_ROW: 6,

  FUND_ROWS: 187,
  FUND_COLS: 29,
  MKT_ROWS: 200,
  MKT_COLS: 41,

  FUND_HEADERS: [
    'Ticker','Nombre','Sector','Precio USD','Market Cap','P/E','Fwd P/E','PEG',
    'ROE','ROA','Debt/Eq','Margen Neto','EPS Growth','Revenue Growth','FCF',
    'FCF Yield','EV/EBITDA','Current Ratio','Quick Ratio','Dividend Yield',
    'Beta Yahoo','Target Price','Upside','Recom. Analistas',
    'Score Calidad (Shrink)','Score Crecimiento (Shrink)','Score Valuación (Shrink)',
    'Fuente','Price / Book'
  ],

  MKT_HEADERS: [
    'Ticker','Yahoo Symbol','Benchmark','Precio','Var 1D','Ret 1M','Ret 3M',
    'Ret 6M','Ret 12M','SMA20','SMA50','SMA200','Dist SMA20','Dist SMA50',
    'Dist SMA200','RSI14','Vol 20D','Vol 60D','Vol 1A','Downside Dev 60D',
    'Max Drawdown 1A','Avg Vol 20D','Dollar Vol 20D','Vol 20/60','RS 3M',
    'RS 6M','Beta 6M','Corr 6M','Dist 52W High','Score Tendencia','Score RS',
    'Score Participación','Score Mercado','Score Volatilidad','Score Tail Risk',
    'Score Liquidez','Beta/Corr Info Score','RISK SCORE','Cobertura Mercado',
    'Fuente','Actualización'
  ],

  AUDIT_HEADERS: [
    'ticker','module','provider_symbol','field','value',
    'source','asof','status','fallback','detail'
  ],

  FAIL_HEADERS: ['ticker','module','provider_symbol','error']
});


function doPost(e) {
  try {
    const body = parseDr1dBody_(e);
    validateDr1dToken_(body.token);

    const action = String(body.action || '').trim();

    if (action === 'dr1d_health') {
      return dr1dJson_(healthDr1d_());
    }

    if (action === 'dr1d_dry_run') {
      return dr1dJson_(dryRunDr1d_(body));
    }

    if (action === 'dr1d_write_core') {
      return dr1dJson_(writeCoreDr1d_(body));
    }

    if (action === 'dr1d_write_audit_chunk') {
      return dr1dJson_(writeAuditChunkDr1d_(body));
    }

    if (action === 'dr1d_write_failures') {
      return dr1dJson_(writeFailuresDr1d_(body));
    }

    if (action === 'dr1d_finalize') {
      return dr1dJson_(finalizeDr1d_(body));
    }

    throw new Error('UNKNOWN_DR1D_ACTION: ' + action);

  } catch (err) {
    return dr1dJson_({
      ok: false,
      error: 'DR1D_ERROR',
      message: String(err && err.message ? err.message : err),
      generated_at: new Date().toISOString()
    });
  }
}


function parseDr1dBody_(e) {
  if (!e || !e.postData || !e.postData.contents) {
    throw new Error('EMPTY_POST_BODY');
  }
  const obj = JSON.parse(e.postData.contents);
  if (!obj || typeof obj !== 'object') throw new Error('INVALID_JSON_BODY');
  return obj;
}


function validateDr1dToken_(suppliedToken) {
  const expected = PropertiesService.getScriptProperties()
    .getProperty(DR1D.TOKEN_PROPERTY);

  if (!expected) throw new Error('API_NOT_CONFIGURED');
  if (!suppliedToken || String(suppliedToken) !== expected) {
    throw new Error('UNAUTHORIZED');
  }
}


function activeDr1dSpreadsheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('NO_ACTIVE_SPREADSHEET');

  if (ss.getId() !== DR1D.EXPECTED_SPREADSHEET_ID) {
    throw new Error(
      'WRONG_SPREADSHEET: expected=' +
      DR1D.EXPECTED_SPREADSHEET_ID +
      ' actual=' + ss.getId()
    );
  }

  return ss;
}


function healthDr1d_() {
  const ss = activeDr1dSpreadsheet_();
  const fund = ss.getSheetByName(DR1D.FUND_SHEET);
  const mkt = ss.getSheetByName(DR1D.MKT_SHEET);

  if (!fund || !mkt) throw new Error('REQUIRED_SHEET_MISSING');

  return {
    ok: true,
    action: 'dr1d_health',
    spreadsheet_id: ss.getId(),
    spreadsheet_name: ss.getName(),
    fund_headers_ok: sameHeadersDr1d_(
      readHeadersDr1d_(fund, DR1D.FUND_COLS),
      DR1D.FUND_HEADERS
    ),
    market_headers_ok: sameHeadersDr1d_(
      readHeadersDr1d_(mkt, DR1D.MKT_COLS),
      DR1D.MKT_HEADERS
    ),
    mode: 'RAW_DATA_WRITE_ONLY',
    v8_scores_allowed: false,
    generated_at: new Date().toISOString()
  };
}


function dryRunDr1d_(body) {
  const ss = activeDr1dSpreadsheet_();
  const fund = ss.getSheetByName(DR1D.FUND_SHEET);
  const mkt = ss.getSheetByName(DR1D.MKT_SHEET);

  if (!fund || !mkt) throw new Error('REQUIRED_SHEET_MISSING');

  validateCorePayloadDr1d_(body);

  const fundHeaders = readHeadersDr1d_(fund, DR1D.FUND_COLS);
  const mktHeaders = readHeadersDr1d_(mkt, DR1D.MKT_COLS);

  if (!sameHeadersDr1d_(fundHeaders, DR1D.FUND_HEADERS)) {
    throw new Error('FUNDAMENTALES_HEADER_MISMATCH');
  }
  if (!sameHeadersDr1d_(mktHeaders, DR1D.MKT_HEADERS)) {
    throw new Error('MERCADO_HEADER_MISMATCH');
  }

  return {
    ok: true,
    action: 'dr1d_dry_run',
    would_write: false,
    fundamentals: {
      rows: body.fundamentals.rows.length,
      cols: body.fundamentals.headers.length
    },
    market: {
      rows: body.market.rows.length,
      cols: body.market.headers.length
    },
    old_score_columns_blank: true,
    spreadsheet_id: ss.getId(),
    generated_at: new Date().toISOString()
  };
}


function writeCoreDr1d_(body) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) throw new Error('LOCK_TIMEOUT');

  try {
    const ss = activeDr1dSpreadsheet_();
    const fund = ss.getSheetByName(DR1D.FUND_SHEET);
    const mkt = ss.getSheetByName(DR1D.MKT_SHEET);

    if (!fund || !mkt) throw new Error('REQUIRED_SHEET_MISSING');

    validateCorePayloadDr1d_(body);

    if (!sameHeadersDr1d_(
      readHeadersDr1d_(fund, DR1D.FUND_COLS),
      DR1D.FUND_HEADERS
    )) {
      throw new Error('FUNDAMENTALES_HEADER_MISMATCH');
    }

    if (!sameHeadersDr1d_(
      readHeadersDr1d_(mkt, DR1D.MKT_COLS),
      DR1D.MKT_HEADERS
    )) {
      throw new Error('MERCADO_HEADER_MISMATCH');
    }

    const stamp = Utilities.formatDate(
      new Date(),
      Session.getScriptTimeZone() || 'America/Argentina/Buenos_Aires',
      'yyyyMMdd_HHmmss'
    );

    backupRangeDr1d_(
      ss,
      fund,
      DR1D.FUND_COLS,
      'DR1D_BKP_FUND_' + stamp
    );

    backupRangeDr1d_(
      ss,
      mkt,
      DR1D.MKT_COLS,
      'DR1D_BKP_MKT_' + stamp
    );

    clearDataDr1d_(fund, DR1D.FUND_COLS);
    clearDataDr1d_(mkt, DR1D.MKT_COLS);

    fund.getRange(
      DR1D.DATA_ROW, 1,
      body.fundamentals.rows.length,
      DR1D.FUND_COLS
    ).setValues(body.fundamentals.rows);

    mkt.getRange(
      DR1D.DATA_ROW, 1,
      body.market.rows.length,
      DR1D.MKT_COLS
    ).setValues(body.market.rows);

    SpreadsheetApp.flush();

    return {
      ok: true,
      action: 'dr1d_write_core',
      written: true,
      fundamentals_rows: body.fundamentals.rows.length,
      market_rows: body.market.rows.length,
      backup_stamp: stamp,
      generated_at: new Date().toISOString()
    };

  } finally {
    lock.releaseLock();
  }
}


function writeAuditChunkDr1d_(body) {
  const ss = activeDr1dSpreadsheet_();
  const rows = Array.isArray(body.rows) ? body.rows : [];
  if (rows.length > 1500) throw new Error('AUDIT_CHUNK_TOO_LARGE');

  rows.forEach((r, i) => {
    if (!Array.isArray(r) || r.length !== DR1D.AUDIT_HEADERS.length) {
      throw new Error('AUDIT_ROW_WIDTH_' + i);
    }
  });

  let sh = ss.getSheetByName(DR1D.AUDIT_SHEET);
  if (!sh) sh = ss.insertSheet(DR1D.AUDIT_SHEET);

  if (body.reset === true) {
    sh.clearContents();
    sh.getRange(1, 1, 1, DR1D.AUDIT_HEADERS.length)
      .setValues([DR1D.AUDIT_HEADERS]);
  }

  if (sh.getLastRow() < 1) {
    sh.getRange(1, 1, 1, DR1D.AUDIT_HEADERS.length)
      .setValues([DR1D.AUDIT_HEADERS]);
  }

  if (rows.length) {
    sh.getRange(
      sh.getLastRow() + 1,
      1,
      rows.length,
      DR1D.AUDIT_HEADERS.length
    ).setValues(rows);
  }

  sh.hideSheet();

  return {
    ok: true,
    action: 'dr1d_write_audit_chunk',
    appended: rows.length,
    total_rows: Math.max(0, sh.getLastRow() - 1),
    generated_at: new Date().toISOString()
  };
}


function writeFailuresDr1d_(body) {
  const ss = activeDr1dSpreadsheet_();
  const rows = Array.isArray(body.rows) ? body.rows : [];

  rows.forEach((r, i) => {
    if (!Array.isArray(r) || r.length !== DR1D.FAIL_HEADERS.length) {
      throw new Error('FAIL_ROW_WIDTH_' + i);
    }
  });

  let sh = ss.getSheetByName(DR1D.FAIL_SHEET);
  if (!sh) sh = ss.insertSheet(DR1D.FAIL_SHEET);

  sh.clearContents();
  sh.getRange(1, 1, 1, DR1D.FAIL_HEADERS.length)
    .setValues([DR1D.FAIL_HEADERS]);

  if (rows.length) {
    sh.getRange(2, 1, rows.length, DR1D.FAIL_HEADERS.length)
      .setValues(rows);
  }

  sh.hideSheet();

  return {
    ok: true,
    action: 'dr1d_write_failures',
    rows: rows.length,
    generated_at: new Date().toISOString()
  };
}


function finalizeDr1d_(body) {
  const ss = activeDr1dSpreadsheet_();

  let sh = ss.getSheetByName(DR1D.STATUS_SHEET);
  if (!sh) sh = ss.insertSheet(DR1D.STATUS_SHEET);

  const summary = body.summary || {};

  sh.clearContents();
  sh.getRange(1, 1, 1, 2).setValues([['key','value']]);

  const rows = [
    ['stage', 'ALPHA_ENGINE_DATA_RECOVERY_V1_DR1D'],
    ['written_at', new Date().toISOString()],
    ['market_asset_rows', String(((summary.market || {}).asset_rows) || '')],
    ['market_symbols_missing', String(((summary.market || {}).asset_symbols_missing) || '')],
    ['fundamental_rows', String(((summary.fundamentals || {}).rows) || '')],
    ['provider_failures', String(summary.provider_failures || 0)],
    ['v8_v10_scores_imported', 'false'],
    ['product_state_regenerated', 'false']
  ];

  sh.getRange(2, 1, rows.length, 2).setValues(rows);
  sh.hideSheet();

  return {
    ok: true,
    action: 'dr1d_finalize',
    finalized: true,
    generated_at: new Date().toISOString()
  };
}


function validateCorePayloadDr1d_(body) {
  if (!body.fundamentals || !body.market) {
    throw new Error('CORE_PAYLOAD_MISSING');
  }

  const fh = body.fundamentals.headers || [];
  const fr = body.fundamentals.rows || [];
  const mh = body.market.headers || [];
  const mr = body.market.rows || [];

  if (!sameHeadersDr1d_(fh, DR1D.FUND_HEADERS)) {
    throw new Error('PAYLOAD_FUND_HEADERS_INVALID');
  }
  if (!sameHeadersDr1d_(mh, DR1D.MKT_HEADERS)) {
    throw new Error('PAYLOAD_MKT_HEADERS_INVALID');
  }

  if (fr.length !== DR1D.FUND_ROWS) {
    throw new Error('PAYLOAD_FUND_ROWS_' + fr.length);
  }
  if (mr.length !== DR1D.MKT_ROWS) {
    throw new Error('PAYLOAD_MKT_ROWS_' + mr.length);
  }

  fr.forEach((r, i) => {
    if (!Array.isArray(r) || r.length !== DR1D.FUND_COLS) {
      throw new Error('PAYLOAD_FUND_WIDTH_ROW_' + i);
    }

    // Zero-based indices 24,25,26 = old V8 fundamental scores.
    [24,25,26].forEach(idx => {
      if (!blankDr1d_(r[idx])) {
        throw new Error(
          'FORBIDDEN_V8_FUND_SCORE row=' + i + ' col=' + idx
        );
      }
    });
  });

  mr.forEach((r, i) => {
    if (!Array.isArray(r) || r.length !== DR1D.MKT_COLS) {
      throw new Error('PAYLOAD_MKT_WIDTH_ROW_' + i);
    }

    // Zero-based indices 29..37 = old V8 market/risk scores.
    for (let idx = 29; idx <= 37; idx++) {
      if (!blankDr1d_(r[idx])) {
        throw new Error(
          'FORBIDDEN_V8_MKT_SCORE row=' + i + ' col=' + idx
        );
      }
    }
  });
}


function backupRangeDr1d_(ss, sourceSheet, colCount, backupName) {
  if (ss.getSheetByName(backupName)) {
    throw new Error('BACKUP_NAME_COLLISION: ' + backupName);
  }

  const b = ss.insertSheet(backupName);
  const lastRow = Math.max(DR1D.HEADER_ROW, sourceSheet.getLastRow());

  const values = sourceSheet
    .getRange(DR1D.HEADER_ROW, 1, lastRow - DR1D.HEADER_ROW + 1, colCount)
    .getValues();

  if (values.length) {
    b.getRange(1, 1, values.length, colCount).setValues(values);
  }

  b.hideSheet();
}


function clearDataDr1d_(sh, colCount) {
  const n = sh.getMaxRows() - DR1D.DATA_ROW + 1;
  if (n > 0) {
    sh.getRange(DR1D.DATA_ROW, 1, n, colCount).clearContent();
  }
}


function readHeadersDr1d_(sh, colCount) {
  return sh.getRange(DR1D.HEADER_ROW, 1, 1, colCount)
    .getValues()[0]
    .map(v => String(v || '').trim());
}


function sameHeadersDr1d_(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b)) return false;
  if (a.length !== b.length) return false;

  for (let i = 0; i < a.length; i++) {
    if (String(a[i] || '').trim() !== String(b[i] || '').trim()) return false;
  }
  return true;
}


function blankDr1d_(v) {
  return v === null || v === undefined || v === '';
}


function dr1dJson_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
'@ | Set-Content -Path (Join-Path $REC "sheets_bridge\ALPHA_ENGINE_DATA_RECOVERY_V1_BRIDGE.gs") -Encoding UTF8

@'
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "outputs" / "data_recovery_v1" / "staging"


def read_csv_matrix(path: Path) -> tuple[list[str], list[list[object]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)

    if not rows:
        raise RuntimeError(f"empty CSV: {path}")

    headers = rows[0]

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

    return headers, [[convert(x) for x in row] for row in rows[1:]]


def post_json(url: str, payload: dict) -> dict:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=120) as resp:
            text = resp.read().decode("utf-8")
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {text}") from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc}") from exc

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Non-JSON response: {text[:500]}") from exc

    if not obj.get("ok"):
        raise RuntimeError(json.dumps(obj, ensure_ascii=False))
    return obj


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--url",
        default=os.getenv("ALPHA_SHEETS_API_URL", ""),
    )
    p.add_argument(
        "--token",
        default=os.getenv("ALPHA_SHEETS_API_TOKEN", ""),
    )
    p.add_argument(
        "--commit",
        action="store_true",
        help="Actually write Sheets. Without this flag: DRY RUN ONLY.",
    )
    args = p.parse_args()

    if not args.url:
        raise RuntimeError(
            "Missing ALPHA_SHEETS_API_URL or --url. "
            "Use your deployed Apps Script /exec URL."
        )
    if not args.token:
        raise RuntimeError(
            "Missing ALPHA_SHEETS_API_TOKEN or --token. "
            "Do not paste the token into chat."
        )

    fund_h, fund_r = read_csv_matrix(
        STAGING / "fundamentales_payload_latest.csv"
    )
    mkt_h, mkt_r = read_csv_matrix(
        STAGING / "mercado_riesgo_payload_latest.csv"
    )
    audit_h, audit_r = read_csv_matrix(
        STAGING / "data_audit_long_latest.csv"
    )
    fail_h, fail_r = read_csv_matrix(
        STAGING / "provider_failures_latest.csv"
    )
    summary = json.loads(
        (STAGING / "recovery_coverage_summary.json").read_text(
            encoding="utf-8"
        )
    )

    if len(fund_r) != 187 or len(fund_h) != 29:
        raise RuntimeError("Fundamentales local structural gate failed")
    if len(mkt_r) != 200 or len(mkt_h) != 41:
        raise RuntimeError("Mercado local structural gate failed")
    if audit_h != [
        "ticker","module","provider_symbol","field","value",
        "source","asof","status","fallback","detail"
    ]:
        raise RuntimeError("Audit header mismatch")

    base = {
        "token": args.token,
        "fundamentals": {"headers": fund_h, "rows": fund_r},
        "market": {"headers": mkt_h, "rows": mkt_r},
    }

    print("[1/2] REMOTE DRY RUN")
    dry = post_json(
        args.url,
        {**base, "action": "dr1d_dry_run"},
    )
    print(json.dumps(dry, indent=2, ensure_ascii=False))

    if not args.commit:
        print("")
        print("DRY RUN PASS. SHEETS NOT MUTATED.")
        print(
            "When approved locally, rerun with --commit. "
            "The sender will backup core ranges first."
        )
        return 0

    print("")
    print("[2/2] COMMIT")
    core = post_json(
        args.url,
        {**base, "action": "dr1d_write_core"},
    )
    print(json.dumps(core, indent=2, ensure_ascii=False))

    chunk_size = 1000
    for start in range(0, len(audit_r), chunk_size):
        chunk = audit_r[start:start + chunk_size]
        r = post_json(
            args.url,
            {
                "token": args.token,
                "action": "dr1d_write_audit_chunk",
                "reset": start == 0,
                "rows": chunk,
            },
        )
        print(
            f"audit {min(start + len(chunk), len(audit_r))}/"
            f"{len(audit_r)} total_remote={r.get('total_rows')}"
        )

    post_json(
        args.url,
        {
            "token": args.token,
            "action": "dr1d_write_failures",
            "rows": fail_r,
        },
    )

    final = post_json(
        args.url,
        {
            "token": args.token,
            "action": "dr1d_finalize",
            "summary": summary,
        },
    )

    print(json.dumps(final, indent=2, ensure_ascii=False))
    print("")
    print("DR1-D COMMIT COMPLETE")
    print("Fundamentales + Mercado & Riesgo written.")
    print("Detailed audit written to hidden _DATA_AUDIT_V1.")
    print("V8/V10 score columns remained blank.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'@ | Set-Content -Path (Join-Path $REC "scripts\push_dr1d_to_sheets.py") -Encoding UTF8

Write-Host "  [OK] sheets_bridge\ALPHA_ENGINE_DATA_RECOVERY_V1_BRIDGE.gs"
Write-Host "  [OK] scripts\push_dr1d_to_sheets.py"

Write-Host ""
Write-Host "[4/4] V13 immutability"
Set-Location $ROOT
$after = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
if (($before | Out-String) -ne ($after | Out-String)) {
    throw "GUARDRAIL: cambió V13 durante DR1-D PREP."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "DR1-D PREP COMPLETE"
Write-Host "DR1-C: SEALED"
Write-Host "ECOG: ACCEPTED AUDITED EXCEPTION"
Write-Host "SPCX: ACCEPTED AUDITED EXCEPTION"
Write-Host "SHEETS BRIDGE: PREPARED, NOT DEPLOYED"
Write-Host "SHEETS: UNCHANGED"
Write-Host "V13: UNCHANGED"
Write-Host "WEB: UNCHANGED"
Write-Host "PRODUCT STATE: NOT REGENERATED"
Write-Host "============================================================"
Write-Host ""
Write-Host "NEXT MANUAL STEP:"
Write-Host "Open the Google Sheet Apps Script project."
Write-Host "Create a NEW .gs file and paste the contents of:"
Write-Host "  $BRG\ALPHA_ENGINE_DATA_RECOVERY_V1_BRIDGE.gs"
Write-Host "Do NOT delete the old V8.2 read-only bridge."
Write-Host "Then deploy a new Web App version using the same deployment."
Write-Host ""
Write-Host "NO token or deployment URL should be pasted into ChatGPT."
