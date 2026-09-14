$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 2"
Write-Host "NESTED MULTI-HORIZON MODEL FACTORY"
Write-Host "BUILD: V13_P2_NESTED_MULTI_HORIZON_MODELS_2026-09-12"
Write-Host "============================================="
$env:PYTHONPATH = "src"
python -m pytest tests/test_v13_phase2_multi_horizon_models.py -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 2 tests failed with exit code $LASTEXITCODE" }
python scripts/run_v13_phase2.py
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 2 gate failed with exit code $LASTEXITCODE" }
