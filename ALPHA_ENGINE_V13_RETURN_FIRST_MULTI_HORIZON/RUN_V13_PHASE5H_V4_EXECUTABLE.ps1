$ErrorActionPreference = "Stop"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE V13 - PHASE 5H V4"
Write-Host "COMPLETE BYMA DUAL-ISSUER INTEGER REPLAY + CAPITAL CAPACITY"
Write-Host "============================================================"

$env:PYTHONPATH = "src"

python research\phase5h_executable_v13_v4.py

if ($LASTEXITCODE -ne 0) {
    throw "PHASE 5H V4 FAILED"
}
