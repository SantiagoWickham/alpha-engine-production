# V13 Phase 2U

Phase 2U is an OOF stacking layer over the Phase 2R predictor. It intentionally adds new information rather than new routing complexity.

The first OOF fold (2017-18) remains a base-score surface and supplies causal training rows. New-information meta predictions begin in 2019-20. For each later fold the meta model trains only on earlier OOF folds whose labels matured before the new fold starts.

2025+ remains hard-blocked.
