$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 2B"
Write-Host "PRICE SEMANTICS & CORPORATE ACTION GATE"
Write-Host "============================================="

if (-not (Test-Path ".\data")) {
    throw "No se encontro .\data. Ejecuta este script desde la raiz ALPHA_ENGINE_V12_RETURN_FIRST_STARTER."
}
if (-not (Test-Path ".\outputs\phase2_canonical_pit_panel.parquet")) {
    throw "No se encontro el panel canonico de Phase 2. Ejecuta RUN_PHASE2.ps1 primero."
}
if (-not (Test-Path ".\config\phase2b.toml")) {
    throw "No se encontro .\config\phase2b.toml. Extrae el ZIP de Phase 2B en la raiz del proyecto."
}

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
$env:PYTHONPATH = "src"

Write-Host "`n[1/2] Running all tests..."
pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }

Write-Host "`n[2/2] Auditing price semantics and corporate actions..."
python scripts/run_phase2b.py
if ($LASTEXITCODE -ne 0) { throw "Phase 2B audit failed with exit code $LASTEXITCODE" }

Write-Host "`nDONE. Send these five SMALL files back to ChatGPT:"
Write-Host "  outputs\phase2b_summary.json"
Write-Host "  outputs\phase2b_gate.csv"
Write-Host "  outputs\phase2b_price_coverage.csv"
Write-Host "  outputs\phase2b_source_semantics.csv"
Write-Host "  outputs\phase2b_adjusted_price_candidates.csv"
Write-Host "`nDo not create alpha targets yet unless the Phase 2B gate passes."
