# Phase 7 — Expected Edge Calibration & Alpha Lineage

Decision primitive:

`net_edge = expected_incremental_return - estimated_total_cost - uncertainty_buffer`

A replacement is proposed only when `net_edge > 0`.

Expected returns are calibrated monotonically from pre-selection OOF H20 scores to realized 20-session returns. The calibration uses daily cross-sectional bin means and Newey-West/HAC uncertainty with 20 lags.

The optimizer lineage is intentionally transparent. Reference weights are equal-weight top-15. The theoretical layer uses calibrated lower-confidence alpha across the top-20 candidate set. A capped continuous optimizer is followed by a discrete MILP that enforces cardinality and weight-grid implementability. Phase 7 measures exactly how much alpha is lost at each transformation.
