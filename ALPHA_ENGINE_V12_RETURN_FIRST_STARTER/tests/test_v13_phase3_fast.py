import numpy as np, pandas as pd
from alpha_engine_v13.fast_portfolio_replay import pre2021_horizon_skill,horizon_weights,partial_target,reaggregate_advisor,HORIZONS

def test_partial_execution_does_not_block_available_names():
    cur={"A":.5,"B":.5}; des={"A":.2,"B":.3,"C":.5}; pres=pd.Series({"A":True,"B":False,"C":True})
    actual,m=partial_target(cur,des,pres)
    assert m["blocked_names"]==1
    assert m["executed"]>0
    assert actual.get("B",0)>0
    assert actual.get("C",0)>0

def test_blocked_rate_counts_only_unavailable_requested_trade():
    cur={"A":.5,"B":.5}; des={"A":.5,"B":0.0,"C":.5}; pres=pd.Series({"A":True,"B":False,"C":True})
    _,m=partial_target(cur,des,pres)
    assert abs(m["requested"]-1.0)<1e-12
    assert abs(m["blocked_requested"]-.5)<1e-12

def test_skill_weights_all_horizons_nonzero():
    rows=[]
    for h in HORIZONS:
      for p in ["EVIDENCE_2017_2018","OUTER_2019_2020"]:
       rows.append({"horizon_sessions":h,"period":p,"architecture":"X","economic_score":.01 if h!=252 else -.05,"worst_cut_robust_excess":.005 if h!=252 else -.1,"mean_rank_ic":.1})
    sk=pre2021_horizon_skill(pd.DataFrame(rows)); w=horizon_weights(sk,1.5)
    assert set(w)==set(HORIZONS) and min(w.values())>0
    assert w[252]<w[20]

def test_equal_beta_is_exactly_equal():
    sk=pd.DataFrame({"horizon_sessions":HORIZONS,"skill_z":[-2,-1,0,1,2,3]})
    w=horizon_weights(sk,0.0)
    assert all(abs(v-1/6)<1e-12 for v in w.values())

def test_reaggregate_preserves_six_nonzero_weights():
    d={"signal_date":[pd.Timestamp('2022-01-03')],"ticker":["A"],"role":["POLICY_SELECTION_2021_2022"]}
    for h in HORIZONS:
        d[f"mu_day_{h}d"]=[.001]; d[f"se_day_{h}d"]=[.002]; d[f"alpha_day_{h}d"]=[.0002]; d[f"alpha_se_day_{h}d"]=[.001]
    x=pd.DataFrame(d); w={h:1/6 for h in HORIZONS}; y=reaggregate_advisor(x,w,"EQUAL")
    assert np.isfinite(y.expected_return_per_session.iloc[0])
    assert all(y[f"return_horizon_weight_{h}d"].iloc[0]>0 for h in HORIZONS)
