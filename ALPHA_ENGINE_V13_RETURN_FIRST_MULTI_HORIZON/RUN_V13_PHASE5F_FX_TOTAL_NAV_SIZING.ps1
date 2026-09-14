$ErrorActionPreference = 'Stop'
Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 5F'
Write-Host 'AUDITED FX + TOTAL-NAV SHADOW SIZING'
Write-Host 'NO REAL ORDERS / NO SHEETS MUTATION / NO TUNING'
Write-Host '============================================================'
$env:PYTHONPATH = 'src'
python -m pytest -q tests/test_v13_phase5f_fx_sizing.py
if ($LASTEXITCODE -ne 0) { throw 'Phase5F tests failed.' }
python scripts/run_v13_phase5f_fx_sizing.py
if ($LASTEXITCODE -ne 0) { throw 'Phase5F audited FX / sizing failed. No execution was attempted.' }
Write-Host '============================================================'
Write-Host 'PHASE 5F COMPLETE - SHADOW SIZING ONLY'
Write-Host 'NO operation_append / NO cash mutation / NO forward execution'
Write-Host 'Send the console back to ChatGPT.'
Write-Host '============================================================'
