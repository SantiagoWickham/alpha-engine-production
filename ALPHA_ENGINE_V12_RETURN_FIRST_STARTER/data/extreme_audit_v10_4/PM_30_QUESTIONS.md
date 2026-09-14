# 30 preguntas de un Portfolio Manager escéptico

## 1. Show me the exact economic hypothesis without citing the backtest.

Growth, valuation through Sales Yield, and trend are hypothesized cross-sectional return signals. The rationale is economically plausible but remains a hypothesis; the backtest is evidence, not the rationale.

## 2. Can you prove every fundamental value was available on the decision date?

For revenue and shares, filed<=asof checks pass on tens of thousands of rows. Exact source-vintage/restatement integrity is still unverified.

## 3. Can you prove the universe is survivorship-free?

No. Current status: UNRESOLVED. A complete champion replay including factor-eligible delisted names has not been certified.

## 4. How many research trials did you actually run?

The automated persisted-path inventory finds 446 distinct paths, explicitly a lower bound. The complete human research history is not certified.

## 5. Is the Deflated Sharpe definitive?

No. Status: PERSISTED_TRIAL_LOWER_BOUND_ONLY. It is lower-bound evidence until the trial inventory is complete.

## 6. Do you have a true untouched holdout?

Not certified. Existing OOS/walk-forward tests are useful, but immutable evidence that the final model was frozen before a never-used holdout is still missing.

## 7. Why should I believe 100% of rolling 3Y/5Y windows?

You should not treat overlapping windows as independent observations. The audit reports overlapping and non-overlapping window evidence separately.

## 8. What is the clean completed-month CAGR?

25.12%, with SPY 13.89%.

## 9. How concentrated was the portfolio?

Average top-1 22.22%; historical max top-1 61.81%. This is material.

## 10. How much turnover?

Average annual turnover 178.27%; high-turnover classification.

## 11. What if execution is one day late?

+1-session close sensitivity CAGR 22.88%. This is sensitivity, not an exact historical fill replay.

## 12. What if I ban your best historical names?

See historical_winner_exclusion_reoptimization: top historical winners are excluded with hindsight and capital is reoptimized. Performance falls but does not vanish in the current evidence.

## 13. Does the model memorize tickers?

No explicit ticker-specific rule is expected under the corrected lexical/context audit, and first-ever entries historically work. That does not rule out research overfitting.

## 14. Which factor is really doing the work?

Revenue Growth is the strongest individual quintile spread in the current evidence; Full Alpha improves composite rank association. Exact causal attribution is not identified.

## 15. What happens if you remove one factor?

The extreme audit writes factor_ablation_sensitivity.csv using predeclared one-/two-factor diagnostics without selecting a replacement model.

## 16. Does alpha survive FF5+Momentum?

See multifactor_alpha_extreme.csv. A positive HAC alpha is evidence against standard factor explanations, not proof of unique structural alpha.

## 17. What benchmark besides SPY?

RSP, QQQ and SMH are compared when benchmark artifacts are available. SPY remains primary opportunity cost.

## 18. Do you model slippage and market impact?

The backtest uses a constant friction and turnover. Security-specific spread/impact is not fully modeled; cost and lag stresses are therefore required.

## 19. What AUM can this handle?

Not certified for CEDEAR execution. Underlying ADV can be a proxy, but BYMA historical liquidity is required before an AUM claim.

## 20. Does the optimizer add value?

The audit compares persisted strategy variants where available. Optimizer value must be separated from factor signal and execution implementation.

## 21. Can integer nominal rounding destroy the edge?

Unknown historically. The original research path was continuous-weight; a historical discrete CEDEAR replay has not been certified.

## 22. Do nearby parameter settings also work?

The extreme audit runs symmetric, predeclared local perturbations and reports all of them. No best variant is selected.

## 23. Where does it fail by regime?

Market and volatility regimes are audited; macro inflation/rate regimes require a PIT macro panel if not already present.

## 24. Are drawdown recovery claims computed correctly?

The forensic auditor fixed the recovery calculation and the extreme audit produces explicit drawdown episodes for Alpha Engine and SPY.

## 25. Can I reconstruct every historical decision?

Most monthly research fields are reconstructable, but exact intraday timestamps, per-trade realized costs and marginal optimizer reasons are not fully persisted.

## 26. Why did it buy PBR/SONY today?

That must be answered from current factor scores, ranking, risk and optimizer state—not from their historical success. current_decisions_audit.csv inventories current evidence.

## 27. What would make you call the backtest false?

Systemic PIT leakage, a survivorship-free replay that erases the edge, complete-trial DSR/PBO showing severe selection bias, or forward performance inconsistent with the hypothesis.

## 28. What would make you stop the forward test?

A predeclared governance rule should stop promotion, not necessarily data collection, after sustained negative active return/IC or an implementation failure. The frozen model must not be retuned mid-test and still called the same test.

## 29. What is the largest unknown today?

Survivorship-free certification and research-selection bias, followed by local execution/capacity and true forward evidence.

## 30. Would you invest institutional capital today?

The audit should not recommend that from backtest evidence alone. Until the critical GO/NO-GO blockers close, the appropriate state is research/forward testing rather than institutional track-record claims.