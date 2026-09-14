# V13 Phase 4B FIX2 — technical resume after reporting failure

The 2025+ holdout has already begun and is therefore considered **observed**. This patch does not restore virgin status and does not attempt to do so.

The sealed engine successfully reached holdout feature construction, scoring, advisor construction and portfolio simulation. It then failed while constructing `horizon_evidence` because `event_sector_incremental_alpha.evaluate()` requires `_alpha_rank`, while `final_holdout.py` merged holdout targets directly without recreating the target-derived `_robust_alpha` / `_alpha_rank` fields that Phase2U `horizon_frame()` created during research.

FIX2 is external to the sealed engine. It:

1. Requires the existing holdout marker to be `OPENING` for seal `46bbbf85...`.
2. Re-verifies every sealed file and the unchanged `final_holdout.py` SHA-256.
3. Keeps the FIX1 typed-key seal compatibility shim.
4. Recreates `_robust_alpha = min(excess_spy, excess_qqq, excess_uew)` and daily percentile `_alpha_rank` **only for ex-post horizon evidence reporting**.
5. Delegates to the original Phase2U `evaluate()`.
6. Calls the original sealed `open_holdout_once()` to resume and persist the already-determined economics.

It does **not** change features, models, scores, horizon reliability, active-alpha translation, Phase3Z portfolio policy, transaction costs, execution rules, NAV simulation, beta attribution, or the economic verdict rule.
