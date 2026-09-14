$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = Join-Path $ROOT "src"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 3Y"
Write-Host "ACTIVE ALPHA + PERSISTENT PORTFOLIO"
Write-Host "BUILD: V13_P3Y_ACTIVE_ALPHA_PERSISTENT_PORTFOLIO_2026-09-13"
Write-Host "============================================="
python -m pytest -q (Join-Path $ROOT "tests")
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3Y tests failed with exit code $LASTEXITCODE" }
python (Join-Path $ROOT "scripts\run_v13_phase3y.py")
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3Y economic gate failed with exit code $LASTEXITCODE" }
