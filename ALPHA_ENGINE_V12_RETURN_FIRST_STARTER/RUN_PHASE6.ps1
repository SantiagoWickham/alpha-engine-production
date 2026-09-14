$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 6"
Write-Host "PORTFOLIO POLICY TOURNAMENT"
Write-Host "BUILD: V1_FIX1_PANDAS_LOC_2026-09-12"
Write-Host "============================================="

if (-not (Test-Path ".\data")) { throw "No se encontro .\data. Ejecuta desde la raiz ALPHA_ENGINE_V12_RETURN_FIRST_STARTER." }
$required = @(
  ".\outputs\phase5_summary.json",
  ".\outputs\phase5_model_spec.json",
  ".\outputs\phase5_feature_pool.csv",
  ".\outputs\phase5_oof_scores.parquet",
  ".\outputs\phase5_validation_scores.parquet",
  ".\outputs\phase4_feature_library.parquet",
  ".\outputs\phase3_return_targets.parquet",
  ".\outputs\phase2c_return_price_layer.parquet",
  ".\outputs\phase3c_terminal_outcome_overlay.csv"
)
foreach ($p in $required) { if (-not (Test-Path $p)) { throw "Missing required Phase 6 input: $p" } }

$build = Select-String -Path ".\src\alpha_engine_v12\portfolio_policy.py" -Pattern 'PHASE6_BUILD = "V1_FIX1_PANDAS_LOC_2026-09-12"' -SimpleMatch -Quiet
if (-not $build) { throw "Phase 6 V1 is not installed in project root." }

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
$env:PYTHONPATH = "src"

Write-Host "`n[1/2] Running all tests..."
pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }

Write-Host "`n[2/2] Running OOF-only return-first portfolio policy tournament..."
python scripts/run_phase6.py
if ($LASTEXITCODE -ne 0) { throw "Phase 6 integrity gate failed with exit code $LASTEXITCODE" }

Write-Host "`nDONE. Send these SMALL files back to ChatGPT:"
Write-Host "  outputs\phase6_summary.json"
Write-Host "  outputs\phase6_gate.csv"
Write-Host "  outputs\phase6_leaderboard.csv"
Write-Host "  outputs\phase6_validation_confirmation.csv"
Write-Host "  outputs\phase6_score_fidelity.csv"
Write-Host "  outputs\phase6_policy_class_summary.csv"
Write-Host "  outputs\phase6_champion_spec.json"
Write-Host "`nKeep phase6_policy_scores.parquet and phase6_champion_validation_nav.csv locally unless requested."
Write-Host "FINAL OOS begins 2025-01-01 and remains untouched. Phase 6 does NOT freeze the final execution policy."
