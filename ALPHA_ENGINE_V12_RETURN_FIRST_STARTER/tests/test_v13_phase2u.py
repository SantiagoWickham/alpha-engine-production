import sys
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
import alpha_engine_v13.event_sector_incremental_alpha as m
from alpha_engine_v13.event_sector_incremental_alpha import HORIZONS,META_EXPERTS,FOLDS,rotation_daily_features,meta_train_test,expert_weights,fit_meta_experts,attach_event_features,run_horizon

class C:
    p={"holdout_start":"2025-01-01","beta_window":20,"beta_min_periods":10,"sector_symbols":["XLB","XLE","XLK"],"macro_symbols":["IEF","SHY","TIP","GLD","DBC"],"max_selected_features":8,"minimum_selected_features":3,"correlation_sample_rows":1000,"correlation_prune_threshold":.95,"ridge_alpha":10.,"hgb_learning_rate":.08,"hgb_max_iter":18,"hgb_max_leaf_nodes":7,"hgb_min_samples_leaf":20,"hgb_l2":2.,"random_state":13,"evaluation_cutoffs":[.05,.10,.20],"expert_weight_temperature":.75,"expert_weight_floor":.03}

def test_horizons(): assert HORIZONS==(5,10,20,60,120,252)
def test_meta_experts_include_base_and_new_information(): assert "BASE_OOF" in META_EXPERTS and "HGB_NEWINFO_WINNER" in META_EXPERTS and "HGB_NEWINFO_AVOID" in META_EXPERTS
def test_strict_holdout_filter():
    d=pd.DataFrame({"signal_date":["2024-12-31","2025-01-02"],"x":[1,2]}); x=m._strict_preholdout(d,pd.Timestamp("2025-01-01")); assert len(x)==1 and x.signal_date.max()<pd.Timestamp("2025-01-01")
def test_next_session_is_strictly_after_filing():
    cal=pd.DatetimeIndex(pd.to_datetime(["2024-01-02","2024-01-03","2024-01-04"])); s=pd.Series(pd.to_datetime(["2024-01-02","2024-01-03"])); x=m._next_session(s,cal); assert list(x)==list(pd.to_datetime(["2024-01-03","2024-01-04"]))
def test_rotation_is_causal_to_future_mutation():
    d=pd.date_range("2020-01-01",periods=400,freq="B"); raw=pd.DataFrame({"date":d})
    for j,s in enumerate(C.p["sector_symbols"]+C.p["macro_symbols"]): raw[s]=100+j+np.cumsum(np.sin(np.arange(len(d))/20)+.2)
    a,_,_=rotation_daily_features(raw,C()); raw2=raw.copy(); raw2.loc[350:,"XLE"]*=3; b,_,_=rotation_daily_features(raw2,C()); c=[q for q in a if q.startswith("rot_xle")]; assert np.allclose(a.loc[:300,c].fillna(0),b.loc[:300,c].fillna(0))
def test_event_merge_never_uses_future_filing():
    keys=pd.DataFrame({"signal_date":pd.to_datetime(["2020-01-03","2020-01-06"]),"ticker":["A","A"]}); ev=pd.DataFrame({"ticker":["A"],"available_date":pd.to_datetime(["2020-01-06"]),"earn_surprise_composite":[2.]}); market=pd.DataFrame({"date":pd.to_datetime(["2020-01-02","2020-01-03","2020-01-06"]*1),"ticker":["A"]*3,"close":[10,10.5,11],"volume":[100,110,120]}); o=attach_event_features(keys,ev,market); assert pd.isna(o.iloc[0].earn_surprise_composite) and o.iloc[1].earn_surprise_composite==2
def test_meta_train_uses_prior_folds_only_and_matured_labels():
    rows=[]
    for fold,st,en in FOLDS:
        for d in pd.date_range(st,periods=3,freq="B"): rows.append({"signal_date":d,"ticker":"A","fold":fold,"target_resolved_5d":True,"target_end_date_5d":d+pd.Timedelta(days=1),"_robust_alpha":.1})
    rows.append({"signal_date":pd.Timestamp("2020-12-31"),"ticker":"B","fold":"WF_2019_2020","target_resolved_5d":True,"target_end_date_5d":pd.Timestamp("2021-01-06"),"_robust_alpha":.1})
    df=pd.DataFrame(rows); tr,va=meta_train_test(df,5,"WF_2021_2022"); assert set(tr.fold).issubset({"WF_2017_2018","WF_2019_2020"}) and set(va.fold)=={"WF_2021_2022"} and "B" not in set(tr.ticker)
def test_weights_sum_and_preserve_base():
    w=expert_weights(pd.DataFrame(),C()); assert abs(sum(w.values())-1)<1e-12 and w["BASE_OOF"]>max(v for k,v in w.items() if k!="BASE_OOF")
def test_fit_meta_experts_shapes():
    rng=np.random.default_rng(2); n=800; tr=pd.DataFrame({"signal_date":np.repeat(pd.date_range("2018-01-01",periods=40,freq="B"),20),"base_score":rng.random(n),"_alpha_rank":rng.random(n),"_robust_alpha":rng.normal(0,.03,n),"_winner":rng.binomial(1,.1,n),"_loser":rng.binomial(1,.2,n),"f1":rng.normal(size=n),"f2":rng.normal(size=n)}); va=tr.iloc[:200].copy(); o=fit_meta_experts(tr,va,["base_score","f1","f2"],C()); assert set(o)==set(META_EXPERTS) and all(len(v)==len(va) for v in o.values())
def test_run_horizon_full_nested_stack():
    rng=np.random.default_rng(7); parts=[]; h=5
    for fi,(fold,st,en) in enumerate(FOLDS):
        dates=pd.date_range(st,periods=60,freq="B"); tick=[f"T{i:03d}" for i in range(100)]; idx=pd.MultiIndex.from_product([dates,tick],names=["signal_date","ticker"]).to_frame(index=False); n=len(idx); alpha=.03*(rng.random(n)-.5)+.02*(rng.random(n)-.5); idx["fold"]=fold; idx["base_score"]=rng.random(n); idx["f1"]=alpha+rng.normal(0,.02,n); idx["f2"]=rng.normal(size=n); idx[f"target_resolved_{h}d"]=True; idx[f"target_end_date_{h}d"]=idx.signal_date+pd.offsets.BDay(2); idx["_robust_alpha"]=alpha; idx["_alpha_rank"]=idx.groupby("signal_date")["_robust_alpha"].rank(pct=True); idx["_winner"]=(idx._alpha_rank>=.9).astype(int); idx["_loser"]=(idx._alpha_rank<=.2).astype(int); idx[f"excess_spy_{h}d"]=alpha; idx[f"excess_qqq_{h}d"]=alpha-.001; idx[f"excess_uew_{h}d"]=alpha+.001; parts.append(idx)
    d=pd.concat(parts,ignore_index=True); ev,oof,w,s=run_horizon(d,h,C(),["base_score","f1","f2"]); assert set(oof.fold)=={x[0] for x in FOLDS} and set(ev.expert).issuperset({"META_BLEND","BASE_OOF","RIDGE_NEWINFO"}) and len(w)>0
