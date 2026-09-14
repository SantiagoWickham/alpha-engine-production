$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 5"
Write-Host "MODEL ARCHITECTURE TOURNAMENT"
Write-Host "BUILD: V1_FIX2_GATE_SEMANTICS_2026-09-12"
Write-Host "============================================="

if (-not (Test-Path ".\data")) { throw "No se encontro .\data. Ejecuta desde la raiz ALPHA_ENGINE_V12_RETURN_FIRST_STARTER." }
if (-not (Test-Path ".\outputs\phase4_feature_library.parquet")) { throw "Missing Phase 4 feature library." }
if (-not (Test-Path ".\outputs\phase4_predictive_diagnostics.csv")) { throw "Missing Phase 4 predictive diagnostics." }
if (-not (Test-Path ".\outputs\phase4_summary.json")) { throw "Missing Phase 4 summary." }
if (-not (Test-Path ".\outputs\phase3_return_targets.parquet")) { throw "Missing Phase 3 targets." }

$phase5Build = Select-String -Path ".\src\alpha_engine_v12\model_tournament.py" -Pattern 'PHASE5_BUILD = "V1_FIX2_GATE_SEMANTICS_2026-09-12"' -SimpleMatch -Quiet
if (-not $phase5Build) { throw "Phase 5 V1 is not installed in project root." }

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
$env:PYTHONPATH = "src"

Write-Host "`n[1/2] Running all tests..."
pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }

Write-Host "`n[2/2] Running DEVELOPMENT-only, purged walk-forward model tournament..."
python scripts/run_phase5.py
if ($LASTEXITCODE -ne 0) { throw "Phase 5 integrity gate failed with exit code $LASTEXITCODE" }

Write-Host "`nDONE. Send these SMALL files back to ChatGPT:"
Write-Host "  outputs\phase5_summary.json"
Write-Host "  outputs\phase5_gate.csv"
Write-Host "  outputs\phase5_feature_pool.csv"
Write-Host "  outputs\phase5_cv_aggregate.csv"
Write-Host "  outputs\phase5_validation_results.csv"
Write-Host "  outputs\phase5_leaderboard.csv"
Write-Host "  outputs\phase5_model_spec.json"
Write-Host "`nKeep outputs\phase5_oof_scores.parquet and phase5_validation_scores.parquet locally unless requested."
Write-Host "FINAL OOS begins 2025-01-01 and remains untouched. Phase 5 does NOT choose trading cadence or portfolio weights."
