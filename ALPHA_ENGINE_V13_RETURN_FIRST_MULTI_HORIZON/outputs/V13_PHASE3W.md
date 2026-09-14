# V13 Phase 3W — Pre-holdout stress and freeze

The Phase3V portfolio economics already qualified. Its only blocking failure was the legacy requirement that >=95% of OOF rows contain all six horizons simultaneously. That requirement confuses **forecast availability** with **outcome maturity**: a 252-session OOF outcome cannot mature near the pre-2025 boundary without using the holdout.

Phase3W therefore audits the intended advisor semantics instead:

1. Every advisor row must have at least one causally available horizon.
2. Available horizon weights must renormalize exactly to one.
3. Every one of 5/10/20/60/120/252 must have positive aggregate influence in every evaluation fold.
4. No horizon may monopolize mean influence.
5. Full six-horizon row completeness remains reported, but is nonblocking in OOF research.
6. Live/deployment generation retains the invariant that all six horizons should be emitted when inputs are available.

The selected Phase3V policy is not reselected. It is replayed under 20, 40, 60, 80 and 100 bps round-trip costs, then frozen with SHA-256 hashes of code, config, predictor outputs and policy artifacts.
