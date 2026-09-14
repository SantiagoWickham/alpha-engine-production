$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:PYTHONPATH = (Join-Path $Root "src")
Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 9"
Write-Host "FINAL OOS ONE-SHOT EVALUATION"
Write-Host "BUILD: V1_FINAL_OOS_ONE_SHOT_2026-09-12"
Write-Host "============================================="
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
Write-Host "`n[1/2] Running all tests..."
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }
Write-Host "`n[2/2] OPENING FINAL OOS EXACTLY ONCE..."
python scripts/run_phase9.py
if ($LASTEXITCODE -ne 0) { throw "Phase 9 integrity evaluation failed with exit code $LASTEXITCODE" }
Write-Host "`nDONE. FINAL OOS IS NOW CONSUMED. Do not rerun/tune against 2025+ results."
Write-Host "Send these SMALL files back to ChatGPT:"
Write-Host "  outputs\phase9_summary.json"
Write-Host "  outputs\phase9_gate.csv"
Write-Host "  outputs\phase9_acceptance_gate.csv"
Write-Host "  outputs\phase9_performance_summary.csv"
Write-Host "  outputs\phase9_predictive_diagnostics.csv"
Write-Host "  outputs\phase9_oos_consumption_receipt.json"
Write-Host "Keep OOS scores/NAV/edge/MILP detail files locally unless requested."
