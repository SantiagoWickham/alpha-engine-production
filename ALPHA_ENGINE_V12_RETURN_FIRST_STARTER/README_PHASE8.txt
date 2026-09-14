ALPHA ENGINE V12 - PHASE 8
PRE-FREEZE REFIT / REPLAY / FINGERPRINT
BUILD: V1_PRE_FREEZE_LOCK_2026-09-12

Purpose
-------
1. Keep the Phase 5 H20 DEV_IC_COMPOSITE feature set fixed.
2. Refit only fixed feature-weight magnitudes on all mature pre-OOS labels.
3. Refit the monotone H20 score -> expected-return calibration on all mature pre-OOS labels.
4. Copy Phase 7 policy hyperparameters exactly. No re-selection.
5. Re-run structural alpha-lineage checks using the final refit parameters.
6. Run the exact pre-OOS engine twice and require identical deterministic hashes.
7. Build a canonical SHA-256 model/policy/calibration fingerprint.
8. Do NOT open 2025+ final OOS.

Important
---------
The pre-freeze replay is NON-EVALUATIVE because the final refit uses all mature pre-OOS information.
Its CAGR is recorded only as an engineering diagnostic. It cannot be used to select or change anything.

After PASS
----------
The model/policy is LOCKED_PRE_OOS. Do not modify it before Phase 9.
Phase 9 will open the final OOS beginning 2025-01-01 exactly once.
