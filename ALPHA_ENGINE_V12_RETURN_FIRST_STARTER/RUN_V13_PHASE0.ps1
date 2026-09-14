$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 0"
Write-Host "RESEARCH RESET & CONTRACT"
Write-Host "BUILD: V13_P0_RESET_CONTRACT_2026-09-12"
Write-Host "============================================="
python -m pytest tests/test_v13_phase0_contract.py -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 0 tests failed with exit code $LASTEXITCODE" }
python scripts/run_v13_phase0.py --source-v12-root "$PWD"
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 0 contract gate failed with exit code $LASTEXITCODE" }
