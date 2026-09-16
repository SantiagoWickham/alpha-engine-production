$ErrorActionPreference = "Stop"

$REC = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION\ALPHA_ENGINE_DATA_RECOVERY_V1"
$BRG = Join-Path $REC "sheets_bridge"
$SCR = Join-Path $REC "scripts"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DR1-D TIMEOUT FIX1"
Write-Host "LOCAL FILE PATCH ONLY"
Write-Host "NO GOOGLE SHEETS MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $REC)) { throw "No existe Recovery V1." }
New-Item -ItemType Directory -Force -Path $BRG | Out-Null
New-Item -ItemType Directory -Force -Path $SCR | Out-Null


@'
/**
 * ALPHA ENGINE - DATA RECOVERY V1 - DR1-D SAFE CHUNKED BRIDGE
 *
 * Replaces ONLY the previously added ALPHA_ENGINE_DATA_RECOVERY_V1_BRIDGE.gs.
 * Does NOT replace or modify the legacy V8.2 read-only bridge.
 *
 * Design:
 * - inspect is read-only
 * - dry-run is read-only
 * - backup is one target sheet per HTTP request
 * - clear is one bounded target range per HTTP request
 * - core writes are max 40 rows per request
 * - audit writes are max 500 rows per request
 * - every write validates headers and forbids old V8/V10 score values
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
  MAX_CORE_CHUNK: 40,
  MAX_AUDIT_CHUNK: 500,

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
    const body = dr1dParseBody_(e);
    dr1dValidateToken_(body.token);
    const action = String(body.action || '').trim();

    if (action === 'dr1d_inspect') return dr1dJson_(dr1dInspect_());
    if (action === 'dr1d_dry_run') return dr1dJson_(dr1dDryRun_(body));
    if (action === 'dr1d_backup_sheet') return dr1dJson_(dr1dBackupSheet_(body));
    if (action === 'dr1d_clear_target') return dr1dJson_(dr1dClearTarget_(body));
    if (action === 'dr1d_write_chunk') return dr1dJson_(dr1dWriteChunk_(body));
    if (action === 'dr1d_verify_target') return dr1dJson_(dr1dVerifyTarget_(body));
    if (action === 'dr1d_write_audit_chunk') return dr1dJson_(dr1dWriteAuditChunk_(body));
    if (action === 'dr1d_write_failures') return dr1dJson_(dr1dWriteFailures_(body));
    if (action === 'dr1d_finalize') return dr1dJson_(dr1dFinalize_(body));

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


function dr1dParseBody_(e) {
  if (!e || !e.postData || !e.postData.contents) throw new Error('EMPTY_POST_BODY');
  const obj = JSON.parse(e.postData.contents);
  if (!obj || typeof obj !== 'object') throw new Error('INVALID_JSON_BODY');
  return obj;
}


function dr1dValidateToken_(suppliedToken) {
  const expected = PropertiesService.getScriptProperties().getProperty(DR1D.TOKEN_PROPERTY);
  if (!expected) throw new Error('API_NOT_CONFIGURED');
  if (!suppliedToken || String(suppliedToken) !== expected) throw new Error('UNAUTHORIZED');
}


function dr1dSpreadsheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('NO_ACTIVE_SPREADSHEET');
  if (ss.getId() !== DR1D.EXPECTED_SPREADSHEET_ID) {
    throw new Error('WRONG_SPREADSHEET: ' + ss.getId());
  }
  return ss;
}


function dr1dSpec_(moduleName) {
  const m = String(moduleName || '').toLowerCase();
  if (m === 'fundamentals') {
    return {
      module: 'fundamentals',
      sheet: DR1D.FUND_SHEET,
      rows: DR1D.FUND_ROWS,
      cols: DR1D.FUND_COLS,
      headers: DR1D.FUND_HEADERS,
      scoreStart: 24,
      scoreEnd: 26,
      backupPrefix: 'DR1D_BKP_FUND_'
    };
  }
  if (m === 'market') {
    return {
      module: 'market',
      sheet: DR1D.MKT_SHEET,
      rows: DR1D.MKT_ROWS,
      cols: DR1D.MKT_COLS,
      headers: DR1D.MKT_HEADERS,
      scoreStart: 29,
      scoreEnd: 37,
      backupPrefix: 'DR1D_BKP_MKT_'
    };
  }
  throw new Error('INVALID_MODULE: ' + moduleName);
}


function dr1dReadHeaders_(sh, cols) {
  return sh.getRange(DR1D.HEADER_ROW, 1, 1, cols).getValues()[0]
    .map(v => String(v || '').trim());
}


function dr1dSameHeaders_(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (String(a[i] || '').trim() !== String(b[i] || '').trim()) return false;
  }
  return true;
}


function dr1dBlank_(v) {
  return v === null || v === undefined || v === '';
}


function dr1dValidateRows_(spec, rows, startIndex) {
  if (!Array.isArray(rows)) throw new Error('ROWS_NOT_ARRAY');
  if (rows.length < 1 || rows.length > DR1D.MAX_CORE_CHUNK) {
    throw new Error('INVALID_CORE_CHUNK_SIZE_' + rows.length);
  }
  if (!Number.isInteger(startIndex) || startIndex < 0 || startIndex + rows.length > spec.rows) {
    throw new Error('INVALID_START_INDEX_' + startIndex);
  }

  rows.forEach((r, i) => {
    if (!Array.isArray(r) || r.length !== spec.cols) {
      throw new Error('ROW_WIDTH_' + (startIndex + i));
    }
    for (let idx = spec.scoreStart; idx <= spec.scoreEnd; idx++) {
      if (!dr1dBlank_(r[idx])) {
        throw new Error('FORBIDDEN_V8_SCORE row=' + (startIndex + i) + ' col=' + idx);
      }
    }
  });
}


function dr1dInspectSheet_(ss, spec) {
  const sh = ss.getSheetByName(spec.sheet);
  if (!sh) return {exists:false, sheet:spec.sheet};

  const lastRow = sh.getLastRow();
  const headersOk = dr1dSameHeaders_(dr1dReadHeaders_(sh, spec.cols), spec.headers);
  const dataRows = Math.max(0, lastRow - DR1D.DATA_ROW + 1);
  const readRows = Math.min(dataRows, Math.max(spec.rows, dataRows));

  let nonblankTickerRows = 0;
  let firstTicker = null;
  let lastTicker = null;
  let scoreNonblank = 0;

  if (readRows > 0) {
    const vals = sh.getRange(DR1D.DATA_ROW, 1, readRows, spec.cols).getValues();
    vals.forEach(r => {
      const t = String(r[0] || '').trim();
      if (t) {
        nonblankTickerRows++;
        if (firstTicker === null) firstTicker = t;
        lastTicker = t;
      }
      for (let idx = spec.scoreStart; idx <= spec.scoreEnd; idx++) {
        if (!dr1dBlank_(r[idx])) scoreNonblank++;
      }
    });
  }

  return {
    exists: true,
    sheet: spec.sheet,
    last_row: lastRow,
    nonblank_ticker_rows: nonblankTickerRows,
    first_ticker: firstTicker,
    last_ticker: lastTicker,
    headers_ok: headersOk,
    old_score_nonblank_cells: scoreNonblank
  };
}


function dr1dInspect_() {
  const ss = dr1dSpreadsheet_();
  const fundSpec = dr1dSpec_('fundamentals');
  const mktSpec = dr1dSpec_('market');

  const backups = ss.getSheets()
    .map(s => s.getName())
    .filter(n => n.indexOf('DR1D_BKP_') === 0)
    .sort();

  return {
    ok: true,
    action: 'dr1d_inspect',
    spreadsheet_id: ss.getId(),
    fundamentals: dr1dInspectSheet_(ss, fundSpec),
    market: dr1dInspectSheet_(ss, mktSpec),
    backup_sheets: backups,
    audit_sheet_exists: !!ss.getSheetByName(DR1D.AUDIT_SHEET),
    failures_sheet_exists: !!ss.getSheetByName(DR1D.FAIL_SHEET),
    status_sheet_exists: !!ss.getSheetByName(DR1D.STATUS_SHEET),
    generated_at: new Date().toISOString()
  };
}


function dr1dDryRun_(body) {
  const ss = dr1dSpreadsheet_();
  const fundSpec = dr1dSpec_('fundamentals');
  const mktSpec = dr1dSpec_('market');

  const fh = (((body || {}).fundamentals || {}).headers) || [];
  const fr = (((body || {}).fundamentals || {}).rows) || [];
  const mh = (((body || {}).market || {}).headers) || [];
  const mr = (((body || {}).market || {}).rows) || [];

  if (!dr1dSameHeaders_(fh, fundSpec.headers) || fr.length !== fundSpec.rows) {
    throw new Error('FUND_PAYLOAD_INVALID');
  }
  if (!dr1dSameHeaders_(mh, mktSpec.headers) || mr.length !== mktSpec.rows) {
    throw new Error('MARKET_PAYLOAD_INVALID');
  }

  // Validate every row locally inside Apps Script, without writing.
  for (let start = 0; start < fr.length; start += DR1D.MAX_CORE_CHUNK) {
    dr1dValidateRows_(fundSpec, fr.slice(start, start + DR1D.MAX_CORE_CHUNK), start);
  }
  for (let start = 0; start < mr.length; start += DR1D.MAX_CORE_CHUNK) {
    dr1dValidateRows_(mktSpec, mr.slice(start, start + DR1D.MAX_CORE_CHUNK), start);
  }

  const fund = ss.getSheetByName(fundSpec.sheet);
  const mkt = ss.getSheetByName(mktSpec.sheet);
  if (!fund || !mkt) throw new Error('REQUIRED_SHEET_MISSING');
  if (!dr1dSameHeaders_(dr1dReadHeaders_(fund, fundSpec.cols), fundSpec.headers)) {
    throw new Error('FUNDAMENTALES_HEADER_MISMATCH');
  }
  if (!dr1dSameHeaders_(dr1dReadHeaders_(mkt, mktSpec.cols), mktSpec.headers)) {
    throw new Error('MERCADO_HEADER_MISMATCH');
  }

  return {
    ok: true,
    action: 'dr1d_dry_run',
    would_write: false,
    fundamentals: {rows:fr.length, cols:fh.length},
    market: {rows:mr.length, cols:mh.length},
    old_score_columns_blank: true,
    generated_at: new Date().toISOString()
  };
}


function dr1dBackupSheet_(body) {
  const ss = dr1dSpreadsheet_();
  const spec = dr1dSpec_(body.module);
  const sh = ss.getSheetByName(spec.sheet);
  if (!sh) throw new Error('SOURCE_SHEET_MISSING');

  const runId = String(body.run_id || '').replace(/[^0-9A-Za-z_-]/g, '');
  if (!runId) throw new Error('RUN_ID_REQUIRED');

  const name = spec.backupPrefix + runId;
  if (ss.getSheetByName(name)) {
    return {ok:true, action:'dr1d_backup_sheet', module:spec.module, backup:name, already_exists:true};
  }

  const lastRow = Math.max(DR1D.HEADER_ROW, sh.getLastRow());
  const nRows = lastRow - DR1D.HEADER_ROW + 1;
  const vals = sh.getRange(DR1D.HEADER_ROW, 1, nRows, spec.cols).getValues();

  const b = ss.insertSheet(name);
  b.getRange(1, 1, vals.length, spec.cols).setValues(vals);
  b.hideSheet();
  SpreadsheetApp.flush();

  return {
    ok:true,
    action:'dr1d_backup_sheet',
    module:spec.module,
    backup:name,
    rows:vals.length,
    cols:spec.cols,
    already_exists:false,
    generated_at:new Date().toISOString()
  };
}


function dr1dClearTarget_(body) {
  const ss = dr1dSpreadsheet_();
  const spec = dr1dSpec_(body.module);
  const sh = ss.getSheetByName(spec.sheet);
  if (!sh) throw new Error('TARGET_SHEET_MISSING');

  if (!dr1dSameHeaders_(dr1dReadHeaders_(sh, spec.cols), spec.headers)) {
    throw new Error('HEADER_MISMATCH_' + spec.module);
  }

  const existingDataRows = Math.max(0, sh.getLastRow() - DR1D.DATA_ROW + 1);
  const rowsToClear = Math.max(spec.rows, existingDataRows);

  if (rowsToClear > 0) {
    sh.getRange(DR1D.DATA_ROW, 1, rowsToClear, spec.cols).clearContent();
  }
  SpreadsheetApp.flush();

  return {
    ok:true,
    action:'dr1d_clear_target',
    module:spec.module,
    rows_cleared:rowsToClear,
    generated_at:new Date().toISOString()
  };
}


function dr1dWriteChunk_(body) {
  const ss = dr1dSpreadsheet_();
  const spec = dr1dSpec_(body.module);
  const sh = ss.getSheetByName(spec.sheet);
  if (!sh) throw new Error('TARGET_SHEET_MISSING');

  const startIndex = Number(body.start_index);
  const rows = body.rows || [];
  dr1dValidateRows_(spec, rows, startIndex);

  if (!dr1dSameHeaders_(dr1dReadHeaders_(sh, spec.cols), spec.headers)) {
    throw new Error('HEADER_MISMATCH_' + spec.module);
  }

  sh.getRange(DR1D.DATA_ROW + startIndex, 1, rows.length, spec.cols).setValues(rows);
  SpreadsheetApp.flush();

  return {
    ok:true,
    action:'dr1d_write_chunk',
    module:spec.module,
    start_index:startIndex,
    rows_written:rows.length,
    end_index:startIndex + rows.length - 1,
    generated_at:new Date().toISOString()
  };
}


function dr1dVerifyTarget_(body) {
  const ss = dr1dSpreadsheet_();
  const spec = dr1dSpec_(body.module);
  const sh = ss.getSheetByName(spec.sheet);
  if (!sh) throw new Error('TARGET_SHEET_MISSING');

  const vals = sh.getRange(DR1D.DATA_ROW, 1, spec.rows, spec.cols).getValues();

  let nonblankTickers = 0;
  let scoreNonblank = 0;
  vals.forEach(r => {
    if (String(r[0] || '').trim()) nonblankTickers++;
    for (let idx = spec.scoreStart; idx <= spec.scoreEnd; idx++) {
      if (!dr1dBlank_(r[idx])) scoreNonblank++;
    }
  });

  const expectedFirst = String(body.expected_first_ticker || '');
  const expectedLast = String(body.expected_last_ticker || '');
  const actualFirst = String(vals[0][0] || '');
  const actualLast = String(vals[vals.length - 1][0] || '');

  const pass =
    nonblankTickers === spec.rows &&
    scoreNonblank === 0 &&
    actualFirst === expectedFirst &&
    actualLast === expectedLast;

  return {
    ok:true,
    action:'dr1d_verify_target',
    module:spec.module,
    pass:pass,
    expected_rows:spec.rows,
    nonblank_ticker_rows:nonblankTickers,
    old_score_nonblank_cells:scoreNonblank,
    expected_first_ticker:expectedFirst,
    actual_first_ticker:actualFirst,
    expected_last_ticker:expectedLast,
    actual_last_ticker:actualLast,
    generated_at:new Date().toISOString()
  };
}


function dr1dWriteAuditChunk_(body) {
  const ss = dr1dSpreadsheet_();
  const rows = Array.isArray(body.rows) ? body.rows : [];
  if (rows.length > DR1D.MAX_AUDIT_CHUNK) throw new Error('AUDIT_CHUNK_TOO_LARGE');

  rows.forEach((r, i) => {
    if (!Array.isArray(r) || r.length !== DR1D.AUDIT_HEADERS.length) {
      throw new Error('AUDIT_ROW_WIDTH_' + i);
    }
  });

  let sh = ss.getSheetByName(DR1D.AUDIT_SHEET);
  if (!sh) sh = ss.insertSheet(DR1D.AUDIT_SHEET);

  if (body.reset === true) {
    sh.clearContents();
    sh.getRange(1, 1, 1, DR1D.AUDIT_HEADERS.length).setValues([DR1D.AUDIT_HEADERS]);
  } else if (sh.getLastRow() < 1) {
    sh.getRange(1, 1, 1, DR1D.AUDIT_HEADERS.length).setValues([DR1D.AUDIT_HEADERS]);
  }

  if (rows.length) {
    sh.getRange(sh.getLastRow() + 1, 1, rows.length, DR1D.AUDIT_HEADERS.length).setValues(rows);
  }

  sh.hideSheet();
  SpreadsheetApp.flush();

  return {
    ok:true,
    action:'dr1d_write_audit_chunk',
    appended:rows.length,
    total_rows:Math.max(0, sh.getLastRow() - 1),
    generated_at:new Date().toISOString()
  };
}


function dr1dWriteFailures_(body) {
  const ss = dr1dSpreadsheet_();
  const rows = Array.isArray(body.rows) ? body.rows : [];

  let sh = ss.getSheetByName(DR1D.FAIL_SHEET);
  if (!sh) sh = ss.insertSheet(DR1D.FAIL_SHEET);

  sh.clearContents();
  sh.getRange(1, 1, 1, DR1D.FAIL_HEADERS.length).setValues([DR1D.FAIL_HEADERS]);

  if (rows.length) {
    rows.forEach((r, i) => {
      if (!Array.isArray(r) || r.length !== DR1D.FAIL_HEADERS.length) {
        throw new Error('FAIL_ROW_WIDTH_' + i);
      }
    });
    sh.getRange(2, 1, rows.length, DR1D.FAIL_HEADERS.length).setValues(rows);
  }

  sh.hideSheet();
  SpreadsheetApp.flush();

  return {ok:true, action:'dr1d_write_failures', rows:rows.length, generated_at:new Date().toISOString()};
}


function dr1dFinalize_(body) {
  const ss = dr1dSpreadsheet_();
  let sh = ss.getSheetByName(DR1D.STATUS_SHEET);
  if (!sh) sh = ss.insertSheet(DR1D.STATUS_SHEET);

  const summary = body.summary || {};
  const rows = [
    ['key','value'],
    ['stage','ALPHA_ENGINE_DATA_RECOVERY_V1_DR1D'],
    ['written_at',new Date().toISOString()],
    ['market_asset_rows',String(((summary.market || {}).asset_rows) || '')],
    ['market_symbols_missing',String(((summary.market || {}).asset_symbols_missing) || '')],
    ['fundamental_rows',String(((summary.fundamentals || {}).rows) || '')],
    ['provider_failures',String(summary.provider_failures || 0)],
    ['v8_v10_scores_imported','false'],
    ['product_state_regenerated','false']
  ];

  sh.clearContents();
  sh.getRange(1, 1, rows.length, 2).setValues(rows);
  sh.hideSheet();
  SpreadsheetApp.flush();

  return {ok:true, action:'dr1d_finalize', finalized:true, generated_at:new Date().toISOString()};
}


function dr1dJson_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
'@ | Set-Content -Path (Join-Path $REC "sheets_bridge\ALPHA_ENGINE_DATA_RECOVERY_V1_BRIDGE.gs") -Encoding UTF8

@'
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
'@ | Set-Content -Path (Join-Path $REC "scripts\push_dr1d_to_sheets.py") -Encoding UTF8

@'
$ErrorActionPreference = "Stop"
$REC = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION\ALPHA_ENGINE_DATA_RECOVERY_V1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE - DR1-D INSPECT"
Write-Host "READ ONLY / NO SHEETS MUTATION"
Write-Host "============================================================"

$url = Read-Host "Pegá SOLO acá la Web App /exec URL"
if (-not $url.EndsWith("/exec")) { throw "URL inválida." }

$secure = Read-Host "Pegá SOLO acá el token MMM_API_TOKEN_V8" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)

try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $env:ALPHA_SHEETS_API_URL = $url
    $env:ALPHA_SHEETS_API_TOKEN = $token
    Set-Location $REC
    python scripts\push_dr1d_to_sheets.py --inspect
    if ($LASTEXITCODE -ne 0) { throw "Inspect falló." }
} finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    Remove-Item Env:ALPHA_SHEETS_API_URL -ErrorAction SilentlyContinue
    Remove-Item Env:ALPHA_SHEETS_API_TOKEN -ErrorAction SilentlyContinue
}
'@ | Set-Content -Path (Join-Path $REC "RUN_ALPHA_ENGINE_DR1D_INSPECT.ps1") -Encoding UTF8

@'
$ErrorActionPreference = "Stop"
$REC = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION\ALPHA_ENGINE_DATA_RECOVERY_V1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE - DR1-D SAFE CHUNKED COMMIT"
Write-Host "BACKUP -> CLEAR -> 40-ROW WRITES -> VERIFY -> AUDIT"
Write-Host "============================================================"

$url = Read-Host "Pegá SOLO acá la Web App /exec URL"
if (-not $url.EndsWith("/exec")) { throw "URL inválida." }

$secure = Read-Host "Pegá SOLO acá el token MMM_API_TOKEN_V8" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)

try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $env:ALPHA_SHEETS_API_URL = $url
    $env:ALPHA_SHEETS_API_TOKEN = $token
    Set-Location $REC
    python scripts\push_dr1d_to_sheets.py --commit-safe
    if ($LASTEXITCODE -ne 0) { throw "Safe commit falló." }
} finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    Remove-Item Env:ALPHA_SHEETS_API_URL -ErrorAction SilentlyContinue
    Remove-Item Env:ALPHA_SHEETS_API_TOKEN -ErrorAction SilentlyContinue
}
'@ | Set-Content -Path (Join-Path $REC "RUN_ALPHA_ENGINE_DR1D_SAFE_COMMIT.ps1") -Encoding UTF8

Write-Host ""
Write-Host "[OK] Updated local safe chunked bridge"
Write-Host "[OK] Updated Python sender"
Write-Host "[OK] Generated READ-ONLY inspect runner"
Write-Host "[OK] Generated safe chunked commit runner"
Write-Host ""
Write-Host "Google Sheets has NOT been touched."
Write-Host ""
Write-Host "NEXT:"
Write-Host "1. Replace ONLY the contents of the Apps Script file:"
Write-Host "   ALPHA_ENGINE_DATA_RECOVERY_V1_BRIDGE.gs"
Write-Host "2. Deploy a NEW VERSION of the SAME web-app deployment."
Write-Host "3. Run:"
Write-Host "   & `"$REC\RUN_ALPHA_ENGINE_DR1D_INSPECT.ps1`""
Write-Host "4. DO NOT run SAFE_COMMIT until inspect output is reviewed."
