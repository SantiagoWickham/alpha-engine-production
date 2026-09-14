import numpy as np
import pandas as pd

from alpha_engine_v13.structural_portfolio_research import (
    HORIZONS,
    skill_prior,
    dynamic_reaggregate,
    partial_target,
    build_target_path,
)


def _skill():
    return pd.DataFrame({
        "horizon_sessions": HORIZONS,
        "skill_z": [0.5, 0.5, 0.6, 0.55, 0.03, -2.2],
    })


def _base_row(alpha252=0.0001, alpha20=0.0001):
    d={"signal_date":[pd.Timestamp("2022-01-03")],"ticker":["A"],"role":["POLICY_SELECTION_2021_2022"]}
    for h in HORIZONS:
        d[f"mu_day_{h}d"]=[0.001]
        d[f"se_day_{h}d"]=[0.001]
        d[f"alpha_day_{h}d"]=[0.0001]
        d[f"alpha_se_day_{h}d"]=[0.0001]
    d["alpha_day_252d"]=[alpha252]
    d["alpha_day_20d"]=[alpha20]
    return pd.DataFrame(d)


def test_skill_prior_keeps_all_horizons_nonzero_and_downweights_bad_252():
    p=skill_prior(_skill(),1.0,0.025)
    assert set(p)==set(HORIZONS)
    assert min(p.values())>0
    assert p[252] < p[20]
    assert abs(sum(p.values())-1)<1e-12


def test_dynamic_horizon_weights_change_by_signal_and_keep_floor():
    prior=skill_prior(_skill(),1.0,0.025)
    a=dynamic_reaggregate(_base_row(alpha252=0.0001,alpha20=0.0001),prior,1.5,0.025)
    b=dynamic_reaggregate(_base_row(alpha252=0.0010,alpha20=-0.0002),prior,1.5,0.025)
    wa=float(a["dynamic_horizon_weight_252d"].iloc[0])
    wb=float(b["dynamic_horizon_weight_252d"].iloc[0])
    assert wb > wa
    for h in HORIZONS:
        assert float(b[f"dynamic_horizon_weight_{h}d"].iloc[0]) > 0


def test_gamma_zero_uses_pre2021_prior_exactly():
    prior=skill_prior(_skill(),1.0,0.025)
    x=dynamic_reaggregate(_base_row(),prior,0.0,0.025)
    for h in HORIZONS:
        assert abs(float(x[f"dynamic_horizon_weight_{h}d"].iloc[0])-prior[h])<1e-12


def test_partial_execution_never_blocks_available_names():
    cur={"A":.5,"B":.5}; des={"A":.2,"B":.3,"C":.5}; pres=pd.Series({"A":True,"B":False,"C":True})
    actual,m=partial_target(cur,des,pres)
    assert m["blocked_names"]==1
    assert m["executed"]>0
    assert actual.get("B",0)>0
    assert actual.get("C",0)>0


def test_partial_execution_reports_only_unavailable_requested_notional():
    cur={"A":.5,"B":.5}; des={"A":.5,"B":0.0,"C":.5}; pres=pd.Series({"A":True,"B":False,"C":True})
    _,m=partial_target(cur,des,pres)
    assert abs(m["requested"]-1.0)<1e-12
    assert abs(m["blocked_requested"]-.5)<1e-12


def test_dynamic_advisor_contains_effective_horizon_not_fixed_holding_period():
    prior=skill_prior(_skill(),1.0,0.025)
    x=dynamic_reaggregate(_base_row(),prior,1.0,0.025)
    h=float(x["effective_horizon_sessions"].iloc[0])
    assert 5 < h < 252


def test_alpha_gate_can_reduce_candidate_set_without_top_n():
    rows=[]
    for i,a in enumerate([0.002,0.0001,-0.001]):
        rows.append({
            "signal_date":pd.Timestamp("2022-01-03"),"ticker":f"T{i}",
            "expected_return_per_session":0.001,"uncertainty_per_session":0.001,
            "expected_robust_alpha_per_session":a,"alpha_uncertainty_per_session":0.001,
        })
    adv=pd.DataFrame(rows)
    class FakeRisk(dict): pass
    idx=pd.DatetimeIndex([pd.Timestamp("2022-01-03")])
    cols=["T0","T1","T2"]
    risk={
        "beta":pd.DataFrame([[1,1,1]],index=idx,columns=cols),
        "idio":pd.DataFrame([[0.01,0.01,0.01]],index=idx,columns=cols),
        "market_var":pd.Series([0.01],index=idx),
    }
    no_gate=build_target_path(adv,risk,0.0,-99.0,0.0)[pd.Timestamp("2022-01-03")]
    gated=build_target_path(adv,risk,0.0,0.5,0.0)[pd.Timestamp("2022-01-03")]
    assert len(gated) < len(no_gate)
    assert len(gated)>=1


def test_alpha_tilt_changes_sizing_signal_without_fixed_cap():
    rows=[]
    for t,a in [("A",0.001),("B",0.0)]:
        rows.append({"signal_date":pd.Timestamp("2022-01-03"),"ticker":t,"expected_return_per_session":0.001,"uncertainty_per_session":0.001,"expected_robust_alpha_per_session":a,"alpha_uncertainty_per_session":0.001})
    adv=pd.DataFrame(rows)
    idx=pd.DatetimeIndex([pd.Timestamp("2022-01-03")]); cols=["A","B"]
    risk={"beta":pd.DataFrame([[0,0]],index=idx,columns=cols),"idio":pd.DataFrame([[0.01,0.01]],index=idx,columns=cols),"market_var":pd.Series([0.01],index=idx)}
    w0=build_target_path(adv,risk,0,-99,0)[pd.Timestamp("2022-01-03")]
    w1=build_target_path(adv,risk,0,-99,1)[pd.Timestamp("2022-01-03")]
    assert w1["A"] > w0["A"]


def test_no_fixed_cardinality_is_embedded_in_target_logic():
    rows=[]
    for i in range(7):
        rows.append({"signal_date":pd.Timestamp("2022-01-03"),"ticker":f"T{i}","expected_return_per_session":0.001+i*0.00001,"uncertainty_per_session":0.001,"expected_robust_alpha_per_session":0.001,"alpha_uncertainty_per_session":0.001})
    adv=pd.DataFrame(rows)
    idx=pd.DatetimeIndex([pd.Timestamp("2022-01-03")]); cols=[f"T{i}" for i in range(7)]
    risk={"beta":pd.DataFrame([np.zeros(7)],index=idx,columns=cols),"idio":pd.DataFrame([np.ones(7)*0.01],index=idx,columns=cols),"market_var":pd.Series([0.01],index=idx)}
    w=build_target_path(adv,risk,0,-99,0)[pd.Timestamp("2022-01-03")]
    assert len(w)==7
