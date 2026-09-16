$ErrorActionPreference = "Stop"

$REC = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION\ALPHA_ENGINE_DATA_RECOVERY_V1"
$SENDER = Join-Path $REC "scripts\push_dr1d_to_sheets.py"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-D COMMIT"
Write-Host "THIS WILL WRITE FUNDAMENTALES + MERCADO & RIESGO"
Write-Host "AUTOMATIC BACKUP BEFORE WRITE"
Write-Host "V8/V10 SCORE COLUMNS FORCED BLANK"
Write-Host "============================================================"

if (-not (Test-Path $SENDER)) {
    throw "No existe sender: $SENDER"
}

$url = Read-Host "Pegá SOLO acá la Web App /exec URL (no la mandes a ChatGPT)"
if (-not $url) { throw "URL vacía." }
if (-not $url.EndsWith("/exec")) {
    throw "La URL debe terminar en /exec."
}

$secure = Read-Host "Pegá SOLO acá el token MMM_API_TOKEN_V8 (no lo mandes a ChatGPT)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)

try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if (-not $token) { throw "Token vacío." }

    $env:ALPHA_SHEETS_API_URL = $url
    $env:ALPHA_SHEETS_API_TOKEN = $token

    Write-Host ""
    Write-Host "[DR1-D COMMIT]"
    Set-Location $REC
    python scripts\push_dr1d_to_sheets.py --commit

    if ($LASTEXITCODE -ne 0) {
        throw "DR1-D commit falló."
    }

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "DR1-D COMMIT COMPLETE"
    Write-Host "FUNDAMENTALES: WRITTEN"
    Write-Host "MERCADO & RIESGO: WRITTEN"
    Write-Host "BACKUPS: CREATED BEFORE WRITE"
    Write-Host "AUDIT SHEET: WRITTEN"
    Write-Host "PROVIDER FAILURES: WRITTEN"
    Write-Host "OLD V8/V10 SCORE COLUMNS: BLANK"
    Write-Host "============================================================"
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    Remove-Item Env:ALPHA_SHEETS_API_URL -ErrorAction SilentlyContinue
    Remove-Item Env:ALPHA_SHEETS_API_TOKEN -ErrorAction SilentlyContinue
}
