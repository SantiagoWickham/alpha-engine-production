# Alpha Engine V10.4 — Forensic Audit Report

**Model:** V10.4_FROZEN_UNCHANGED
**Audit:** V0.8_FORENSIC_BASE
**Rule:** V10.4 remains frozen. No retuning, no new factor, no threshold change, no cherry-picking.

## 1. Replay integrity
- Exact optimizer replay status: **FAIL**
- Secondary economic-closeness assessment: **NEAR_REPLAY_MAX_ERROR_LE_10BPS**
- Matched official monthly periods: 152
- Maximum absolute monthly net-return replay error: 7.208 bps
- Median absolute monthly net-return replay error: 0.322 bps
- CAGR gap reconstructed minus persisted on matched rows: 0.00%
- Exact FAIL is not upgraded to PASS merely because the error is small. Component-level gross/turnover/cost diagnostics are in replay_diagnostics.csv.

## 1B. Raw decision path vs frozen official monthly path
- Raw score-decision rows: 153
- Frozen official CORE profile months: 152
- Rows removed by the documented profile month-dedup rule: 1
- Raw forward-interval uniqueness: **FAIL**
- Official monthly forward-interval uniqueness: **PASS**
- Frozen profile cross-check: **PASS**
- Decision/forward causality: **FAIL** (1 violations)
- Latest interval: **PARTIAL_LATEST_INTERVAL**
- Important: a raw duplicate and an official monthly duplicate are not the same issue. V10.4's profile-freeze code explicitly keeps the last row per period_end month; the audit reports that semantics separately from the raw decision ledger.

## 2. Performance paths
- Frozen official profile months: 152; CAGR 25.19%; SPY 13.83%; spread 11.36%
- Completed-month-only diagnostic: 151 months; CAGR 25.12%; SPY 13.89%; spread 11.23%
- Causally-valid monthly diagnostic (NOT a replacement model): 152 months; CAGR 25.16%; SPY 13.83%; spread 11.33%
- Annualized volatility (official): 19.28%
- Max drawdown (official): -20.47%
- Recovery months from worst trough: 5
- Tracking error: 13.54%
- Information ratio: 0.750
- Beta vs SPY: 0.952
- Correlation vs SPY: 0.714
- Upside capture: 1.188
- Downside capture: 0.624

## 3. Holding period and turnover
- Holding episodes total: 757
- Closed holding episodes used for completed-duration statistics: 728
- Open/right-censored episodes at sample end: 29
- Unique tickers held: 122
- Average completed days held: 116.029
- Median completed days held: 61.000
- P25 / P75 completed days: 31.000 / 122.000
- Winner share by closed holding episode: 52.75%
- Average winner: 23.40%
- Average loser: -7.46%
- Average annual turnover: 178.27%
- Turnover classification: **HIGH TURNOVER**
- Average trade transitions/year: 148.538

## 4. Portfolio concentration
- Average positions: 11.237
- Average Top-1 / Top-3 / Top-5 weight: 22.22% / 56.30% / 77.51%
- Average HHI: 0.151; median effective N: 7.138
- Maximum historical Top-1 weight: 61.81% at 2014-02-28 00:00:00
- First-12-month average Top-1: 30.72%; post-first-12 average Top-1: 21.49%
- Concentration is descriptive. No cap is retroactively imposed on V10.4.

## 5. Factor IC stability
- Full Alpha mean monthly rank IC: 0.040
- Full Alpha positive-month share: 58.17%
- Full Alpha positive-year share: 84.62%
- Negative Full Alpha IC years: [2019, 2023]
- Association only; no causal attribution is claimed.

## 6. Execution-lag stress
- Basis: Completed official monthly path, reconstructed V10.4 weights, close-to-close execution delay, same period-level cost assumption.
- +0 sessions close: CAGR 25.13%; delta vs reconstructed same-close 0.00%; valid periods 151
- +1 sessions close: CAGR 22.88%; delta vs reconstructed same-close -2.25%; valid periods 151
- +2 sessions close: CAGR 21.75%; delta vs reconstructed same-close -3.38%; valid periods 151
- +3 sessions close: CAGR 20.67%; delta vs reconstructed same-close -4.46%; valid periods 151
- This is a sensitivity diagnostic using reconstructed frozen weights, not a new optimized strategy.

