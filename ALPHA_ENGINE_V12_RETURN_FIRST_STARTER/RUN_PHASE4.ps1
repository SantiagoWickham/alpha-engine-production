$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 4"
Write-Host "LEAKAGE-FREE FEATURE LIBRARY & PREDICTIVE RESEARCH"
Write-Host "BUILD: V1_PURGED_PRE_OOS_2026-09-12"
Write-Host "============================================="

if (-not (Test-Path ".\data")) { throw "No se encontro .\data. Ejecuta desde la raiz ALPHA_ENGINE_V12_RETURN_FIRST_STARTER." }
if (-not (Test-Path ".\outputs\phase2_canonical_pit_panel.parquet")) { throw "Missing Phase 2 canonical PIT panel." }
if (-not (Test-Path ".\outputs\phase3_return_targets.parquet")) { throw "Missing Phase 3 return targets." }
if (-not (Test-Path ".\outputs\phase3_summary.json")) { throw "Missing Phase 3 summary." }
if (-not (Test-Path ".\outputs\phase3c_research_exclusions.csv")) { throw "Missing Phase 3C research exclusions." }
if (-not (Test-Path ".\data\v12\adjusted_prices_yahoo")) { throw "Missing Phase 2C Yahoo cache used for feature-safe backward return transforms." }

$phase4Build = Select-String -Path ".\src\alpha_engine_v12\feature_research.py" -Pattern 'PHASE4_BUILD = "V1_PURGED_PRE_OOS_2026-09-12"' -SimpleMatch -Quiet
if (-not $phase4Build) { throw "Phase 4 V1 is not installed in project root." }

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
$env:PYTHONPATH = "src"

Write-Host "`n[1/2] Running all tests..."
pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }

Write-Host "`n[2/2] Building causal features and PRE-OOS predictive diagnostics..."
python scripts/run_phase4.py
if ($LASTEXITCODE -ne 0) { throw "Phase 4 integrity gate failed with exit code $LASTEXITCODE" }

Write-Host "`nDONE. Send these SMALL files back to ChatGPT:"
Write-Host "  outputs\phase4_summary.json"
Write-Host "  outputs\phase4_gate.csv"
Write-Host "  outputs\phase4_feature_coverage.csv"
Write-Host "  outputs\phase4_candidate_features.csv"
Write-Host "  outputs\phase4_family_summary.csv"
Write-Host "  outputs\phase4_research_partitions.csv"
Write-Host "`nKeep outputs\phase4_feature_library.parquet and phase4_predictive_diagnostics.csv locally unless requested."
Write-Host "FINAL OOS begins 2025-01-01 and remains untouched for model selection."
