import json, math
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from alpha_engine_v13.preholdout_freeze import _coverage_audit, _gate_map, BUILD


def test_build_tag():
    assert BUILD.startswith("V13_P3W_")


def test_gate_map():
    x=_gate_map([{"test":"A","status":"PASS"}]); assert x["A"]["status"]=="PASS"


def _advisor():
    rows=[]
    for fold in ["WF_2019_2020","WF_2021_2022","WF_2023_2024"]:
        for i in range(5):
            w=np.array([.30,.25,.20,.10,.10,.05])
            if i>=3: w[-1]=0; w=w/w.sum()
            rows.append({"signal_date":pd.Timestamp("2020-01-02")+pd.Timedelta(days=i),"ticker":f"T{i}","fold":fold,**{f"horizon_weight_{h}d":float(v) for h,v in zip((5,10,20,60,120,252),w)}})
    return pd.DataFrame(rows)


def test_maturity_aware_coverage_semantics_accepts_partial_six_rows():
    a=_advisor()
    infl=[]
    for fold,g in a.groupby("fold"):
        for h in (5,10,20,60,120,252): infl.append({"fold":fold,"horizon_sessions":h,"mean_weight":g[f"horizon_weight_{h}d"].mean()})
    legacy=pd.DataFrame({"fold":["WF_2019_2020","WF_2021_2022","WF_2023_2024"],"all_six_horizon_coverage":[.60,.52,.55]})
    out,sem=_coverage_audit(a,pd.DataFrame(infl),legacy,{"weight_sum_tolerance":1e-8,"maximum_mean_horizon_weight":.85})
    assert sem["available_weights_renormalize_to_one"]
    assert sem["all_six_horizons_positive_in_every_fold"]
    assert sem["no_single_horizon_mean_monopoly"]
    assert sem["legacy_all_six_coverage_min"]==pytest.approx(.52)
    assert out["all_six_row_coverage"].min()<.95


def test_coverage_rejects_weight_sum_error():
    a=_advisor(); a.loc[0,"horizon_weight_5d"]+=.1
    infl=[]
    for fold,g in a.groupby("fold"):
        for h in (5,10,20,60,120,252): infl.append({"fold":fold,"horizon_sessions":h,"mean_weight":g[f"horizon_weight_{h}d"].mean()})
    legacy=pd.DataFrame({"fold":["WF_2019_2020","WF_2021_2022","WF_2023_2024"],"all_six_horizon_coverage":[.6,.6,.6]})
    _,sem=_coverage_audit(a,pd.DataFrame(infl),legacy,{"weight_sum_tolerance":1e-8,"maximum_mean_horizon_weight":.85})
    assert not sem["available_weights_renormalize_to_one"]


def test_coverage_rejects_monopoly():
    a=_advisor()
    for h in (5,10,20,60,120,252): a[f"horizon_weight_{h}d"]=0.0
    a["horizon_weight_5d"]=0.9; a["horizon_weight_10d"]=0.1
    infl=[]
    for fold,g in a.groupby("fold"):
        for h in (5,10,20,60,120,252): infl.append({"fold":fold,"horizon_sessions":h,"mean_weight":g[f"horizon_weight_{h}d"].mean()})
    legacy=pd.DataFrame({"fold":["WF_2019_2020","WF_2021_2022","WF_2023_2024"],"all_six_horizon_coverage":[.6,.6,.6]})
    _,sem=_coverage_audit(a,pd.DataFrame(infl),legacy,{"weight_sum_tolerance":1e-8,"maximum_mean_horizon_weight":.85})
    assert not sem["all_six_horizons_positive_in_every_fold"]
    assert not sem["no_single_horizon_mean_monopoly"]


def test_holdout_constant_not_2025_opened():
    # Structural test: module contains no holdout loader and the phase is explicitly freeze-only.
    import alpha_engine_v13.preholdout_freeze as m
    src=Path(m.__file__).read_text(encoding="utf-8")
    assert "READY_TO_OPEN_CODE_BLINDED_2025_PLUS_ONCE" in src
    assert "holdout_used\": False" in src or '"holdout_used": False' in src


