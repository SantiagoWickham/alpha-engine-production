ALPHA ENGINE BYMA NATIVE 2.1.1
================================

Purpose
-------
Final structural research attempt for the independent BYMA-native model.

Observed in 2.0.1:
- PRE2025 mean IC: 0.0559
- 2025+ mean IC: 0.0588
- PRE2025 portfolio CAGR 20bps: 19.28%
- Holdout portfolio CAGR 20bps: 20.90%
- failure was portfolio economics, not ranking collapse.

2.1 therefore does NOT discard the native base ranking.

Architecture
------------
Stage 1:
  BYMA Native 2.0.1 OOF scores / holdout scores.

Stage 2:
  A fresh walk-forward meta-alpha layer trained only on BYMA observations:
  - base native score
  - market/state features
  - sector/rotation features
  - SEC/event features
  - residual-sector interactions

Three magnitude experts:
  - Ridge
  - HistGradientBoosting
  - monotonic Isotonic score->active-alpha mapping

Expert weights are learned prospectively from an inner temporal validation
window inside each training sample. No 2025+ result is used for tuning.

Target
------
Expected active return per session:

  50% excess vs current-BYMA equal weight
  25% excess vs SPY
  25% excess vs QQQ

Portfolio
---------
Same cost-aware Phase3Z economics:
- no Top-N
- no arbitrary number of positions
- entry must justify full round-trip cost
- existing position persistence / resize hysteresis
- theoretical continuous portfolio is authoritative
- integer nominal snapshots are implementation utilities only

Primary acceptance (PRE2025 OOF only)
-------------------------------------
Must pass all:
- CAGR > 0 at 20 / 40 / 60 bps
- annualized regression alpha > 0 vs SPY
- annualized regression alpha > 0 vs QQQ
- annualized regression alpha > 0 vs BYMA equal-weight
- CAGR > BYMA equal-weight CAGR
- MaxDD > -40%
- at least 2 of 3 OOF portfolio subperiods positive
- at least 2 of 3 OOF subperiods beat BYMA equal-weight

If PASS:
  FREEZE_NATIVE_2_1_AND_START_FORWARD_SHADOW

If FAIL:
  REJECT_NATIVE_FINAL_USE_TRANSFER
  Native research stops. Use V13 IDEAL + BYMA TRANSFER as the two model tracks.

Run
---
PowerShell -ExecutionPolicy Bypass -File .\RUN_ALPHA_ENGINE_BYMA_NATIVE_2_1.ps1


2.1.1 engineering correction
----------------------------
2.1.0 stopped during WF_2019_2020 / 252d before producing a complete model
because its single fixed inner-validation split left no fully resolved 252-day
targets in the inner training partition.

2.1.1 does NOT change:
- model hypothesis,
- features,
- experts,
- portfolio economics,
- primary gates,
- 2025+ treatment,
- no-Top-N policy.

It only replaces the brittle fixed inner split with a purged temporal split
feasibility search inside the outer training sample. The search chooses the
feasible split closest to the original 75/25 design and fails closed with row
counts if none exists. fit_two_models also explicitly rejects empty or
degenerate target arrays.
