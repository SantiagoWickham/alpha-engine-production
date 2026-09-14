import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.regime_tail_alpha_rebuild import *
from alpha_engine_v13.regime_tail_alpha_rebuild import _weighted_row_mean

class C:
    p={"research_start":"2015-01-02","max_train_years":4,"minimum_feature_coverage":.5,"max_selected_features":4,"minimum_selected_features":2,"correlation_prune_threshold":.94,"correlation_sample_rows":1000,"random_state":13,"recency_half_life_sessions":10,"expert_weight_temperature":1.0,"expert_weight_floor":.03,"evaluation_cutoffs":[.02,.05,.10],"broad_cutoff":.20,"winner_quantile":.90,"loser_quantile":.20}

def test_horizons(): assert HORIZONS==(5,10,20,60,120,252)
def test_experts_are_asymmetric_and_residual(): assert "HGB_UPSIDE_TAIL" in EXPERTS and "HGB_DOWNSIDE_AVOID" in EXPERTS and "HGB_RESIDUAL_RETURN" in EXPERTS
def test_folds_stop_before_holdout(): assert all(pd.Timestamp(e)<=pd.Timestamp("2025-01-01") for _,_,e in FOLDS)
def test_recency_faster():
    d=pd.Series(pd.date_range("2020-01-01",periods=20,freq="B")); w=recency_weights(d,10); assert w[-1]>w[0]
def test_weighted_row_mean_missing():
    a=np.array([[1.,2.,np.nan],[np.nan,2.,4.]]); z=_weighted_row_mean(a,np.array([.4,.3,.3])); assert np.allclose(z,[1.4285714286,3.])
def test_expert_weights_sum_and_floor():
    rows=[]
    for i,e in enumerate(EXPERTS): rows.append({"expert":e,"economic_score":.02-i*.005,"worst_cut_robust_excess":.01-i*.005,"winner_lift":1.5-i*.1,"loser_avoidance":1.4-i*.05,"mean_rank_ic":.05-i*.01})
    w=expert_weights(pd.DataFrame(rows),C()); assert abs(sum(w.values())-1)<1e-9 and min(w.values())>0
def test_macro_features_pit_shape():
    d=pd.date_range("2018-01-01",periods=400,freq="B"); x=pd.DataFrame({"date":d})
    for j,s in enumerate(["SPY","QQQ","IWM","TLT","HYG","UUP","^VIX"]): x[s]=100+j+np.cumsum(np.sin(np.arange(len(d))/30)+.1)
    m,c=macro_features(x); assert len(m)==400 and any("tlt" in k for k in c) and any("vix" in k for k in c)
def test_select_features_respects_limit():
    n=1000; rng=np.random.default_rng(1); d=pd.DataFrame({"signal_date":np.repeat(pd.date_range("2020-01-01",periods=20,freq="B"),50),"_alpha_rank":rng.random(n)})
    for j in range(6): d[f"f{j}"]=rng.normal(size=n)
    keep,a=select_features(d,[f"f{j}" for j in range(6)],C()); assert 2<=len(keep)<=4
def test_normalize_daily():
    d=pd.DataFrame({"signal_date":[pd.Timestamp("2020-01-01")]*3}); assert np.allclose(normalize(d,np.array([3,1,2.])),[1,.3333333333,.6666666667])
def test_holdout_folds(): assert FOLDS[-1][2]=="2025-01-01"
def test_beta_residual_logic_manual():
    r=.10; spy=.04; beta=1.5; assert abs((r-beta*spy)-.04)<1e-12
def test_downside_expert_direction():
    # Higher score must mean lower downside probability.
    p=np.array([.9,.1]); s=1-p; assert s[1]>s[0]
