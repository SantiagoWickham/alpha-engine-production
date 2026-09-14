ALPHA ENGINE V13 - PHASE 3
Cross-Horizon Advisor + Dynamic Portfolio

This phase implements the advisor requested by the user:
- Every stock is evaluated simultaneously at 5D, 10D, 20D, 60D, 120D and 252D.
- No horizon is selected as the only horizon.
- There is no fixed holding period. Every session re-evaluates the full term structure.
- Tactical view = 5/10/20D. Strategic view = 60/120/252D. Both remain visible.
- Portfolio cardinality is endogenous from positive robust net edge. There is no Top-N.
- Position weights are endogenous long-only robust-Kelly weights using a causal one-factor covariance model and cash. There is no 3%-12% band and no fixed name cap.
- Decisions are evaluated every session and execute next session only when expected incremental excess return exceeds costs + selected extra edge.
- 2019-2020 calibrates score->robust excess; 2021-2022 selects portfolio-policy parameters; 2023-2024 confirms only; 2025+ remains blocked.

Important dense-score repair:
Phase 2 score files contain only dates whose horizon labels mature inside each evaluation fold. Phase 3 therefore regenerates score-only surfaces for EVERY pre-2025 signal date using models trained strictly before each period. This is necessary for a true daily six-horizon advisor and does not use future labels.

Outputs are written to the separate V13 workspace under outputs/.
