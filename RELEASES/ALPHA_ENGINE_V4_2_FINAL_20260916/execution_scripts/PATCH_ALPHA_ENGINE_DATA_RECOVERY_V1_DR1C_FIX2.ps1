$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"
$STG  = Join-Path $REC "outputs\data_recovery_v1\staging"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-C FIX2"
Write-Host "POWERSHELL STRUCTURAL GATE FIX"
Write-Host "NO DATA ENGINE CHANGE / NO REFETCH REQUIRED"
Write-Host "NO V13 / SHEETS / WEB / PRODUCT STATE MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $REC)) { throw "No existe Recovery V1: $REC" }
if (-not (Test-Path $V13)) { throw "No existe V13: $V13" }
if (-not (Test-Path $STG)) { throw "No existe staging DR1-C: $STG" }

Set-Location $ROOT
$before = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"

Write-Host ""
Write-Host "[1/5] Reuse existing DR1-C staging (NO NETWORK REFETCH)"
$fundPath = Join-Path $STG "fundamentales_payload_latest.csv"
$mktPath  = Join-Path $STG "mercado_riesgo_payload_latest.csv"
$audPath  = Join-Path $STG "data_audit_long_latest.csv"
$failPath = Join-Path $STG "provider_failures_latest.csv"
$sumPath  = Join-Path $STG "recovery_coverage_summary.json"

foreach ($p in @($fundPath,$mktPath,$audPath,$failPath,$sumPath)) {
    if (-not (Test-Path $p)) { throw "Falta staging file: $p" }
}
Write-Host "  [OK] staging files present"

Write-Host ""
Write-Host "[2/5] Correct structural gate"
$fund = Import-Csv $fundPath
$mkt  = Import-Csv $mktPath

$fundCols = @($fund[0].PSObject.Properties).Count
$mktCols  = @($mkt[0].PSObject.Properties).Count

if ($fund.Count -ne 187) { throw "FUND ROW GATE: $($fund.Count) != 187" }
if ($mkt.Count -ne 200) { throw "MKT ROW GATE: $($mkt.Count) != 200" }
if ($fundCols -ne 29) { throw "FUND WIDTH GATE: $fundCols != 29" }
if ($mktCols -ne 41) { throw "MKT WIDTH GATE: $mktCols != 41" }

Write-Host "  [OK] Fundamentales rows=$($fund.Count) cols=$fundCols"
Write-Host "  [OK] Mercado & Riesgo rows=$($mkt.Count) cols=$mktCols"

Write-Host ""
Write-Host "[3/5] Forbidden-score blank gate"
$badFund = @($fund | Where-Object {
    $_.'Score Calidad (Shrink)' -or
    $_.'Score Crecimiento (Shrink)' -or
    $_.'Score Valuación (Shrink)'
})
if ($badFund.Count -gt 0) {
    throw "FORBIDDEN SCORE GATE: $($badFund.Count) fundamental rows contain old scores."
}

$badMkt = @($mkt | Where-Object {
    $_.'Score Tendencia' -or
    $_.'Score RS' -or
    $_.'Score Participación' -or
    $_.'Score Mercado' -or
    $_.'Score Volatilidad' -or
    $_.'Score Tail Risk' -or
    $_.'Score Liquidez' -or
    $_.'Beta/Corr Info Score' -or
    $_.'RISK SCORE'
})
if ($badMkt.Count -gt 0) {
    throw "FORBIDDEN SCORE GATE: $($badMkt.Count) market rows contain old scores."
}
Write-Host "  [OK] All V8/V10 score columns are blank"

Write-Host ""
Write-Host "[4/5] Coverage diagnostics"
Write-Host "----- recovery_coverage_summary.json -----"
Get-Content $sumPath

Write-Host ""
Write-Host "----- provider_failures_latest.csv -----"
$fail = @(Import-Csv $failPath)
if ($fail.Count -eq 0) {
    Write-Host "  none"
} else {
    $fail | Format-Table ticker,module,provider_symbol,error -AutoSize | Out-String | Write-Host
}

Write-Host ""
Write-Host "----- fundamental coverage below OK -----"

# Reconstruct per-ticker data completeness from the audit file.
$audit = Import-Csv $audPath
$fundAudit = $audit | Where-Object { $_.module -eq "fundamentals" }

$required = @(
    "company_name","market_cap","pe","roe",
    "debt_equity","net_margin","revenue_growth","free_cash_flow"
)

$diag = foreach ($ticker in ($fund | Select-Object -ExpandProperty Ticker)) {
    $rows = @($fundAudit | Where-Object { $_.ticker -eq $ticker })
    $available = 0
    foreach ($field in $required) {
        $r = $rows | Where-Object { $_.field -eq $field } | Select-Object -First 1
        if ($r -and $null -ne $r.value -and [string]$r.value -ne "") {
            $available++
        }
    }
    $coverage = $available / $required.Count

    $yerr = $rows |
        Where-Object { $_.field -eq "_yahoo_error" -and $_.value } |
        Select-Object -First 1
    $serr = $rows |
        Where-Object { $_.field -eq "_sec_error" -and $_.value } |
        Select-Object -First 1

    $status =
        if ($coverage -ge 0.875 -and -not $yerr) { "OK" }
        elseif ($coverage -ge 0.625) { "PARTIAL" }
        else { "INCOMPLETE" }

    if ($status -ne "OK") {
        [pscustomobject]@{
            ticker = $ticker
            status = $status
            coverage = ("{0:P0}" -f $coverage)
            yahoo_error = if ($yerr) { $yerr.value } else { "" }
            sec_error = if ($serr) { $serr.value } else { "" }
        }
    }
}

if (@($diag).Count -eq 0) {
    Write-Host "  none"
} else {
    $diag | Format-Table -AutoSize | Out-String -Width 220 | Write-Host
}

Write-Host ""
Write-Host "[5/5] V13 immutability"
Set-Location $ROOT
$after = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
if (($before | Out-String) -ne ($after | Out-String)) {
    throw "GUARDRAIL: cambió V13 durante DR1-C FIX2."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "DR1-C FIX2 COMPLETE"
Write-Host "FULL UNIVERSE STAGING: STRUCTURALLY VALID"
Write-Host "MARKET: 200 / 200 ASSET ROWS"
Write-Host "FUNDAMENTALS: 187 ROWS"
Write-Host "OLD V8/V10 SCORE COLUMNS: BLANK"
Write-Host "PER-DATUM AUDIT: ACTIVE"
Write-Host "V13: UNCHANGED"
Write-Host "SHEETS: UNCHANGED"
Write-Host "WEB: UNCHANGED"
Write-Host "PRODUCT STATE: NOT REGENERATED"
Write-Host "============================================================"
Write-Host ""
Write-Host "Pegame la salida completa desde [2/5] hasta el final."
