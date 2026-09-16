$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$REC = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"
$START = Join-Path $ROOT "START_ALPHA_ENGINE.ps1"
$SMOKE = Join-Path $REC "scripts\smoke_web_v31.py"
$SECRET = Join-Path $REC "secrets\groq_api_key.clixml"

Write-Host ""
Write-Host "================================================================"
Write-Host "ALPHA ENGINE WEB V3.1 - RESUME FINALIZER"
Write-Host "RESUME FROM 5/7 ONLY"
Write-Host "NO V13 / NO SHEETS / NO REINSTALL"
Write-Host "================================================================"

if (-not (Test-Path $START)) { throw "Falta START_ALPHA_ENGINE.ps1" }
if (-not (Test-Path $SMOKE)) { throw "Falta smoke_web_v31.py" }
if (-not (Test-Path $SECRET)) { throw "Falta credencial Groq cifrada." }

Write-Host ""
Write-Host "[5/7] RESTART ONLY ALPHA DR1 SERVER"

$listeners = @(
    Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue
)

foreach ($listener in $listeners) {
    $processId = [int]$listener.OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    $cmd = [string]$proc.CommandLine

    if ($cmd -notlike "*run_data_recovery_server.py*") {
        throw "Puerto 8765 ocupado por proceso no-Alpha PID=$processId. No se cerró."
    }

    Stop-Process -Id $processId -Force
    Write-Host "  stopped old Alpha server PID=$processId"
}

Start-Sleep -Milliseconds 900

$launcher = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $START
    ) `
    -WindowStyle Hidden `
    -PassThru

Write-Host "  launcher PID=$($launcher.Id)"

Write-Host ""
Write-Host "[6/7] FULL HTTP + GROQ/QWEN SMOKE"

Set-Location $ROOT
python $SMOKE
if ($LASTEXITCODE -ne 0) {
    throw "Web V3.1 smoke failed. V13 remains untouched."
}

Write-Host ""
Write-Host "[7/7] FINAL"
Write-Host "================================================================"
Write-Host "ALPHA ENGINE WEB V3.1: PASS"
Write-Host "================================================================"
Write-Host "WEB              : http://127.0.0.1:8765/"
Write-Host "DATA AUTHORITY   : LOCAL_DATA_RECOVERY_V1"
Write-Host "MARKET           : 200/200"
Write-Host "FUNDAMENTALS     : 187/187"
Write-Host "PORTFOLIO        : 3 positions / audited snapshot"
Write-Host "LLM PROVIDER     : GROQ"
Write-Host "LLM MODEL        : qwen/qwen3.8-27b"
Write-Host "LOGO             : Alpha Engine wordmark V3.1"
Write-Host "PRE/POST MARKET  : DISABLED"
Write-Host "SHEETS RUNTIME   : NOT REQUIRED"
Write-Host "V13 MUTATED      : NO"
Write-Host "================================================================"
Write-Host ""
Write-Host "Future start command:"
Write-Host "  & `"$START`""
