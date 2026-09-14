ALPHA ENGINE V12 - PHASE 2 ADDITIVE PACKAGE

1) Extract this ZIP directly into the existing project root.
2) It should add config/phase2.toml, RUN_PHASE2.ps1, scripts/run_phase2.py,
   src/alpha_engine_v12/pit_panel.py, tests/test_phase2_pit_panel.py and docs/PHASE2.md.
3) Run from PowerShell at the project root:

   Set-ExecutionPolicy -Scope Process Bypass
   .\RUN_PHASE2.ps1

4) Send back only:
   outputs/phase2_summary.json
   outputs/phase2_source_audit.csv
   outputs/phase2_pit_audit.csv
   outputs/phase2_panel_schema.json

PATCH 1 (2026-09-12)
- Canonicalizes all internal date keys to datetime64[ns].
- Sorts merge_asof inputs by the temporal key before ticker.
- Adds regression coverage for mixed datetime precision and multiple tickers.
- RUN_PHASE2.ps1 now stops on pytest/Python non-zero exit codes.
