ALPHA ENGINE V13 - PHASE 5C SHEETS SHADOW BRIDGE

Purpose
- Connect the already-PASS V13 Phase5B live shadow contract to the existing Apps Script API.
- Python V13 remains the ONLY source of model truth.
- Read current positions, cash and mandate from Sheets for audit/snapshot.
- Publish the exact V13 contract to _ALPHA_DECISION_STATE and shadow alerts to _ALERT_STATE.
- Read both back and require parity.

Safety
- Does NOT call operation_append.
- Does NOT mutate cash.
- Does NOT append forward execution events.
- Does NOT retrain/tune/change the sealed model.
- Does NOT require editing or redeploying Apps Script; it reuses V9.1-FORWARD-CLOUD API already present.
- Reads MMM_SHEET_API_URL and MMM_SHEET_API_TOKEN from process env or .env. Secrets are never written to outputs.

This phase deliberately does NOT yet convert model targets into real BUY/HOLD/REDUCE/EXIT instructions. It first captures the actual portfolio/cash/mandate schema and proves the transport/readback bridge end-to-end. The next phase can translate the sealed Phase3Z economic target against the real portfolio state without guessing portfolio semantics.
