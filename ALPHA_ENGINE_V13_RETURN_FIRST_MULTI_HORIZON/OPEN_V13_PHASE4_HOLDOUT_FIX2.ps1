$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root 'src'
$ExpectedSeal = '46bbbf853561e26625ee3ecbccb6037051556f2f3ca26dcb4e311c165c08d8e9'
$ResumeTag = 'v13-holdout-resume-reportfix2-46bbbf85'

Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 4B FIX2'
Write-Host 'TECHNICAL RESUME - HORIZON EVIDENCE SCHEMA COMPATIBILITY'
Write-Host '============================================================'
Write-Host '2025+ IS ALREADY OBSERVED. This is a same-seal technical resume only.'
Write-Host 'No predictor, score, policy, cost, portfolio or sealed file is modified.'
Write-Host ''

python -m pytest tests/test_v13_phase4.py tests/test_v13_phase4_seal_compat.py tests/test_v13_phase4_report_resume_fix2.py -q
if ($LASTEXITCODE -ne 0) { throw 'Phase4 FIX2 tests failed; resume aborted' }

python scripts/open_v13_phase4_holdout_fix2.py --verify-only
if ($LASTEXITCODE -ne 0) { throw 'Phase4 FIX2 resume preflight failed' }

# Publish only the external technical-resume wrapper before completing the interrupted run.
$files = @(
  'OPEN_V13_PHASE4_HOLDOUT_FIX2.ps1',
  'README_V13_PHASE4_FIX2.txt',
  'scripts/open_v13_phase4_holdout_fix2.py',
  'tests/test_v13_phase4_report_resume_fix2.py',
  'docs/V13_PHASE4_TECHNICAL_RESUME_FIX2.md'
)

git add -- $files
if ($LASTEXITCODE -ne 0) { throw 'git add for FIX2 failed' }
$staged = git diff --cached --name-only
if ($LASTEXITCODE -ne 0) { throw 'git diff --cached failed' }
$unexpected = @($staged | Where-Object { $_ -and ($files -notcontains $_) })
if ($unexpected.Count -gt 0) { throw ('Unexpected staged files: ' + ($unexpected -join ', ')) }

if ($staged) {
  git commit -m 'fix: Phase4 reporting-only technical resume 46bbbf85'
  if ($LASTEXITCODE -ne 0) { throw 'FIX2 commit failed' }
  git push origin main
  if ($LASTEXITCODE -ne 0) { throw 'FIX2 push failed' }
}

$tagExists = git tag --list $ResumeTag
if (-not ($tagExists -contains $ResumeTag)) {
  git tag -a $ResumeTag -m 'Phase4 reporting-only technical resume; sealed economics unchanged'
  if ($LASTEXITCODE -ne 0) { throw 'FIX2 tag creation failed' }
}
git push origin $ResumeTag
if ($LASTEXITCODE -ne 0) {
  $remoteTag = git ls-remote --tags origin "refs/tags/$ResumeTag"
  if (-not $remoteTag) { throw 'FIX2 tag push failed' }
}

Write-Host ''
Write-Host 'Technical resume patch published. Resuming ORIGINAL sealed holdout economics...'
python scripts/open_v13_phase4_holdout_fix2.py
if ($LASTEXITCODE -ne 0) { throw 'Phase4 FIX2 resume failed. Do not alter sealed model; inspect technical error only.' }

Write-Host '============================================================'
Write-Host 'PHASE 4 HOLDOUT TECHNICAL RESUME COMPLETE'
Write-Host "Seal ID: $ExpectedSeal"
Write-Host "Resume tag: $ResumeTag"
Write-Host '2025+ remains observed validation evidence. Do not retune on it.'
Write-Host '============================================================'
