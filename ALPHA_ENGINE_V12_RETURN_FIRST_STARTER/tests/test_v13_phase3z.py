from pathlib import Path
import json
import numpy as np, pandas as pd
import alpha_engine_v13.roundtrip_resize_hysteresis as m
from alpha_engine_v13 import active_alpha_persistent_portfolio as p3y
from alpha_engine_v13 import economic_portfolio_closure as p3v


def test_resize_band_uses_full_roundtrip_cost():
    assert abs(m._resize_band(.002,.5)-.004)<1e-12


def test_resize_band_invalid_curvature_blocks():
    assert m._resize_band(.002,np.nan)==1.0


def test_phase3y_target_respects_band():
    cur={'A':.2}; plan={'A':{'desired':.205,'alpha_total':.01,'entry_ok':True,'band':.01}}
    d=p3y._economic_target(cur,plan); assert abs(d['A']-.2)<1e-12


def test_phase3y_target_exits_negative_alpha():
    cur={'A':.2}; plan={'A':{'desired':.4,'alpha_total':-.01,'entry_ok':True,'band':.5}}
    assert 'A' not in p3y._economic_target(cur,plan)


def test_turnover_metric_decomposition():
    d=pd.DataFrame({'turnover':[.1,.2],'entry_exit_notional':[.05,.05],'resize_notional':[.1,.2]})
    r=p3y._turnover(d); assert r['annual_turnover']>0 and abs(r['entry_exit_share']-.25)<1e-12


def test_ols_positive_alpha():
    x=pd.Series(np.linspace(-.01,.01,1000)); y=.0001+.8*x
    r=p3y._ols(y,x); assert r['alpha_ann']>0 and abs(r['beta']-.8)<1e-10


def test_baseline_reader(tmp_path):
    (tmp_path/'outputs').mkdir(); s={'full_period_20bps':{'cagr':.3},'full_period_40bps':{'cagr':.25},'turnover':{'annual_turnover':18},'beta_attribution':[{'benchmark':'UEW','alpha_ann':.03}]}
    (tmp_path/'outputs'/'v13_phase3y_summary.json').write_text(json.dumps(s))
    cfg=m.Cfg({'phase3y_summary':'outputs/v13_phase3y_summary.json'})
    b=m._get_baseline(tmp_path,cfg); assert b['turnover']==18 and b['uew_alpha']==.03


def _synthetic_inputs():
    dates=pd.date_range('2017-01-03','2024-12-31',freq='10B'); ticks=[f'T{i}' for i in range(12)]
    folddef=[('WF_2017_2018',pd.Timestamp('2017-01-03'),pd.Timestamp('2019-01-02')),('WF_2019_2020',pd.Timestamp('2019-01-02'),pd.Timestamp('2021-01-04')),('WF_2021_2022',pd.Timestamp('2021-01-04'),pd.Timestamp('2023-01-03')),('WF_2023_2024',pd.Timestamp('2023-01-03'),pd.Timestamp('2025-01-01'))]
    tr=[]; sc=[]; rng=np.random.default_rng(7)
    for d in dates:
        fold=next((n for n,a,b in folddef if d>=a and d<b),None)
        if fold is None: continue
        base=[]
        for i,t in enumerate(ticks):
            u=(i+1)/(len(ticks)+1); base.append({'signal_date':d,'ticker':t})
            for h in p3y.HORIZONS: sc.append({'signal_date':d,'ticker':t,'horizon_sessions':h,'fold':fold,'score':u})
        for r in base:
            i=int(r['ticker'][1:]); u=(i+1)/(len(ticks)+1)
            for h in p3y.HORIZONS:
                end=d+pd.Timedelta(days=int(h*1.6)); alpha=(u-.55)*.04*np.sqrt(h/20); rr=.01*np.sqrt(h/20)+alpha+rng.normal(0,.002)
                r[f'target_end_date_{h}d']=end; r[f'target_resolved_{h}d']=end<pd.Timestamp('2025-01-01'); r[f'fwd_return_{h}d']=rr; r[f'excess_spy_{h}d']=alpha; r[f'excess_qqq_{h}d']=alpha*.9; r[f'excess_uew_{h}d']=alpha*1.1
        tr.extend(base)
    return pd.DataFrame(sc),pd.DataFrame(tr)


