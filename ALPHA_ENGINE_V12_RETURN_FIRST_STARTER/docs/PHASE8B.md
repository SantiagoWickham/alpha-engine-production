# Phase 8B — Pre-OOS Execution Parity Lock

This is a correctness patch before final OOS. It does not tune or re-select anything. It makes the NAV engine use the portfolio-weighting path already audited in Phase 7/8.

Frozen membership decisions come from expected net edge. On a membership-changing event only, weights are recomputed as expected-return LCB → continuous capped weights → MILP, constrained to exactly the membership approved by the net-edge decision. This preserves the one-replacement-per-session rule while making research and future live execution identical.
