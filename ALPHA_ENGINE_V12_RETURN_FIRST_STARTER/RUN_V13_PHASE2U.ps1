$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 2U"
Write-Host "EVENT + SECTOR INCREMENTAL ALPHA"
Write-Host "BUILD: V13_P2U_EVENT_SECTOR_INCREMENTAL_ALPHA_2026-09-12"
Write-Host "============================================="
python -m pytest tests/test_v13_phase2u.py -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 2U tests failed with exit code $LASTEXITCODE" }
python scripts/run_v13_phase2u.py
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 2U runner failed with exit code $LASTEXITCODE" }
