V13 PHASE 2T — REGIME ROUTER META-ADVISOR
BUILD: V13_P2T_FIX2_PHASE1_TARGET_SURFACE_2026-09-12

Purpose:
- Reuse Phase2S OOF predictions. No expert retraining.
- Learn conditional expected alpha from each horizon score plus causal macro regime state.
- Keep all six horizons evaluated while allowing confidence to vary sharply by regime.
- Router selection is nested: current fold may use only router evidence from earlier OOF folds.
- 2025+ remains blocked.

Critical FIX2:
- Phase2T now uses outputs/v13_phase1_research_targets.parquet, the SAME research target surface used by Phase2S.
- It no longer reads the broader V12 outputs/phase3_return_targets.parquet.
- A schema preflight validates every required target/excess column for all six horizons before any router fit.
- Phase2S score/feature caches and Phase1 research targets must contain no 2025+ signal dates.
- Each horizon additionally requires target_resolved=true and target_end_date < 2025-01-01, so a pre-2025 signal can never consume a label realized in the holdout.

Validation:
- 9/9 tests PASS.
- Includes a full synthetic end-to-end build_router run across 4 walk-forward folds and all 6 horizons.

Run from V12 starter root:
  .\RUN_V13_PHASE2T.ps1