def test_load_phase3v_contract_allows_only_legacy_coverage_fail(tmp_path):
    from alpha_engine_v13.preholdout_freeze import _load_phase3v_contract
    out=tmp_path/'outputs'; out.mkdir()
    (out/'v13_phase3v_summary.json').write_text(json.dumps({'status':'FAIL'}))
    pd.DataFrame([
        {'test':'PHASE2U_CORE_QUALITY_ACCEPTED','status':'PASS','blocking':True},
        {'test':'FINAL_HOLDOUT_NOT_LOADED','status':'PASS','blocking':True},
        {'test':'ALL_SIX_HORIZONS_RETAINED','status':'PASS','blocking':True},
        {'test':'MULTI_HORIZON_ADVISOR_COVERAGE','status':'FAIL','blocking':True},
        {'test':'QUALIFIED_FULL_PERIOD_POLICY_EXISTS','status':'PASS','blocking':True},
    ]).to_csv(out/'v13_phase3v_gate.csv',index=False)
    policy={'alpha_tilt':1.0,'edge_z':0.0,'edge_power':2.0}
    (out/'v13_phase3v_selected_policy.json').write_text(json.dumps(policy))
    pd.DataFrame([{'alpha_tilt':1.0,'edge_z':0.0,'edge_power':2.0,'qualified':True}]).to_csv(out/'v13_phase3v_policy_leaderboard.csv',index=False)
    cfg={'phase3v_summary':'outputs/v13_phase3v_summary.json','phase3v_gate':'outputs/v13_phase3v_gate.csv','phase3v_selected_policy':'outputs/v13_phase3v_selected_policy.json','phase3v_leaderboard':'outputs/v13_phase3v_policy_leaderboard.csv'}
    s,p,*_= _load_phase3v_contract(tmp_path,cfg)
    assert p==policy


def test_load_phase3v_contract_rejects_other_blocking_fail(tmp_path):
    from alpha_engine_v13.preholdout_freeze import _load_phase3v_contract
    out=tmp_path/'outputs'; out.mkdir()
    (out/'v13_phase3v_summary.json').write_text(json.dumps({'status':'FAIL'}))
    pd.DataFrame([
        {'test':'PHASE2U_CORE_QUALITY_ACCEPTED','status':'PASS','blocking':True},
        {'test':'FINAL_HOLDOUT_NOT_LOADED','status':'PASS','blocking':True},
        {'test':'ALL_SIX_HORIZONS_RETAINED','status':'PASS','blocking':True},
        {'test':'MULTI_HORIZON_ADVISOR_COVERAGE','status':'FAIL','blocking':True},
        {'test':'QUALIFIED_FULL_PERIOD_POLICY_EXISTS','status':'PASS','blocking':True},
        {'test':'SOMETHING_ELSE','status':'FAIL','blocking':True},
    ]).to_csv(out/'v13_phase3v_gate.csv',index=False)
    (out/'v13_phase3v_selected_policy.json').write_text(json.dumps({'alpha_tilt':1.0,'edge_z':0.0,'edge_power':2.0}))
    pd.DataFrame([{'alpha_tilt':1.0,'edge_z':0.0,'edge_power':2.0,'qualified':True}]).to_csv(out/'v13_phase3v_policy_leaderboard.csv',index=False)
    cfg={'phase3v_summary':'outputs/v13_phase3v_summary.json','phase3v_gate':'outputs/v13_phase3v_gate.csv','phase3v_selected_policy':'outputs/v13_phase3v_selected_policy.json','phase3v_leaderboard':'outputs/v13_phase3v_policy_leaderboard.csv'}
    with pytest.raises(RuntimeError): _load_phase3v_contract(tmp_path,cfg)
