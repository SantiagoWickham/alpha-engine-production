$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$env:PYTHONPATH = (Join-Path $root 'src')
Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 5B'
Write-Host 'LIVE PIT SHADOW FORWARD - NO REAL ORDERS / NO TUNING'
Write-Host '============================================================'
python -m pytest tests/test_v13_phase5_live_shadow.py -q
if ($LASTEXITCODE -ne 0) { throw 'Phase5B tests failed.' }
python scripts/run_v13_phase5_live_shadow.py
if ($LASTEXITCODE -ne 0) { throw 'Phase5B live shadow failed. Do NOT change the sealed model; inspect data-quality diagnostics only.' }
Write-Host '============================================================'
Write-Host 'PHASE 5B COMPLETE'
Write-Host 'NO REAL ORDERS / NO TUNING'
Write-Host 'Send the console and outputs\live_shadow\v13_live_shadow_summary.json back to ChatGPT.'
Write-Host '============================================================'
