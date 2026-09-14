ALPHA ENGINE V13 — PHASE 5C FIX1
COMPACT DECISION STATE FOR GOOGLE SHEETS 50K CELL LIMIT

Why this fix exists
-------------------
The Apps Script action decision_state_replace intentionally stores one JSON object in one Google Sheets cell.
Google Sheets caps a cell at 50,000 characters. Phase 5C originally embedded all 183 V13 contract rows inside that JSON, so the Apps Script correctly rejected it.

What changes
------------
- _ALPHA_DECISION_STATE now receives compact metadata only: seal_id, asof, input fingerprint, contract digest, row count, flags, model version.
- _ALERT_STATE receives the 183 row-wise ticker decisions using the API's existing structured table interface.
- The full authoritative contract remains in Python under outputs/live_shadow/v13_live_shadow_contract_latest.json.
- Readback still proves seal_id, asof, contract_digest, advisor row count, alert row count, shadow_only and real_orders_sent=false.

What does NOT change
--------------------
- sealed model
- features
- scores
- horizons
- Phase 3Z policy
- target weights
- costs
- live PIT inputs
- portfolio operations
- cash
- forward ledger
- Apps Script deployment

No Google Apps Script changes are required for this fix.
