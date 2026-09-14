$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root 'src'
Write-Host '============================================================'
Write-Host 'ALPHA ENGINE V13 - PHASE 4A'
Write-Host 'FINAL PRE-2025 MODEL SEAL + GITHUB PUBLISH'
Write-Host '============================================================'
python -m pytest tests/test_v13_phase4.py -q
if ($LASTEXITCODE -ne 0) { throw 'Phase4 tests failed' }
python scripts/seal_v13_phase4.py
if ($LASTEXITCODE -ne 0) { throw 'Phase4 model seal failed' }
$manifest = Get-Content 'outputs/v13_phase4_model_seal_manifest.json' -Raw | ConvertFrom-Json
$seal = [string]$manifest.seal_id
$tag = 'v13-holdout-seal-' + $seal.Substring(0,8)
Write-Host "Seal ID: $seal"
Write-Host "Publishing tag: $tag"
$files = @(
  'config/v13_phase4.toml',
  'src/alpha_engine_v13/final_holdout.py',
  'scripts/seal_v13_phase4.py',
  'scripts/open_v13_phase4_holdout.py',
  'tests/test_v13_phase4.py',
  'docs/V13_PHASE4.md',
  'README_V13_PHASE4.txt',
  'SEAL_V13_PHASE4.ps1',
  'OPEN_V13_PHASE4_HOLDOUT.ps1',
  'artifacts/freeze/v13_phase4_model_seal_manifest.json'
)
git add -- $files
if ($LASTEXITCODE -ne 0) { throw 'git add failed' }
$staged = git diff --cached --name-only
if (-not $staged) { Write-Host 'Phase4 seal files already committed; continuing.' }
else {
  git commit -m "seal: Alpha Engine V13 final models before 2025+ holdout $($seal.Substring(0,8))"
  if ($LASTEXITCODE -ne 0) { throw 'git commit failed' }
}
git push origin main
if ($LASTEXITCODE -ne 0) { throw 'git push main failed' }
$tags = git tag --list $tag
if (-not $tags) { git tag -a $tag -m "Alpha Engine V13 final model seal before 2025+ holdout" }
git push origin $tag
if ($LASTEXITCODE -ne 0) { throw 'git push tag failed' }
Write-Host '============================================================'
Write-Host 'PHASE 4 MODEL SEAL PUBLISHED SUCCESSFULLY'
Write-Host "Tag:     $tag"
Write-Host "Seal ID: $seal"
Write-Host '2025+ HAS NOT BEEN OPENED.'
Write-Host 'Next command: .\OPEN_V13_PHASE4_HOLDOUT.ps1'
Write-Host '============================================================'
