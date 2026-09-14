ALPHA ENGINE V13 - PHASE 5B LIVE PIT SHADOW FORWARD

Purpose
-------
Apply the exact sealed V13 model to new completed US sessions after the observed holdout end.
This is shadow only. It sends no orders and performs no tuning.

Inputs
------
- Phase5A PASS contract
- Phase4 sealed model bundle and seal manifest
- V12/V13 canonical historical source identified by Phase0
- Yahoo Finance live daily market data
- SEC companyfacts live PIT fundamentals

Safety / methodology
--------------------
- V13 sealed model is never retrained.
- Phase3Z policy is unchanged.
- Latest eligible-universe snapshot is carried forward only while within the configured age bound.
- Live Yahoo adjusted prices are rebased to the frozen historical feature-price anchor to avoid artificial jumps from subsequent dividends/splits.
- SEC facts are attached by filed date -> next trading session; no future filing is backfilled.
- Insufficient market/SEC/universe quality blocks publication.
- Outputs are append-only shadow evidence plus a latest production contract.

Run
---
.\RUN_V13_PHASE5B_LIVE_SHADOW.ps1

Key outputs
-----------
outputs/live_shadow/v13_live_shadow_summary.json
outputs/live_shadow/v13_live_shadow_contract_latest.csv
outputs/live_shadow/v13_live_shadow_contract_latest.json
outputs/live_shadow/v13_live_shadow_contract_history.csv
outputs/live_shadow/v13_live_shadow_scores.parquet
outputs/live_shadow/v13_live_shadow_advisor.parquet
outputs/live_shadow/v13_live_market_audit.csv
outputs/live_shadow/v13_live_sec_audit.csv
outputs/live_shadow/v13_live_adjusted_anchor_audit.csv