## 7. Anti-memorization / historical-winner dependence
- Explicit historical ticker literals in frozen decision code: **PASS**
- First-ever-entry mean episode return: 10.43%
- Re-entry mean episode return: 8.50%
- Re-entry minus first-entry mean-return gap: -1.92%
- Returning-not-prev-month minus never-held selection-rate gap at similar score decile: —
- Current recommendation familiarity status: **CURRENT_STATE_DIAGNOSTIC**; historically-seen share 69.44%
- Historical-winner exclusion is an ex-post fragility stress only; it is never a rule for the live model.
- BASELINE_RECONSTRUCTED: CAGR 25.13%; delta vs baseline 0.00%; excluded 
- EXCLUDE_TOP_1_HISTORICAL_CONTRIBUTORS_REOPTIMIZE: CAGR 24.89%; delta vs baseline -0.23%; excluded UNH
- EXCLUDE_TOP_3_HISTORICAL_CONTRIBUTORS_REOPTIMIZE: CAGR 23.45%; delta vs baseline -1.68%; excluded UNH;NFLX;MAR
- EXCLUDE_TOP_5_HISTORICAL_CONTRIBUTORS_REOPTIMIZE: CAGR 22.52%; delta vs baseline -2.60%; excluded UNH;NFLX;MAR;NVDA;PBR
- EXCLUDE_TOP_10_HISTORICAL_CONTRIBUTORS_REOPTIMIZE: CAGR 20.00%; delta vs baseline -5.13%; excluded UNH;NFLX;MAR;NVDA;PBR;KLAC;CMG;TJX;AMZN;SBUX
- PASS on explicit ticker literals does not prove absence of research overfitting. Forward testing remains the decisive prospective test.

## 8. Point-in-Time / leakage classification
- **Revenue Growth / revenue: PASS** — Checked 14,750 rows: filed <= asof; violations=0.
- **Sales Yield / revenue: PASS** — Checked 14,750 rows: filed <= asof; violations=0.
- **Sales Yield / shares_outstanding: PASS** — Checked 23,870 rows: filed <= asof; violations=0.
- **Sales Yield / market_cap_pit: PASS WITH LIMITATIONS** — PIT feature builder defines market cap as price known at t × latest shares outstanding filed by t. Problem: Daily date is known, but exact intraday execution time is not persisted; same-close tradability remains unverified.
- **Trend / historical prices: PASS WITH LIMITATIONS** — Frozen V10 code slices each ticker price series with s.loc[:asof]; no future price is an input to Trend. Problem: If execution is assumed at the same close used by the signal, exact decision/execution timestamp is not persisted.
- **Risk / 126-session trailing returns / covariance: PASS WITH LIMITATIONS** — trailing_returns_matrix filters OHLCV date <= asof and uses only the trailing window before optimization. Problem: Same-close execution timing is not timestamp-certified.
- **Portfolio construction / candidate scores, covariance, previous weights: PASS** — Frozen optimizer receives current candidate scores, trailing covariance inputs and previous weights; forward returns are used only after weights are determined to score the backtest.
- **Rebalance timing / signal/decision/execution sequence: UNVERIFIED** — Backtest maps score date to the last market month-end <= asof and measures the next monthly return. Problem: The research artifacts do not persist exact intraday signal timestamp versus execution price. Same-close execution therefore cannot be certified.
- **Universe / historical lifecycle membership: PASS WITH LIMITATIONS** — Historical lifecycle and PIT-with-delisted artifacts are present. Problem: V10.4's published champion was still frozen with the survivorship limitation disclosed; presence of later artifacts alone does not retroactively certify the original backtest.

## 9. Survivorship
- Final status: **UNRESOLVED**
- The audit does not convert missing delisted/PIT evidence into a PASS.
- Minimum closure dataset is listed in survivorship_status.json.

## 10. What is explicitly NOT proven
- Historical integer share/CEDEAR quantities: **NO PROBADO / not part of the V10.4 continuous research backtest.**
- Exact per-trade commission allocation: **NO PROBADO / only period-level cost is exact.**
- Exact intraday signal-to-execution timestamp: **NO PROBADO.**
- Full survivorship-free champion result: **NO PROBADO unless the dedicated historical universe/delisted closure is complete.**
- Causal alpha attribution to Revenue Growth vs Sales Yield vs Trend: **NO PROBADO; factor outputs are association diagnostics.**

