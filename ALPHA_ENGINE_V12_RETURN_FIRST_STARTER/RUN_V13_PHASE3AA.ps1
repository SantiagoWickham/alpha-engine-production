$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = Join-Path $ROOT "src"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 3AA"
Write-Host "FINAL PRE-HOLDOUT REVIEW + FREEZE"
Write-Host "BUILD: V13_P3AA_FINAL_PREHOLDOUT_REVIEW_FREEZE_2026-09-13"
Write-Host "============================================="
python -m pytest -q (Join-Path $ROOT "tests")
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3AA tests failed with exit code $LASTEXITCODE" }
python (Join-Path $ROOT "scripts\run_v13_phase3aa.py")
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3AA final review failed with exit code $LASTEXITCODE" }
