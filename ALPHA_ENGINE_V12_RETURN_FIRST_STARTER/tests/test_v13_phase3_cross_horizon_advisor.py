from types import SimpleNamespace
import numpy as np
import pandas as pd
from alpha_engine_v13.cross_horizon_advisor import (
    HORIZONS, build_advisor_surface, one_factor_kelly_weights, candidate_specs,
    rank_policies, evaluate_gate,
)

def _cfg(**kw):
    base={"holdout_start":"2025-01-01","uncertainty_z_grid":[0,0.5],"entry_hurdle_bps_grid":[0,50],"rebalance_extra_edge_bps_grid":[0,50]}
    base.update(kw); return SimpleNamespace(p=base)

def _cal():
    rows=[]
    for h in HORIZONS:
        for b,c in enumerate([.1,.3,.5,.7,.9]): rows.append({"horizon_sessions":h,"score_center":c,"expected_return":0.001*h/20+(c-.5)*0.02*h/20,"hac_se_return":0.01*h/20,"expected_robust_excess":(c-.5)*0.02*h/20,"hac_se_robust_excess":0.01*h/20})
    return pd.DataFrame(rows)

def test_all_six_horizons_are_simultaneous_contract(): assert HORIZONS==(5,10,20,60,120,252)

def test_advisor_changes_when_one_horizon_changes():
    rows=[]
    for h in HORIZONS: rows.append({"signal_date":pd.Timestamp("2022-01-03"),"ticker":"A","horizon_sessions":h,"score":.7,"role":"X"})
    d=pd.DataFrame(rows); a=build_advisor_surface(d,_cal(),"X")
    d.loc[d.horizon_sessions.eq(252),"score"]=.95; b=build_advisor_surface(d,_cal(),"X")
    assert float(a.expected_excess_per_session.iloc[0]) != float(b.expected_excess_per_session.iloc[0])

def test_tactical_and_strategic_views_are_both_exported():
    rows=[{"signal_date":pd.Timestamp("2022-01-03"),"ticker":"A","horizon_sessions":h,"score":.8,"role":"X"} for h in HORIZONS]
    x=build_advisor_surface(pd.DataFrame(rows),_cal(),"X")
    assert "tactical_expected_excess_per_session" in x and "strategic_expected_excess_per_session" in x

def test_no_fixed_cardinality_candidate_grid():
    specs=candidate_specs(_cfg()); assert len(specs)==8
    assert all("top_n" not in s for s in specs)

def test_kelly_can_concentrate_above_twelve_percent():
    w=one_factor_kelly_weights({"A":0.01,"B":0.0001},np.array([.5,.5]),np.array([.0001,.01]),.0001)
    assert w["A"]>0.12

def test_kelly_cardinality_is_endogenous():
    w1=one_factor_kelly_weights({"A":.01},np.array([1.]),np.array([.001]),.0001)
    w2=one_factor_kelly_weights({"A":.01,"B":.008},np.array([1.,.5]),np.array([.001,.001]),.0001)
    assert len(w1)!=len(w2)

def test_return_first_policy_ranking_prefers_robust_excess():
    d=pd.DataFrame([
        {"qualified":True,"robust_excess_cagr_20bps":.20,"cagr_20bps":.25,"robust_excess_cagr_40bps":.18,"max_drawdown_20bps":-.4,"annual_turnover_20bps":5},
        {"qualified":True,"robust_excess_cagr_20bps":.10,"cagr_20bps":.40,"robust_excess_cagr_40bps":.09,"max_drawdown_20bps":-.1,"annual_turnover_20bps":1},
    ])
    assert rank_policies(d).iloc[0].robust_excess_cagr_20bps==.20

def test_validation_is_nonblocking_confirmation_gate():
    parts={"phase2_status":"PASS","max_score_date":pd.Timestamp("2024-12-31"),"dense_horizons":list(HORIZONS),"minimum_daily_horizon_count":6,"fixed_cardinality":False,"fixed_position_cap":False,"qualified_policies":1,"validation_used_for_selection":False,"validation_confirmed":False}
    g,status=evaluate_gate(parts,_cfg()); assert status=="PASS"; assert bool(g.loc[g.test.eq("VALIDATION_CONFIRMATION"),"blocking"].iloc[0]) is False

def test_holdout_boundary_is_blocking():
    parts={"phase2_status":"PASS","max_score_date":pd.Timestamp("2025-01-02"),"dense_horizons":list(HORIZONS),"minimum_daily_horizon_count":6,"fixed_cardinality":False,"fixed_position_cap":False,"qualified_policies":1,"validation_used_for_selection":False,"validation_confirmed":True}
    _,status=evaluate_gate(parts,_cfg()); assert status=="FAIL"

def test_missing_horizon_fails_complete_term_structure_gate():
    parts={"phase2_status":"PASS","max_score_date":pd.Timestamp("2024-12-31"),"dense_horizons":list(HORIZONS),"minimum_daily_horizon_count":5,"fixed_cardinality":False,"fixed_position_cap":False,"qualified_policies":1,"validation_used_for_selection":False,"validation_confirmed":True}
    _,status=evaluate_gate(parts,_cfg()); assert status=="FAIL"

def test_effective_horizon_is_endogenous_between_short_and_long():
    rows=[{"signal_date":pd.Timestamp("2022-01-03"),"ticker":"A","horizon_sessions":h,"score":.8,"role":"X"} for h in HORIZONS]
    x=build_advisor_surface(pd.DataFrame(rows),_cal(),"X")
    eh=float(x.effective_horizon_sessions.iloc[0])
    assert 5.0 <= eh <= 252.0


