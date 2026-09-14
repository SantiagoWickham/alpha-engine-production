# V13 Phase 4B seal verifier compatibility fix

This patch does **not** change the sealed model, features, portfolio policy, configs, or `final_holdout.py`.

The Phase 4 seal was computed before JSON serialization while `horizon_reliability` used integer keys. After JSON round-trip, object keys are strings. `json.dumps(sort_keys=True)` sorts integer keys numerically but string keys lexicographically, so the same semantic payload produced a different verifier hash.

The compatibility wrapper:

1. requires the exact published seal id `46bbbf853561e26625ee3ecbccb6037051556f2f3ca26dcb4e311c165c08d8e9`;
2. verifies that the ordinary post-JSON hash mismatches;
3. restores **only** the six horizon-key types and requires that this reproduces the published seal exactly;
4. verifies every sealed file SHA-256 unchanged;
5. installs the compatibility hash in process memory only, then calls the original sealed `open_holdout_once()`.

No 2025+ data is accessed by the preflight.
