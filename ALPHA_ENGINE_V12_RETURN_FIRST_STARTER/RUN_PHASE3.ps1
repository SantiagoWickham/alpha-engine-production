$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 3"
Write-Host "RETURN TARGET ENGINE"
Write-Host "BUILD: V2_TICKER_SESSIONS_2026-09-12"
Write-Host "============================================="

if (-not (Test-Path ".\data")) {
    throw "No se encontro .\data. Ejecuta este script desde la raiz ALPHA_ENGINE_V12_RETURN_FIRST_STARTER."
}
if (-not (Test-Path ".\outputs\phase2_canonical_pit_panel.parquet")) {
    throw "No se encontro Phase 2 canonical panel. Ejecuta RUN_PHASE2.ps1 primero."
}
if (-not (Test-Path ".\outputs\phase2c_return_price_layer.parquet")) {
    throw "No se encontro Phase 2C return-price layer. Ejecuta RUN_PHASE2C.ps1 primero."
}
if (-not (Test-Path ".\outputs\phase2c_summary.json")) {
    throw "No se encontro outputs\phase2c_summary.json."
}
if (-not (Test-Path ".\config\phase3.toml")) {
    throw "No se encontro .\config\phase3.toml. Extrae el ZIP de Phase 3 FIX1 en la raiz."
}

$buildCheck = Select-String -Path ".\src\alpha_engine_v12\return_targets.py" -Pattern 'PHASE3_BUILD = "V2_TICKER_SESSIONS_2026-09-12"' -SimpleMatch -Quiet
if (-not $buildCheck) {
    throw "Phase 3 V2 no esta instalado en la raiz. Verifica src\alpha_engine_v12\return_targets.py."
}

$phase2c = Get-Content ".\outputs\phase2c_summary.json" -Raw | ConvertFrom-Json
if ($phase2c.status -ne "PASS") {
    throw "Phase 2C no esta en PASS. No se pueden construir targets."
}

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
$env:PYTHONPATH = "src"

Write-Host "`n[1/2] Running all tests..."
pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }

Write-Host "`n[2/2] Building causal multi-horizon return targets..."
python scripts/run_phase3.py
if ($LASTEXITCODE -ne 0) { throw "Phase 3 gate failed with exit code $LASTEXITCODE" }

Write-Host "`nDONE. Send these four SMALL files back to ChatGPT:"
Write-Host "  outputs\phase3_summary.json"
Write-Host "  outputs\phase3_gate.csv"
Write-Host "  outputs\phase3_horizon_diagnostics.csv"
Write-Host "  outputs\phase3_target_schema.json"
Write-Host "`nKeep outputs\phase3_return_targets.parquet locally. Do not train alpha yet."
