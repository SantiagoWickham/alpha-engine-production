ALPHA ENGINE V12 - PHASE 4
LEAKAGE-FREE FEATURE LIBRARY & PREDICTIVE RESEARCH
BUILD: V1_PURGED_PRE_OOS_2026-09-12

PURPOSE
- Build features from scratch using only information available at or before each signal close.
- Keep adjusted-price levels and all Phase 3 targets out of the feature library.
- Measure pre-OOS cross-sectional predictive evidence with daily Spearman IC, HAC t-statistics,
  Benjamini-Hochberg FDR, validation sign confirmation, top-bottom return spreads and winner lift.
- Fix the final untouched OOS before model research.

PARTITIONS
- Development signals: from 2015-01-02, with outcomes ending BEFORE 2023-01-03.
- Validation signals: from 2023-01-03, with outcomes ending BEFORE 2025-01-01.
- Final OOS signals: 2025-01-01 onward. Their labels are NOT used in Phase 4 predictive research.

IMPORTANT PRICE FIREWALL
Phase 4 does NOT read outputs/phase2c_return_price_layer.parquet to create features.
It reconstructs a temporary source adjusted-price surface from:
1) canonical panel adj_close where historically available, and
2) Phase 2C Yahoo source-cache adj_close only when panel adj_close is missing.
The adjusted LEVEL is never exported. Only backward-looking scale-invariant transforms
(returns, trend ratios, vol, drawdown/distances) are retained.

Phase 3 targets are joined only inside predictive research AFTER the feature parquet is built.
No target column is written to outputs/phase4_feature_library.parquet.
