$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 2"
Write-Host "============================================="

if (-not (Test-Path ".\data")) {
    throw "No se encontro .\data. Ejecuta este script desde la raiz ALPHA_ENGINE_V12_RETURN_FIRST_STARTER."
}
if (-not (Test-Path ".\config\project.toml")) {
    throw "No se encontro Phase 1. Falta .\config\project.toml."
}
if (-not (Test-Path ".\config\phase2.toml")) {
    throw "No se encontro .\config\phase2.toml. Extrae el ZIP de Phase 2 en la raiz del proyecto."
}

python -m pip install -r requirements.txt
$env:PYTHONPATH = "src"

Write-Host "`n[1/2] Running all tests..."
pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }

Write-Host "`n[2/2] Building canonical PIT panel..."
python scripts/run_phase2.py
if ($LASTEXITCODE -ne 0) { throw "Phase 2 build failed with exit code $LASTEXITCODE" }

Write-Host "`nDONE. Send these four SMALL files back to ChatGPT:"
Write-Host "  outputs\phase2_summary.json"
Write-Host "  outputs\phase2_source_audit.csv"
Write-Host "  outputs\phase2_pit_audit.csv"
Write-Host "  outputs\phase2_panel_schema.json"
Write-Host "`nKeep the parquet outputs locally; do not upload them unless requested."
