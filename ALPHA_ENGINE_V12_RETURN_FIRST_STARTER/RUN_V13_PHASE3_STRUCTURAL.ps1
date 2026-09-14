$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 3S"
Write-Host "FAST STRUCTURAL REPAIR"
Write-Host "BUILD: V13_P3S_FAST_STRUCTURAL_REPAIR_2026-09-12"
Write-Host "============================================="
$env:PYTHONPATH = "$PSScriptRoot\src"
python -m pytest "$PSScriptRoot\tests\test_v13_phase3_structural.py" -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3S tests failed with exit code $LASTEXITCODE" }
python "$PSScriptRoot\scripts\run_v13_phase3_structural.py"
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3S runner failed with exit code $LASTEXITCODE" }
