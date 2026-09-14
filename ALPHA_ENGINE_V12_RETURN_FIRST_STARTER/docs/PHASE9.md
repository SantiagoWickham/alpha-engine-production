# Phase 9 — Final OOS One-Shot Evaluation

Phase 9 is not research. It is the one-time opening of the untouched `2025-01-01+` holdout.

## Frozen identity
The package is bound to Phase 8B final freeze fingerprint:
`3cd792488b41f5954b6a7cf944e05cff582fe94fc30d187c42e6935a1c5e3e1d`.

Before opening OOS it verifies the Phase 8 source manifest, the Phase 8B execution fingerprint,
and the exact reviewed `execution_parity.py` source SHA-256. It also regenerates 2024 scores and
requires essentially perfect correlation with the stored Phase 8 frozen scores.

## Carry-in state
The final OOS portfolio starts from the state produced by the frozen engine immediately before
2025. Phase 9 reconstructs that state by replaying frozen pre-OOS scores beginning 2023-01-03,
then continues the same engine into 2025+. Performance metrics are rebased only at the OOS boundary.

## Performance verdict
The verdict is return-first and predeclared. `PASS_FOR_SHADOW_FORWARD` requires at least 252 OOS
sessions, positive net CAGR under both 20 bps and 40 bps round-trip assumptions, and max drawdown
within 50%. Integrity additionally requires deterministic replay, no execution failure, 100% MILP
success, and exact frozen identity.

A failure is a genuine final OOS failure. The holdout is consumed either way and must not be retuned
and reused as if it were untouched.
