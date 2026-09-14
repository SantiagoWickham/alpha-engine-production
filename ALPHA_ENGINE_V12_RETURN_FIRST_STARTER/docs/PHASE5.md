# Phase 5 — Model Architecture Tournament

Phase 5 compares predictive architectures without opening the final OOS (2025+).

## Critical anti-double-dipping rule

Phase 4 used validation to label features as VALIDATED/WATCH. Phase 5 **does not use those labels to admit features**. The model feature pool is reconstructed from DEVELOPMENT-only coverage, FDR and IC.

## Tournament

Horizons: 20, 60, 120, 252 observed trading sessions.

Architectures:
- `DEV_IC_COMPOSITE`: deterministic development-IC weighted cross-sectional rank composite.
- `RIDGE_RANK`: linear regularized cross-sectional rank regression.
- `HGB_RANK`: nonlinear histogram gradient boosting rank regression.
- `HGB_WINNER`: direct future top-decile probability model.
- `BLEND_RIDGE_HGB`: rank blend of linear and nonlinear regression models.

Feature preprocessing is same-date cross-sectional percentile ranking. No target, future return, target price, adjusted-price level, Phase 4 validation status or final OOS label is a model feature.

## Walk-forward

Two expanding, purged DEVELOPMENT folds:
- 2019–2020 test window
- 2021–2022 test window

Training labels must end before each test window begins. Test labels must end before the test window boundary. Final validation is 2023–2024 with `target_end_date < 2025-01-01`.

## What Phase 5 does not decide

It does not freeze the final model, choose the event threshold, rebalance cadence, portfolio weights, transaction-cost model or execution rules. Those belong to Phase 6+.
