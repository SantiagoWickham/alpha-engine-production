# V13 Phase 5A — Shadow Production Parity Contract

Purpose: establish a deterministic production interface from the sealed V13 model without changing economics.

Gate sequence:
1. Recompute the published Phase4 seal using the documented integer-key JSON compatibility rule.
2. Verify every sealed file SHA-256.
3. Require completed observed holdout with STRONG_CONFIRMATION and no post-open retraining/policy change.
4. Rebuild the holdout advisor from the sealed bundle and persisted holdout scores.
5. Require numeric parity to persisted advisor within 1e-12.
6. Translate the latest advisor state through unchanged Phase3Z target construction.
7. Emit a UI/API-neutral contract. No portfolio actions are inferred until real holdings/cash are connected.
