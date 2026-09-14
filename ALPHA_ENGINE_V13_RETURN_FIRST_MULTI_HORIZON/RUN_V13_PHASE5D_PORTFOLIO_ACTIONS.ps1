$ErrorActionPreference = 'Stop'
Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 5D'
Write-Host 'PORTFOLIO-AWARE SHADOW ACTIONS - NO REAL ORDERS / NO TUNING'
Write-Host '============================================================'
$env:PYTHONPATH = 'src'
python -m pytest -q tests/test_v13_phase5d_portfolio_actions.py
if ($LASTEXITCODE -ne 0) { throw 'Phase5D tests failed.' }
python scripts/run_v13_phase5d_portfolio_actions.py
if ($LASTEXITCODE -ne 0) { throw 'Phase5D portfolio action shadow failed. No real orders were sent.' }
Write-Host '============================================================'
Write-Host 'PHASE 5D COMPLETE - DISPLAY/SHADOW ONLY'
Write-Host 'NO operation_append / NO cash mutation / NO forward execution'
Write-Host '============================================================'