## 11. Top linked terminal contributors
- UNH: linked terminal contribution index=333.4454, share of terminal gain=20.57%
- NFLX: linked terminal contribution index=294.6735, share of terminal gain=18.18%
- MAR: linked terminal contribution index=110.6701, share of terminal gain=6.83%
- NVDA: linked terminal contribution index=103.9937, share of terminal gain=6.42%
- PBR: linked terminal contribution index=81.8379, share of terminal gain=5.05%
- KLAC: linked terminal contribution index=78.4142, share of terminal gain=4.84%
- CMG: linked terminal contribution index=74.0790, share of terminal gain=4.57%
- TJX: linked terminal contribution index=73.5503, share of terminal gain=4.54%
- AMZN: linked terminal contribution index=69.3441, share of terminal gain=4.28%
- SBUX: linked terminal contribution index=63.8116, share of terminal gain=3.94%

## 12. Best / worst annual periods
- 2014: Alpha Engine 9.20%, SPY 12.49%, active -3.29%, turnover 315.86%
- 2015: Alpha Engine 16.31%, SPY 1.23%, active 15.08%, turnover 161.42%
- 2016: Alpha Engine 26.72%, SPY 12.00%, active 14.72%, turnover 263.84%
- 2017: Alpha Engine 33.13%, SPY 21.71%, active 11.42%, turnover 171.91%
- 2018: Alpha Engine 14.19%, SPY -4.57%, active 18.76%, turnover 196.41%
- 2019: Alpha Engine 15.87%, SPY 31.22%, active -15.35%, turnover 279.38%
- 2020: Alpha Engine 47.78%, SPY 18.33%, active 29.45%, turnover 139.84%
- 2021: Alpha Engine 36.63%, SPY 28.73%, active 7.90%, turnover 149.87%
- 2022: Alpha Engine -1.86%, SPY -18.18%, active 16.32%, turnover 151.08%
- 2023: Alpha Engine 30.45%, SPY 26.18%, active 4.27%, turnover 124.46%
- 2024: Alpha Engine 35.01%, SPY 24.89%, active 10.13%, turnover 154.71%
- 2025: Alpha Engine 32.92%, SPY 17.72%, active 15.20%, turnover 88.56%
- 2026: Alpha Engine 30.83%, SPY 13.54%, active 17.29%, turnover 120.15%

## 13. Conceptual contribution fragility stress
- Remove top 1 holding episodes: CAGR 22.29%. CONCEPTUAL_CONTRIBUTION_REMOVAL_NO_REOPTIMIZATION.
- Remove top 3 holding episodes: CAGR 19.64%. CONCEPTUAL_CONTRIBUTION_REMOVAL_NO_REOPTIMIZATION.
- Remove top 5 holding episodes: CAGR 17.82%. CONCEPTUAL_CONTRIBUTION_REMOVAL_NO_REOPTIMIZATION.
- Remove top 10 holding episodes: CAGR 14.69%. CONCEPTUAL_CONTRIBUTION_REMOVAL_NO_REOPTIMIZATION.
- Remove top 20 holding episodes: CAGR 8.54%. CONCEPTUAL_CONTRIBUTION_REMOVAL_NO_REOPTIMIZATION.

## 14. Artifact availability

The audit distinguishes missing evidence from failed evidence:
- PRESENT — frozen_full_alpha_panel — `data/v10/frozen_full_alpha_panel.parquet`
- PRESENT — strategy_monthly_returns — `data/v10/strategy_monthly_returns.csv`
- PRESENT — extended_ohlcv — `data/cache/market_ohlcv_extended.parquet`
- PRESENT — benchmark_monthly_returns — `data/v10_2/benchmark_monthly_returns.parquet`
- PRESENT — locked_replication_panel — `data/validation/locked_replication_panel.parquet`
- PRESENT — historical_universe — `data/universe/historical_universe_monthly.parquet`
- PRESENT — lifecycle_mapping — `data/universe/historical_lifecycle_sec_mapping.csv`
- PRESENT — pit_delisted_panel — `data/research_closure/historical_pit_locked_factor_panel_with_delisted.parquet`
- PRESENT — fama_french — `data/cache/fama_french_us_monthly.parquet`
- PRESENT — v10_1_holdings — `data/v10_1/holdings_by_month.parquet`
- PRESENT — v10_4_profiles — `data/v10_4/profile_monthly_returns.csv`
- PRESENT — v10_4_freeze_decision — `data/v10_4/final_model_freeze_decision.json`

## Final scientific position

The purpose of this report is not to prove that Alpha Engine works. It is to identify which parts of the historical evidence can be reproduced exactly, which are robust under diagnostics, and which remain unverified. A PASS in replay integrity does not eliminate survivorship bias, same-close timing ambiguity, or the need for forward testing.
