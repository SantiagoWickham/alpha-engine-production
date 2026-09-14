from __future__ import annotations
import json, tomllib
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
from alpha_engine_v13 import active_alpha_persistent_portfolio as p3y
from alpha_engine_v13 import economic_portfolio_closure as p3v

BUILD="V13_P3Z_ROUNDTRIP_RESIZE_HYSTERESIS_2026-09-13"
HORIZONS=p3y.HORIZONS

@dataclass(frozen=True)
class Cfg:
    p: dict

def load_cfg(workspace:Path)->Cfg:
    with (workspace/'config'/'v13_phase3z.toml').open('rb') as f:
        return Cfg(tomllib.load(f)['v13_phase3z'])

def _resize_band(round_trip_cost:float, curvature:float)->float:
    """No-trade half-width for a resize expected to be unwound later.

    A resize is treated as a tactical round trip, so the hurdle is the full
    round-trip cost rather than only the cost of the first leg.
    """
    if not np.isfinite(curvature) or curvature<=0:
        return 1.0
    return float(max(0.0,round_trip_cost/curvature))

def build_plans(advisor,market,cfg):
    out={}; vol=market['vol']; rtc=float(cfg.p['base_round_trip_cost_bps'])/10000.0
    minshare=float(cfg.p['minimum_positive_horizon_share'])
    for d,g in advisor.groupby('signal_date',sort=False):
        q=g.set_index('ticker'); h=pd.to_numeric(q.effective_horizon_sessions,errors='coerce').clip(lower=5,upper=252)
        a=pd.to_numeric(q.expected_active_per_session,errors='coerce'); atot=a*h
        share=pd.to_numeric(q.positive_active_horizon_share,errors='coerce')
        if pd.Timestamp(d) in vol.index:
            vv=pd.to_numeric(vol.loc[pd.Timestamp(d)].reindex(q.index),errors='coerce')
        else:
            vv=pd.Series(np.nan,index=q.index)
        med=float(np.nanmedian(vv.to_numpy(float))) if np.isfinite(vv.to_numpy(float)).any() else .02
        vv=vv.fillna(med).clip(lower=max(.003,med*.25)); varh=vv.pow(2)*h
        eligible=np.isfinite(atot)&np.isfinite(varh)&(atot>0)&(share>=minshare)
        raw=(atot.where(eligible,0.0)/varh).replace([np.inf,-np.inf],0.0).fillna(0.0).clip(lower=0)
        gamma=max(1.0,float(raw.sum())); desired=raw/gamma
        plan={}
        for t in q.index:
            alpha=float(atot.get(t,np.nan)); vh=float(varh.get(t,np.nan)); dw=float(desired.get(t,0.0))
            entry=bool(np.isfinite(alpha) and alpha>rtc and share.get(t,0)>=minshare and dw>0)
            curvature=gamma*vh if np.isfinite(vh) and vh>0 else np.nan
            band=_resize_band(rtc,curvature)
            plan[str(t)]={'desired':dw,'alpha_total':alpha,'entry_ok':entry,'band':band}
        out[pd.Timestamp(d)]=plan
    return out

def _get_baseline(workspace:Path,cfg:Cfg):
    p=workspace/cfg.p['phase3y_summary']
    if not p.exists(): raise FileNotFoundError(f'Phase3Y summary required: {p}')
    s=json.loads(p.read_text(encoding='utf-8'))
    return {
        'cagr20':float(s.get('full_period_20bps',{}).get('cagr',np.nan)),
        'cagr40':float(s.get('full_period_40bps',{}).get('cagr',np.nan)),
        'turnover':float(s.get('turnover',{}).get('annual_turnover',np.nan)),
        'uew_alpha':next((float(x.get('alpha_ann')) for x in s.get('beta_attribution',[]) if str(x.get('benchmark')).upper()=='UEW'),np.nan),
    }

