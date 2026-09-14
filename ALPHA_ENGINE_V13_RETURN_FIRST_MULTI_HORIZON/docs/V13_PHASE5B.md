# V13 Phase 5B — Live PIT Shadow Forward

Phase 5B is the first post-holdout forward inference layer. It consumes only completed US sessions after the Phase 5A parity anchor, reconstructs V13 features using live market and SEC PIT information, applies the sealed Phase 4 model bundle, and emits the unchanged Phase 3Z target-weight contract.

It is deliberately **not** a model-development phase. No target, feature selection, model coefficient, horizon reliability, calibration, portfolio policy, cost assumption, or threshold is estimated from forward outcomes.

The output contract is intended to become the single decision source for Google Sheets and the web interface. Those surfaces may display portfolio state and translate target weights into user-facing actions, but they must not implement a second alpha model.
