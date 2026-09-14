ALPHA ENGINE V13 - PHASE 3Y
ACTIVE ALPHA + PERSISTENT PORTFOLIO

Purpose
-------
Rebuild only the score-to-weight translation after Phase3X showed:
- positive alpha vs SPY/QQQ but negative alpha vs Universe-EW,
- 87.6% of trading is resize churn,
- 5/10/20-day horizon dominance,
- daily rebalancing destroys value versus 5/10/20-session counterfactuals.

Phase3Y does NOT retrain Phase2U and does NOT open 2025+.

Structural changes
------------------
1. Portfolio weights are driven only by ACTIVE ALPHA, not absolute return.
   50% excess vs dynamic Universe-EW + 25% excess vs SPY + 25% excess vs QQQ.
2. No Top-N, no fixed per-name cap, no fixed holding period.
3. New entries require expected active alpha over the effective horizon to pay round-trip cost.
4. Existing holdings may persist while active alpha remains positive: transaction-cost hysteresis.
5. Resizes pass through an economically derived no-trade band based on transaction cost and risk curvature.
6. Daily evaluation remains intact; only economically unjustified trading is suppressed.
7. Universe membership lineage is written for survivorship diagnostics.

Main outputs
------------
v13_phase3y_summary.json
v13_phase3y_gate.csv
v13_phase3y_beta_attribution.csv
v13_phase3y_turnover.csv
v13_phase3y_conviction_curve.csv
v13_phase3y_period_metrics.csv
v13_phase3y_horizon_influence.csv
v13_phase3y_horizon_reliability.csv
v13_phase3y_universe_lineage.csv
v13_phase3y_nav_20bps.csv
v13_phase3y_nav_40bps.csv
