# AUDITORÍA EXTREMA — ALPHA ENGINE V10.4

**Audit version:** V0.8.1_EXTREME_AUDIT
**Model:** V10.4_FROZEN_UNCHANGED
**Generated UTC:** 2026-09-07T22:50:29.124162+00:00

> Mandato: intentar demostrar que el modelo NO funciona. Ningún missing se convierte en PASS; ningún sensitivity test retunea V10.4.

## Resumen ejecutivo

- Completed-month CAGR: **25.12%** vs SPY **13.89%**; spread **11.23%**.
- Exact optimizer replay: **FAIL**; secondary: **NEAR_REPLAY_MAX_ERROR_LE_10BPS**.
- Survivorship: **UNRESOLVED**.
- Global category: **🟢 Prometedor**.
- Critical institutional blockers: **8**.

## 1. Tesis central

Long-only cross-sectional asset-selection and portfolio-construction system. It does not forecast a point price; it implicitly forecasts relative expected returns by ranking current characteristics and allocating more capital to selected names.

### Hipótesis económica

- **Revenue Growth:** Firms with stronger current revenue growth may contain information about business momentum not fully reflected immediately in relative prices.
- **Sales Yield:** Higher revenue relative to market capitalization is a valuation signal; if revenue is economically durable, cheaper sales can imply higher prospective relative returns.
- **Trend:** Price trends can persist because information diffusion, underreaction, flows and behavioral frictions are gradual rather than instantaneous.
- **combination:** Growth, valuation and trend are intended to be partially complementary; no single factor needs to dominate in every regime.

**Clasificación:** HYPOTHESIS. La plausibilidad económica no prueba alpha.

## 2. Data leakage / look-ahead

**Systemic future-data use**
- Estado: **FAVORABLE_EVIDENCE / PASS_WITH_OPEN_VULNERABILITIES**
- Conclusión: No systemic look-ahead has been found in the tested factor/risk/optimizer path, but vintage and exact execution timing remain open.
- Evidencia: {'PASS': 6, 'PASS WITH LIMITATIONS': 5, 'UNVERIFIED': 4}
- Artefacto: `extreme_data_leakage.csv`

## 3. Point-in-Time

**Can exact historical information set be reconstructed?**
- Estado: **FAVORABLE_EVIDENCE / PASS_WITH_LIMITATIONS**
- Conclusión: Fundamental filing dates, current-date ranks and trailing prices are reconstructable at daily resolution; exact intraday/vintage state is not fully certified.
- Evidencia: {'PASS': 4, 'PASS WITH LIMITATIONS': 4, 'UNVERIFIED': 1}
- Falta: intraday timestamps; independent vintage database snapshots
- Artefacto: `data/audit_v10_4/pit_audit.csv`

## 4. Survivorship bias

**Survivorship-free champion replay**
- Estado: **PENDING_DATA / UNRESOLVED**
- Conclusión: Cannot certify the headline alpha as survivorship-free yet.
- Evidencia: ['A formal pre-V10 survivorship/PIT gate was executed and persisted.', 'Delisted-price acquisition attempts are auditable from a persisted manifest.']
- Falta: Point-in-time monthly universe membership including delisted names for the full backtest window; Historical prices covering the investment horizon for factor-eligible delisted securities; Point-in-time Revenue Growth and Sales Yield inputs for those delisted securities; Historical shares outstanding/filing availability dates needed for PIT market cap
- Artefacto: `data/audit_v10_4/survivorship_status.json`

## 5. Data mining / overfitting

**Complete multiple-testing / false-discovery control**
- Estado: **PENDING_DATA / PERSISTED_TRIAL_LOWER_BOUND_ONLY**
- Conclusión: Recovered DSR/PBO are lower-bound diagnostics only until the historical research-trial inventory is certified complete.
- Evidencia: persisted paths=446
- Falta: complete manual trial history
- Artefacto: `false_discovery_audit.json`

## 6. Out-of-sample

**True untouched holdout**
- Estado: **UNKNOWN / UNVERIFIED_TRUE_NEVER_TOUCHED_HOLDOUT**
- Conclusión: Existing OOS/walk-forward evidence does not by itself prove a never-touched holdout after final freeze.
- Evidencia: {'market_oos_summary': False, 'fundamental_walk_forward': False, 'v10_profile_freeze': True, 'v11_challenger': False}
- Falta: immutable pre-holdout freeze evidence
- Artefacto: `oos_audit.json`

