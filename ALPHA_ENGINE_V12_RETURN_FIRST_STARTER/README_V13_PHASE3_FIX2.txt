ALPHA ENGINE V13 - PHASE 3 FIX2
BUILD: V13_P3_FIX2_PARTIAL_EXECUTION_AND_AUDIT_2026-09-12

WHY THIS FIX EXISTS
The prior simulator treated a rebalance as all-or-nothing at t+1. If one ticker
in the trade set lacked an executable price, the entire portfolio rebalance was
cancelled. With a broad dynamic target this mechanically produced 501 skipped
executions out of 502 validation sessions. That makes the economic result
uninterpretable.

FIX2 CONTRACT
- 2025+ remains hard-blocked.
- Phase 2 champions and all six simultaneous horizons are unchanged.
- No fixed holding period, Top-N, min weight, or max weight is introduced.
- t+1 execution is now per ticker: unavailable names are left unchanged/not opened;
  executable names still trade. One unavailable ticker cannot cancel the rebalance.
- Execution quality is measured as unfilled requested notional / requested notional.
- New audit exports benchmark semantics for SPY/QQQ/Universe-EW.
- New audit exports the actual influence weight of every horizon in the advisor.
- The return hurdle / qualification standard is NOT relaxed.

NEW OUTPUTS
  outputs/v13_phase3_benchmark_audit.csv
  outputs/v13_phase3_horizon_influence_audit.csv

RUN
Extract over the V12 starter root and run only:
  Set-ExecutionPolicy -Scope Process Bypass
  .\RUN_V13_PHASE3.ps1

Expected build signature:
  V13_P3_FIX2_PARTIAL_EXECUTION_AND_AUDIT_2026-09-12
