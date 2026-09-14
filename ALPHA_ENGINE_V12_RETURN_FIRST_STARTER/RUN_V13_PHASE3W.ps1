$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 3W"
Write-Host "PRE-HOLDOUT STRESS + FREEZE"
Write-Host "BUILD: V13_P3W_PREHOLDOUT_STRESS_FREEZE_2026-09-13"
Write-Host "============================================="
$env:PYTHONPATH = "src"
python -m pytest tests/test_v13_phase3w.py -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3W tests failed with exit code $LASTEXITCODE" }
python scripts/run_v13_phase3w.py
if ($LASTEXITCODE -ne 0) {
  Write-Host "Phase 3W freeze gate did not pass. 2025+ remains unopened." -ForegroundColor Yellow
}
