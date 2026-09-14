$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 3R FAST"
Write-Host "CACHED PORTFOLIO RESEARCH"
Write-Host "BUILD: V13_P3R_FAST_CACHED_EXECUTION_HORIZON_SPARSITY_2026-09-12"
Write-Host "============================================="
$env:PYTHONPATH = "src"
python -m pytest tests/test_v13_phase3_fast.py -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3R FAST tests failed with exit code $LASTEXITCODE" }
python scripts/run_v13_phase3_fast.py
if ($LASTEXITCODE -ne 0) { Write-Host "`nPhase 3R research gate did not pass. Outputs were still written for diagnosis." -ForegroundColor Yellow }