def test_no_topn_or_weight_cap_in_selected_advisor_contract_primitives():
    specs=candidate_specs(_cfg())
    assert all("top_n" not in z and "max_weight" not in z and "min_weight" not in z for z in specs)

def test_advisor_exports_absolute_return_and_alpha_separately():
    rows=[{"signal_date":pd.Timestamp("2022-01-03"),"ticker":"A","horizon_sessions":h,"score":.8,"role":"X"} for h in HORIZONS]
    cal=_cal()
    x=build_advisor_surface(pd.DataFrame(rows),cal,"X")
    assert "expected_return_per_session" in x.columns
    assert "expected_robust_alpha_per_session" in x.columns


def test_portfolio_qualification_remains_benchmark_level_not_single_name_contract():
    # The policy grid must not contain any per-name benchmark hurdle parameter.
    specs=candidate_specs(_cfg())
    assert all("benchmark_hurdle" not in s and "excess_hurdle" not in s for s in specs)


def test_negative_alpha_does_not_automatically_forbid_positive_return_candidate():
    # Alpha is a portfolio-level qualification objective, not a per-name admission veto.
    rows=[]
    for h in HORIZONS:
        rows.append({"signal_date":pd.Timestamp("2022-01-03"),"ticker":"A","horizon_sessions":h,"score":.9,"role":"X"})
    cal=_cal().copy()
    cal["expected_return"]=0.02
    cal["hac_se_return"]=0.001
    cal["expected_robust_excess"]=-0.01
    cal["hac_se_robust_excess"]=0.001
    x=build_advisor_surface(pd.DataFrame(rows),cal,"X")
    assert float(x["expected_return_per_session"].iloc[0]) > 0
    assert float(x["expected_robust_alpha_per_session"].iloc[0]) < 0


def test_lcb_uncertainty_is_not_the_kelly_mean_vector():
    from alpha_engine_v13.cross_horizon_advisor import build_target_path
    d=pd.Timestamp("2022-01-03")
    a=pd.DataFrame({
        "signal_date":[d,d],"ticker":["A","B"],
        "expected_return_per_session":[0.01,0.005],
        "uncertainty_per_session":[0.004,0.004],
        "effective_horizon_sessions":[20.0,20.0],
    })
    risk={
        "beta":pd.DataFrame([[0.0,0.0]],index=[d],columns=["A","B"]),
        "idio":pd.DataFrame([[0.01,0.01]],index=[d],columns=["A","B"]),
        "market_var":pd.Series([0.0001],index=[d]),
    }
    w=build_target_path(a,risk,1.0,0.0)[d]
    # If LCB were passed as the mean again, A/B ratio would be 0.006/0.001=6.
    # Correct posterior-mean sizing gives 0.01/0.005=2 with equal risk.
    assert abs((w["A"]/w["B"])-2.0) < 1e-6


def test_calibration_exports_absolute_and_alpha_mappings():
    from alpha_engine_v13.cross_horizon_advisor import fit_horizon_calibration
    h=5
    dates=pd.bdate_range("2019-01-02",periods=50)
    sr=[]; tr=[]
    for j,d in enumerate(dates):
        for i in range(20):
            ticker=f"T{i:02d}"
            score=(i+.5)/20
            r=0.002 + 0.03*score
            sr.append({"signal_date":d,"ticker":ticker,"horizon_sessions":h,"score":score})
            tr.append({"signal_date":d,"ticker":ticker,f"target_end_date_{h}d":d+pd.Timedelta(days=2),f"fwd_return_{h}d":r,f"excess_spy_{h}d":r-0.01,f"excess_qqq_{h}d":r-0.012,f"excess_uew_{h}d":r-0.008,f"target_resolved_{h}d":True})
    tab=fit_horizon_calibration(pd.DataFrame(sr),pd.DataFrame(tr),h,10,20,pd.Timestamp("2021-01-01"))
    assert {"expected_return","hac_se_return","expected_robust_excess","hac_se_robust_excess"}.issubset(tab.columns)
    assert tab["expected_return"].iloc[-1] >= tab["expected_return"].iloc[0]

def test_partial_execution_does_not_cancel_whole_rebalance():
    from alpha_engine_v13.cross_horizon_advisor import _partial_execution_target
    current={"A":0.5,"B":0.5}
    target={"A":0.2,"B":0.8}
    presence=pd.Series({"A":True,"B":False})
    actual,meta=_partial_execution_target(current,target,presence)
    assert abs(actual["A"]-0.2) < 1e-12
    assert abs(actual["B"]-0.5) < 1e-12
    assert meta["executed_notional"] > 0
    assert meta["unfilled_notional"] > 0
    assert meta["partial"] is True
    assert meta["full_skip"] is False


def test_horizon_influence_weights_sum_to_one():
    rows=[{"signal_date":pd.Timestamp("2022-01-03"),"ticker":"A","horizon_sessions":h,"score":.8,"role":"X"} for h in HORIZONS]
    x=build_advisor_surface(pd.DataFrame(rows),_cal(),"X")
    rsum=sum(float(x[f"return_horizon_weight_{h}d"].iloc[0]) for h in HORIZONS)
    asum=sum(float(x[f"alpha_horizon_weight_{h}d"].iloc[0]) for h in HORIZONS)
    assert abs(rsum-1.0) < 1e-9
    assert abs(asum-1.0) < 1e-9
