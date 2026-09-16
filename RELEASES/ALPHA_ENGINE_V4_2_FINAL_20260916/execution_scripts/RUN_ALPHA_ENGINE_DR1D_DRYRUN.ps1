$ErrorActionPreference = "Stop"

$REC = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION\ALPHA_ENGINE_DATA_RECOVERY_V1"
$SENDER = Join-Path $REC "scripts\push_dr1d_to_sheets.py"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-D REMOTE DRY RUN"
Write-Host "NO --commit"
Write-Host "NO SHEETS MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $SENDER)) {
    throw "No existe sender: $SENDER"
}

$url = Read-Host "Pegá SOLO acá la Web App /exec URL (no la mandes a ChatGPT)"
if (-not $url) { throw "URL vacía." }
if (-not $url.EndsWith("/exec")) {
    throw "La URL debe ser la Web App versionada y terminar en /exec."
}

$secure = Read-Host "Pegá SOLO acá el token MMM_API_TOKEN_V8 (no lo mandes a ChatGPT)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)

try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if (-not $token) { throw "Token vacío." }

    $env:ALPHA_SHEETS_API_URL = $url
    $env:ALPHA_SHEETS_API_TOKEN = $token

    Write-Host ""
    Write-Host "[REMOTE DRY RUN]"
    Set-Location $REC
    python scripts\push_dr1d_to_sheets.py

    if ($LASTEXITCODE -ne 0) {
        throw "DR1-D dry-run remoto falló."
    }

    Write-Host ""
    Write-Host "============================================================"
    Write-Host "DR1-D REMOTE DRY RUN COMPLETE"
    Write-Host "SHEETS: NOT MUTATED"
    Write-Host "NO --commit WAS USED"
    Write-Host "============================================================"
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    Remove-Item Env:ALPHA_SHEETS_API_URL -ErrorAction SilentlyContinue
    Remove-Item Env:ALPHA_SHEETS_API_TOKEN -ErrorAction SilentlyContinue
}
