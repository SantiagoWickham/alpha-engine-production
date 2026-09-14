$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 3C"
Write-Host "TERMINAL OUTCOME REPAIR + PHASE 3 REBUILD"
Write-Host "BUILD: V1_2026-09-12 / PHASE3 V3"
Write-Host "============================================="

if (-not (Test-Path ".\data")) { throw "No se encontro .\data. Ejecuta desde la raiz ALPHA_ENGINE_V12_RETURN_FIRST_STARTER." }
if (-not (Test-Path ".\outputs\phase3b_summary.json")) { throw "Missing outputs\phase3b_summary.json. Run Phase 3B first." }
if (-not (Test-Path ".\outputs\phase3b_unresolved_tickers.csv")) { throw "Missing outputs\phase3b_unresolved_tickers.csv. Run Phase 3B first." }
if (-not (Test-Path ".\outputs\phase2_canonical_pit_panel.parquet")) { throw "Missing Phase 2 canonical panel." }
if (-not (Test-Path ".\outputs\phase2c_return_price_layer.parquet")) { throw "Missing Phase 2C return-price layer." }
if (-not (Test-Path ".\outputs\phase2c_summary.json")) { throw "Missing Phase 2C summary." }
if (-not (Test-Path ".\config\phase3c_manual_resolutions.csv")) { throw "Missing Phase 3C manual-resolution audit file." }

$repairBuild = Select-String -Path ".\src\alpha_engine_v12\terminal_repair.py" -Pattern 'PHASE3C_BUILD = "V1_2026-09-12"' -SimpleMatch -Quiet
if (-not $repairBuild) { throw "Phase 3C V1 is not installed in project root." }
$targetBuild = Select-String -Path ".\src\alpha_engine_v12\return_targets.py" -Pattern 'PHASE3_BUILD = "V3_TERMINAL_OVERLAY_2026-09-12"' -SimpleMatch -Quiet
if (-not $targetBuild) { throw "Phase 3 V3 terminal-overlay target engine is not installed in project root." }

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
$env:PYTHONPATH = "src"

Write-Host "`n[1/3] Running all tests..."
pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }

Write-Host "`n[2/3] Building validated terminal-outcome repair..."
python scripts/run_phase3c.py
if ($LASTEXITCODE -ne 0) { throw "Phase 3C gate failed with exit code $LASTEXITCODE" }

Write-Host "`n[3/3] Rebuilding Phase 3 targets with terminal overlay and non-equity exclusion..."
python scripts/run_phase3.py
if ($LASTEXITCODE -ne 0) { throw "Rebuilt Phase 3 gate failed with exit code $LASTEXITCODE" }

Write-Host "`nDONE. Send these SMALL files back to ChatGPT:"
Write-Host "  outputs\phase3c_summary.json"
Write-Host "  outputs\phase3c_gate.csv"
Write-Host "  outputs\phase3c_evidence_audit.csv"
Write-Host "  outputs\phase3c_research_exclusions.csv"
Write-Host "  outputs\phase3_summary.json"
Write-Host "  outputs\phase3_gate.csv"
Write-Host "  outputs\phase3_horizon_diagnostics.csv"
Write-Host "`nKeep outputs\phase3_return_targets.parquet locally. Do not train alpha unless rebuilt Phase 3 is PASS."
