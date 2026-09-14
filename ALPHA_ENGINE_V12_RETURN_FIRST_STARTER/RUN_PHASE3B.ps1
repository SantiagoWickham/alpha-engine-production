$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 3B"
Write-Host "UNRESOLVED TERMINATION AUDIT"
Write-Host "BUILD: V1_2026-09-12"
Write-Host "============================================="

if (-not (Test-Path ".\outputs\phase3_return_targets.parquet")) { throw "Missing outputs\phase3_return_targets.parquet. Run Phase 3 first." }
if (-not (Test-Path ".\outputs\phase3_summary.json")) { throw "Missing outputs\phase3_summary.json." }
if (-not (Test-Path ".\outputs\phase2_canonical_pit_panel.parquet")) { throw "Missing Phase 2 canonical panel." }
if (-not (Test-Path ".\outputs\phase2c_return_price_layer.parquet")) { throw "Missing Phase 2C return price layer." }

$buildCheck = Select-String -Path ".\src\alpha_engine_v12\termination_audit.py" -Pattern 'PHASE3B_BUILD = "V1_2026-09-12"' -SimpleMatch -Quiet
if (-not $buildCheck) { throw "Phase 3B V1 is not installed in project root." }

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed with exit code $LASTEXITCODE" }
$env:PYTHONPATH = "src"

Write-Host "`n[1/2] Running all tests..."
pytest
if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE" }

Write-Host "`n[2/2] Auditing unresolved terminations..."
python scripts/run_phase3b.py
if ($LASTEXITCODE -ne 0) { throw "Phase 3B audit failed with exit code $LASTEXITCODE" }

Write-Host "`nDONE. Send these four SMALL files back to ChatGPT:"
Write-Host "  outputs\phase3b_summary.json"
Write-Host "  outputs\phase3b_unresolved_tickers.csv"
Write-Host "  outputs\phase3b_classification_summary.csv"
Write-Host "  outputs\phase3b_repair_plan.csv"
Write-Host "`nKeep the large Phase 3 target parquet locally. Do not train alpha yet."
