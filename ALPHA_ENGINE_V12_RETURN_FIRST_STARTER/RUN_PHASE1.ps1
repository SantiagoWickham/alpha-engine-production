$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 1"
Write-Host "============================================="

if (-not (Test-Path ".\data")) {
    throw "No se encontro .\data. Ejecuta este script desde la raiz ALPHA_ENGINE_V12_RETURN_FIRST_STARTER."
}

python -m pip install -r requirements.txt
$env:PYTHONPATH = "src"

Write-Host "`n[1/2] Running tests..."
pytest

Write-Host "`n[2/2] Building Phase 1 foundation..."
python scripts/run_phase1.py

Write-Host "`nDONE. Send these three files back to ChatGPT:"
Write-Host "  outputs\phase1_summary.json"
Write-Host "  outputs\phase1_data_catalog.json"
Write-Host "  outputs\phase1_decision_clock.json"
