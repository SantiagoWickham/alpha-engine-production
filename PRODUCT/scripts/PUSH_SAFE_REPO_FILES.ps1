$ErrorActionPreference="Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

Write-Host "============================================================"
Write-Host "ALPHA ENGINE - SAFE GITHUB PUBLISH"
Write-Host "============================================================"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is not installed or not on PATH."
}

if (-not (Test-Path ".git")) {
    git init
}

$remote = git remote get-url origin 2>$null
if (-not $remote) {
    Write-Host ""
    Write-Host "NO ORIGIN REMOTE CONFIGURED."
    Write-Host "Add your GitHub origin once, then rerun this script."
    exit 2
}

git add .gitignore README_FINAL.md TRACKS.json PRODUCT `
  ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\src `
  ALPHA_ENGINE_BYMA\research `
  ALPHA_ENGINE_BYMA\README*.txt `
  ALPHA_ENGINE_BYMA\RUN_*.ps1 2>$null

git status --short

Write-Host ""
Write-Host "Review above. This script intentionally excludes large outputs/data."
Write-Host "Commit and push manually when satisfied:"
Write-Host '  git commit -m "Production freeze: V13 Ideal + BYMA Transfer + web/sheets"'
Write-Host "  git push -u origin main"
