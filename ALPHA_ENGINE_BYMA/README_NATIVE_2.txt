ALPHA ENGINE BYMA NATIVE 2.0.1
================================

This build is intentionally different from BYMA 1.0/1.0.1.

1.x = transfer benchmark:
      frozen V13 predictions -> BYMA universe -> portfolio.

2.0 = native BYMA predictor:
      PIT feature library -> BYMA universe FIRST -> fresh walk-forward models
      -> OOF calibration -> portfolio.

The native model does NOT read v13_phase2u_oof_scores.parquet and does NOT use
v13_phase4_holdout_advisor.parquet as predictions.

Shared with V13:
- PIT raw feature/target infrastructure
- market/execution data
- transaction-cost / hysteresis portfolio mechanics
- benchmark machinery
- fixed feature engineering code

Independent:
- fitted prediction models
- OOF scores
- horizon calibration
- advisor predictions
- portfolio targets
- native model bundle

The 2025+ period has already been observed during prior work. Therefore:
- 2019-2024 walk-forward OOF evidence is PRIMARY.
- 2025+ is SECONDARY / POST-HOC diagnostic.
- if pre-2025 passes, the model is frozen and forward shadow starts now.

Run:
    PowerShell -ExecutionPolicy Bypass -File .\RUN_ALPHA_ENGINE_BYMA_NATIVE.ps1

Key outputs:
    outputs\native_v2\byma_native_summary.json
    outputs\native_v2\byma_native_oof_scores.parquet
    outputs\native_v2\byma_native_holdout_scores.parquet
    outputs\native_v2\byma_native_holdout_gap_diagnostic.csv
    outputs\native_v2\byma_native_ic_by_horizon.csv
    outputs\native_v2\byma_native_nav_pre2025_20bps.csv
    outputs\native_v2\byma_native_nav_holdout_20bps.csv
    outputs\native_v2\byma_native_current_target_continuous.csv
    outputs\native_v2\byma_native_current_target_usd320.csv
    outputs\native_v2\byma_native_current_target_usd1000.csv
    outputs\native_v2\byma_native_model_bundle.joblib


2.0.1 correction
----------------
2.0.0 unnecessarily called the V13 Phase4 production-seal verifier only to
obtain the old fitted bundle's feature architecture. That is inappropriate for
an independent native model and failed because the working V13 tree is no
longer byte-identical to the original seal.

2.0.1:
- does NOT verify or mutate the V13 production seal;
- does NOT load V13 fitted model bundle;
- does NOT use V13 OOF scores;
- does NOT use V13 holdout advisor predictions;
- derives the model feature universe from the PIT phase1 feature library;
- applies explicit leakage-name guards;
- still shares the already-built PIT data and execution/backtest machinery.

This makes the predictor materially more independent from V13.
