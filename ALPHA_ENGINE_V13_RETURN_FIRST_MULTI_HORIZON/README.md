# Alpha Engine

Quantitative multi-horizon active-alpha research and portfolio engine.

## Current frozen research state

The repository is initialized from the **V13 pre-holdout freeze**. The code-blinded holdout begins on **2025-01-01** and must be opened only after verifying the frozen manifest.

- Freeze artifact: `artifacts/freeze/v13_phase3aa_freeze_manifest.json`
- Research status at freeze: `PASS`
- Predictor: Phase 2U frozen
- Portfolio translation: Phase 3Z round-trip resize hysteresis
- 2025+ data: not used at freeze

## Repository policy

Source code, configuration, scripts, tests, documentation, and curated freeze manifests are versioned. Raw datasets, caches, Parquet files, derived outputs, credentials, and secrets are intentionally excluded.

## Architecture

`Python engine -> stable decision/output contract -> Google Sheets / Apps Script + Web UI`

Python is the source of truth for model scores, active alpha, horizon logic, target weights, and portfolio actions. Sheets and the web application are consumers/operational interfaces, not independent model implementations.
