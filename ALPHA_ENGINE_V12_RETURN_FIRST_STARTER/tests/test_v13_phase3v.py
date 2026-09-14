import json,sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import alpha_engine_v13.economic_portfolio_closure as m

class C:
    p={
        "horizon_weight_floor":0.02,
        "horizon_skill_temperature":0.75,
        "minimum_positive_horizon_share":0.50,
        "alpha_tilt_grid":[0.0,0.5,1.0],
        "edge_z_grid":[0.0,0.5,1.0],
        "edge_power_grid":[1.0,1.5,2.0],
    }

def synth_scores_targets():
    rng=np.random.default_rng(7); rows=[]; tr=[]
    folds=[
        ("WF_2017_2018",pd.date_range("2017-02-01",periods=8,freq="20D")),
        ("WF_2019_2020",pd.date_range("2019-02-01",periods=8,freq="20D")),
        ("WF_2021_2022",pd.date_range("2021-02-01",periods=8,freq="20D")),
        ("WF_2023_2024",pd.date_range("2023-02-01",periods=8,freq="20D")),
    ]
    tickers=[f"T{i:02d}" for i in range(30)]
    tmap={}
    for fold,dates in folds:
        for d in dates:
            for j,t in enumerate(tickers):
                latent=(j/(len(tickers)-1)-0.5)+rng.normal(0,.08)
                key=(d,t); x={"signal_date":d,"ticker":t}
                for h in m.HORIZONS:
                    score=np.clip(.5+.35*latent+rng.normal(0,.03),.001,.999)
                    rows.append({"signal_date":d,"ticker":t,"horizon_sessions":h,"fold":fold,"score":score})
                    ret=.01*latent*(h/20)**.35+rng.normal(0,.005)
                    x[f"target_end_date_{h}d"]=d+pd.Timedelta(days=5)
                    x[f"target_resolved_{h}d"]=True
                    x[f"fwd_return_{h}d"]=ret
                    x[f"excess_spy_{h}d"]=ret-.001
                    x[f"excess_uew_{h}d"]=ret-.0005
                tmap[key]=x
    return pd.DataFrame(rows),pd.DataFrame(tmap.values())

def test_candidate_count():
    assert len(m.candidate_specs(C()))==27

def test_phase2u_old_2021_failure_is_not_required(tmp_path):
    (tmp_path/"outputs").mkdir()
    p0={"status":"PASS","source_manifest":{"source_v12_root":str(tmp_path)}}
    gates=[]
    for k in ["FINAL_HOLDOUT_NOT_LOADED","ROTATION_SOURCES_READY","PIT_EARNINGS_EVENTS_READY","ALL_SIX_HORIZONS_RETAINED","PRE2025_NEWINFO_ALPHA","2023_2024_NEWINFO_CONFIRMATION","NEW_INFORMATION_INCREMENTAL_2021_2022"]:
        gates.append({"test":k,"status":"PASS"})
    gates.append({"test":"2021_2022_NEWINFO_RECOVERY","status":"FAIL"})
    p2={"status":"FAIL","gate":gates}
    (tmp_path/"outputs/v13_phase0_summary.json").write_text(json.dumps(p0))
    (tmp_path/"outputs/v13_phase2u_summary.json").write_text(json.dumps(p2))
    cfg=type("X",(),{"p":{"phase0_summary":"outputs/v13_phase0_summary.json","phase2u_summary":"outputs/v13_phase2u_summary.json"}})()
    _,b,_=m.load_contracts(tmp_path,cfg)
    assert b["status"]=="FAIL"

