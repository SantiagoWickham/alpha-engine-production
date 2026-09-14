$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = Join-Path $ROOT "src"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V13 - PHASE 3Z"
Write-Host "ROUNDTRIP RESIZE HYSTERESIS"
Write-Host "BUILD: V13_P3Z_ROUNDTRIP_RESIZE_HYSTERESIS_2026-09-13"
Write-Host "============================================="
python -m pytest -q (Join-Path $ROOT "tests")
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3Z tests failed with exit code $LASTEXITCODE" }
python (Join-Path $ROOT "scripts\run_v13_phase3z.py")
if ($LASTEXITCODE -ne 0) { throw "V13 Phase 3Z economic gate failed with exit code $LASTEXITCODE" }
