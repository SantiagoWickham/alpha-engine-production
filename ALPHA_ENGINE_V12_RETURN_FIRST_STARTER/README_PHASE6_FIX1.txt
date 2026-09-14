ALPHA ENGINE V12 - PHASE 6 FIX1
BUILD: V1_FIX1_PANDAS_LOC_2026-09-12

Fix only: boolean row mask + explicit column selection now uses DataFrame.loc in both OOF and validation score-surface regeneration.
No methodology, Phase 5 champion, OOS boundary, costs, ensemble, cadence, top-N, hysteresis, or portfolio-selection logic changed.
Regression test added for the exact pandas InvalidIndexError.
