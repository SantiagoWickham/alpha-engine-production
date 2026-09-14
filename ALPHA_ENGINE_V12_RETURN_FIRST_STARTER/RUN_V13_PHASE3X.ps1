$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = Join-Path $ROOT "src"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 3X"
Write-Host "ALPHA ATTRIBUTION + TURNOVER AUDIT"
Write-Host "BUILD: V13_P3X_ALPHA_ATTRIBUTION_TURNOVER_AUDIT_2026-09-13"
Write-Host "============================================="
python -m pytest -q (Join-Path $ROOT "tests")
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3X tests failed with exit code $LASTEXITCODE" }
python (Join-Path $ROOT "scripts\run_v13_phase3x.py")
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3X runner failed with exit code $LASTEXITCODE" }