def test_phase2u_core_failure_still_blocks(tmp_path):
    (tmp_path/"outputs").mkdir()
    p0={"status":"PASS","source_manifest":{"source_v12_root":str(tmp_path)}}
    gates=[{"test":k,"status":"PASS"} for k in ["FINAL_HOLDOUT_NOT_LOADED","ROTATION_SOURCES_READY","PIT_EARNINGS_EVENTS_READY","ALL_SIX_HORIZONS_RETAINED","PRE2025_NEWINFO_ALPHA","2023_2024_NEWINFO_CONFIRMATION","NEW_INFORMATION_INCREMENTAL_2021_2022"]]
    gates[4]["status"]="FAIL"
    (tmp_path/"outputs/v13_phase0_summary.json").write_text(json.dumps(p0)); (tmp_path/"outputs/v13_phase2u_summary.json").write_text(json.dumps({"status":"FAIL","gate":gates}))
    cfg=type("X",(),{"p":{"phase0_summary":"outputs/v13_phase0_summary.json","phase2u_summary":"outputs/v13_phase2u_summary.json"}})()
    try: m.load_contracts(tmp_path,cfg); assert False
    except RuntimeError as e: assert "PRE2025_NEWINFO_ALPHA" in str(e)

def test_all_six_horizons_causally_aggregate():
    s,t=synth_scores_targets(); a,rel,inf,cov=m.build_causal_advisor(s,t,C())
    assert set(rel.horizon_sessions)==set(m.HORIZONS)
    assert cov.all_six_horizon_coverage.min()==1.0
    wcols=[f"horizon_weight_{h}d" for h in m.HORIZONS]
    assert np.allclose(a[wcols].sum(axis=1),1.0)
    assert (a[wcols].min(axis=1)>0).all()

def test_2021_fold_uses_only_prior_rows():
    s,t=synth_scores_targets(); _,rel,_,_=m.build_causal_advisor(s,t,C())
    r=rel[(rel.fold=="WF_2021_2022")&(rel.horizon_sessions==5)].iloc[0]
    # 2017+2019 folds: 16 dates x 30 tickers = 480, target maturity before 2021.
    assert r.training_rows==480

def test_partial_execution_does_not_cancel_portfolio():
    cur={"A":.5,"B":.5}; des={"A":.2,"B":.3,"C":.5}; pres=pd.Series({"A":True,"B":False,"C":True})
    actual,meta=m.partial_target(cur,des,pres)
    assert meta["blocked"]>0
    assert actual["B"]==.5
    assert actual.get("A",0)!=cur["A"] or actual.get("C",0)>0
    assert meta["executed"]>0

def test_target_cardinality_is_endogenous():
    dates=[pd.Timestamp("2023-01-03"),pd.Timestamp("2023-01-04")]; rows=[]
    for d,n in zip(dates,[4,9]):
        for i in range(10):
            mu=.003 if i<n else -.001
            rows.append({"signal_date":d,"ticker":f"T{i}","expected_abs_per_session":mu,"expected_alpha_per_session":0.0,"uncertainty_per_session":.002,"positive_horizon_share":.8,"effective_horizon_sessions":20})
    a=pd.DataFrame(rows); cols=[f"T{i}" for i in range(10)]; vol=pd.DataFrame(.02,index=dates,columns=cols)
    market={"vol":vol}; cfg=type("X",(),{"p":{"minimum_positive_horizon_share":.5}})(); spec={"alpha_tilt":0.0,"edge_z":0.0,"edge_power":1.0}
    tp=m.build_target_path(a,market,spec,cfg)
    assert len(tp[dates[0]])==4 and len(tp[dates[1]])==9

def test_simulator_positive_market_and_zero_blocking():
    cal=pd.date_range("2023-01-03",periods=8,freq="B"); cols=["A","B"]
    ret=pd.DataFrame(.001,index=cal,columns=cols); vol=pd.DataFrame(.02,index=cal,columns=cols); pres=pd.DataFrame(True,index=cal,columns=cols); elig=pd.DataFrame(True,index=cal,columns=cols)
    market={"calendar":cal,"returns":ret,"vol":vol,"execution_presence":pres,"research_eligible":elig}; benches={"SPY":pd.Series(0.0,index=cal),"QQQ":pd.Series(0.0,index=cal),"UEW":pd.Series(.001,index=cal)}
    targets={cal[0]:{"A":.6,"B":.4}}
    d=m.simulate(targets,market,benches,{},cal[0],cal[-1]+pd.Timedelta(days=1),20)
    assert d.nav.iloc[-1]>1
    assert d.blocked.sum()==0
    assert d.holdings.max()==2

