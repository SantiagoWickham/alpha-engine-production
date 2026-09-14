$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 8B"
Write-Host "PRE-OOS EXECUTION PARITY LOCK"
Write-Host "BUILD: V1_EXECUTION_PARITY_2026-09-12"
Write-Host "============================================="
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
$env:PYTHONPATH = "src"
Write-Host "`n[1/2] Running all tests..."
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Phase 8B tests failed with exit code $LASTEXITCODE" }
Write-Host "`n[2/2] Locking execution parity without opening final OOS..."
python scripts/run_phase8b.py
if ($LASTEXITCODE -ne 0) { throw "Phase 8B integrity gate failed with exit code $LASTEXITCODE" }
Write-Host "`nDONE. Send these SMALL files back to ChatGPT:"
Write-Host "  outputs\phase8b_summary.json"
Write-Host "  outputs\phase8b_gate.csv"
Write-Host "  outputs\phase8b_validation_confirmation.csv"
Write-Host "  outputs\phase8b_execution_model_spec.json"
Write-Host "  outputs\phase8b_freeze_manifest.json"
Write-Host "Keep NAV/edge/MILP audit CSVs locally unless requested."
Write-Host "FINAL OOS 2025+ remains untouched."
