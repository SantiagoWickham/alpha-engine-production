import json
from pathlib import Path
import numpy as np, pandas as pd
import alpha_engine_v13.active_alpha_persistent_portfolio as m
from alpha_engine_v13 import economic_portfolio_closure as p3v


def test_softmax_weights_sum_one():
    w=m._softmax({5:.01,10:.02,20:.03,60:0,120:-.01,252:-.02},.02,.75)
    assert abs(sum(w.values())-1)<1e-12 and all(v>0 for v in w.values())


def test_economic_target_entry_requires_cost_hurdle():
    cur={}; plan={'A':{'desired':.3,'alpha_total':.001,'entry_ok':False,'band':.01},'B':{'desired':.4,'alpha_total':.01,'entry_ok':True,'band':.01}}
    d=m._economic_target(cur,plan)
    assert 'A' not in d and d['B']>.39


def test_economic_target_holds_positive_existing_below_entry():
    cur={'A':.2}; plan={'A':{'desired':0.0,'alpha_total':.0005,'entry_ok':False,'band':.01}}
    d=m._economic_target(cur,plan); assert abs(d['A']-.2)<1e-12


def test_economic_target_exits_negative_existing():
    cur={'A':.2}; plan={'A':{'desired':.1,'alpha_total':-.001,'entry_ok':False,'band':.01}}
    d=m._economic_target(cur,plan); assert 'A' not in d


def test_no_trade_band_suppresses_small_resize():
    cur={'A':.20}; plan={'A':{'desired':.205,'alpha_total':.01,'entry_ok':True,'band':.01}}
    d=m._economic_target(cur,plan); assert abs(d['A']-.20)<1e-12


def test_no_trade_band_soft_thresholds_large_resize():
    cur={'A':.20}; plan={'A':{'desired':.30,'alpha_total':.01,'entry_ok':True,'band':.02}}
    d=m._economic_target(cur,plan); assert abs(d['A']-.28)<1e-12


def test_simulator_daily_review_not_fixed_holding():
    idx=pd.date_range('2020-01-02',periods=8,freq='B'); ret=pd.DataFrame({'A':0.0,'B':0.0},index=idx); pres=ret.notna()
    market={'calendar':idx,'returns':ret,'execution_presence':pres}
    plans={idx[0]:{'A':{'desired':1.0,'alpha_total':.02,'entry_ok':True,'band':0}},idx[2]:{'A':{'desired':0,'alpha_total':-.01,'entry_ok':False,'band':0},'B':{'desired':1.0,'alpha_total':.02,'entry_ok':True,'band':0}}}
    d=m.simulate_persistent(plans,market,{},idx[0],idx[-1]+pd.Timedelta(days=1),20)
    assert d.turnover.sum()>0 and d.holdings.max()>=1


def test_ols_recovers_alpha_beta():
    x=pd.Series(np.linspace(-.02,.02,1000)); y=.0002+1.1*x; r=m._ols(y,x)
    assert abs(r['beta']-1.1)<1e-10 and abs(r['alpha_ann']-.0504)<1e-10


def test_universe_lineage_detects_entries_exits():
    idx=pd.date_range('2020-01-02',periods=5,freq='B'); e=pd.DataFrame({'A':[1,1,1,1,1],'B':[0,1,1,1,1],'C':[1,1,1,0,0]},index=idx).astype(bool)
    x,s=m._universe_lineage({'research_eligible':e},idx[0],idx[-1]+pd.Timedelta(days=1))
    assert s['entries_after_start']==1 and s['exits_before_end']==1


