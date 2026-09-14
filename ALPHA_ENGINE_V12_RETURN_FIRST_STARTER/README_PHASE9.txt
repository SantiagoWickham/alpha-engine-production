ALPHA ENGINE V12 - PHASE 9
FINAL OOS ONE-SHOT EVALUATION
BUILD: V1_FINAL_OOS_ONE_SHOT_2026-09-12

This phase consumes the untouched 2025+ holdout exactly once.
It is cryptographically bound to final Phase 8B freeze fingerprint:
3cd792488b41f5954b6a7cf944e05cff582fe94fc30d187c42e6935a1c5e3e1d

It does NOT refit, tune, select features, change thresholds, change costs,
change membership rules, change optimizer rules, or change MILP rules.

Important state treatment:
- Frozen scores from 2023-01-03 through 2024-12-31 reconstruct portfolio carry-in state.
- OOS scores are generated from 2025-01-01 onward with the frozen nine-feature H20 model.
- Therefore 2025 does NOT start artificially from 100% cash.
- A decision made at the last pre-OOS close and executed in the first 2025 session is correctly charged to OOS.

Acceptance criteria are fixed BEFORE seeing OOS:
- at least 252 OOS sessions,
- positive net CAGR at 20 bps round-trip,
- positive net CAGR at 40 bps round-trip,
- max drawdown no worse than -50%,
- execution skip rate <=5%,
- MILP success rate 100%,
- deterministic replay and exact freeze/scorer integrity.

After a successful run, phase9_oos_consumption_receipt.json is written and a second run is refused.
If OOS fails, do not tune on 2025+ and call it OOS again.
