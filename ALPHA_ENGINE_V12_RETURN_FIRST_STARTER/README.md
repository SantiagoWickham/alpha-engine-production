# ALPHA ENGINE V12 RETURN FIRST

Fresh rebuild. Data is the only inherited asset.

## Phase 1 goal

Establish an immutable data boundary, causal timing contracts, and an event-driven decision clock before any alpha model is trained.

## Install

From PowerShell in the project root:

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH="src"
pytest
python scripts/run_phase1.py
```

Optional slower fingerprinting of approved inputs:

```powershell
python scripts/run_phase1.py --hash-allowed
```

## Expected outputs

- `outputs/phase1_summary.json`
- `outputs/phase1_data_catalog.json`
- `outputs/phase1_decision_clock.json`

Phase 1 does **not** train a model, build a portfolio, place trades, alter Sheets, or publish a website.
