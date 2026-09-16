$ErrorActionPreference = "Stop"

$REC = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION\ALPHA_ENGINE_DATA_RECOVERY_V1"
$BRIDGE = Join-Path $REC "sheets_bridge\ALPHA_ENGINE_DATA_RECOVERY_V1_BRIDGE.gs"
$PY = Join-Path $REC "scripts\run_dr1e_guard.py"
$RUN = Join-Path $REC "RUN_ALPHA_ENGINE_DR1E_GUARD.ps1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE - DR1-E LOCAL PREP"
Write-Host "PATCH BRIDGE + INSTALL GUARD RUNNER"
Write-Host "NO GOOGLE SHEETS MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $BRIDGE)) { throw "No existe bridge DR1-D: $BRIDGE" }

$text = Get-Content $BRIDGE -Raw

if ($text -notmatch "dr1e_inspect") {
    $needle = "    if (action === 'dr1d_finalize') return dr1dJson_(dr1dFinalize_(body));"
    if (-not $text.Contains($needle)) {
        throw "No pude localizar el router DR1-D para insertar DR1-E."
    }

    $replacement = @"
$needle
    if (action === 'dr1e_inspect') return dr1dJson_(dr1eInspect_(body));
    if (action === 'dr1e_disable_legacy_triggers') return dr1dJson_(dr1eDisableLegacyTriggers_());
"@

    $text = $text.Replace($needle, $replacement)

    $text = $text.TrimEnd() + "`r`n`r`n" + @'
/* =====================================================================
 * DR1-E - LEGACY TRIGGER GUARD + SENTINEL DATA INSPECTION
 * ===================================================================== */

const DR1E_LEGACY_TRIGGER_HANDLERS = Object.freeze([
  'actualizarPreciosV8',
  'actualizarMercadoV8',
  'actualizarFundamentalesV8',
  'cierreDiarioV8_',
  'actualizarReturnsExportV8_',
  'guardarSnapshotPortfolioV8',
  'actualizarTodoV8_Etapa2_',
  'actualizarTodoV8_Etapa3_',
  'actualizarPreciosV7',
  'actualizarMercadoV7',
  'actualizarFundamentalesV7',
  'cierreDiarioV7_'
]);


// PUBLIC MANUAL SAFETY SWITCH.
// Run this once from the Apps Script editor immediately after saving DR1-E.
// It changes triggers only; it does NOT write spreadsheet cells.
function DR1E_DISABLE_LEGACY_AUTOMATION_NOW() {
  const result = dr1eDisableLegacyTriggers_();
  console.log(JSON.stringify(result, null, 2));
  SpreadsheetApp.getActive().toast(
    'DR1-E: automatización V7/V8 desactivada. Triggers eliminados: ' +
      result.deleted.length,
    'ALPHA ENGINE',
    10
  );
  return result;
}


function dr1eTriggerInventory_() {
  return ScriptApp.getProjectTriggers().map(t => ({
    handler: t.getHandlerFunction(),
    event_type: String(t.getEventType()),
    trigger_source: String(t.getTriggerSource()),
    unique_id: String(t.getUniqueId ? t.getUniqueId() : '')
  }));
}


function dr1eSelectedRows_(sheetName, headers, dataRows, requestedTickers, wantedHeaders) {
  const ss = dr1dSpreadsheet_();
  const sh = ss.getSheetByName(sheetName);
  if (!sh) throw new Error('SHEET_NOT_FOUND: ' + sheetName);

  const values = sh.getRange(DR1D.DATA_ROW, 1, dataRows, headers.length).getValues();
  const hmap = {};
  headers.forEach((h, i) => hmap[h] = i);

  const wanted = {};
  (requestedTickers || []).forEach(t => wanted[String(t || '').trim().toUpperCase()] = true);

  const out = {};
  values.forEach(r => {
    const ticker = String(r[0] || '').trim().toUpperCase();
    if (!ticker || !wanted[ticker]) return;

    const row = {};
    wantedHeaders.forEach(h => {
      const idx = hmap[h];
      row[h] = idx === undefined ? null : dr1eJsonValue_(r[idx]);
    });
    out[ticker] = row;
  });

  return out;
}


function dr1eJsonValue_(v) {
  if (v instanceof Date) return v.toISOString();
  if (typeof v === 'number') return isFinite(v) ? v : null;
  if (v === undefined) return null;
  return v;
}


function dr1eInspect_(body) {
  const ss = dr1dSpreadsheet_();
  const requested = Array.isArray(body.tickers) ? body.tickers : [];

  const triggers = dr1eTriggerInventory_();
  const risky = triggers.filter(t => DR1E_LEGACY_TRIGGER_HANDLERS.indexOf(t.handler) >= 0);

  const marketFields = [
    'Ticker','Yahoo Symbol','Precio','Var 1D','Ret 1M',
    'SMA20','Beta 6M','Cobertura Mercado','Fuente'
  ];
  const fundFields = [
    'Ticker','Nombre','Precio USD','Market Cap','P/E',
    'ROE','Revenue Growth','Fuente'
  ];

  return {
    ok: true,
    action: 'dr1e_inspect',
    spreadsheet_id: ss.getId(),
    requested_tickers: requested,
    triggers: triggers,
    risky_legacy_triggers: risky,
    market: dr1eSelectedRows_(
      DR1D.MKT_SHEET,
      DR1D.MKT_HEADERS,
      DR1D.MKT_ROWS,
      requested,
      marketFields
    ),
    fundamentals: dr1eSelectedRows_(
      DR1D.FUND_SHEET,
      DR1D.FUND_HEADERS,
      DR1D.FUND_ROWS,
      requested,
      fundFields
    ),
    generated_at: new Date().toISOString()
  };
}


function dr1eDisableLegacyTriggers_() {
  const before = dr1eTriggerInventory_();
  const deleted = [];

  ScriptApp.getProjectTriggers().forEach(t => {
    const handler = t.getHandlerFunction();
    if (DR1E_LEGACY_TRIGGER_HANDLERS.indexOf(handler) >= 0) {
      deleted.push({
        handler: handler,
        event_type: String(t.getEventType()),
        trigger_source: String(t.getTriggerSource()),
        unique_id: String(t.getUniqueId ? t.getUniqueId() : '')
      });
      ScriptApp.deleteTrigger(t);
    }
  });

  const after = dr1eTriggerInventory_();
  const riskyAfter = after.filter(t => DR1E_LEGACY_TRIGGER_HANDLERS.indexOf(t.handler) >= 0);

  PropertiesService.getScriptProperties().setProperty(
    'DR1E_LEGACY_AUTOMATION_DISABLED_AT',
    new Date().toISOString()
  );

  return {
    ok: true,
    action: 'dr1e_disable_legacy_triggers',
    before_count: before.length,
    deleted: deleted,
    after_count: after.length,
    risky_remaining: riskyAfter,
    generated_at: new Date().toISOString()
  };
}
'@
    Set-Content -Path $BRIDGE -Value $text -Encoding UTF8
    Write-Host "[OK] DR1-E actions appended to local bridge."
} else {
    Write-Host "[OK] Local bridge already contains DR1-E actions."
}

