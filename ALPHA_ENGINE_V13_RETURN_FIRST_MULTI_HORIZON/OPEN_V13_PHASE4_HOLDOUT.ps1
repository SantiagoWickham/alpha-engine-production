$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root 'src'
Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 4B'
Write-Host 'ONE-SHOT CODE-BLINDED 2025+ HOLDOUT OPEN'
Write-Host '============================================================'
python -m pytest tests/test_v13_phase4.py -q
if ($LASTEXITCODE -ne 0) { throw 'Phase4 tests failed; holdout not opened' }
python scripts/open_v13_phase4_holdout.py
if ($LASTEXITCODE -ne 0) { throw 'Phase4 holdout run failed. Do NOT edit code; same-seal/same-code resume only.' }
Write-Host '============================================================'
Write-Host 'PHASE 4 HOLDOUT OPEN COMPLETE'
Write-Host 'Do not retune on these results.'
Write-Host '============================================================'
