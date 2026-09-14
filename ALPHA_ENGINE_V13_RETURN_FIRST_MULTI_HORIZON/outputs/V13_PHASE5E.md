# V13 Phase 5E — Portfolio Action Review + Weight Basis Audit

This phase is governance/operations only. It does not change the sealed predictor or Phase3Z policy.

It consumes the successful Phase5D shadow action file and the read-only Sheets snapshots captured by Phase5C. It writes only local audit/review outputs under `outputs/portfolio_review/`.

The key control is weight-basis semantics. Legacy V8 Sheets normalizes `current_weight` over invested equity only. Phase3Z produces total-NAV target weights and may hold cash. Therefore exact dollar sizing is blocked whenever non-USD cash cannot be converted with an audited FX source.

Outputs:
- `v13_held_positions_review.csv`
- `v13_buy_candidates_review.csv`
- `v13_reduce_exit_review.csv`
- `v13_portfolio_basis_audit.json`
- `v13_portfolio_review_summary.json`
