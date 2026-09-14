# V13 Phase 3 — Cross-Horizon Advisor + Dynamic Portfolio

## Advisor contract
For every stock and every completed session, keep all six forecast horizons alive: 5, 10, 20, 60, 120 and 252 sessions. Horizon forecasts are calibrated to benchmark-robust expected excess return using OOF data only. They are expressed on a comparable per-session basis and combined using precision weights; disagreement increases uncertainty rather than being hidden by a simple average.

The surface retains tactical (5/10/20D) and strategic (60/120/252D) views separately. A 60D or 252D forecast is never a mandatory holding period.

## Portfolio contract
The number of holdings is not a parameter. A name is eligible only when its cross-horizon lower-confidence-bound excess return remains positive after an economically selected economic entry hurdle. Long-only weights use a one-factor robust Kelly approximation with causal trailing risk estimates and cash. No fixed per-name max/min weight is imposed.

The model evaluates each session. Trading is event-driven and executes t+1 only if expected incremental expected excess benefit over the endogenous effective horizon exceeds estimated transaction costs plus the selected extra-edge buffer.

## Temporal contract
- 2019-2020: OOF calibration only.
- 2021-2022: dynamic portfolio policy selection only.
- 2023-2024: confirmation only.
- 2025+: blocked.
