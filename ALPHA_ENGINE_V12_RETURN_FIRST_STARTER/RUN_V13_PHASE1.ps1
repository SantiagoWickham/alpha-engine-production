$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 1"
Write-Host "FRESH MULTI-HORIZON ALPHA FACTORY"
Write-Host "BUILD: V13_P1_FIX2_CANONICAL_PIT_PANEL_2026-09-12"
Write-Host "============================================="
python -m pytest tests/test_v13_phase0_contract.py tests/test_v13_phase1_alpha_factory.py -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 1 tests failed with exit code $LASTEXITCODE" }
python scripts/run_v13_phase1.py --source-v12-root "$PWD"
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 1 gate failed with exit code $LASTEXITCODE" }