def test_stress_regime_gate_is_nonblocking_by_design():
    # Architectural assertion: the source uses a nonblocking 2021 stress gate.
    src=(ROOT/"src/alpha_engine_v13/economic_portfolio_closure.py").read_text()
    assert '"2021_2022_STRESS_REGIME"' in src
    assert '"diagnostic only: a difficult regime may underperform",False' in src

def test_no_topn_or_position_cap_primitive():
    src=(ROOT/"src/alpha_engine_v13/economic_portfolio_closure.py").read_text().lower()
    assert "top_n" not in src and "topn" not in src
    assert "max_position" not in src and "position_cap" not in src

def test_build_identifier():
    assert m.BUILD=="V13_P3V_FIX1_V13_WORKSPACE_RESOLUTION_2026-09-13"

def test_full_build_pipeline_runs_without_parquet_loader(monkeypatch,tmp_path):
    s,t=synth_scores_targets()
    cfgdict={
        "name":"TEST","objective":"TEST","holdout_start":"2025-01-01","portfolio_start":"2019-01-02",
        "risk_lookback_sessions":60,"minimum_risk_observations":20,"horizon_weight_floor":.02,"horizon_skill_temperature":.75,
        "minimum_positive_horizon_share":.5,"base_round_trip_cost_bps":20.0,"stress_round_trip_cost_bps":40.0,"maximum_execution_blocked_rate":.05,
        "alpha_tilt_grid":[0.0,0.5,1.0],"edge_z_grid":[0.0,0.5,1.0],"edge_power_grid":[1.0,1.5,2.0],
        "source_spy_benchmark":"x","source_qqq_benchmark":"y","source_terminal_overlay":"z","execution_surface_cache":"e",
    }
    monkeypatch.setattr(m,"load_cfg",lambda ws:type("X",(),{"p":cfgdict})())
    p2={"status":"FAIL","gate":[]}
    monkeypatch.setattr(m,"load_contracts",lambda ws,cfg:({"status":"PASS"},p2,tmp_path))
    monkeypatch.setattr(m,"load_scores_targets",lambda ws,cfg:(s,t))
    cal=pd.date_range("2018-01-02","2024-12-31",freq="B"); tickers=[f"T{i:02d}" for i in range(30)]; rows=[]
    for j,tic in enumerate(tickers):
        p=100.0
        for d in cal:
            # cross-sectional drift so higher-index names are modestly stronger
            p*=1.0+0.00015+0.000006*j
            rows.append({"date":d,"ticker":tic,"execution_close":p,"mark_price":p,"research_eligible":True})
    surface=pd.DataFrame(rows)
    monkeypatch.setattr(m,"load_market",lambda ws,src,cfg,needed:surface[surface.ticker.isin(needed)].copy())
    spy=pd.Series(100*np.cumprod(np.full(len(cal),1.0001)),index=cal,name="SPY")
    qqq=pd.Series(100*np.cumprod(np.full(len(cal),1.00012)),index=cal,name="QQQ")
    monkeypatch.setattr(m,"_load_benchmark",lambda src,rel,symbol,hold: spy if symbol=="SPY" else qqq)
    monkeypatch.setattr(m,"load_terminals",lambda src,cfg:{})
    (tmp_path/"outputs").mkdir(exist_ok=True)
    out=m.build_phase3v(tmp_path)
    assert out["phase"]=="V13-P3V"
    assert out["selection"]["candidate_policies"]==27
    assert out["research_contract"]["holdout_used"] is False
    assert (tmp_path/"outputs/v13_phase3v_summary.json").exists()


def test_runner_targets_canonical_v13_workspace():
    src=(ROOT/"scripts/run_v13_phase3v.py").read_text()
    assert 'ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON' in src
    assert '_preflight(workspace)' in src
    assert 'build_phase3v(workspace)' in src
