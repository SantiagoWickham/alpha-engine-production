$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 7"
Write-Host "EXPECTED EDGE CALIBRATION & ALPHA LINEAGE"
Write-Host "BUILD: V1_EDGE_LINEAGE_2026-09-12"
Write-Host "============================================="

if (-not (Test-Path ".\data")) { throw "No se encontro .\data. Ejecuta desde la raiz ALPHA_ENGINE_V12_RETURN_FIRST_STARTER." }
$required = @(
  ".\outputs\phase6_summary.json",
  ".\outputs\phase6_champion_spec.json",
  ".\outputs\phase6_policy_scores.parquet",
  ".\outputs\phase3_return_targets.parquet",
  ".\outputs\phase2c_return_price_layer.parquet",
  ".\outputs\phase3c_terminal_outcome_overlay.csv"
)
foreach ($p in $required) { if (-not (Test-Path $p)) { throw "Missing required Phase 7 input: $p" } }

$build = Select-String -Path ".\src\alpha_engine_v12\edge_lineage.py" -Pattern 'PHASE7_BUILD = "V1_EDGE_LINEAGE_2026-09-12"' -SimpleMatch -Quiet
if (-not $build) { throw "Phase 7 V1 is not installed in project root." }

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
$env:PYTHONPATH = "src"

Write-Host "`n[1/2] Running all tests..."
pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }

Write-Host "`n[2/2] Calibrating net-edge and auditing alpha lineage..."
python scripts/run_phase7.py
if ($LASTEXITCODE -ne 0) { throw "Phase 7 integrity gate failed with exit code $LASTEXITCODE" }

Write-Host "`nDONE. Send these SMALL files back to ChatGPT:"
Write-Host "  outputs\phase7_summary.json"
Write-Host "  outputs\phase7_gate.csv"
Write-Host "  outputs\phase7_edge_calibration_selection.csv"
Write-Host "  outputs\phase7_edge_policy_leaderboard.csv"
Write-Host "  outputs\phase7_validation_confirmation.csv"
Write-Host "  outputs\phase7_lineage_summary.csv"
Write-Host "  outputs\phase7_pre_freeze_candidate.json"
Write-Host "`nKeep phase7_lineage_snapshot_audit.csv and phase7_validation_nav.csv locally unless requested."
Write-Host "FINAL OOS 2025+ remains untouched. Phase 7 does NOT open final OOS."
