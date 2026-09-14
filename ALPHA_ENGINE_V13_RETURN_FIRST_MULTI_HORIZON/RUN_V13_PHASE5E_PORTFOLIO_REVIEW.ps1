$ErrorActionPreference = 'Stop'
Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 5E'
Write-Host 'PORTFOLIO ACTION REVIEW + WEIGHT BASIS AUDIT'
Write-Host 'NO REAL ORDERS / NO SHEETS MUTATION / NO TUNING'
Write-Host '============================================================'
$env:PYTHONPATH = 'src'
python -m pytest -q tests/test_v13_phase5e_portfolio_review.py
if ($LASTEXITCODE -ne 0) { throw 'Phase5E tests failed.' }
python scripts/run_v13_phase5e_portfolio_review.py
if ($LASTEXITCODE -ne 0) { throw 'Phase5E portfolio review failed.' }
Write-Host '============================================================'
Write-Host 'PHASE 5E COMPLETE - REVIEW/AUDIT ONLY'
Write-Host 'NO operation_append / NO cash mutation / NO Sheets write'
Write-Host 'Send the console back to ChatGPT.'
Write-Host '============================================================'
