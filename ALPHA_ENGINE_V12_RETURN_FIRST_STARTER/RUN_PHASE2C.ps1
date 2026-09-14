$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 2C"
Write-Host "RETURN PRICE ENRICHMENT"
Write-Host "BUILD: FIX3_FLAT_2026-09-12"
Write-Host "============================================="

if (-not (Test-Path ".\data")) {
    throw "No se encontro .\data. Ejecuta este script desde la raiz ALPHA_ENGINE_V12_RETURN_FIRST_STARTER."
}
if (-not (Test-Path ".\outputs\phase2_canonical_pit_panel.parquet")) {
    throw "No se encontro Phase 2 canonical panel. Ejecuta RUN_PHASE2.ps1 primero."
}
if (-not (Test-Path ".\outputs\phase2b_adjusted_price_requirements.csv")) {
    throw "No se encontro Phase 2B requirements. Ejecuta RUN_PHASE2B.ps1 primero."
}
if (-not (Test-Path ".\config\phase2c.toml")) {
    throw "No se encontro .\config\phase2c.toml. Extrae el ZIP de Phase 2C en la raiz."
}

$buildCheck = Select-String -Path ".\src\alpha_engine_v12\return_price_enrichment.py" -Pattern 'PHASE2C_BUILD = "FIX3_FLAT_2026-09-12"' -SimpleMatch -Quiet
if (-not $buildCheck) {
    throw "FIX3 no esta instalado en la raiz. Verifica que src\alpha_engine_v12\return_price_enrichment.py haya sido reemplazado."
}

$configCheck = Select-String -Path ".\config\phase2c.toml" -Pattern 'minimum_short_history_validation_rows = 20' -SimpleMatch -Quiet
if (-not $configCheck) {
    throw "La configuracion Phase 2C sigue siendo vieja. Reemplaza config\phase2c.toml con FIX3."
}

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
$env:PYTHONPATH = "src"

Write-Host "`n[1/2] Running all tests..."
pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }

Write-Host "`n[2/2] Downloading/validating target-only adjusted histories..."
python scripts/run_phase2c.py
if ($LASTEXITCODE -ne 0) { throw "Phase 2C failed with exit code $LASTEXITCODE" }

Write-Host "`nDONE. Send these five SMALL files back to ChatGPT:"
Write-Host "  outputs\phase2c_summary.json"
Write-Host "  outputs\phase2c_gate.csv"
Write-Host "  outputs\phase2c_download_manifest.csv"
Write-Host "  outputs\phase2c_provider_validation.csv"
Write-Host "  outputs\phase2c_ticker_coverage.csv"
Write-Host "`nKeep phase2c_return_price_layer.parquet locally. Do not train alpha unless Phase 2C PASSes."
