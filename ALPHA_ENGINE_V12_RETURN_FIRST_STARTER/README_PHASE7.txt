ALPHA ENGINE V12 — PHASE 7
EXPECTED EDGE CALIBRATION & ALPHA LINEAGE
BUILD: V1_EDGE_LINEAGE_2026-09-12

PURPOSE
- Convert H20 alpha score into an expected 20-session return curve.
- Trade only when expected incremental return exceeds total cost + uncertainty buffer.
- Select edge/hysteresis parameters chronologically without final OOS.
- Audit alpha lineage from score -> reference -> theoretical -> optimizer -> MILP weights.

TEMPORAL CONTRACT
- 2019-2020: expected-return calibration only.
- 2021-2022: edge-policy selection only.
- 2023-2024: confirmation only; no hyperparameter tuning.
- 2025+: untouched final OOS.

IMPORTANT
Phase 6 Weekly/H20/Top15 remains the research benchmark. Phase 7 does not force Weekly or blindly force a calendar cadence. It builds the event-driven economic rule required for final execution: TRADE only when net expected benefit is positive after costs and uncertainty.

ALPHA LINEAGE
Same-snapshot diagnostics include Spearman, Kendall tau, top-5/top-10 capture/overlap, zero-reference-to-positive-theoretical mass, inversions, excluded top-alpha names, rank displacement, amplification, L1 distances, Alpha Capture, optimizer-vs-MILP localization and explicit loss mechanism.
