$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src"
Write-Host "============================================================"
Write-Host "ALPHA ENGINE BYMA 1.0.1"
Write-Host "FULL BUILD + VALIDATION + INTEGER CAPACITY"
Write-Host "============================================================"
python research\run_alpha_engine_byma_full.py
if ($LASTEXITCODE -ne 0) { throw "ALPHA ENGINE BYMA FULL BUILD FAILED" }