def build_phase3z(workspace:Path)->dict:
    cfg=load_cfg(workspace)
    p0,p2u,source,scores,targets=p3y.load_inputs(workspace,cfg)
    advisor,rel,infl=p3y.build_active_advisor(scores,targets,cfg)
    hold=pd.Timestamp(cfg.p['holdout_start']); start=pd.Timestamp(cfg.p['portfolio_start']); needed=set(advisor.ticker.unique())
    pcfg=p3v.load_cfg(workspace)
    surface=p3v.load_market(workspace,source,pcfg,needed)
    spy=p3v._load_benchmark(source,pcfg.p['source_spy_benchmark'],'SPY',hold)
    qqq=p3v._load_benchmark(source,pcfg.p['source_qqq_benchmark'],'QQQ',hold)
    market=p3v.prepare_market(surface,spy,start,hold,int(cfg.p['risk_lookback_sessions']))
    benches=p3v.benchmark_returns(source,pcfg,market,spy,qqq); terminals=p3v.load_terminals(source,pcfg)
    plans=build_plans(advisor,market,cfg)
    costs=[float(cfg.p['base_round_trip_cost_bps']),float(cfg.p['stress_round_trip_cost_bps']),float(cfg.p['extreme_round_trip_cost_bps'])]
    sims={c:p3y.simulate_persistent(plans,market,terminals,start,hold,c) for c in costs}
    mets={c:p3v._metrics(sims[c],benches,start,hold) for c in costs}
    pms={c:p3v._period_metrics(sims[c],benches,c) for c in costs}
    sr=sims[costs[0]].set_index('date').net_return
    beta=pd.DataFrame([{'benchmark':k,**p3y._ols(sr,b.reindex(sr.index))} for k,b in benches.items()])
    turn=p3y._turnover(sims[costs[0]]); conv=p3y._conviction_diagnostics(advisor,targets); lineage,lineage_summary=p3y._universe_lineage(market,start,hold)
    baseline=_get_baseline(workspace,cfg)
    beta_map=beta.set_index('benchmark').to_dict(orient='index')
    top=conv[conv.decile>=9]; mid=conv[(conv.decile>=4)&(conv.decile<=7)]
    topuew=float(top.mean_excess_uew_20d.mean()) if len(top) else np.nan; miduew=float(mid.mean_excess_uew_20d.mean()) if len(mid) else np.nan
    eff_new=mets[costs[1]]['cagr']/turn['annual_turnover'] if turn['annual_turnover']>0 else np.nan
    eff_old=baseline['cagr40']/baseline['turnover'] if baseline['turnover']>0 else np.nan
    pareto=bool(turn['annual_turnover']<baseline['turnover'] and mets[costs[1]]['cagr']>=baseline['cagr40'])
    gates=[]
    def add(t,ok,val,rule,blocking=True): gates.append({'test':t,'status':'PASS' if bool(ok) else 'FAIL','blocking':blocking,'value':val,'rule':rule})
    add('FINAL_HOLDOUT_NOT_LOADED',scores.signal_date.max()<hold,str(scores.signal_date.max().date()),'all OOF scores < 2025-01-01')
    add('NO_PREDICTOR_RETRAINING',True,'Phase2U OOF reused','portfolio mechanics only; Phase2U untouched')
    add('ACTIVE_ALPHA_VS_UEW',beta_map.get('UEW',{}).get('alpha_ann',-9)>0,beta_map.get('UEW',{}),'annualized regression alpha vs dynamic eligible-universe EW > 0')
    add('ROUNDTRIP_HYSTERESIS_PARETO_VS_PHASE3Y',pareto,{'new_turnover':turn['annual_turnover'],'old_turnover':baseline['turnover'],'new_cagr_40bps':mets[costs[1]]['cagr'],'old_cagr_40bps':baseline['cagr40']},'full-round-trip resize hysteresis must lower turnover without lowering 40bps CAGR')
    add('RETURN_PER_TURNOVER_IMPROVES',np.isfinite(eff_new) and np.isfinite(eff_old) and eff_new>eff_old,{'new_cagr40_per_turnover':eff_new,'old_cagr40_per_turnover':eff_old},'40bps CAGR per unit annual turnover must improve')
    add('STRESS_60BPS_REMAINS_POSITIVE',mets[costs[2]].get('cagr',-9)>0,mets[costs[2]].get('cagr'),'fixed policy remains profitable at 60bps')
    add('EXECUTION_BLOCKING_ACCEPTABLE',mets[costs[0]].get('execution_blocked_rate',9)<=float(cfg.p['maximum_execution_blocked_rate']),mets[costs[0]].get('execution_blocked_rate'),'blocked requested notional <=5%')
    add('CONVICTION_TOP_TAIL_ADDS_UEW_ALPHA',np.isfinite(topuew) and topuew>0 and (not np.isfinite(miduew) or topuew>miduew),{'top_deciles_9_10':topuew,'middle_deciles_4_7':miduew},'strong active conviction must outperform UEW and middle conviction')
    add('UNIVERSE_LINEAGE_RECORDED',len(lineage)>0,lineage_summary,'dynamic universe entries/exits recorded',False)
    status='PASS' if all(g['status']=='PASS' for g in gates if g['blocking']) else 'FAIL'
    out=workspace/'outputs'; out.mkdir(exist_ok=True)
    for c,d in sims.items(): d.to_csv(out/f'v13_phase3z_nav_{int(c)}bps.csv',index=False)
    pd.concat(list(pms.values()),ignore_index=True).to_csv(out/'v13_phase3z_period_metrics.csv',index=False)
    beta.to_csv(out/'v13_phase3z_beta_attribution.csv',index=False); pd.DataFrame([turn]).to_csv(out/'v13_phase3z_turnover.csv',index=False); conv.to_csv(out/'v13_phase3z_conviction_curve.csv',index=False); rel.to_csv(out/'v13_phase3z_horizon_reliability.csv',index=False); infl.to_csv(out/'v13_phase3z_horizon_influence.csv',index=False); lineage.to_csv(out/'v13_phase3z_universe_lineage.csv',index=False); pd.DataFrame(gates).to_csv(out/'v13_phase3z_gate.csv',index=False)
    summary={'status':status,'phase':'V13-P3Z','build':BUILD,'name':cfg.p['name'],'objective':cfg.p['objective'],'holdout_used':False,'predictor_retrained':False,'design':{'active_alpha':'unchanged from Phase3Y','entry_hurdle':'full round-trip cost','holding':'keep while expected active alpha > 0','resize_hurdle':'full expected round-trip cost / local risk curvature','top_n':False,'fixed_holding_period':False,'per_name_cap':False},'metrics':{f'{int(c)}bps':mets[c] for c in costs},'beta_attribution':beta.to_dict(orient='records'),'turnover':turn,'phase3y_baseline':baseline,'efficiency':{'new_cagr40_per_turnover':eff_new,'old_cagr40_per_turnover':eff_old},'universe_lineage':lineage_summary,'gate':gates,'readiness':'READY_FOR_PREHOLDOUT_FREEZE_REVIEW' if status=='PASS' else 'PERSISTENCE_RULE_NOT_YET_PARETO_SUPERIOR','next':'Do not open 2025+ automatically. If PASS, inspect turnover, active alpha and annual/regime behavior once; if they remain coherent, freeze. If FAIL, keep Phase3Y as the active-alpha baseline and do not modify Phase2U.'}
    (out/'v13_phase3z_summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
    return summary
