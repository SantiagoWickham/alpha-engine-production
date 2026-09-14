# Phase 4 — Leakage-Free Feature Library & Predictive Research

Phase 4 is the first alpha-research stage, but it does **not** fit the final model.

The data flow is strictly one-way:

`PIT sources -> feature library` and separately `Phase 3 labels -> isolated research join`.

## OOS firewall

The final OOS begins on signal date **2025-01-01**. Phase 4 never measures predictive performance on those labels.
Development and validation are additionally purged by each horizon's `target_end_date`, so a 252-session outcome cannot cross into the next partition.

## Statistical diagnostics

For each feature and target horizon, Phase 4 reports daily cross-sectional Spearman IC, Newey-West/HAC inference for the mean IC, Benjamini-Hochberg false-discovery-rate q-values, validation sign stability, and—only for statistically plausible discoveries—validation top-vs-bottom return spread and future-winner lift.

The feature direction is learned from DEVELOPMENT only. Validation cannot flip direction after the fact.

## Feature-price contract

Adjusted prices are not model inputs as levels. They are temporary source variables used solely to calculate causal, backward-looking, scale-invariant transformations. The target-only `target_total_return_price` is never read during feature generation.

## Fundamental contract

Fundamental inputs inherit Phase 2 strict-next-trading-session availability. Flow ratios are labelled `reported`/`snapshot`; Phase 4 does not falsely call a latest reported SEC fact a standardized TTM observation.
