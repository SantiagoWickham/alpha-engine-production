$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src"
Write-Host "============================================================"
Write-Host "ALPHA ENGINE BYMA NATIVE 2.1.2.2"
Write-Host "FINAL NATIVE RESEARCH - META ALPHA ARCHITECTURE"
Write-Host "============================================================"
python research\run_byma_native_2_1.py
if ($LASTEXITCODE -ne 0) { throw "ALPHA ENGINE BYMA NATIVE 2.1.2.2 FAILED" }
