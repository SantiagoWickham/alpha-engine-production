import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.adaptive_alpha_rebuild import *

class C:
    p={"research_start":"2015-01-02","max_train_years":5,"minimum_feature_coverage":.5,"max_selected_features":4,"minimum_selected_features":2,"correlation_prune_threshold":.95,"correlation_sample_rows":1000,"random_state":13,"recency_half_life_sessions":10}

def test_horizons_fixed(): assert HORIZONS==(5,10,20,60,120,252)
def test_five_experts(): assert len(EXPERTS)==5
def test_four_forward_folds_end_before_holdout(): assert FOLDS[-1][2]=="2025-01-01"
def test_recency_weight_newer_higher():
    d=pd.Series(pd.date_range("2020-01-01",periods=20,freq="B")); w=recency_weights(d,10); assert w[-1]>w[0] and abs(w[-1]-1)<1e-12
def test_equal_weights():
    w=expert_weights(pd.DataFrame(),"EQUAL",0,0); assert abs(sum(w.values())-1)<1e-12 and len(w)==5
def test_adaptive_weights_sum_and_floor():
    x=pd.DataFrame({"expert":list(EXPERTS),"economic_score":[.1,.05,0,-.02,-.1],"worst_cut_robust_excess":[.05,.01,0,-.03,-.2],"winner_lift":[1.4,1.2,1,0.9,.7]})
    w=expert_weights(x,"ADAPTIVE_T150",1.5,.04); assert abs(sum(w.values())-1)<1e-9 and min(w.values())>0
def test_dynamic_weights_prefer_skill():
    x=pd.DataFrame({"expert":list(EXPERTS),"economic_score":[.2,.03,.01,0,-.1],"worst_cut_robust_excess":[.1,.01,0,-.01,-.2],"winner_lift":[2,1,1,1,.5]})
    w=expert_weights(x,"ADAPTIVE_T075",.75,.04); assert w[EXPERTS[0]]>w[EXPERTS[-1]]
def test_select_features_respects_limit():
    n=1000; rng=np.random.default_rng(1); d=pd.DataFrame({"signal_date":np.repeat(pd.date_range("2020-01-01",periods=20,freq="B"),50),"fwd_return_5d":rng.normal(size=n)})
    for j in range(6): d[f"f{j}"]=rng.normal(size=n)
    keep,a=select_features(d,[f"f{j}" for j in range(6)],5,C()); assert 2<=len(keep)<=4 and a.selected.sum()==len(keep)
def test_purged_fold_blocks_target_end_leak():
    dates=pd.date_range("2018-01-01","2020-12-31",freq="B"); n=len(dates)
    d=pd.DataFrame({"signal_date":dates,"target_end_date_5d":dates+pd.Timedelta(days=7),"target_resolved_5d":True,"fwd_return_5d":1.0})
    tr,te=purged_fold(d,5,"2020-01-02","2021-01-04",C()); assert (tr.target_end_date_5d<pd.Timestamp("2020-01-02")).all()
def test_normalize_is_daily_rank():
    d=pd.DataFrame({"signal_date":[pd.Timestamp("2020-01-01")]*3}); s=normalize(d,np.array([3,1,2.])); assert np.allclose(s,[1,.3333333333,.6666666667])
def test_blend_scores_renormalizes_missing():
    sf=pd.DataFrame({e:[.2,.8] for e in EXPERTS}); sf.loc[0,EXPERTS[0]]=np.nan; w={e:1/5 for e in EXPERTS}; z=blend_scores(sf,w); assert np.isfinite(z).all()
def test_no_2025_fold():
    for _,_,end in FOLDS: assert pd.Timestamp(end)<=pd.Timestamp("2025-01-01")
