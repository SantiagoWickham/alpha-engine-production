$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 3V"
Write-Host "OOF ECONOMIC PORTFOLIO CLOSURE"
Write-Host "BUILD: V13_P3V_FIX1_V13_WORKSPACE_RESOLUTION_2026-09-13"
Write-Host "============================================="
$env:PYTHONPATH = "src"
python -m pytest tests/test_v13_phase3v.py -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3V tests failed with exit code $LASTEXITCODE" }
python scripts/run_v13_phase3v.py
if ($LASTEXITCODE -ne 0) {
  Write-Host "Phase 3V economic gate did not pass. Outputs were still written; 2021-2022 alone is NOT the blocker." -ForegroundColor Yellow
}
