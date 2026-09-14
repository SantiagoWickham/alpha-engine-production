from __future__ import annotations

import json, math, tomllib
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from alpha_engine_v13 import economic_portfolio_closure as p3v

BUILD = "V13_P3Y_ACTIVE_ALPHA_PERSISTENT_PORTFOLIO_2026-09-13"
HORIZONS = p3v.HORIZONS
EVAL_FOLDS = p3v.EVAL_FOLDS

@dataclass(frozen=True)
class Cfg:
    p: dict

def load_cfg(workspace:Path)->Cfg:
    with (workspace/"config"/"v13_phase3y.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase3y"])

def _date(s):
    return pd.to_datetime(s,errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")

def _ticker(s):
    return s.astype(str).str.upper().str.replace(".","-",regex=False).str.strip()

def load_inputs(workspace:Path,cfg:Cfg):
    hold=pd.Timestamp(cfg.p["holdout_start"])
    p0=json.loads((workspace/cfg.p["phase0_summary"]).read_text(encoding="utf-8"))
    p2u=json.loads((workspace/cfg.p["phase2u_summary"]).read_text(encoding="utf-8"))
    src=p0.get("source_manifest",{}).get("source_v12_root")
    if p0.get("status")!="PASS" or not src: raise RuntimeError("Phase0 contract invalid")
    s=pd.read_parquet(workspace/cfg.p["phase2u_oof_scores"])
    need={"signal_date","ticker","horizon_sessions","fold","score"}
    if not need.issubset(s.columns): raise RuntimeError(f"Phase2U OOF schema missing: {sorted(need-set(s.columns))}")
    s["signal_date"]=_date(s.signal_date); s["ticker"]=_ticker(s.ticker); s["horizon_sessions"]=pd.to_numeric(s.horizon_sessions,errors="raise").astype(int)
    if (s.signal_date>=hold).any(): raise RuntimeError("HOLDOUT BREACH in Phase2U OOF")
    t=pd.read_parquet(workspace/cfg.p["research_targets"]); t["signal_date"]=_date(t.signal_date); t["ticker"]=_ticker(t.ticker); t=t[t.signal_date<hold].copy()
    for h in HORIZONS:
        req=[f"target_end_date_{h}d",f"target_resolved_{h}d",f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]
        miss=[c for c in req if c not in t.columns]
        if miss: raise RuntimeError(f"research targets missing h={h}: {miss}")
        t[f"target_end_date_{h}d"]=_date(t[f"target_end_date_{h}d"])
        bad=t[f"target_end_date_{h}d"].isna() | (t[f"target_end_date_{h}d"]>=hold)
        t.loc[bad,f"target_resolved_{h}d"]=False
        for c in [f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]: t.loc[bad,c]=np.nan
    return p0,p2u,Path(src),s.sort_values(["signal_date","ticker","horizon_sessions"]),t.sort_values(["signal_date","ticker"])

def _winsor(x,lo=.01,hi=.99):
    a=np.asarray(x,float); ok=np.isfinite(a)
    if ok.sum()<20:return a
    q=np.nanquantile(a[ok],[lo,hi]); return np.clip(a,q[0],q[1])

def _fit_iso(score,y):
    x=np.asarray(score,float); z=np.asarray(y,float); ok=np.isfinite(x)&np.isfinite(z); x=x[ok]; z=_winsor(z[ok])
    if len(x)<500 or np.unique(x).size<10:
        m=float(np.nanmean(z)) if len(z) else 0.0; sd=float(np.nanstd(z)) if len(z)>1 else 1e-4
        return (lambda q,m=m:np.full(len(q),m,float)),max(sd,1e-6)
    iso=IsotonicRegression(increasing=True,out_of_bounds="clip").fit(x,z); pred=iso.predict(x); sd=max(float(np.nanstd(z-pred)),1e-6)
    return (lambda q,m=iso:m.predict(np.asarray(q,float))),sd

def _train_rows(scores,targets,h,before,cfg):
    s=scores[(scores.horizon_sessions.eq(h))&(scores.signal_date<before)][["signal_date","ticker","score"]]
    cols=["signal_date","ticker",f"target_end_date_{h}d",f"target_resolved_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]
    x=s.merge(targets[cols],on=["signal_date","ticker"],how="inner",validate="one_to_one")
    x=x[x[f"target_resolved_{h}d"].fillna(False)&x[f"target_end_date_{h}d"].notna()&(x[f"target_end_date_{h}d"]<before)].copy()
    wuew=float(cfg.p["active_weight_uew"]); wspy=float(cfg.p["active_weight_spy"]); wqqq=float(cfg.p["active_weight_qqq"])
    x["active_total"]=wuew*pd.to_numeric(x[f"excess_uew_{h}d"],errors="coerce")+wspy*pd.to_numeric(x[f"excess_spy_{h}d"],errors="coerce")+wqqq*pd.to_numeric(x[f"excess_qqq_{h}d"],errors="coerce")
    x["active_day"]=x.active_total/float(h)
    return x

def _skill(tr,h):
    if len(tr)<1000:return 0.0
    q=tr[pd.to_numeric(tr.score,errors="coerce")>=.80]
    return float(pd.to_numeric(q.active_day,errors="coerce").mean()*20.0) if len(q)>=100 else 0.0

def _softmax(skills,floor,temp):
    a=np.array([skills.get(h,0.0) for h in HORIZONS],float); med=np.nanmedian(a); mad=np.nanmedian(np.abs(a-med)); scale=max(1e-6,1.4826*mad)
    z=np.clip((a-med)/scale,-4,4)*float(temp); z-=np.max(z); e=np.exp(z); e/=e.sum(); e=np.maximum(e,float(floor)); e/=e.sum()
    return {h:float(v) for h,v in zip(HORIZONS,e)}

def build_active_advisor(scores,targets,cfg):
    out=[]; rel=[]; infl=[]
    for fold,start,end in EVAL_FOLDS:
        pieces=[]; skills={}; calibrators={}
        for h in HORIZONS:
            tr=_train_rows(scores,targets,h,start,cfg); skills[h]=_skill(tr,h); f,sd=_fit_iso(tr.score,tr.active_day); calibrators[h]=(f,sd,len(tr))
        prior=_softmax(skills,float(cfg.p["horizon_weight_floor"]),float(cfg.p["horizon_skill_temperature"]))
        for h in HORIZONS:
            rel.append({"fold":fold,"horizon_sessions":h,"prior_active_skill_20eq":skills[h],"prior_reliability_weight":prior[h],"training_rows":calibrators[h][2]})
            q=scores[(scores.fold.eq(fold))&scores.horizon_sessions.eq(h)&(scores.signal_date>=start)&(scores.signal_date<end)][["signal_date","ticker","score"]].copy()
            f,sd,_=calibrators[h]; q[f"active_{h}"]=f(q.score.to_numpy(float)); q[f"sigma_{h}"]=sd; q[f"score_{h}"]=q.score; q=q.drop(columns="score"); pieces.append(q)
        z=pieces[0]
        for q in pieces[1:]: z=z.merge(q,on=["signal_date","ticker"],how="outer",validate="one_to_one")
        sm=np.column_stack([pd.to_numeric(z.get(f"score_{h}"),errors="coerce") for h in HORIZONS]); am=np.column_stack([pd.to_numeric(z.get(f"active_{h}"),errors="coerce") for h in HORIZONS]); sig=np.column_stack([pd.to_numeric(z.get(f"sigma_{h}"),errors="coerce") for h in HORIZONS])
        pw=np.array([prior[h] for h in HORIZONS],float)[None,:]; ok=np.isfinite(sm)&np.isfinite(am); dyn=pw*(.25+np.abs(sm-.5)); dyn=np.where(ok,dyn,0.0); den=dyn.sum(1,keepdims=True); w=np.divide(dyn,den,out=np.zeros_like(dyn),where=den>0)
        z["expected_active_per_session"]=np.nansum(w*am,axis=1); z["uncertainty_per_session"]=np.sqrt(np.nansum((w*sig)**2,axis=1)); z["positive_active_horizon_share"]=np.nansum(w*(am>0),axis=1); z["effective_horizon_sessions"]=np.nansum(w*np.array(HORIZONS,float)[None,:],axis=1); z["fold"]=fold
        for j,h in enumerate(HORIZONS): z[f"horizon_weight_{h}d"]=w[:,j]; infl.append({"fold":fold,"horizon_sessions":h,"mean_weight":float(np.nanmean(w[:,j])),"median_weight":float(np.nanmedian(w[:,j]))})
        keep=["signal_date","ticker","fold","expected_active_per_session","uncertainty_per_session","positive_active_horizon_share","effective_horizon_sessions"]+[f"horizon_weight_{h}d" for h in HORIZONS]; out.append(z[keep])
    return pd.concat(out,ignore_index=True).sort_values(["signal_date","ticker"]),pd.DataFrame(rel),pd.DataFrame(infl)

def build_plans(advisor,market,cfg):
    out={}; vol=market["vol"]; rtc=float(cfg.p["base_round_trip_cost_bps"])/10000.0; one=rtc/2; minshare=float(cfg.p["minimum_positive_horizon_share"])
    for d,g in advisor.groupby("signal_date",sort=False):
        q=g.set_index("ticker"); h=pd.to_numeric(q.effective_horizon_sessions,errors="coerce").clip(lower=5,upper=252); a=pd.to_numeric(q.expected_active_per_session,errors="coerce"); atot=a*h; share=pd.to_numeric(q.positive_active_horizon_share,errors="coerce")
        if pd.Timestamp(d) in vol.index: vv=pd.to_numeric(vol.loc[pd.Timestamp(d)].reindex(q.index),errors="coerce")
        else: vv=pd.Series(np.nan,index=q.index)
        med=float(np.nanmedian(vv.to_numpy(float))) if np.isfinite(vv.to_numpy(float)).any() else .02; vv=vv.fillna(med).clip(lower=max(.003,med*.25)); varh=vv.pow(2)*h
        eligible=np.isfinite(atot)&np.isfinite(varh)&(atot>0)&(share>=minshare); raw=(atot.where(eligible,0.0)/varh).replace([np.inf,-np.inf],0.0).fillna(0.0).clip(lower=0)
        gamma=max(1.0,float(raw.sum())); desired=raw/gamma
        plan={}
        for t in q.index:
            alpha=float(atot.get(t,np.nan)); vh=float(varh.get(t,np.nan)); dw=float(desired.get(t,0.0)); entry=bool(np.isfinite(alpha) and alpha>rtc and share.get(t,0)>=minshare and dw>0)
            curvature=gamma*vh if np.isfinite(vh) and vh>0 else np.nan; band=float(one/curvature) if np.isfinite(curvature) and curvature>0 else 1.0
            plan[str(t)]={"desired":dw,"alpha_total":alpha,"entry_ok":entry,"band":max(0.0,band)}
        out[pd.Timestamp(d)]=plan
    return out

def _economic_target(cur,plan):
    names=set(cur)|set(plan); des={}
    for t in names:
        c=float(cur.get(t,0.0)); p=plan.get(t); 
        if p is None: des[t]=0.0; continue
        alpha=float(p.get("alpha_total",np.nan)); target=max(0.0,float(p.get("desired",0.0))); band=max(0.0,float(p.get("band",0.0)))
        if c<=1e-14:
            v=target if bool(p.get("entry_ok",False)) else 0.0
        else:
            if not np.isfinite(alpha) or alpha<=0: v=0.0
            elif target<=0: v=c
            else:
                delta=target-c
                if abs(delta)<=band: v=c
                else: v=c+np.sign(delta)*(abs(delta)-band)
        if v>1e-14: des[t]=float(max(0.0,v))
    sm=sum(des.values())
    if sm>1.0+1e-12: des={t:w/sm for t,w in des.items()}
    return des

def simulate_persistent(plans,market,terminals,start,end,round_trip_bps):
    cal=market["calendar"][(market["calendar"]>=start)&(market["calendar"]<end)]; ret=market["returns"]; pres=market["execution_presence"]
    w={}; cash=1.0; nav=1.0; pending=None; rows=[]; one=float(round_trip_bps)/2/10000.0
    for d in cal:
        d=pd.Timestamp(d); prev=nav
        if w:
            rr=ret.loc[d] if d in ret.index else pd.Series(dtype=float); vals={t:v*(1+(float(rr.get(t,0.0)) if np.isfinite(rr.get(t,np.nan)) else 0.0)) for t,v in w.items()}; total=cash+sum(vals.values())
            if total>0: w={t:v/total for t,v in vals.items() if v>1e-14}; cash=cash/total; nav*=max(0.0,float(total))
        meta={"requested":0.0,"executed":0.0,"blocked":0.0,"deviation":0.0,"blocked_names":0}; turnover=0.0; cost=0.0; entry_exit=0.0; resize=0.0
        if pending is not None:
            old=dict(w); econ=_economic_target(old,pending); actual,meta=p3v.partial_target(old,econ,pres.loc[d] if d in pres.index else pd.Series(dtype=bool)); oldcash=cash; newcash=max(0.0,1.0-sum(actual.values())); turnover=.5*(meta["executed"]+abs(newcash-oldcash)); cost=one*meta["executed"]; nav*=max(0.0,1.0-cost)
            for t in set(old)|set(actual):
                a=float(old.get(t,0)); b=float(actual.get(t,0)); ch=abs(b-a)
                if (a<=1e-14)!=(b<=1e-14): entry_exit+=ch
                else: resize+=ch
            w=actual; cash=newcash; pending=None
        for t in [t for t in list(w) if terminals.get(t)==d]: cash+=w.pop(t)
        if d in plans: pending=plans[d]
        rows.append({"date":d,"nav":nav,"net_return":nav/prev-1 if prev>0 else -1.0,"turnover":turnover,"entry_exit_notional":entry_exit,"resize_notional":resize,"cost_fraction":cost,"holdings":len(w),"cash_weight":cash,"max_name_weight":max(w.values()) if w else 0.0,"requested":meta["requested"],"executed":meta["executed"],"blocked":meta["blocked"],"deviation":meta["deviation"]})
    return pd.DataFrame(rows)

def _ols(y,x):
    z=pd.concat([pd.to_numeric(y,errors="coerce"),pd.to_numeric(x,errors="coerce")],axis=1).dropna(); yy=z.iloc[:,0].to_numpy(float); xx=z.iloc[:,1].to_numpy(float)
    if len(z)<50:return {"n":len(z),"alpha_ann":np.nan,"beta":np.nan,"r2":np.nan}
    X=np.column_stack([np.ones(len(xx)),xx]); b=np.linalg.lstsq(X,yy,rcond=None)[0]; pred=X@b; sst=float(np.sum((yy-yy.mean())**2)); ssr=float(np.sum((yy-pred)**2)); return {"n":len(z),"alpha_ann":float(b[0]*252),"beta":float(b[1]),"r2":float(1-ssr/sst) if sst>0 else np.nan}

def _turnover(d):
    den=float(d.entry_exit_notional.sum()+d.resize_notional.sum()); yrs=len(d)/252
    return {"annual_turnover":float(d.turnover.sum()/yrs),"entry_exit_share":float(d.entry_exit_notional.sum()/den) if den>0 else 0.0,"resize_share":float(d.resize_notional.sum()/den) if den>0 else 0.0}

def _conviction_diagnostics(advisor,targets):
    x=advisor[["signal_date","ticker","expected_active_per_session","uncertainty_per_session"]].copy(); x["conviction"]=x.expected_active_per_session/x.uncertainty_per_session.replace(0,np.nan)
    z=x.merge(targets[["signal_date","ticker","target_resolved_20d","target_end_date_20d","excess_uew_20d","excess_spy_20d","excess_qqq_20d"]],on=["signal_date","ticker"],how="inner")
    z=z[z.target_resolved_20d.fillna(False)&z.excess_uew_20d.notna()].copy(); z["decile"]=np.ceil(z.groupby("signal_date").conviction.rank(method="first",pct=True)*10).clip(1,10)
    return z.groupby("decile",as_index=False).agg(rows=("ticker","size"),median_conviction=("conviction","median"),mean_excess_uew_20d=("excess_uew_20d","mean"),mean_excess_spy_20d=("excess_spy_20d","mean"),mean_excess_qqq_20d=("excess_qqq_20d","mean"))

def _universe_lineage(market,start,hold):
    e=market["research_eligible"].loc[(market["research_eligible"].index>=start)&(market["research_eligible"].index<hold)]
    rows=[]
    for t in e.columns:
        ds=e.index[e[t].fillna(False)]
        if len(ds): rows.append({"ticker":t,"first_eligible":ds.min(),"last_eligible":ds.max(),"eligible_sessions":len(ds),"eligible_at_start":bool(e.iloc[0].get(t,False)),"eligible_at_end":bool(e.iloc[-1].get(t,False))})
    x=pd.DataFrame(rows); summary={"tickers_ever_eligible":int(len(x)),"eligible_at_start":int(x.eligible_at_start.sum()) if len(x) else 0,"eligible_at_end":int(x.eligible_at_end.sum()) if len(x) else 0,"entries_after_start":int((~x.eligible_at_start).sum()) if len(x) else 0,"exits_before_end":int((~x.eligible_at_end).sum()) if len(x) else 0}
    return x,summary

def build_phase3y(workspace:Path)->dict:
    cfg=load_cfg(workspace); p0,p2u,source,scores,targets=load_inputs(workspace,cfg); advisor,rel,infl=build_active_advisor(scores,targets,cfg)
    hold=pd.Timestamp(cfg.p["holdout_start"]); start=pd.Timestamp(cfg.p["portfolio_start"]); needed=set(advisor.ticker.unique())
    # Reuse Phase3V market loader; point it at equivalent config keys through a lightweight adapter.
    pcfg=p3v.load_cfg(workspace); surface=p3v.load_market(workspace,source,pcfg,needed); spy=p3v._load_benchmark(source,pcfg.p["source_spy_benchmark"],"SPY",hold); qqq=p3v._load_benchmark(source,pcfg.p["source_qqq_benchmark"],"QQQ",hold); market=p3v.prepare_market(surface,spy,start,hold,int(cfg.p["risk_lookback_sessions"])); benches=p3v.benchmark_returns(source,pcfg,market,spy,qqq); terminals=p3v.load_terminals(source,pcfg)
    plans=build_plans(advisor,market,cfg); base=float(cfg.p["base_round_trip_cost_bps"]); stress=float(cfg.p["stress_round_trip_cost_bps"])
    d20=simulate_persistent(plans,market,terminals,start,hold,base); d40=simulate_persistent(plans,market,terminals,start,hold,stress); m20=p3v._metrics(d20,benches,start,hold); m40=p3v._metrics(d40,benches,start,hold); p20=p3v._period_metrics(d20,benches,base); p40=p3v._period_metrics(d40,benches,stress)
    sr20=d20.set_index("date").net_return; beta=[]
    for k,b in benches.items(): beta.append({"benchmark":k,**_ols(sr20,b.reindex(sr20.index))})
    beta=pd.DataFrame(beta); turn=_turnover(d20); conv=_conviction_diagnostics(advisor,targets); lineage,lineage_summary=_universe_lineage(market,start,hold)
    # Compare with Phase3X baseline if present.
    base_summary={}; bp=workspace/cfg.p["phase3x_summary"]
    if bp.exists(): base_summary=json.loads(bp.read_text(encoding="utf-8"))
    baseline_turn=float(base_summary.get("headline",{}).get("annual_turnover",np.nan)); baseline_cagr=float(base_summary.get("headline",{}).get("cagr_20bps",np.nan))
    base_uew_alpha=np.nan; bb=workspace/cfg.p["phase3x_beta"]
    if bb.exists():
        bdf=pd.read_csv(bb); q=bdf[bdf.benchmark.astype(str).str.upper().eq("UEW")]
        if len(q): base_uew_alpha=float(q.iloc[0].alpha_ann)
    beta_map=beta.set_index("benchmark").to_dict(orient="index")
    top=conv[conv.decile>=9]; mid=conv[(conv.decile>=4)&(conv.decile<=7)]
    gates=[]
    def add(t,ok,val,rule,blocking=True): gates.append({"test":t,"status":"PASS" if bool(ok) else "FAIL","blocking":blocking,"value":val,"rule":rule})
    add("FINAL_HOLDOUT_NOT_LOADED",scores.signal_date.max()<hold,str(scores.signal_date.max().date()),"all OOF scores < 2025-01-01")
    add("NO_PREDICTOR_RETRAINING",True,"Phase2U OOF reused","portfolio translation only; Phase2U untouched")
    add("ACTIVE_ALPHA_VS_SPY",beta_map.get("SPY",{}).get("alpha_ann",-9)>0,beta_map.get("SPY",{}),"annualized regression alpha vs SPY > 0")
    add("ACTIVE_ALPHA_VS_UEW",beta_map.get("UEW",{}).get("alpha_ann",-9)>0,beta_map.get("UEW",{}),"annualized regression alpha vs dynamic eligible-universe EW > 0")
    red=turn["annual_turnover"]/baseline_turn if np.isfinite(baseline_turn) and baseline_turn>0 else np.nan
    add("PERSISTENCE_REDUCES_TURNOVER",np.isfinite(red) and red<=float(cfg.p["turnover_reduction_target_fraction"]),{"new":turn["annual_turnover"],"baseline":baseline_turn,"fraction":red},"cost-aware persistence should remove at least 40% of baseline turnover")
    add("STRESS_40BPS_REMAINS_POSITIVE",m40.get("cagr",-9)>0,m40.get("cagr"),"fixed active-alpha persistent policy remains profitable at 40bps")
    add("EXECUTION_BLOCKING_ACCEPTABLE",m20.get("execution_blocked_rate",9)<=float(cfg.p["maximum_execution_blocked_rate"]),m20.get("execution_blocked_rate"),"blocked requested notional <=5%")
    topuew=float(top.mean_excess_uew_20d.mean()) if len(top) else np.nan; miduew=float(mid.mean_excess_uew_20d.mean()) if len(mid) else np.nan
    add("CONVICTION_TOP_TAIL_ADDS_UEW_ALPHA",np.isfinite(topuew) and topuew>0 and (not np.isfinite(miduew) or topuew>miduew),{"top_deciles_9_10":topuew,"middle_deciles_4_7":miduew},"strong active conviction must outperform UEW and middle conviction")
    add("UNIVERSE_LINEAGE_RECORDED",len(lineage)>0,lineage_summary,"dynamic universe entries/exits recorded before holdout",False)
    add("BASELINE_UEW_ALPHA_REFERENCE",True,{"baseline_alpha_ann":base_uew_alpha,"new_alpha_ann":beta_map.get("UEW",{}).get("alpha_ann")},"diagnostic comparison to Phase3X",False)
    status="PASS" if all(g["status"]=="PASS" for g in gates if g["blocking"]) else "FAIL"
    out=workspace/"outputs"; out.mkdir(exist_ok=True)
    d20.to_csv(out/"v13_phase3y_nav_20bps.csv",index=False); d40.to_csv(out/"v13_phase3y_nav_40bps.csv",index=False); pd.concat([p20,p40],ignore_index=True).to_csv(out/"v13_phase3y_period_metrics.csv",index=False); beta.to_csv(out/"v13_phase3y_beta_attribution.csv",index=False); pd.DataFrame([turn]).to_csv(out/"v13_phase3y_turnover.csv",index=False); conv.to_csv(out/"v13_phase3y_conviction_curve.csv",index=False); rel.to_csv(out/"v13_phase3y_horizon_reliability.csv",index=False); infl.to_csv(out/"v13_phase3y_horizon_influence.csv",index=False); lineage.to_csv(out/"v13_phase3y_universe_lineage.csv",index=False); pd.DataFrame(gates).to_csv(out/"v13_phase3y_gate.csv",index=False)
    summary={"status":status,"phase":"V13-P3Y","build":BUILD,"name":cfg.p["name"],"objective":cfg.p["objective"],"holdout_used":False,"predictor_retrained":False,"design":{"ranking_target":"active alpha: 50% UEW excess + 25% SPY excess + 25% QQQ excess","entry":"expected active alpha over effective horizon must exceed round-trip cost","holding":"existing position may persist while expected active alpha remains positive","resize":"transaction-cost/risk no-trade band via soft threshold","top_n":False,"fixed_holding_period":False,"per_name_cap":False},"full_period_20bps":m20,"full_period_40bps":m40,"beta_attribution":beta.to_dict(orient="records"),"turnover":turn,"baseline_comparison":{"phase3x_cagr_20bps":baseline_cagr,"phase3x_turnover":baseline_turn,"phase3x_uew_alpha_ann":base_uew_alpha},"universe_lineage":lineage_summary,"gate":gates,"readiness":"READY_FOR_FINAL_PREHOLDOUT_REVIEW" if status=="PASS" else "PORTFOLIO_TRANSLATION_NEEDS_REVIEW_BEFORE_HOLDOUT","next":"Do not open 2025+. If PASS, review active-alpha attribution and universe lineage once, then freeze. If FAIL, diagnose which structural objective failed; do not retune Phase2U or 2021-2022."}
    (out/"v13_phase3y_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    return summary
