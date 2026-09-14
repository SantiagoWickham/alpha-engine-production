ALPHA ENGINE V13 - PHASE 3Z
ROUNDTRIP RESIZE HYSTERESIS

Purpose
-------
Phase3Y proved that active-alpha translation can create positive residual alpha versus SPY, QQQ and the dynamic eligible-universe equal-weight benchmark. Its remaining weakness was high turnover, with most turnover still coming from resizing existing positions.

Phase3Z changes ONE structural rule only:
- entry still must pay the full round-trip hurdle;
- an existing position is still held while active alpha remains positive;
- a resize of an existing position now must justify the FULL expected round-trip cost of that tactical weight change, rather than only one transaction leg.

Unchanged
---------
- Phase2U predictor and OOF scores
- active-alpha target (50% UEW excess, 25% SPY excess, 25% QQQ excess)
- six horizons
- daily review
- no Top-N
- no per-name cap
- no fixed holding period
- 2025+ hard blocked

Decision rule
-------------
The new persistence rule must be Pareto-superior to Phase3Y at the 40bps stress case: lower annual turnover without lower 40bps CAGR. This avoids an arbitrary turnover target.
