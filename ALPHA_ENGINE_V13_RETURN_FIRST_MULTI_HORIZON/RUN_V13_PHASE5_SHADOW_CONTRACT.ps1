$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$env:PYTHONPATH = (Join-Path $root 'src')
Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 5A'
Write-Host 'SHADOW PRODUCTION PARITY CONTRACT'
Write-Host '============================================================'
python -m pytest tests/test_v13_phase5_shadow_contract.py -q
if ($LASTEXITCODE -ne 0) { throw 'Phase5A tests failed.' }
python scripts/run_v13_phase5_shadow_contract.py
if ($LASTEXITCODE -ne 0) { throw 'Phase5A shadow contract failed.' }
Write-Host '============================================================'
Write-Host 'PHASE 5A COMPLETE - NO REAL ORDERS / NO TUNING'
Write-Host 'Send outputs\shadow\v13_shadow_contract_summary.json and the console back to ChatGPT.'
Write-Host '============================================================'