## 7. Walk-forward / rolling windows

**Rolling-window consistency with dependence acknowledged**
- Estado: **FAVORABLE_EVIDENCE / DESCRIPTIVE_DEPENDENCE_ADJUSTED**
- Conclusión: Rolling evidence is useful but overlapping windows are not independent tests.
- Evidencia: {'24': {'overlapping_windows': 127, 'overlapping_outperform_share': 0.968503937007874, 'worst_overlapping_spread': -0.061402052327311996, 'nonoverlap_window_instances_across_offsets': 67, 'nonoverlap_outperform_share': 0.9552238805970149, 'warning': 'Overlapping rolling windows are strongly dependent; their count is not a count of independent experiments.'}, '36': {'overlapping_windows': 115, 'overlapping_outperform_share': 1.0, 'worst_overlapping_spread': 0.014240882524918286, 'nonoverlap_window_instances_across_offsets': 43, 'nonoverlap_outperform_share': 1.0, 'warning': 'Overlapping rolling windows are strongly dependent; their count is not a count of independent experiments.'}, '48': {'overlapping_windows': 103, 'overlapping_outperform_share': 1.0, 'worst_overlapping_spread': 0.04111746969709551, 'nonoverlap_window_instances_across_offsets': 31, 'nonoverlap_outperform_share': 1.0, 'warning': 'Overlapping rolling windows are strongly dependent; their count is not a count of independent experiments.'}, '60': {'overlapping_windows': 91, 'overlapping_outperform_share': 1.0, 'worst_overlapping_spread': 0.05964319519063199, 'nonoverlap_window_instances_across_offsets': 24, 'nonoverlap_outperform_share': 1.0, 'warning': 'Overlapping rolling windows are strongly dependent; their count is not a count of independent experiments.'}}
- Artefacto: `rolling_window_audit.json`

## 8. Performance

**Completed-month benchmark-relative performance**
- Estado: **FAVORABLE_EVIDENCE / COMPUTED**
- Conclusión: Completed-month CAGR 25.12% vs SPY 13.89%; strong historically, not proof of future alpha.
- Evidencia: {'months': 151, 'cagr': 0.25120819657807125, 'spy_cagr': 0.1388961367317143, 'cagr_spread_vs_spy': 0.11231205984635695, 'annualized_arithmetic_return': 0.24453914846072264, 'annualized_volatility': 0.1933900076539617, 'sharpe': 1.1890840277042916, 'sharpe_basis': 'KENNETH_FRENCH_MONTHLY_RF', 'sortino_rf0': 1.3459532136996861, 'max_drawdown': -0.20468786476134004, 'calmar': 1.227274498519844, 'beta_vs_spy': 0.9523237905470291, 'correlation_vs_spy': 0.7144510646465334, 'tracking_error': 0.13576939810220004, 'information_ratio': 0.7403352745465306, 'upside_capture': 1.182454987045632, 'downside_capture': 0.6239689458454432, 'recovery_months_from_worst_trough': 5, 'positive_month_share': 0.6754966887417219, 'months_beating_spy_share': 0.5866666666666667, 'best_month': 0.1901626552419456, 'worst_month': -0.1828752672558496}
- Artefacto: `data/audit_v10_4/completed_month_performance.csv`

## 9. Factor attribution

**Ablations and combinations**
- Estado: **FAVORABLE_EVIDENCE / SENSITIVITY_ONLY_NO_RETUNING**
- Conclusión: Factor ablations are sensitivity evidence, not causal decomposition.
- Evidencia: rows=7
- Artefacto: `factor_ablation_sensitivity.csv`

## 10. Fama-French + Momentum

