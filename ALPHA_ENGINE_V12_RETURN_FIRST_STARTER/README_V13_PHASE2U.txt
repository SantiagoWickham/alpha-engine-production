V13 Phase 2U - Event + Sector Incremental Alpha

Purpose
-------
This is a single-block predictive expansion after Phase 2T showed that architecture/routing alone could not recover robust alpha.
It reuses Phase2R OOF scores and adds genuinely new PIT information:
- SEC filing/earnings-event surprise, growth, freshness, and post-event reaction features.
- Sector ETF raw-close rotation plus rates/inflation/commodity proxies.
- Stock-specific rolling sector beta / implied sector momentum.

No 2025+ data are used. No portfolio is run. Base Phase2R models are not retrained.

Run
---
.\RUN_V13_PHASE2U.ps1

Key outputs
-----------
outputs/v13_phase2u_summary.json
outputs/v13_phase2u_gate.csv
outputs/v13_phase2u_horizon_summary.csv
outputs/v13_phase2u_2021_2022_evidence.csv
outputs/v13_phase2u_2023_2024_evidence.csv
outputs/v13_phase2u_incremental_vs_base.csv
outputs/v13_phase2u_rotation_source_audit.csv
outputs/v13_phase2u_event_source_audit.csv
outputs/v13_phase2u_oof_scores.parquet