def _synthetic_inputs():
    dates=pd.date_range('2017-01-03','2024-12-31',freq='10B'); ticks=[f'T{i}' for i in range(12)]
    folddef=[('WF_2017_2018',pd.Timestamp('2017-01-03'),pd.Timestamp('2019-01-02')),('WF_2019_2020',pd.Timestamp('2019-01-02'),pd.Timestamp('2021-01-04')),('WF_2021_2022',pd.Timestamp('2021-01-04'),pd.Timestamp('2023-01-03')),('WF_2023_2024',pd.Timestamp('2023-01-03'),pd.Timestamp('2025-01-01'))]
    tr=[]; sc=[]
    rng=np.random.default_rng(7)
    for d in dates:
        fold=next((n for n,a,b in folddef if d>=a and d<b),None)
        if fold is None: continue
        base=[]
        for i,t in enumerate(ticks):
            u=(i+1)/(len(ticks)+1); base.append({'signal_date':d,'ticker':t})
            for h in m.HORIZONS: sc.append({'signal_date':d,'ticker':t,'horizon_sessions':h,'fold':fold,'score':u})
        for r in base:
            i=int(r['ticker'][1:]); u=(i+1)/(len(ticks)+1)
            for h in m.HORIZONS:
                end=d+pd.Timedelta(days=int(h*1.6)); alpha=(u-.55)*.04*np.sqrt(h/20); market=.01*np.sqrt(h/20); rr=market+alpha+rng.normal(0,.002)
                r[f'target_end_date_{h}d']=end; r[f'target_resolved_{h}d']=end<pd.Timestamp('2025-01-01'); r[f'fwd_return_{h}d']=rr; r[f'excess_spy_{h}d']=alpha; r[f'excess_qqq_{h}d']=alpha*.9; r[f'excess_uew_{h}d']=alpha*1.1
        tr.extend(base)
    return pd.DataFrame(sc),pd.DataFrame(tr)


def test_full_build_synthetic(tmp_path,monkeypatch):
    (tmp_path/'config').mkdir(); (tmp_path/'outputs').mkdir();
    cfgtext=(Path(__file__).resolve().parents[1]/'config'/'v13_phase3y.toml').read_text(); (tmp_path/'config'/'v13_phase3y.toml').write_text(cfgtext)
    scores,targets=_synthetic_inputs(); p0={'status':'PASS','source_manifest':{'source_v12_root':str(tmp_path)}}; p2u={'status':'FAIL'}
    monkeypatch.setattr(m,'load_inputs',lambda ws,cfg:(p0,p2u,tmp_path,scores,targets))
    pcfg=p3v.Cfg({'source_spy_benchmark':'x','source_qqq_benchmark':'y','execution_surface_cache':'x','source_canonical_pit_panel':'x','source_return_price_layer':'x','source_terminal_overlay':'x'})
    monkeypatch.setattr(p3v,'load_cfg',lambda ws:pcfg); monkeypatch.setattr(p3v,'load_market',lambda *a,**k:pd.DataFrame())
    idx=pd.date_range('2018-01-02','2024-12-31',freq='B'); rng=np.random.default_rng(8); cols=sorted(scores.ticker.unique()); rets=pd.DataFrame(rng.normal(.0004,.012,(len(idx),len(cols))),index=idx,columns=cols); vol=rets.rolling(60,min_periods=20).std().fillna(.012); elig=pd.DataFrame(True,index=idx,columns=cols); pres=elig.copy(); market={'calendar':idx,'returns':rets,'vol':vol,'execution_presence':pres,'research_eligible':elig}
    spy=pd.Series(rng.normal(.0003,.01,len(idx)),index=idx); qqq=pd.Series(rng.normal(.00035,.012,len(idx)),index=idx)
    calls={'n':0}
    def lb(*a,**k): calls['n']+=1; return spy if calls['n']==1 else qqq
    monkeypatch.setattr(p3v,'_load_benchmark',lb); monkeypatch.setattr(p3v,'prepare_market',lambda *a,**k:market); monkeypatch.setattr(p3v,'benchmark_returns',lambda *a,**k:{'SPY':spy,'QQQ':qqq,'UEW':rets.mean(axis=1)}); monkeypatch.setattr(p3v,'load_terminals',lambda *a,**k:{})
    s=m.build_phase3y(tmp_path)
    assert s['phase']=='V13-P3Y' and (tmp_path/'outputs'/'v13_phase3y_summary.json').exists() and s['holdout_used'] is False