**Alpha after standard factor controls**
- Estado: **FAVORABLE_EVIDENCE / COMPUTED**
- Conclusión: A positive factor-adjusted alpha can reject some simple explanations; it cannot establish causality or eliminate data-mining bias.
- Evidencia: [{'strategy': 'FINAL_OPTIMIZER', 'sample': 'FULL', 'model': 'CAPM', 'months': 149, 'alpha_ann': 0.11474846264766678, 'alpha_hac_t': 3.380250677222189, 'p_value_normal_approx': 0.00072419746157355, 'residual_vol_ann': 0.1325966680241843, 'r2': 0.534019554476072}, {'strategy': 'FINAL_OPTIMIZER', 'sample': 'FULL', 'model': 'FF3', 'months': 149, 'alpha_ann': 0.1164534957322706, 'alpha_hac_t': 3.4732800722498416, 'p_value_normal_approx': 0.0005141385364273863, 'residual_vol_ann': 0.13209535953326318, 'r2': 0.5375363603130439}, {'strategy': 'FINAL_OPTIMIZER', 'sample': 'FULL', 'model': 'FF5', 'months': 149, 'alpha_ann': 0.1154626115251853, 'alpha_hac_t': 3.4865918101622433, 'p_value_normal_approx': 0.0004892174304963918, 'residual_vol_ann': 0.13099825757730071, 'r2': 0.5451863310083032}, {'strategy': 'FINAL_OPTIMIZER', 'sample': 'FULL', 'model': 'FF5_MOM', 'months': 149, 'alpha_ann': 0.10633942828329632, 'alpha_hac_t': 3.1932698508544286, 'p_value_normal_approx': 0.0014067142206679244, 'residual_vol_ann': 0.12989323371646552, 'r2': 0.552827046724985}]
- Artefacto: `multifactor_alpha_extreme.csv`

## 11. Transaction costs

**Implementation cost sensitivity**
- Estado: **FAVORABLE_EVIDENCE / SENSITIVITY_ONLY**
- Conclusión: Constant-cost break-even estimate is 255.23 one-way bps; security-specific impact remains unmodeled.
- Evidencia: {'status': 'SENSITIVITY_ONLY', 'baseline_one_way_cost_bps': 0.5, 'break_even_one_way_cost_bps_vs_spy': 255.22766622900758, 'note': 'Historical backtest cost model uses period turnover and a constant one-way friction; it does not model security-specific spreads or market impact.'}
- Artefacto: `transaction_cost_stress_extreme.csv`

## 12. Capacidad / scalability

**AUM/CEDEAR scalability**
- Estado: **PENDING_DATA / PENDING_DATA**
- Conclusión: US underlying liquidity cannot certify CEDEAR capacity.
- Evidencia: {'status': 'PENDING_DATA', 'underlying_capacity_proxy': 'UNAVAILABLE_NO_VOLUME', 'cedear_capacity': 'UNVERIFIED', 'missing_data': ['historical underlying volume', 'historical BYMA CEDEAR price/volume/order-book spreads', 'broker participation/impact assumptions']}
- Falta: historical BYMA CEDEAR volume/spreads/market impact
- Artefacto: `capacity_audit.json`

## 13. Portfolio optimizer

**Separate factor, optimizer and execution value**
- Estado: **FAVORABLE_EVIDENCE / DESCRIPTIVE_HISTORICAL_STRATEGY_COMPARISON**
- Conclusión: Persisted strategy variants can compare theoretical weighting layers; historical discrete CEDEAR transformation remains unverified.
- Evidencia: ['FINAL_OPTIMIZER', 'FULL_ALPHA_CONVICTION', 'FULL_ALPHA_EQUAL', 'FULL_ALPHA_RISK', 'RG_ONLY', 'RG_SY_EQUAL', 'SY_ONLY', 'TREND_ONLY']
- Artefacto: `optimizer_layer_comparison.csv`

## 14. Robustez

**Zone around exact V10.4**
- Estado: **FAVORABLE_EVIDENCE / SENSITIVITY_ONLY_NO_RETUNING**
- Conclusión: Predeclared nearby variants are reported without selecting a winner; collapse around the base would be a warning.
- Evidencia: zone rows=12
- Artefacto: `parameter_neighborhood_sensitivity.csv`

## 15. Regímenes

**Performance by market/macro regime**
- Estado: **FAVORABLE_EVIDENCE / RECOVERED_V10_3**
- Conclusión: Market/volatility regimes can be tested; macro rate/inflation regimes require PIT macro data if absent.
- Evidencia: {'status': 'RECOVERED_V10_3', 'rows': 4, 'macro_regimes': 'ONLY_IF_PRESENT_IN_ARTIFACT'}
- Artefacto: `regime_analysis.csv`

