$ErrorActionPreference = 'Stop'
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 4C'
Write-Host 'OBSERVED HOLDOUT EVIDENCE CHECKPOINT'
Write-Host '============================================================'
python "$ROOT\scripts\checkpoint_v13_holdout_evidence.py" "$ROOT"
if ($LASTEXITCODE -ne 0) { throw 'Phase4C evidence checkpoint failed.' }
