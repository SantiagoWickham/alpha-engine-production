$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 2R"
Write-Host "ADAPTIVE MULTI-EXPERT ALPHA REBUILD"
Write-Host "BUILD: V13_P2R_ADAPTIVE_MULTI_EXPERT_ALPHA_REBUILD_2026-09-12"
Write-Host "============================================="
$env:PYTHONPATH = "$PSScriptRoot\src"
python -m pytest "$PSScriptRoot\tests\test_v13_phase2r.py" -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 2R tests failed with exit code $LASTEXITCODE" }
python "$PSScriptRoot\scripts\run_v13_phase2r.py"
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 2R runner failed with exit code $LASTEXITCODE" }