## 16. Drawdowns

**Peak/trough/recovery audit**
- Estado: **DEMONSTRATED / COMPUTED**
- Conclusión: Explicit episode table prevents ambiguous recovery claims.
- Evidencia: {'status': 'COMPUTED', 'alpha_engine': {'episodes': 26, 'worst_drawdown': -0.20468786476134004, 'worst_trough': '2022-06-30 00:00:00', 'worst_recovery': '2022-11-30 00:00:00', 'average_trough_to_recovery_months': 2.0}, 'spy': {'episodes': 23, 'worst_drawdown': -0.23927182389219837, 'worst_trough': '2022-09-30 00:00:00', 'worst_recovery': '2023-12-29 00:00:00', 'average_trough_to_recovery_months': 2.4347826086956523}}
- Artefacto: `drawdown_episodes.csv`

## 17. Historial de decisiones

**Third-party reproducibility of every decision**
- Estado: **PENDING_DATA / PASS_WITH_LIMITATIONS**
- Conclusión: Monthly research decisions are largely reconstructable; some execution/optimizer rationale fields are not persisted.
- Evidencia: {'status': 'PASS_WITH_LIMITATIONS', 'present_fields': 11, 'total_fields': 16, 'missing_fields': ['intraday_signal_timestamp', 'intraday_execution_timestamp', 'per_trade_realized_cost', 'optimizer_marginal_reason_per_asset', 'discarded_alternative_reason_per_asset']}
- Falta: intraday_signal_timestamp; intraday_execution_timestamp; per_trade_realized_cost; optimizer_marginal_reason_per_asset; discarded_alternative_reason_per_asset
- Artefacto: `decision_history_completeness.csv`

## 18. ¿Por qué compró esto?

**Current recommendation explainability**
- Estado: **FAVORABLE_EVIDENCE / CURRENT_STATE_DIAGNOSTIC**
- Conclusión: Current names must be justified from current factors/risk/optimizer, never from historical subsequent returns.
- Evidencia: {'status': 'CURRENT_STATE_DIAGNOSTIC', 'requested_names': 15, 'found': 15, 'missing_names': []}
- Artefacto: `current_decisions_audit.csv`

## 19. Decisiones individuales

**GOOGL/AVGO/NVDA/... methodology coherence**
- Estado: **FAVORABLE_EVIDENCE / CURRENT_STATE_DIAGNOSTIC**
- Conclusión: The audit inventories current runtime records; any absent factor/optimizer rationale is explicitly left unverified.
- Evidencia: {'status': 'CURRENT_STATE_DIAGNOSTIC', 'requested_names': 15, 'found': 15, 'missing_names': []}
- Artefacto: `current_decisions_audit.csv`

## 20. Current portfolio vs target

**Discrete implementation vs continuous target**
- Estado: **FAVORABLE_EVIDENCE / CURRENT_STATE_DIAGNOSTIC**
- Conclusión: Current integer implementation can be inspected, but historical nominal-rounding alpha loss is not yet a certified backtest.
- Evidencia: {'status': 'CURRENT_STATE_DIAGNOSTIC', 'portfolio_value_ars': 492250.0, 'cash_ars': 0.0, 'cash_pct': 0.13921787709497208, 'discrete_holdings': 13, 'discrete_turnover_ars': 763770.0, 'solver': 'SCIPY_MILP_LEXICOGRAPHIC', 'objective_primary': 0.2294081225640572, 'note': 'The current integer/CEDEAR implementation is audited separately from the continuous historical research backtest. Historical alpha loss from nominal rounding cannot be claimed without a historical discrete replay.'}
- Artefacto: `current_portfolio_vs_target.json`

## 21. Survivorship + PIT

