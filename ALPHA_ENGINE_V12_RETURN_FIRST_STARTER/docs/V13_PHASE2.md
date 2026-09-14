# V13 Phase 2 — Nested Multi-Horizon Model Factory

Phase 2 converts the fresh causal feature library into six independent alpha surfaces. It deliberately does not solve portfolio sizing or cardinality.

## Economic selection criterion
For each model score and horizon, the highest-conviction 5%, 10%, and 20% of the cross-section are evaluated. At each cutoff, excess return is calculated versus SPY, QQQ, and the same-date equal-weight universe. The robust excess is the minimum of the three. The primary architecture score is the average robust excess across the three conviction cutoffs.

This avoids choosing models because of a high IC that does not translate into economically useful return concentration.

## Nested model selection
Architecture choice itself is nested through time. The 2019-2020 OOF surface uses an architecture selected using 2017-2018 evidence only. The 2021-2022 OOF surface uses only evidence available through 2020. These nested OOF surfaces are the only Phase-2 scores Phase 3 may use to select a portfolio policy.

## Holdout firewall
No 2025+ feature, target, score, return, or benchmark observation is loaded. Validation 2023-2024 never participates in champion selection.
