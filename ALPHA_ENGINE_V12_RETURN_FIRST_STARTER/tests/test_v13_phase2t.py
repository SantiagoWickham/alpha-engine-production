from pathlib import Path
import numpy as np, pandas as pd
from alpha_engine_v13.regime_router import HORIZONS, FOLD_ORDER, _router_features, _choose_router, _eval

def test_horizons_preserved(): assert HORIZONS==(5,10,20,60,120,252)
def test_fold_order(): assert FOLD_ORDER[-2:]==("WF_2021_2022","WF_2023_2024")
def test_router_features_interact_with_regime():
    d=pd.DataFrame({"score":[.2,.8],"macro_x_z252":[-1.,1.]})
    X,n=_router_features(d,["macro_x_z252"])
    assert X.shape==(2,5) and "score_x_macro_x_z252" in n

def test_router_choice_uses_history():
    h=pd.DataFrame([
        {"router":"RIDGE_REGIME","economic_score":.01,"worst_cut_robust_excess":.001,"positive_cut_share":.8,"winner_lift":1.2},
        {"router":"HGB_REGIME","economic_score":-.01,"worst_cut_robust_excess":-.02,"positive_cut_share":.2,"winner_lift":.9},
        {"router":"BLEND_REGIME","economic_score":0,"worst_cut_robust_excess":-.001,"positive_cut_share":.5,"winner_lift":1.0},
    ])
    assert _choose_router(h)=="RIDGE_REGIME"
def test_eval_rewards_good_predictions():
    rows=[]
    for d in pd.date_range("2020-01-01",periods=10,freq="B"):
        for i in range(100): rows.append({"signal_date":d,"robust_excess":(i-50)/5000,"winner":1.0 if i>=90 else 0.0})
    x=pd.DataFrame(rows); p=np.tile(np.arange(100),10)
    e=_eval(x,p); assert e["economic_score"]>0 and e["winner_lift"]>1

def test_horizon_frame_blocks_labels_resolving_in_holdout():
    from alpha_engine_v13.regime_router import _horizon_frame
    scores=pd.DataFrame({
        "signal_date":pd.to_datetime(["2024-06-03","2024-12-20"]),
        "ticker":["AAA","BBB"],"fold":["WF_2023_2024","WF_2023_2024"],
        "horizon_sessions":[5,5],"score":[.8,.9],
    })
    targets=pd.DataFrame({
        "signal_date":pd.to_datetime(["2024-06-03","2024-12-20"]),"ticker":["AAA","BBB"],
        "target_end_date_5d":pd.to_datetime(["2024-06-10","2025-01-03"]),
        "target_resolved_5d":[True,True],"fwd_return_5d":[.02,.50],
        "excess_spy_5d":[.01,.40],"excess_qqq_5d":[.005,.35],"excess_uew_5d":[.008,.30],
    })
    macro=pd.DataFrame({"signal_date":pd.to_datetime(["2024-06-03","2024-12-20"])})
    z=_horizon_frame(scores,targets,macro,5)
    assert z.ticker.tolist()==["AAA"]


def _target_frame_one_row():
    row={"signal_date":pd.Timestamp("2024-01-02"),"ticker":"AAA"}
    for h in HORIZONS:
        row.update({f"target_end_date_{h}d":pd.Timestamp("2024-06-01"),f"target_resolved_{h}d":True,
                    f"fwd_return_{h}d":.01,f"excess_spy_{h}d":.001,f"excess_qqq_{h}d":.002,f"excess_uew_{h}d":.003})
    return pd.DataFrame([row])


def test_load_inputs_uses_phase1_research_targets(tmp_path,monkeypatch):
    import alpha_engine_v13.regime_router as rr
    out=tmp_path/"outputs"; out.mkdir()
    for name in ["v13_phase2s_oof_scores.parquet","v13_phase2s_enriched_feature_surface.parquet","v13_phase1_research_targets.parquet"]:
        (out/name).touch()
    frames={
      "v13_phase2s_oof_scores.parquet":pd.DataFrame({"signal_date":[pd.Timestamp("2024-01-02")],"ticker":["AAA"],"fold":["WF_2023_2024"],"horizon_sessions":[5],"score":[.5]}),
      "v13_phase2s_enriched_feature_surface.parquet":pd.DataFrame({"signal_date":[pd.Timestamp("2024-01-02")],"ticker":["AAA"],"macro_a_z252":[0.]}),
      "v13_phase1_research_targets.parquet":_target_frame_one_row(),
    }
    monkeypatch.setattr(rr.pd,"read_parquet",lambda path,*a,**k: frames[Path(path).name].copy())
    _,_,t,path=rr.load_inputs(tmp_path)
    assert path.name=="v13_phase1_research_targets.parquet"
    assert "excess_spy_5d" in t.columns


