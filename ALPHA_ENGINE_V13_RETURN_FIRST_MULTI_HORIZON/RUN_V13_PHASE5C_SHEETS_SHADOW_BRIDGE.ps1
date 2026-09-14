$ErrorActionPreference = 'Stop'
Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 5C'
Write-Host 'SHEETS SHADOW BRIDGE - NO REAL ORDERS / NO TUNING'
Write-Host '============================================================'
$env:PYTHONPATH = 'src'
python -m pytest tests/test_v13_phase5c_sheets_shadow_bridge.py -q
if ($LASTEXITCODE -ne 0) { throw 'Phase5C tests failed.' }
python scripts/run_v13_phase5c_sheets_shadow_bridge.py
if ($LASTEXITCODE -ne 0) { throw 'Phase5C Sheets bridge failed. No model change; inspect API diagnostics only.' }
Write-Host '============================================================'
Write-Host 'PHASE 5C COMPLETE - SHADOW STATE ONLY'
Write-Host 'NO operation_append / NO cash mutation / NO forward execution'
Write-Host 'Send the console and outputs\sheets_shadow\v13_sheets_shadow_bridge_summary.json back to ChatGPT.'
Write-Host '============================================================'
