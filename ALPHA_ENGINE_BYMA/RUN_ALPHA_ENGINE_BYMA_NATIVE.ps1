$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src"
Write-Host "============================================================"
Write-Host "ALPHA ENGINE BYMA NATIVE 2.0.1"
Write-Host "NATIVE TRAINING + HOLDOUT GAP DIAGNOSTIC + LIVE TARGET"
Write-Host "============================================================"
python research\run_byma_native_2.py
if ($LASTEXITCODE -ne 0) { throw "ALPHA ENGINE BYMA NATIVE 2.0.1 FAILED" }
