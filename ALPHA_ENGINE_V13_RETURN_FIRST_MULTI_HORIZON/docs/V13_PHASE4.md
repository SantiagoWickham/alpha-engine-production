# Alpha Engine V13 — Phase 4

Phase 4 is intentionally two-stage.

1. `SEAL_V13_PHASE4.ps1` trains the final six pre-2025 model stacks using only labels matured before 2025-01-01, serializes them, hashes every research input/model artifact, commits the Phase 4 implementation + seal manifest, pushes it, and tags the result `v13-holdout-seal-<seal-prefix>`.
2. `OPEN_V13_PHASE4_HOLDOUT.ps1` refuses to run unless the published seal tag contains the same manifest. It then opens 2025+ exactly once. A same-code/same-seal interrupted OPEN may resume; a completed OPEN cannot be rerun.

The holdout never chooses new hyperparameters, features, horizons, policy parameters, transaction-cost assumptions, or portfolio gates.
