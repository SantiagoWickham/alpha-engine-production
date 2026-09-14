# Phase 6 — Portfolio Policy Tournament

Phase 6 compares research portfolio policies using the Phase 5 champion predictive architectures without touching the final OOS period (2025+).

## Selection contract

- Champion model architecture per horizon is inherited unchanged from Phase 5.
- Full daily score surfaces are regenerated causally inside each OOF fold and validation period. Long-horizon scores do not require matured future labels to exist.
- Policy hyperparameters are selected **only on OOF 2019–2022**.
- 2023–2024 is confirmation only and cannot change ensemble, top-N, cadence, or event hysteresis.
- Final OOS 2025+ is not loaded.

## Policy families

Scheduled research baselines: MONTHLY, WEEKLY, DAILY.

Event-driven research baselines: daily evaluation with rank hysteresis, material challenger edge and no calendar rebalance. These are not yet the final net-edge engine; Phase 7 converts the selected score policy into expected incremental return minus cost minus uncertainty buffer.

## Objective

Selection is return-first: base-cost OOF CAGR, worst-fold CAGR, stress-cost CAGR, then drawdown and turnover as robustness/tie-break diagnostics. Sharpe is not the optimization objective.