@'
from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "outputs" / "data_recovery_v1" / "staging"
OUT = ROOT / "outputs" / "data_recovery_v1" / "dr1e_guard_report.json"

SENTINELS = ["SPY", "NVDA", "MSFT", "NKE", "PAMP", "YPF", "ECOG", "SPCX"]

MARKET_FIELDS = [
    "Ticker", "Yahoo Symbol", "Precio", "Var 1D", "Ret 1M",
    "SMA20", "Beta 6M", "Cobertura Mercado", "Fuente",
]
FUND_FIELDS = [
    "Ticker", "Nombre", "Precio USD", "Market Cap", "P/E",
    "ROE", "Revenue Growth", "Fuente",
]


def read_csv_dict(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {
        str(r.get("Ticker", "")).strip().upper(): r
        for r in rows
        if str(r.get("Ticker", "")).strip()
    }


def post(url: str, token: str, action: str, **extra) -> dict:
    payload = {"token": token, "action": action, **extra}
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=90) as resp:
            text = resp.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:700]}") from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc}") from exc

    obj = json.loads(text)
    if not obj.get("ok"):
        raise RuntimeError(json.dumps(obj, ensure_ascii=False))
    return obj


def blank(x) -> bool:
    return x is None or str(x).strip() == ""


def to_float(x):
    if blank(x):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def equal_value(local, remote) -> bool:
    if blank(local) and blank(remote):
        return True

    lf = to_float(local)
    rf = to_float(remote)
    if lf is not None and rf is not None:
        tol = max(1e-9, 1e-8 * max(1.0, abs(lf), abs(rf)))
        return abs(lf - rf) <= tol

    return str(local).strip() == str(remote).strip()


