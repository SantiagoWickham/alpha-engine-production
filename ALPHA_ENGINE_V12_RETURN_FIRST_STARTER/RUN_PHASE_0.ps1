$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

Write-Host "============================================================"
Write-Host "ALPHA ENGINE V12.0 - RETURN FIRST - PHASE 0"
Write-Host "============================================================"

python .\scripts\00_environment.py
python .\scripts\01_inventory_data.py
python .\scripts\02_inventory_repo.py
python .\scripts\03_inventory_spreadsheets.py
python .\scripts\04_find_return_research_assets.py
python .\scripts\99_build_summary.py

Write-Host ""
Write-Host "PHASE 0 COMPLETE"
Write-Host "Subime los archivos de .\outputs indicados en README_START_HERE.md"
