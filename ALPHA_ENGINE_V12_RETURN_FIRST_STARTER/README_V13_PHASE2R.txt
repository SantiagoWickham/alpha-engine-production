ALPHA ENGINE V13 - PHASE 2R
ADAPTIVE MULTI-EXPERT ALPHA REBUILD

Why this exists
---------------
Phase 3S proved that the current Phase-2 forecasters had negative 2021-2022 OOF economic alpha at every horizon. Portfolio optimization is therefore paused until the predictive engine recovers OOF alpha.

What Phase 2R changes
---------------------
1. Uses all PRE-2025 history as research through purged forward folds: 2017-18, 2019-20, 2021-22, 2023-24.
2. Keeps 2025+ hard-blocked.
3. Uses rolling five-year training and exponential recency weights instead of stale expanding-history fits.
4. Adds causal market-regime state variables derived only from same-date/past features.
5. Train-only feature ranking + redundancy pruning inside every horizon/fold.
6. Five experts per horizon:
   - Ridge future-return rank
   - HGB future-return rank
   - HGB absolute future return
   - HGB worst(SPY,QQQ) benchmark excess
   - HGB future-winner probability
7. Dynamic ensemble weights are learned only from PRIOR OOF evidence for each fold. No single architecture has to win forever.
8. No portfolio optimization is run. If predictor alpha is not recovered, portfolio work stops.

Run
---
From the V12 starter/root folder after extracting this package:
  Set-ExecutionPolicy -Scope Process Bypass
  .\RUN_V13_PHASE2R.ps1

Key outputs are written to sibling V13 workspace /outputs.
