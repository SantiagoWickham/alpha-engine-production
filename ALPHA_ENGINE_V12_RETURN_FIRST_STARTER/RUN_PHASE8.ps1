$ErrorActionPreference = "Stop"
Write-Host "============================================="
Write-Host "ALPHA ENGINE V12 - PHASE 8"
Write-Host "PRE-FREEZE REFIT / REPLAY / FINGERPRINT"
Write-Host "BUILD: V1_PRE_FREEZE_LOCK_2026-09-12"
Write-Host "============================================="

$env:PYTHONPATH = "src"
python -m pip install -r requirements.txt

Write-Host ""
Write-Host "[1/2] Running all tests..."
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Phase 8 test gate failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "[2/2] Refitting fixed components and locking pre-OOS freeze..."
python scripts/run_phase8.py
if ($LASTEXITCODE -ne 0) { throw "Phase 8 integrity gate failed with exit code $LASTEXITCODE" }

Write-Host ""
Write-Host "DONE. Send these SMALL files back to ChatGPT:"
Write-Host "  outputs\phase8_summary.json"
Write-Host "  outputs\phase8_gate.csv"
Write-Host "  outputs\phase8_final_feature_weights.csv"
Write-Host "  outputs\phase8_final_edge_calibration.csv"
Write-Host "  outputs\phase8_final_model_spec.json"
Write-Host "  outputs\phase8_freeze_manifest.json"
Write-Host "  outputs\phase8_replay_summary.csv"
Write-Host ""
Write-Host "Keep the larger pre-OOS score/replay files locally."
Write-Host "DO NOT run any 2025+ OOS script until Phase 8 is PASS and reviewed."
