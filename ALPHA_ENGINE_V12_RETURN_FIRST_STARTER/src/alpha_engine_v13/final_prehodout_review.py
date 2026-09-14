from __future__ import annotations
import hashlib, json, tomllib
from pathlib import Path
import numpy as np
import pandas as pd
from alpha_engine_v13 import economic_portfolio_closure as p3v

BUILD="V13_P3AA_FINAL_PREHOLDOUT_REVIEW_FREEZE_2026-09-13"

def _cfg(ws:Path):
    with (ws/'config'/'v13_phase3aa.toml').open('rb') as f:return tomllib.load(f)['v13_phase3aa']

def _sha(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def _cagr(r):
    r=pd.to_numeric(r,errors='coerce').fillna(0.0); n=len(r)
    if n==0:return np.nan
    v=float((1+r).prod()); return float(v**(252/n)-1) if v>0 else -1.0

def _ols(y,x):
    z=pd.concat([pd.to_numeric(y,errors='coerce'),pd.to_numeric(x,errors='coerce')],axis=1).dropna()
    if len(z)<50:return {'n':len(z),'alpha_ann':np.nan,'beta':np.nan,'r2':np.nan}
    yy=z.iloc[:,0].to_numpy(float); xx=z.iloc[:,1].to_numpy(float); X=np.c_[np.ones(len(xx)),xx]
    b=np.linalg.lstsq(X,yy,rcond=None)[0]; pred=X@b; sst=((yy-yy.mean())**2).sum(); ssr=((yy-pred)**2).sum()
    return {'n':len(z),'alpha_ann':float(b[0]*252),'beta':float(b[1]),'r2':float(1-ssr/sst) if sst>0 else np.nan}

def _dd(navdf):
    d=navdf.copy(); d['date']=pd.to_datetime(d.date); nav=(1+pd.to_numeric(d.net_return,errors='coerce').fillna(0)).cumprod(); peak=nav.cummax(); dd=nav/peak-1
    ti=int(dd.idxmin()); trough=d.loc[ti,'date']; pi=int(nav.loc[:ti].idxmax()); peak_date=d.loc[pi,'date']; peak_val=float(nav.iloc[pi]); rec=None
    later=np.where(nav.iloc[ti+1:].to_numpy()>=peak_val)[0]
    if len(later): rec=d.iloc[ti+1+int(later[0])].date
    return {'max_drawdown':float(dd.min()),'peak_date':str(pd.Timestamp(peak_date).date()),'trough_date':str(pd.Timestamp(trough).date()),'recovery_date':str(pd.Timestamp(rec).date()) if rec is not None else None,'sessions_peak_to_trough':int(ti-pi),'sessions_to_recovery':int((ti+1+int(later[0])-pi)) if len(later) else None}

def _load_benches(ws,cfg,needed):
    p0=json.loads((ws/cfg['phase0_summary']).read_text()); src=Path(p0['source_manifest']['source_v12_root']); hold=pd.Timestamp(cfg['holdout_start']); start=pd.Timestamp(cfg['portfolio_start'])
    pcfg=p3v.load_cfg(ws); surf=p3v.load_market(ws,src,pcfg,needed); spy=p3v._load_benchmark(src,cfg['source_spy_benchmark'],'SPY',hold); qqq=p3v._load_benchmark(src,cfg['source_qqq_benchmark'],'QQQ',hold)
    market=p3v.prepare_market(surf,spy,start,hold,int(cfg['risk_lookback_sessions'])); return p3v.benchmark_returns(src,pcfg,market,spy,qqq)

def build_phase3aa(ws:Path):
    cfg=_cfg(ws); hold=pd.Timestamp(cfg['holdout_start']); z=json.loads((ws/cfg['phase3z_summary']).read_text());
    if z.get('status')!='PASS': raise RuntimeError('Phase3Z must PASS before final review')
    navs={c:pd.read_csv(ws/cfg[f'phase3z_nav_{c}bps']) for c in (20,40,60)}
    for d in navs.values(): d['date']=pd.to_datetime(d.date).dt.normalize()
    if any((d.date>=hold).any() for d in navs.values()): raise RuntimeError('HOLDOUT BREACH in Phase3Z NAV')
    lin=pd.read_csv(ws/cfg['phase3z_lineage']); needed=set(lin.ticker.astype(str).str.upper())
    benches=_load_benches(ws,cfg,needed); base=navs[20].set_index('date').net_return
    annual=[]; alpha_year=[]; yearly_ops=[]
    for y in range(2019,2025):
        d=navs[20][navs[20].date.dt.year.eq(y)].copy(); sr=d.set_index('date').net_return
        row={'year':y,'strategy_return':float((1+sr).prod()-1),'turnover':float(d.turnover.sum()),'median_holdings':float(d.holdings.median()),'median_max_name_weight':float(d.max_name_weight.median())}
        for k,b in benches.items():
            br=b.reindex(sr.index).fillna(0); row[f'{k.lower()}_return']=float((1+br).prod()-1); row[f'excess_vs_{k.lower()}']=row['strategy_return']-row[f'{k.lower()}_return']; alpha_year.append({'year':y,'benchmark':k,**_ols(sr,br)})
        annual.append(row)
        den=float(d.entry_exit_notional.sum()+d.resize_notional.sum()); yearly_ops.append({'year':y,'annualized_turnover':float(d.turnover.sum()*252/max(1,len(d))),'entry_exit_share':float(d.entry_exit_notional.sum()/den) if den else 0,'resize_share':float(d.resize_notional.sum()/den) if den else 0})
    annual=pd.DataFrame(annual); alpha_year=pd.DataFrame(alpha_year); yearly_ops=pd.DataFrame(yearly_ops)
    dd=_dd(navs[20]); full_alpha=pd.DataFrame([{'benchmark':k,**_ols(base,b.reindex(base.index))} for k,b in benches.items()])
    pos_logs=np.log1p(annual.strategy_return.clip(lower=-.999999)); pos=pos_logs.clip(lower=0); dep=float(pos.max()/pos.sum()) if pos.sum()>0 else np.nan
    files=[cfg['phase0_summary'],cfg['phase3z_summary'],cfg['phase3z_nav_20bps'],cfg['phase3z_nav_40bps'],cfg['phase3z_nav_60bps'],cfg['phase3z_lineage'],'config/v13_phase3z.toml','config/v13_phase3aa.toml','src/alpha_engine_v13/roundtrip_resize_hysteresis.py','src/alpha_engine_v13/active_alpha_persistent_portfolio.py','src/alpha_engine_v13/economic_portfolio_closure.py','src/alpha_engine_v13/final_prehodout_review.py']
    manifest=[]
    for rel in files:
        p=ws/rel
        if not p.exists(): raise FileNotFoundError(p)
        manifest.append({'path':rel,'sha256':_sha(p),'bytes':p.stat().st_size})
    freeze_id=hashlib.sha256(''.join(x['sha256'] for x in manifest).encode()).hexdigest()
    amap=full_alpha.set_index('benchmark').to_dict('index'); m60=z['metrics']['60bps']; gates=[]
    def add(t,ok,val,rule,blocking=True):gates.append({'test':t,'status':'PASS' if bool(ok) else 'FAIL','blocking':blocking,'value':val,'rule':rule})
    add('PHASE3Z_PASS',True,z.get('build'),'Phase3Z structural portfolio must already pass')
    add('FINAL_HOLDOUT_NOT_LOADED',max(d.date.max() for d in navs.values())<hold,str(max(d.date.max() for d in navs.values()).date()),'all reviewed NAV dates < 2025-01-01')
    add('FULL_PERIOD_ALPHA_POSITIVE_VS_SPY_QQQ_UEW',all(amap.get(k,{}).get('alpha_ann',-9)>0 for k in ['SPY','QQQ','UEW']),amap,'annualized pre-holdout regression alpha >0 vs all three benchmarks')
    add('60BPS_STILL_BEATS_SPY',m60['cagr']>m60['spy_cagr'],{'strategy':m60['cagr'],'spy':m60['spy_cagr']},'fixed frozen candidate beats SPY even at 60bps')
    add('ANNUAL_BEHAVIOR_RECORDED',True,annual.to_dict('records'),'year-by-year behavior is diagnostic, not a requirement to win every year',False)
    add('DRAWDOWN_RECORDED',True,dd,'drawdown is recorded, not tuned away',False)
    add('NO_SINGLE_POSITIVE_YEAR_DOMINANCE',not np.isfinite(dep) or dep<.85,dep,'diagnostic: no single positive calendar year contributes >=85% of positive log return',False)
    status='PASS' if all(g['status']=='PASS' for g in gates if g['blocking']) else 'FAIL'
    out=ws/'outputs'; annual.to_csv(out/'v13_phase3aa_annual_returns.csv',index=False); alpha_year.to_csv(out/'v13_phase3aa_annual_alpha.csv',index=False); yearly_ops.to_csv(out/'v13_phase3aa_yearly_turnover.csv',index=False); full_alpha.to_csv(out/'v13_phase3aa_full_alpha.csv',index=False); pd.DataFrame(gates).to_csv(out/'v13_phase3aa_gate.csv',index=False)
    freeze={'build':BUILD,'freeze_id':freeze_id,'holdout_start':cfg['holdout_start'],'phase3z_build':z.get('build'),'phase3z_design':z.get('design'),'files':manifest}
    (out/'v13_phase3aa_freeze_manifest.json').write_text(json.dumps(freeze,indent=2)); summary={'status':status,'phase':'V13-P3AA','build':BUILD,'name':cfg['name'],'objective':cfg['objective'],'holdout_used':False,'policy_changed':False,'predictor_retrained':False,'phase3z_metrics':z['metrics'],'full_period_alpha':full_alpha.to_dict('records'),'annual_returns':annual.to_dict('records'),'yearly_turnover':yearly_ops.to_dict('records'),'drawdown_episode':dd,'single_positive_year_dependency':dep,'freeze_id':freeze_id,'gate':gates,'readiness':'READY_TO_OPEN_CODE_BLINDED_2025_PLUS_ONCE' if status=='PASS' else 'PREHOLDOUT_REVIEW_NOT_FROZEN','next':'If PASS: make no further pre-2025 changes. Open the code-blinded 2025+ holdout exactly once using this freeze manifest.'}
    (out/'v13_phase3aa_summary.json').write_text(json.dumps(summary,indent=2,default=str)); return summary
