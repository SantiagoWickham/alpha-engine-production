$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 3"
Write-Host "CROSS-HORIZON ADVISOR + DYNAMIC PORTFOLIO"
Write-Host "BUILD: V13_P3_FIX2_PARTIAL_EXECUTION_AND_AUDIT_2026-09-12"
Write-Host "============================================="
$env:PYTHONPATH = "src"
python -m pytest tests/test_v13_phase3_cross_horizon_advisor.py -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3 tests failed with exit code $LASTEXITCODE" }
python scripts/run_v13_phase3.py
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3 gate failed with exit code $LASTEXITCODE" }