def test_load_inputs_preflight_all_horizons(tmp_path,monkeypatch):
    import alpha_engine_v13.regime_router as rr
    out=tmp_path/"outputs"; out.mkdir()
    for name in ["v13_phase2s_oof_scores.parquet","v13_phase2s_enriched_feature_surface.parquet","v13_phase1_research_targets.parquet"]:
        (out/name).touch()
    frames={
      "v13_phase2s_oof_scores.parquet":pd.DataFrame({"signal_date":[pd.Timestamp("2024-01-02")],"ticker":["AAA"],"fold":["WF_2023_2024"],"horizon_sessions":[5],"score":[.5]}),
      "v13_phase2s_enriched_feature_surface.parquet":pd.DataFrame({"signal_date":[pd.Timestamp("2024-01-02")],"ticker":["AAA"],"macro_a_z252":[0.]}),
      "v13_phase1_research_targets.parquet":pd.DataFrame({"signal_date":[pd.Timestamp("2024-01-02")],"ticker":["AAA"]}),
    }
    monkeypatch.setattr(rr.pd,"read_parquet",lambda path,*a,**k: frames[Path(path).name].copy())
    import pytest
    with pytest.raises(RuntimeError,match="schema incomplete"):
        rr.load_inputs(tmp_path)


def test_full_router_pipeline_synthetic(tmp_path,monkeypatch):
    import alpha_engine_v13.regime_router as rr
    rng=np.random.default_rng(13)
    fold_ranges={
      "WF_2017_2018":pd.bdate_range("2018-01-02",periods=15),
      "WF_2019_2020":pd.bdate_range("2020-01-02",periods=15),
      "WF_2021_2022":pd.bdate_range("2022-01-03",periods=15),
      "WF_2023_2024":pd.bdate_range("2024-01-02",periods=15),
    }
    tickers=[f"T{i:02d}" for i in range(25)]
    target_rows=[]; score_rows=[]; feature_rows=[]
    for fold,dates in fold_ranges.items():
        for j,dt in enumerate(dates):
            macro={f"macro_m{k}_z252":float(np.sin(j/(k+2))) for k in range(6)}
            feature_rows.append({"signal_date":dt,"ticker":"T00",**macro})
            for ti,tick in enumerate(tickers):
                latent=(ti-12)/12 + .15*np.sin(j/3)
                tr={"signal_date":dt,"ticker":tick}
                for h in HORIZONS:
                    ret=.002*latent + rng.normal(0,.002)
                    tr.update({f"target_end_date_{h}d":dt+pd.Timedelta(days=1),f"target_resolved_{h}d":True,
                               f"fwd_return_{h}d":ret,f"excess_spy_{h}d":ret-.0002,
                               f"excess_qqq_{h}d":ret-.0003,f"excess_uew_{h}d":ret-.0001})
                    score=1/(1+np.exp(-(latent+rng.normal(0,.25))))
                    score_rows.append({"signal_date":dt,"ticker":tick,"fold":fold,"horizon_sessions":h,"score":score})
                target_rows.append(tr)
    scores=pd.DataFrame(score_rows); features=pd.DataFrame(feature_rows); targets=pd.DataFrame(target_rows)
    monkeypatch.setattr(rr,"load_inputs",lambda workspace:(scores.copy(),features.copy(),targets.copy(),tmp_path/"outputs"/"v13_phase1_research_targets.parquet"))
    monkeypatch.setattr(pd.DataFrame,"to_parquet",lambda self,*a,**k: None)
    s=rr.build_router(tmp_path)
    assert s["phase"]=="V13-P2T"
    assert len(s["meta_advisor_evidence"])==3
    assert {r["test"] for r in s["gate"]}>={"FINAL_HOLDOUT_NOT_LOADED","ALL_SIX_HORIZONS_RETAINED","2021_2022_META_ADVISOR_RECOVERY"}
