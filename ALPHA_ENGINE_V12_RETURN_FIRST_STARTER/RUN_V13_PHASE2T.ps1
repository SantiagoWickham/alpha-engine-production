$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 2T"
Write-Host "REGIME ROUTER META-ADVISOR"
Write-Host "BUILD: V13_P2T_FIX2_PHASE1_TARGET_SURFACE_2026-09-12"
Write-Host "============================================="
$env:PYTHONPATH = "$PSScriptRoot\src"
python -m pytest "$PSScriptRoot\tests\test_v13_phase2t.py" -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 2T tests failed with exit code $LASTEXITCODE" }
python "$PSScriptRoot\scripts\run_v13_phase2t.py"
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 2T runner failed with exit code $LASTEXITCODE" }
