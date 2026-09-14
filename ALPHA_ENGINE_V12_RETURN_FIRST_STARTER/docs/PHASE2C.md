# Phase 2C — Return Price Enrichment

Phase 2C resolves the failed Phase 2B corporate-action gate without changing the canonical observable price series.

The invariant is:

- `close` remains the observable raw/session-close field.
- `target_total_return_price` is a separate adjusted-price field used for label construction only.
- `target_price_feature_allowed` is hard-coded `False`.

Fresh Yahoo chart histories are cached in `data/v12/adjusted_prices_yahoo/` and validated by raw-close identity against the Phase 2 PIT panel. The existing six-year adjusted dataset is used only as an independent cross-check.

No alpha training is permitted until `outputs/phase2c_summary.json` reports `PASS`.