def compare_module(name, local_map, remote_map, fields):
    mismatches = []
    checked = 0

    for ticker in SENTINELS:
        local = local_map.get(ticker)
        remote = remote_map.get(ticker)

        # Not every sentinel belongs to both modules.
        if local is None:
            continue

        if remote is None:
            mismatches.append({
                "module": name,
                "ticker": ticker,
                "field": "__row__",
                "local": "present",
                "remote": "missing",
            })
            continue

        for field in fields:
            checked += 1
            lv = local.get(field)
            rv = remote.get(field)
            if not equal_value(lv, rv):
                mismatches.append({
                    "module": name,
                    "ticker": ticker,
                    "field": field,
                    "local": lv,
                    "remote": rv,
                })

    return checked, mismatches


def compact_market(snapshot):
    rows = []
    for ticker in SENTINELS:
        r = snapshot.get("market", {}).get(ticker)
        if not r:
            continue
        rows.append({
            "ticker": ticker,
            "symbol": r.get("Yahoo Symbol"),
            "price": r.get("Precio"),
            "var1d": r.get("Var 1D"),
            "source": r.get("Fuente"),
        })
    return rows


def main() -> int:
    url = os.getenv("ALPHA_SHEETS_API_URL", "")
    token = os.getenv("ALPHA_SHEETS_API_TOKEN", "")
    if not url or not token:
        raise RuntimeError("Missing URL/token")

    local_market = read_csv_dict(STAGING / "mercado_riesgo_payload_latest.csv")
    local_fund = read_csv_dict(STAGING / "fundamentales_payload_latest.csv")

    print("[1/4] INSPECT DATA + TRIGGERS (READ ONLY)")
    before = post(
        url, token, "dr1e_inspect", tickers=SENTINELS
    )

    print(f"  total project triggers: {len(before.get('triggers', []))}")
    risky = before.get("risky_legacy_triggers", [])
    print(f"  risky legacy triggers: {len(risky)}")
    for t in risky:
        print(f"    - {t.get('handler')} [{t.get('event_type')}]")

    print("")
    print("  sentinel market snapshot:")
    for r in compact_market(before):
        print(
            f"    {r['ticker']:5s} symbol={str(r['symbol']):10s} "
            f"price={r['price']} var1d={r['var1d']} source={r['source']}"
        )

    print("")
    print("[2/4] COMPARE REMOTE SHEET VS SEALED LOCAL STAGING")
    m_checked, m_bad = compare_module(
        "market", local_market, before.get("market", {}), MARKET_FIELDS
    )
    f_checked, f_bad = compare_module(
        "fundamentals", local_fund, before.get("fundamentals", {}), FUND_FIELDS
    )
    mismatches = m_bad + f_bad

    print(f"  market critical cells checked: {m_checked}")
    print(f"  fundamental critical cells checked: {f_checked}")
    print(f"  mismatches: {len(mismatches)}")

    if mismatches:
        for x in mismatches[:20]:
            print(
                f"    MISMATCH {x['module']} {x['ticker']} {x['field']} "
                f"local={x['local']!r} remote={x['remote']!r}"
            )
        raise RuntimeError(
            "DR1-E ABORT: remote Sheet does not match sealed staging. "
            "NO TRIGGERS WERE DELETED."
        )

    print("  [PASS] Remote critical data matches sealed staging.")

    print("")
    print("[3/4] DISABLE ONLY LEGACY V7/V8 AUTOMATION TRIGGERS")
    guard = post(url, token, "dr1e_disable_legacy_triggers")
    deleted = guard.get("deleted", [])
    print(f"  deleted legacy triggers: {len(deleted)}")
    for t in deleted:
        print(f"    - {t.get('handler')}")
    print(f"  risky remaining: {len(guard.get('risky_remaining', []))}")

    if guard.get("risky_remaining"):
        raise RuntimeError("DR1-E GUARD FAILED: risky legacy triggers remain.")

    print("")
    print("[4/4] POST-GUARD REINSPECTION")
    after = post(
        url, token, "dr1e_inspect", tickers=SENTINELS
    )
    risky_after = after.get("risky_legacy_triggers", [])
    if risky_after:
        raise RuntimeError("DR1-E POST-GUARD: risky triggers remain.")

    m2_checked, m2_bad = compare_module(
        "market", local_market, after.get("market", {}), MARKET_FIELDS
    )
    f2_checked, f2_bad = compare_module(
        "fundamentals", local_fund, after.get("fundamentals", {}), FUND_FIELDS
    )
    if m2_bad or f2_bad:
        raise RuntimeError(
            "DR1-E POST-GUARD DATA CHECK FAILED after trigger removal."
        )

    report = {
        "stage": "ALPHA_ENGINE_DATA_RECOVERY_V1_DR1E",
        "status": "PASS",
        "sentinels": SENTINELS,
        "pre_guard_project_triggers": before.get("triggers", []),
        "legacy_triggers_deleted": deleted,
        "post_guard_project_triggers": after.get("triggers", []),
        "risky_legacy_triggers_remaining": risky_after,
        "market_critical_cells_checked": m_checked + m2_checked,
        "fundamental_critical_cells_checked": f_checked + f2_checked,
        "mismatches": [],
        "sheet_cells_mutated_by_dr1e": False,
        "v13_mutated": False,
        "web_mutated": False,
        "product_state_mutated": False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("")
    print("============================================================")
    print("DR1-E GUARD COMPLETE")
    print("REMOTE DATA: MATCHES SEALED STAGING")
    print("LEGACY V7/V8 AUTOMATION TRIGGERS: DISABLED")
    print("RISKY LEGACY TRIGGERS REMAINING: 0")
    print("SHEET CELLS CHANGED BY DR1-E: NO")
    print("V13: UNCHANGED")
    print("WEB: UNCHANGED")
    print("PRODUCT STATE: UNCHANGED")
    print("============================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'@ | Set-Content -Path $PY -Encoding UTF8

@'
$ErrorActionPreference = "Stop"

$REC = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION\ALPHA_ENGINE_DATA_RECOVERY_V1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE - DR1-E GUARD"
Write-Host "VALIDATE SEALED DATA -> DISABLE ONLY LEGACY V7/V8 TRIGGERS"
Write-Host "NO SHEET CELL WRITES"
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
    python scripts\run_dr1e_guard.py
    if ($LASTEXITCODE -ne 0) { throw "DR1-E guard falló." }
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    Remove-Item Env:ALPHA_SHEETS_API_URL -ErrorAction SilentlyContinue
    Remove-Item Env:ALPHA_SHEETS_API_TOKEN -ErrorAction SilentlyContinue
}
'@ | Set-Content -Path $RUN -Encoding UTF8

Write-Host "[OK] scripts\run_dr1e_guard.py"
Write-Host "[OK] RUN_ALPHA_ENGINE_DR1E_GUARD.ps1"
Write-Host ""
Write-Host "LOCAL PREP COMPLETE."
Write-Host "Google Sheet was NOT touched."
Write-Host ""
Write-Host "NEXT:"
Write-Host "1. Copy the UPDATED bridge into the SAME Apps Script file."
Write-Host "2. Deploy a NEW VERSION of the SAME Web App."
Write-Host "3. Run RUN_ALPHA_ENGINE_DR1E_GUARD.ps1."