**Joint evidentiary strength**
- Estado: **PENDING_DATA / PROMISING_INCOMPLETE**
- Conclusión: Passing PIT does not neutralize unresolved survivorship; headline performance remains conditional on that data limitation.
- Evidencia: {'status': 'UNRESOLVED', 'what_is_proven': ['A formal pre-V10 survivorship/PIT gate was executed and persisted.', 'Delisted-price acquisition attempts are auditable from a persisted manifest.'], 'what_is_not_proven': ['A complete survivorship-free V10.4 champion backtest has not been certified by the frozen research decision.'], 'minimum_dataset_to_close': ['Point-in-time monthly universe membership including delisted names for the full backtest window', 'Historical prices covering the investment horizon for factor-eligible delisted securities', 'Point-in-time Revenue Growth and Sales Yield inputs for those delisted securities', 'Historical shares outstanding/filing availability dates needed for PIT market cap'], 'research_closure_gates': [{'name': 'SEC_MAPPING', 'status': 'PASS', 'detail': 'lifecycle mapped=46.5%'}, {'name': 'REVENUE_GROWTH_PIT_COVERAGE', 'status': 'PASS', 'detail': 'median usable=58.3%'}, {'name': 'SALES_YIELD_PIT_COVERAGE', 'status': 'FAIL', 'detail': 'median usable=3.3%'}, {'name': 'DELISTED_PRICE_COVERAGE', 'status': 'FAIL', 'detail': 'eligible delisted=285/1,837 (15.5%)'}, {'name': 'MODEL_RESEARCH_CLOSURE', 'status': 'FAIL', 'detail': 'Automatic aggregation of data-integrity and locked-alpha gates.'}], 'delisted_attempted': 1837, 'delisted_with_usable_rows': 285}
- Artefacto: `survivorship_status.json`

## 22. False discovery

**Chance result after model search**
- Estado: **PENDING_DATA / INSUFFICIENT_ALIGNED_TRIAL_MATRIX**
- Conclusión: No exact false-discovery probability can be claimed without complete research-trial history.
- Evidencia: {'status': 'INSUFFICIENT_ALIGNED_TRIAL_MATRIX', 'strategies': 0}
- Artefacto: `false_discovery_audit.json`

## 23. Red team — 10 razones por las que podría ser falso

### 1. Survivorship bias may inflate returns
- Gravedad: **CRITICAL**
- Estado: **UNRESOLVED**
- Evidencia: Fundamental PIT checks pass for surviving panel, but champion is not certified survivorship-free.
- Test necesario: PIT lifecycle universe + delisted factors/prices replay

### 2. Research overfitting / false discovery
- Gravedad: **CRITICAL**
- Estado: **UNRESOLVED**
- Evidencia: Persisted trial paths are only a lower bound; champion was selected after multiple research choices.
- Test necesario: Complete trial inventory + definitive DSR/PBO + untouched holdout

### 3. Same-close execution may be untradeable
- Gravedad: **HIGH**
- Estado: **PARTIAL**
- Evidencia: Lag stress remains profitable historically, but exact same-close tradability is unverified.
- Test necesario: Timestamped signal/fill or next-session execution protocol

### 4. Fundamental restatement/vintage contamination
- Gravedad: **HIGH**
- Estado: **UNVERIFIED**
- Evidencia: filed<=asof does not independently prove the exact value vintage known on that date.
- Test necesario: Vintage fact database or source snapshots

### 5. Portfolio concentration can dominate factor skill
- Gravedad: **HIGH**
- Estado: **OBSERVED**
- Evidencia: Historical max single-name weight 61.81%.
- Test necesario: Concentration-cap sensitivity + forward concentration monitoring

### 6. Alpha may depend on a small tail of winners
- Gravedad: **HIGH**
- Estado: **OBSERVED**
- Evidencia: Top historical contributors matter materially even though exclusion/reoptimization does not destroy all performance.
- Test necesario: Winner-exclusion reoptimization + forward breadth of contributors

### 7. High turnover can make historical costs optimistic
- Gravedad: **HIGH**
- Estado: **OBSERVED**
- Evidencia: Average annual turnover 178.27%.
- Test necesario: Security-specific spread/slippage/market-impact model

### 8. Factor IC is statistically small and can decay
- Gravedad: **MEDIUM**
- Estado: **OBSERVED**
- Evidencia: Mean Full Alpha rank IC 0.040.
- Test necesario: Forward IC monitoring and regime stability

### 9. Exact optimizer replay is not numerically identical
- Gravedad: **MEDIUM**
- Estado: **OPEN**
- Evidencia: Exact replay FAIL but secondary NEAR_REPLAY_MAX_ERROR_LE_10BPS.
- Test necesario: Historical environment lock or persisted exact weights

