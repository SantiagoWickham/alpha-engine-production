# Alpha Engine V12 architecture

V12 is rebuilt from data only.

Pipeline:

1. DATA FOUNDATION
2. POINT-IN-TIME RESEARCH PANEL
3. RETURN TARGETS AND LABELS
4. SIGNAL RESEARCH
5. WALK-FORWARD MODEL SELECTION
6. EVENT-DRIVEN DECISION POLICY
7. PORTFOLIO CONSTRUCTION
8. EXECUTION AND COST MODEL
9. FREEZE + UNTOUCHED OOS
10. LIVE FORWARD STATE
11. API / WEB
12. GOOGLE SHEETS
13. GITHUB / CI / RELEASES

The model is evaluated each trading session (and later on eligible information events), but trading is not calendar-forced. A trade must improve expected portfolio value net of costs and uncertainty by more than a pre-registered threshold.

Old model outputs are never permitted as V12 predictors. They may only be used after the fact as benchmarks or audit evidence.
