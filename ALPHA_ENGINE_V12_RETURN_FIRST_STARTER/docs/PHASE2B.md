# Phase 2B — Price Semantics & Corporate Action Gate

Purpose: prevent corporate actions from contaminating forward-return targets.

This phase does **not** train an alpha model and does **not** create target returns.
It audits whether `close` is raw or adjusted, measures `adj_close` coverage,
compares primary/secondary prices to the delisted Yahoo reference where overlap exists,
scans the data tree for adjusted-price or corporate-action resources, and produces the
exact ticker/date requirements for any adjusted-history enrichment.

A FAIL is an expected research outcome, not a software failure. If the gate fails,
Phase 2C must repair/enrich adjusted price history before Phase 3 target construction.