def test_build_plans_daily_review_without_fixed_holding():
    idx=pd.date_range('2020-01-02',periods=3,freq='B'); adv=pd.DataFrame({'signal_date':[idx[0]],'ticker':['A'],'expected_active_per_session':[.001],'uncertainty_per_session':[.01],'positive_active_horizon_share':[1.0],'effective_horizon_sessions':[20.0]})
    vol=pd.DataFrame({'A':[.02,.02,.02]},index=idx); cfg=m.Cfg({'base_round_trip_cost_bps':20.0,'minimum_positive_horizon_share':.5})
    p=m.build_plans(adv,{'vol':vol},cfg); assert idx[0] in p and 'A' in p[idx[0]] and p[idx[0]]['A']['band']>0


def test_full_build_synthetic(tmp_path,monkeypatch):
    (tmp_path/'config').mkdir(); (tmp_path/'outputs').mkdir()
    cfgtext=(Path(__file__).resolve().parents[1]/'config'/'v13_phase3z.toml').read_text(); (tmp_path/'config'/'v13_phase3z.toml').write_text(cfgtext)
    # baseline deliberately weak enough for synthetic Pareto pass/fail to be immaterial to execution correctness
    baseline={'full_period_20bps':{'cagr':-.5},'full_period_40bps':{'cagr':-.5},'turnover':{'annual_turnover':1e6},'beta_attribution':[{'benchmark':'UEW','alpha_ann':-.1}]}
    (tmp_path/'outputs'/'v13_phase3y_summary.json').write_text(json.dumps(baseline))
    scores,targets=_synthetic_inputs(); p0={'status':'PASS','source_manifest':{'source_v12_root':str(tmp_path)}}; p2u={'status':'FAIL'}
    monkeypatch.setattr(p3y,'load_inputs',lambda ws,cfg:(p0,p2u,tmp_path,scores,targets))
    pcfg=p3v.Cfg({'source_spy_benchmark':'x','source_qqq_benchmark':'y','execution_surface_cache':'x','source_canonical_pit_panel':'x','source_return_price_layer':'x','source_terminal_overlay':'x'})
    monkeypatch.setattr(p3v,'load_cfg',lambda ws:pcfg); monkeypatch.setattr(p3v,'load_market',lambda *a,**k:pd.DataFrame())
    idx=pd.date_range('2018-01-02','2024-12-31',freq='B'); rng=np.random.default_rng(8); cols=sorted(scores.ticker.unique()); rets=pd.DataFrame(rng.normal(.0004,.012,(len(idx),len(cols))),index=idx,columns=cols); vol=rets.rolling(60,min_periods=20).std().fillna(.012); elig=pd.DataFrame(True,index=idx,columns=cols); pres=elig.copy(); market={'calendar':idx,'returns':rets,'vol':vol,'execution_presence':pres,'research_eligible':elig}
    spy=pd.Series(rng.normal(.0003,.01,len(idx)),index=idx); qqq=pd.Series(rng.normal(.00035,.012,len(idx)),index=idx)
    calls={'n':0}
    def lb(*a,**k): calls['n']+=1; return spy if calls['n']==1 else qqq
    monkeypatch.setattr(p3v,'_load_benchmark',lb); monkeypatch.setattr(p3v,'prepare_market',lambda *a,**k:market); monkeypatch.setattr(p3v,'benchmark_returns',lambda *a,**k:{'SPY':spy,'QQQ':qqq,'UEW':rets.mean(axis=1)}); monkeypatch.setattr(p3v,'load_terminals',lambda *a,**k:{})
    s=m.build_phase3z(tmp_path)
    assert s['phase']=='V13-P3Z' and (tmp_path/'outputs'/'v13_phase3z_summary.json').exists() and s['holdout_used'] is False
