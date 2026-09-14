ALPHA ENGINE V13 - PHASE 5D
PORTFOLIO-AWARE SHADOW ACTIONS

Purpose
-------
Cross the frozen V13 live contract against the real portfolio snapshot already read from Google Sheets in Phase 5C.

Critical invariant
------------------
The translator calls the ORIGINAL Phase3Y/Phase3Z _economic_target() hysteresis logic. It adds no new Top-N, holding period, per-name cap or rebalance threshold.

Actions
-------
BUY    : economic target > current weight
HOLD   : no economic change required (including no-position/no-entry)
REDUCE : economic target remains positive but below current weight
EXIT   : exact Phase3Z target goes to zero

Safety
------
- Shadow/display only.
- No operation_append.
- No cash mutation.
- No forward ledger mutation.
- No tuning.

Run
---
.\RUN_V13_PHASE5D_PORTFOLIO_ACTIONS.ps1

Outputs
-------
outputs/portfolio_shadow/v13_portfolio_actions_latest.csv
outputs/portfolio_shadow/v13_portfolio_actions_latest.json
outputs/portfolio_shadow/v13_portfolio_actions_summary.json
