$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 2S"
Write-Host "REGIME + TAIL + RESIDUAL ALPHA REBUILD"
Write-Host "BUILD: V13_P2S_REGIME_TAIL_RESIDUAL_ALPHA_2026-09-12"
Write-Host "============================================="
$env:PYTHONPATH = "$PSScriptRoot\src"
python -m pytest "$PSScriptRoot\tests\test_v13_phase2s.py" -q
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 2S tests failed with exit code $LASTEXITCODE" }
python "$PSScriptRoot\scripts\run_v13_phase2s.py"
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 2S runner failed with exit code $LASTEXITCODE" }