### 10. Live CEDEAR/integer implementation may lose alpha
- Gravedad: **CRITICAL_FOR_LOCAL_PRODUCT**
- Estado: **UNVERIFIED_HISTORICALLY**
- Evidencia: Research backtest is continuous underlying weights; local discrete layer is newer.
- Test necesario: Historical local execution replay with ratios, volumes, spreads and nominal rounding

## 24. Inversor escéptico — 30 preguntas

### 1. Show me the exact economic hypothesis without citing the backtest.
Growth, valuation through Sales Yield, and trend are hypothesized cross-sectional return signals. The rationale is economically plausible but remains a hypothesis; the backtest is evidence, not the rationale.

### 2. Can you prove every fundamental value was available on the decision date?
For revenue and shares, filed<=asof checks pass on tens of thousands of rows. Exact source-vintage/restatement integrity is still unverified.

### 3. Can you prove the universe is survivorship-free?
No. Current status: UNRESOLVED. A complete champion replay including factor-eligible delisted names has not been certified.

### 4. How many research trials did you actually run?
The automated persisted-path inventory finds 446 distinct paths, explicitly a lower bound. The complete human research history is not certified.

### 5. Is the Deflated Sharpe definitive?
No. Status: PERSISTED_TRIAL_LOWER_BOUND_ONLY. It is lower-bound evidence until the trial inventory is complete.

### 6. Do you have a true untouched holdout?
Not certified. Existing OOS/walk-forward tests are useful, but immutable evidence that the final model was frozen before a never-used holdout is still missing.

### 7. Why should I believe 100% of rolling 3Y/5Y windows?
You should not treat overlapping windows as independent observations. The audit reports overlapping and non-overlapping window evidence separately.

### 8. What is the clean completed-month CAGR?
25.12%, with SPY 13.89%.

### 9. How concentrated was the portfolio?
Average top-1 22.22%; historical max top-1 61.81%. This is material.

### 10. How much turnover?
Average annual turnover 178.27%; high-turnover classification.

### 11. What if execution is one day late?
+1-session close sensitivity CAGR 22.88%. This is sensitivity, not an exact historical fill replay.

### 12. What if I ban your best historical names?
See historical_winner_exclusion_reoptimization: top historical winners are excluded with hindsight and capital is reoptimized. Performance falls but does not vanish in the current evidence.

### 13. Does the model memorize tickers?
No explicit ticker-specific rule is expected under the corrected lexical/context audit, and first-ever entries historically work. That does not rule out research overfitting.

### 14. Which factor is really doing the work?
Revenue Growth is the strongest individual quintile spread in the current evidence; Full Alpha improves composite rank association. Exact causal attribution is not identified.

### 15. What happens if you remove one factor?
The extreme audit writes factor_ablation_sensitivity.csv using predeclared one-/two-factor diagnostics without selecting a replacement model.

### 16. Does alpha survive FF5+Momentum?
See multifactor_alpha_extreme.csv. A positive HAC alpha is evidence against standard factor explanations, not proof of unique structural alpha.

### 17. What benchmark besides SPY?
RSP, QQQ and SMH are compared when benchmark artifacts are available. SPY remains primary opportunity cost.

### 18. Do you model slippage and market impact?
The backtest uses a constant friction and turnover. Security-specific spread/impact is not fully modeled; cost and lag stresses are therefore required.

### 19. What AUM can this handle?
Not certified for CEDEAR execution. Underlying ADV can be a proxy, but BYMA historical liquidity is required before an AUM claim.

### 20. Does the optimizer add value?
The audit compares persisted strategy variants where available. Optimizer value must be separated from factor signal and execution implementation.

### 21. Can integer nominal rounding destroy the edge?
Unknown historically. The original research path was continuous-weight; a historical discrete CEDEAR replay has not been certified.

### 22. Do nearby parameter settings also work?
The extreme audit runs symmetric, predeclared local perturbations and reports all of them. No best variant is selected.

### 23. Where does it fail by regime?
Market and volatility regimes are audited; macro inflation/rate regimes require a PIT macro panel if not already present.

### 24. Are drawdown recovery claims computed correctly?
The forensic auditor fixed the recovery calculation and the extreme audit produces explicit drawdown episodes for Alpha Engine and SPY.

