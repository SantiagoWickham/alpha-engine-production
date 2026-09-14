# Phase 4C — Observed holdout evidence checkpoint

Archival-only step after the one-shot 2025+ holdout. It copies small holdout evidence into `artifacts/validation`, hashes all large outputs, commits the evidence manifest, and publishes tag `v13-holdout-observed-46bbbf85`.

It does **not** retrain, rescore, alter weights, alter costs, or modify the sealed V13 model.
