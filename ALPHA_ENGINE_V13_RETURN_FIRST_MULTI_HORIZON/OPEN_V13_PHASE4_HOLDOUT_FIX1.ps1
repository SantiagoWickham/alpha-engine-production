$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root 'src'
$ExpectedSeal = '46bbbf853561e26625ee3ecbccb6037051556f2f3ca26dcb4e311c165c08d8e9'
$CompatTag = 'v13-holdout-open-compat-46bbbf85'

Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 4B FIX1'
Write-Host 'SEALED-MANIFEST COMPATIBILITY + ONE-SHOT HOLDOUT OPEN'
Write-Host '============================================================'
Write-Host 'This fix does NOT modify final_holdout.py, sealed models, features, policy, or configs.'
Write-Host ''

python -m pytest tests/test_v13_phase4.py tests/test_v13_phase4_seal_compat.py -q
if ($LASTEXITCODE -ne 0) { throw 'Phase4 compatibility tests failed; holdout not opened' }

python scripts/open_v13_phase4_holdout_fix1.py --verify-only
if ($LASTEXITCODE -ne 0) { throw 'Phase4 compatibility preflight failed; holdout not opened' }

# Publish only the external compatibility wrapper before opening the holdout.
$files = @(
  'OPEN_V13_PHASE4_HOLDOUT_FIX1.ps1',
  'scripts/open_v13_phase4_holdout_fix1.py',
  'tests/test_v13_phase4_seal_compat.py',
  'docs/V13_PHASE4_SEAL_COMPAT_FIX1.md'
)

git add -- $files
if ($LASTEXITCODE -ne 0) { throw 'git add for compatibility patch failed' }

$staged = git diff --cached --name-only
if ($LASTEXITCODE -ne 0) { throw 'git diff --cached failed' }

$unexpected = @($staged | Where-Object { $_ -and ($files -notcontains $_) })
if ($unexpected.Count -gt 0) {
  throw ('Unexpected staged files detected; refusing to open holdout: ' + ($unexpected -join ', '))
}

if ($staged) {
  git commit -m 'fix: Phase4 sealed-manifest verifier compatibility 46bbbf85'
  if ($LASTEXITCODE -ne 0) { throw 'Compatibility commit failed; holdout not opened' }
  git push origin main
  if ($LASTEXITCODE -ne 0) { throw 'Compatibility push failed; holdout not opened' }
}

$tagExists = $false
$localTags = git tag --list $CompatTag
if ($localTags -contains $CompatTag) { $tagExists = $true }
if (-not $tagExists) {
  git tag -a $CompatTag -m 'Phase4 verifier-only compatibility patch; sealed model unchanged'
  if ($LASTEXITCODE -ne 0) { throw 'Compatibility tag creation failed; holdout not opened' }
}

git push origin $CompatTag
if ($LASTEXITCODE -ne 0) {
  # If remote already has the exact tag, accept it.
  $remoteTag = git ls-remote --tags origin "refs/tags/$CompatTag"
  if (-not $remoteTag) { throw 'Compatibility tag push failed; holdout not opened' }
}

Write-Host ''
Write-Host 'Compatibility patch published. Opening one-shot holdout with the ORIGINAL sealed engine...'
python scripts/open_v13_phase4_holdout_fix1.py
if ($LASTEXITCODE -ne 0) { throw 'Phase4 holdout run failed. Same seal/same sealed engine resume only.' }

Write-Host '============================================================'
Write-Host 'PHASE 4 HOLDOUT OPEN COMPLETE'
Write-Host "Seal ID: $ExpectedSeal"
Write-Host "Compatibility tag: $CompatTag"
Write-Host 'Do not retune on these results.'
Write-Host '============================================================'