### 25. Can I reconstruct every historical decision?
Most monthly research fields are reconstructable, but exact intraday timestamps, per-trade realized costs and marginal optimizer reasons are not fully persisted.

### 26. Why did it buy PBR/SONY today?
That must be answered from current factor scores, ranking, risk and optimizer state—not from their historical success. current_decisions_audit.csv inventories current evidence.

### 27. What would make you call the backtest false?
Systemic PIT leakage, a survivorship-free replay that erases the edge, complete-trial DSR/PBO showing severe selection bias, or forward performance inconsistent with the hypothesis.

### 28. What would make you stop the forward test?
A predeclared governance rule should stop promotion, not necessarily data collection, after sustained negative active return/IC or an implementation failure. The frozen model must not be retuned mid-test and still called the same test.

### 29. What is the largest unknown today?
Survivorship-free certification and research-selection bias, followed by local execution/capacity and true forward evidence.

### 30. Would you invest institutional capital today?
The audit should not recommend that from backtest evidence alone. Until the critical GO/NO-GO blockers close, the appropriate state is research/forward testing rather than institutional track-record claims.

## 25. Reclutador quant

La calidad técnica del proyecto y la validez económica de la estrategia se evalúan por separado.

- **technically_impressive:** PIT fundamental pipeline; frozen model governance; forensic portfolio reconstruction; optimizer/execution separation; red-team/false-discovery work; live cloud/ledger architecture
- **easy_to_replicate:** basic factor ranking; standard performance ratios; simple FastAPI dashboard
- **shows_judgment:** refusing to convert exact replay FAIL into PASS; separating backtest/PAPER/REAL; documenting survivorship as unresolved; pre-registering forward hash
- **concerns:** survivorship unresolved; true OOS history not certified; local capacity unproven; research trial history incomplete

## 26. Inversor / fondo

- **hedge_fund:** Will focus on independent alpha, false discovery, capacity, execution and reproducibility.
- **family_office:** Will focus on drawdown, transparency, live evidence and operational simplicity.
- **ALyC:** Will focus on CEDEAR execution, suitability, compliance, liquidity, audit trail and client communication.
- **fintech:** Will focus on product reliability, explainability, scalability, data licensing and user safety.
- **bank:** Will require governance, model risk management, compliance, reproducibility and vendor/data controls.
- **asset_manager:** Will focus on benchmark-relative performance, capacity, factor exposures, turnover, drawdowns and team/process repeatability.

## 27. Valor económico

- **today:** Software/research IP can have professional and development value, but a backtest alone is not an institutional track record and does not justify an arbitrary strategy valuation.
- **12_months:** A clean forward year adds evidence about implementation and signal persistence but remains statistically short.
- **3_years:** A frozen, net-of-cost three-year forward record can materially change credibility, especially with benchmark-relative and factor-adjusted evidence.
- **5_years:** Five years of independently auditable live/forward history across regimes can support far stronger commercial, AUM and licensing discussions, subject to capacity and regulation.

## 28. Forward test definitivo

**No modificar durante el test:** factor definitions; factor weights; candidate fraction; risk lookback; optimizer objective/penalties; rebalance cadence; execution convention used for scoring; benchmark set; cost-accounting rule

**Registrar cada decisión:** UTC timestamp; data cutoff; factor inputs and filing timestamps; score/rank; risk inputs; previous weights; continuous target; discrete/local target; orders/fills; costs/slippage; cash; benchmark prices; model hash

## 29. Regla 2029

- **minimum_forward_months:** 36
- **model_hash_unchanged:** True
- **net_of_all_realized_costs:** True
- **primary_active_cagr_gt_0:** True
- **information_ratio_target:** >=0.50 is favorable; <0 is failure evidence
- **full_alpha_rank_ic_mean:** >0 and positive in >=55% of forward months is favorable
- **ff5_mom_alpha:** >0; HAC t-stat >=1.5 encouraging and >=2.0 materially stronger, recognizing 36 months is a short sample
- **drawdown:** must remain within the predeclared risk mandate; no ex-post threshold change
- **benchmark_robustness:** positive active evidence vs SPY plus at least one of RSP/QQQ over the same period
- **failure_rule:** If 36-month net active CAGR <=0 and mean forward IC <=0, the alpha hypothesis has failed its first serious forward hurdle. Continue observation only as research; do not retune and relabel the same test.

## 30. Veredicto final

- **A_alpha_engine_parece_funcionar:** No podemos saber todavía hacia adelante; históricamente hay evidencia favorable.
- **B_evidencia_actual_fuerte:** Parcial: fuerte en varias dimensiones del backtest, incompleta en survivorship, research selection, exact execution/capacity and forward evidence.
- **C_mayor_debilidad:** Survivorship-free certification and complete research-trial/false-discovery history are not closed.
- **D_mayor_riesgo_resultado_falso:** Combination of survivorship bias and research selection/data mining, amplified by concentration/high turnover.
- **E_test_urgente:** Close survivorship-free PIT replay and lock/execute the true forward protocol; both matter more than another optimized backtest.
- **F_test_redundante:** More ex-post parameter searching for a better champion would add little and increase false-discovery risk.
- **G_bien_construido:** Frozen profile reconstruction, PIT filing checks, factor/risk temporal slicing, forensic holdings/replay, explicit layer separation and audit logging.
- **H_rehacer:** Any claim of institutional readiness/capacity before local liquidity and forward evidence; also historical data-vintage certification if unavailable.
- **I_listo_para_congelarse:** Sí: V10.4 should remain frozen; changing it now would contaminate the forward test.
- **J_listo_para_forward_testing:** Sí, as research/shadow testing, provided the hash and execution rule are fixed and every decision is logged before outcomes.
- **K_listo_para_profesionales:** Sí as a transparent research project, with unresolved limitations presented prominently; no as a proven institutional strategy.
- **L_listo_para_monetizar:** No as a proven alpha product. Software/research tooling can have value, but strategy monetization claims should wait for critical evidence.
- **global_category:** 🟢 Prometedor
- **rule:** Category is capped by critical unresolved evidence. Strong backtest performance cannot override missing survivorship/false-discovery/forward proof.

# GO / NO-GO antes de presentarlo como estrategia cuantitativa seria

- **GO — Frozen monthly profile identity**: PASS. GO: Exact match to persisted CORE
- **GO_WITH_LIMITATIONS — Point-in-time fundamentals**: {'PASS': 4, 'PASS WITH LIMITATIONS': 4, 'UNVERIFIED': 1}. GO: No filed>asof violations; normalizations cross-sectional at date
- **NO-GO — Data vintage/restatement integrity**: UNVERIFIED. GO: Historical vintage of each fact independently certified
- **NO-GO — Exact signal/fill timing**: UNVERIFIED. GO: Executable price strictly after information availability or documented next-session rule
- **NO-GO — Survivorship-free replay**: UNRESOLVED. GO: Full lifecycle universe + delisted prices + PIT factors included and champion replayed
- **NO-GO — Research multiple-testing inventory**: 446. GO: All tried specifications manually certified
- **NO-GO — DSR/PBO**: PERSISTED_TRIAL_LOWER_BOUND_ONLY. GO: Computed on complete research-trial history, not lower bound
- **GO — Execution delay**: 22.88%. GO: +1 session retains positive meaningful spread vs SPY
- **GO_WITH_LIMITATIONS — Cost stress**: 2.55%. GO: Positive spread under conservative implementation cost
- **GO_WITH_LIMITATIONS — Factor ordering stability**: 84.62%. GO: Composite IC positive across most years and not concentrated in one regime
- **GO_WITH_LIMITATIONS — Parameter neighborhood**: SENSITIVITY_ONLY_NO_RETUNING. GO: Nearby predeclared variants retain positive alpha without selecting a winner
- **NO-GO — Capacity / CEDEAR liquidity**: UNVERIFIED. GO: Local BYMA liquidity supports intended AUM at conservative participation
- **NO-GO — True forward test**: NOT YET MATURE. GO: >=36 monthly observations on frozen hash, net of costs, with no retuning
- **NO-GO — Decision reconstruction**: PASS_WITH_LIMITATIONS. GO: Third party can reconstruct inputs, score, target and execution with timestamps

# Regla epistemológica

Cada conclusión del paquete está clasificada como DEMONSTRATED, FAVORABLE_EVIDENCE, HYPOTHESIS, UNKNOWN, PENDING_DATA o FAIL. El lector no debe elevar una categoría sin nueva evidencia.
