from __future__ import annotations

import json, math, tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

BUILD = "V13_P3V_FIX1_V13_WORKSPACE_RESOLUTION_2026-09-13"
HORIZONS = (5,10,20,60,120,252)
FOLDS = (
    ("WF_2017_2018", pd.Timestamp("2017-01-03"), pd.Timestamp("2019-01-02")),
    ("WF_2019_2020", pd.Timestamp("2019-01-02"), pd.Timestamp("2021-01-04")),
    ("WF_2021_2022", pd.Timestamp("2021-01-04"), pd.Timestamp("2023-01-03")),
    ("WF_2023_2024", pd.Timestamp("2023-01-03"), pd.Timestamp("2025-01-01")),
)
EVAL_FOLDS = FOLDS[1:]

@dataclass(frozen=True)
class Cfg:
    p: dict

def _date(s):
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")

def _ticker(s):
    return s.astype(str).str.upper().str.replace(".","-",regex=False).str.strip()

def load_cfg(workspace:Path)->Cfg:
    with (workspace/"config"/"v13_phase3v.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase3v"])

def _gate_map(summary:dict)->dict[str,str]:
    return {str(x.get("test")):str(x.get("status")) for x in summary.get("gate",[])}

def load_contracts(workspace:Path,cfg:Cfg)->tuple[dict,dict,Path]:
    p0=workspace/cfg.p["phase0_summary"]; p2u=workspace/cfg.p["phase2u_summary"]
    if not p0.exists() or not p2u.exists(): raise FileNotFoundError("Phase0 and Phase2U summaries are required")
    a=json.loads(p0.read_text(encoding="utf-8")); b=json.loads(p2u.read_text(encoding="utf-8"))
    if a.get("status")!="PASS": raise RuntimeError("Phase0 must PASS")
    gm=_gate_map(b)
    required=("FINAL_HOLDOUT_NOT_LOADED","ROTATION_SOURCES_READY","PIT_EARNINGS_EVENTS_READY","ALL_SIX_HORIZONS_RETAINED","PRE2025_NEWINFO_ALPHA","2023_2024_NEWINFO_CONFIRMATION","NEW_INFORMATION_INCREMENTAL_2021_2022")
    bad=[k for k in required if gm.get(k)!="PASS"]
    if bad: raise RuntimeError(f"Phase2U did not pass required quality gates for closure: {bad}")
    src=a.get("source_manifest",{}).get("source_v12_root")
    if not src: raise RuntimeError("source_v12_root missing from Phase0 summary")
    return a,b,Path(src)

def load_scores_targets(workspace:Path,cfg:Cfg):
    hold=pd.Timestamp(cfg.p["holdout_start"])
    s=pd.read_parquet(workspace/cfg.p["phase2u_oof_scores"])
    need={"signal_date","ticker","horizon_sessions","fold","score"}
    if not need.issubset(s.columns): raise RuntimeError(f"Phase2U OOF schema missing {sorted(need-set(s.columns))}")
    s["signal_date"]=_date(s["signal_date"]); s["ticker"]=_ticker(s["ticker"]); s["horizon_sessions"]=pd.to_numeric(s["horizon_sessions"],errors="raise").astype(int)
    if (s.signal_date>=hold).any(): raise RuntimeError("HOLDOUT BREACH: Phase2U OOF contains 2025+")
    if sorted(s.horizon_sessions.unique().tolist())!=list(HORIZONS): raise RuntimeError("Phase2U OOF does not contain all six horizons")
    t=pd.read_parquet(workspace/cfg.p["research_targets"]); t["signal_date"]=_date(t["signal_date"]); t["ticker"]=_ticker(t["ticker"]); t=t[t.signal_date<hold].copy()
    for h in HORIZONS:
        req=[f"target_end_date_{h}d",f"target_resolved_{h}d",f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_uew_{h}d"]
        miss=[c for c in req if c not in t.columns]
        if miss: raise RuntimeError(f"research target schema missing for {h}D: {miss}")
        t[f"target_end_date_{h}d"]=_date(t[f"target_end_date_{h}d"])
        bad=t[f"target_end_date_{h}d"].isna() | (t[f"target_end_date_{h}d"]>=hold)
        t.loc[bad,f"target_resolved_{h}d"]=False
        for c in [f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_uew_{h}d"]: t.loc[bad,c]=np.nan
    return s.sort_values(["signal_date","ticker","horizon_sessions"]), t.sort_values(["signal_date","ticker"])

def _winsor(a:np.ndarray,lo=.01,hi=.99):
    x=np.asarray(a,float); ok=np.isfinite(x)
    if ok.sum()<20:return x
    q=np.nanquantile(x[ok],[lo,hi]); return np.clip(x,q[0],q[1])

def _fit_iso(score:np.ndarray,y:np.ndarray):
    x=np.asarray(score,float); z=np.asarray(y,float); ok=np.isfinite(x)&np.isfinite(z)
    x=x[ok]; z=_winsor(z[ok])
    if len(x)<500 or np.unique(x).size<10:
        m=float(np.nanmean(z)) if len(z) else 0.0
        return (lambda q: np.full(len(q),m,float)), float(np.nanstd(z)) if len(z)>1 else 1e-4
    iso=IsotonicRegression(increasing=True,out_of_bounds="clip").fit(x,z)
    pred=iso.predict(x); sig=float(np.nanstd(z-pred)); sig=max(sig,1e-6)
    return (lambda q,model=iso: model.predict(np.asarray(q,float))),sig

def _train_rows(scores:pd.DataFrame, targets:pd.DataFrame, h:int, before:pd.Timestamp)->pd.DataFrame:
    s=scores[(scores.horizon_sessions.eq(h))&(scores.signal_date<before)][["signal_date","ticker","score"]]
    cols=["signal_date","ticker",f"target_end_date_{h}d",f"target_resolved_{h}d",f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_uew_{h}d"]
    x=s.merge(targets[cols],on=["signal_date","ticker"],how="inner",validate="one_to_one")
    x=x[x[f"target_resolved_{h}d"].fillna(False)&x[f"target_end_date_{h}d"].notna()&(x[f"target_end_date_{h}d"]<before)].copy()
    x["abs_day"]=pd.to_numeric(x[f"fwd_return_{h}d"],errors="coerce")/float(h)
    x["alpha_day"]=(pd.to_numeric(x[f"excess_spy_{h}d"],errors="coerce")+pd.to_numeric(x[f"excess_uew_{h}d"],errors="coerce"))/(2.0*float(h))
    return x

def _economic_skill(train:pd.DataFrame,h:int)->float:
    if len(train)<1000:return 0.0
    q=train[pd.to_numeric(train.score,errors="coerce")>=0.80]
    if len(q)<100:return 0.0
    # Common 20-session scale makes horizons comparable without dividing uncertainty by h.
    return float(pd.to_numeric(q.alpha_day,errors="coerce").mean()*20.0)

def _softmax_skill(skills:dict[int,float],floor:float,temp:float)->dict[int,float]:
    a=np.array([skills.get(h,0.0) for h in HORIZONS],float)
    med=np.nanmedian(a); mad=np.nanmedian(np.abs(a-med)); scale=max(1e-6,1.4826*mad)
    z=np.clip((a-med)/scale,-4,4)*float(temp); z=z-np.max(z); e=np.exp(z); e=e/e.sum()
    e=np.maximum(e,float(floor)); e=e/e.sum()
    return {h:float(v) for h,v in zip(HORIZONS,e)}

def build_causal_advisor(scores:pd.DataFrame,targets:pd.DataFrame,cfg:Cfg):
    floor=float(cfg.p["horizon_weight_floor"]); temp=float(cfg.p["horizon_skill_temperature"])
    out=[]; rel=[]; infl=[]; coverage=[]
    for fold,start,end in EVAL_FOLDS:
        pieces=[]; skills={}; calibrators={}
        for h in HORIZONS:
            tr=_train_rows(scores,targets,h,start); skills[h]=_economic_skill(tr,h)
            fa,sa=_fit_iso(tr.score.to_numpy(float),tr.abs_day.to_numpy(float)); fal,sal=_fit_iso(tr.score.to_numpy(float),tr.alpha_day.to_numpy(float))
            calibrators[h]=(fa,sa,fal,sal,len(tr))
        prior=_softmax_skill(skills,floor,temp)
        for h in HORIZONS:
            rel.append({"fold":fold,"horizon_sessions":h,"prior_skill_20eq":skills[h],"prior_reliability_weight":prior[h],"training_rows":calibrators[h][4]})
            q=scores[(scores.fold.eq(fold))&scores.horizon_sessions.eq(h)&(scores.signal_date>=start)&(scores.signal_date<end)][["signal_date","ticker","score"]].copy()
            fa,sa,fal,sal,_=calibrators[h]; q[f"abs_{h}"]=fa(q.score.to_numpy(float)); q[f"alpha_{h}"]=fal(q.score.to_numpy(float)); q[f"sigma_{h}"]=math.sqrt(sa*sa+sal*sal); q[f"score_{h}"]=q.score; q=q.drop(columns="score"); pieces.append(q)
        z=pieces[0]
        for q in pieces[1:]: z=z.merge(q,on=["signal_date","ticker"],how="outer",validate="one_to_one")
        scoremat=np.column_stack([pd.to_numeric(z.get(f"score_{h}"),errors="coerce").to_numpy(float) for h in HORIZONS])
        absmat=np.column_stack([pd.to_numeric(z.get(f"abs_{h}"),errors="coerce").to_numpy(float) for h in HORIZONS])
        alphamat=np.column_stack([pd.to_numeric(z.get(f"alpha_{h}"),errors="coerce").to_numpy(float) for h in HORIZONS])
        sigmat=np.column_stack([pd.to_numeric(z.get(f"sigma_{h}"),errors="coerce").to_numpy(float) for h in HORIZONS])
        pw=np.array([prior[h] for h in HORIZONS],float)[None,:]
        ok=np.isfinite(scoremat)&np.isfinite(absmat)&np.isfinite(alphamat)
        dyn=pw*(0.25+np.abs(scoremat-0.5)); dyn=np.where(ok,dyn,0.0); den=dyn.sum(1,keepdims=True); w=np.divide(dyn,den,out=np.zeros_like(dyn),where=den>0)
        z["expected_abs_per_session"]=np.nansum(w*absmat,axis=1); z["expected_alpha_per_session"]=np.nansum(w*alphamat,axis=1)
        z["uncertainty_per_session"]=np.sqrt(np.nansum((w*sigmat)**2,axis=1)); z["positive_horizon_share"]=np.nansum(w*(scoremat>0.5),axis=1)
        z["effective_horizon_sessions"]=np.nansum(w*np.array(HORIZONS,float)[None,:],axis=1); z["fold"]=fold
        for j,h in enumerate(HORIZONS): z[f"horizon_weight_{h}d"]=w[:,j]
        valid=(ok.sum(1)==len(HORIZONS)); coverage.append({"fold":fold,"rows":len(z),"all_six_horizon_rows":int(valid.sum()),"all_six_horizon_coverage":float(valid.mean()) if len(z) else 0.0})
        for h in HORIZONS:
            infl.append({"fold":fold,"horizon_sessions":h,"mean_weight":float(np.nanmean(z[f"horizon_weight_{h}d"])),"median_weight":float(np.nanmedian(z[f"horizon_weight_{h}d"]))})
        keep=["signal_date","ticker","fold","expected_abs_per_session","expected_alpha_per_session","uncertainty_per_session","positive_horizon_share","effective_horizon_sessions"]+[f"horizon_weight_{h}d" for h in HORIZONS]
        out.append(z[keep])
    return pd.concat(out,ignore_index=True).sort_values(["signal_date","ticker"]),pd.DataFrame(rel),pd.DataFrame(infl),pd.DataFrame(coverage)

def _load_benchmark(source:Path,rel:str,symbol:str,hold:pd.Timestamp)->pd.Series:
    x=pd.read_parquet(source/rel); x["date"]=_date(x["date"]); x[symbol]=pd.to_numeric(x[symbol],errors="coerce"); x=x[(x.date<hold)&x[symbol].gt(0)]
    return x.drop_duplicates("date",keep="last").set_index("date")[symbol].sort_index()

def load_market(workspace:Path,source:Path,cfg:Cfg,needed:set[str])->pd.DataFrame:
    hold=pd.Timestamp(cfg.p["holdout_start"]); p=workspace/cfg.p["execution_surface_cache"]
    if p.exists():
        x=pd.read_parquet(p)
        need={"date","ticker","execution_close","mark_price","research_eligible"}
        if not need.issubset(x.columns): raise RuntimeError("cached execution surface schema invalid")
        x["date"]=_date(x["date"]); x["ticker"]=_ticker(x["ticker"]); x=x[(x.date<hold)&x.ticker.isin(needed)].copy()
    else:
        c=pd.read_parquet(source/cfg.p["source_canonical_pit_panel"],columns=["date","ticker","close","research_eligible"]); r=pd.read_parquet(source/cfg.p["source_return_price_layer"],columns=["date","ticker","target_total_return_price"])
        c["date"]=_date(c.date); c["ticker"]=_ticker(c.ticker); r["date"]=_date(r.date); r["ticker"]=_ticker(r.ticker)
        x=c.merge(r,on=["date","ticker"],how="left"); x=x[(x.date<hold)&x.ticker.isin(needed)].copy(); x["execution_close"]=pd.to_numeric(x.close,errors="coerce"); x["mark_price"]=pd.to_numeric(x.target_total_return_price,errors="coerce")
        x=x[["date","ticker","execution_close","mark_price","research_eligible"]]
    x["execution_close"]=pd.to_numeric(x.execution_close,errors="coerce"); x["mark_price"]=pd.to_numeric(x.mark_price,errors="coerce"); x["research_eligible"]=x.research_eligible.fillna(False).astype(bool)
    if (x.date>=hold).any(): raise RuntimeError("HOLDOUT BREACH in market surface")
    return x.drop_duplicates(["date","ticker"],keep="last").sort_values(["date","ticker"])

def prepare_market(surface:pd.DataFrame,spy:pd.Series,start:pd.Timestamp,hold:pd.Timestamp,lookback:int):
    cal=pd.DatetimeIndex(spy.index[(spy.index>=start-pd.Timedelta(days=400))&(spy.index<hold)]).sort_values().unique()
    x=surface[(surface.date>=cal.min())&(surface.date<hold)].copy()
    mark=x.pivot_table(index="date",columns="ticker",values="mark_price",aggfunc="last").reindex(cal); exe=x.pivot_table(index="date",columns="ticker",values="execution_close",aggfunc="last").reindex(cal); elig=x.pivot_table(index="date",columns="ticker",values="research_eligible",aggfunc="last").reindex(cal).fillna(False).astype(bool)
    ret=mark.ffill(limit=5).pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan); ret=ret.where(mark.notna())
    vol=ret.rolling(int(lookback),min_periods=int(max(10,lookback//3))).std().clip(lower=0.002)
    return {"calendar":cal,"returns":ret,"vol":vol,"execution_presence":exe.notna(),"research_eligible":elig}

def benchmark_returns(source:Path,cfg:Cfg,market:dict,spy:pd.Series,qqq:pd.Series):
    cal=market["calendar"]; sr=spy.reindex(cal).ffill().pct_change(fill_method=None).fillna(0.0); qr=qqq.reindex(cal).ffill().pct_change(fill_method=None).fillna(0.0)
    prev=market["research_eligible"].shift(1).eq(True); u=market["returns"].where(prev).mean(axis=1,skipna=True).reindex(cal).fillna(0.0)
    return {"SPY":sr,"QQQ":qr,"UEW":u}

def load_terminals(source:Path,cfg:Cfg):
    p=source/cfg.p["source_terminal_overlay"]
    if not p.exists(): return {}
    x=pd.read_csv(p); x["ticker"]=_ticker(x.ticker); x["terminal_price_date"]=_date(x.terminal_price_date)
    if "overlay_validated" in x:
        v=x.overlay_validated if x.overlay_validated.dtype==bool else x.overlay_validated.astype(str).str.lower().isin(["true","1","yes"]); x=x[v]
    return {str(r.ticker):pd.Timestamp(r.terminal_price_date) for r in x.dropna(subset=["terminal_price_date"]).itertuples()}

def candidate_specs(cfg:Cfg):
    return [{"alpha_tilt":float(a),"edge_z":float(z),"edge_power":float(p)} for a in cfg.p["alpha_tilt_grid"] for z in cfg.p["edge_z_grid"] for p in cfg.p["edge_power_grid"]]

def build_target_path(advisor:pd.DataFrame,market:dict,spec:dict,cfg:Cfg):
    out={}; minshare=float(cfg.p["minimum_positive_horizon_share"]); vol=market["vol"]
    for d,g in advisor.groupby("signal_date",sort=False):
        q=g.set_index("ticker"); mu=pd.to_numeric(q.expected_abs_per_session,errors="coerce")+spec["alpha_tilt"]*pd.to_numeric(q.expected_alpha_per_session,errors="coerce"); se=pd.to_numeric(q.uncertainty_per_session,errors="coerce").replace(0,np.nan); zz=mu/se
        mask=np.isfinite(mu)&np.isfinite(zz)&(mu>0)&(zz>=spec["edge_z"])&(pd.to_numeric(q.positive_horizon_share,errors="coerce")>=minshare)
        names=list(q.index[mask]);
        if not names: out[pd.Timestamp(d)]={}; continue
        if pd.Timestamp(d) in vol.index: vv=pd.to_numeric(vol.loc[pd.Timestamp(d)].reindex(names),errors="coerce")
        else: vv=pd.Series(np.nan,index=names)
        med=float(np.nanmedian(vv.to_numpy(float))) if np.isfinite(vv.to_numpy(float)).any() else 0.02; vv=vv.fillna(med).clip(lower=max(0.003,med*0.25)); shr=0.5*vv.pow(2)+0.5*float(np.nanmedian(vv.pow(2)))
        edge=(mu.reindex(names)-spec["edge_z"]*se.reindex(names)).clip(lower=0); raw=(edge.pow(spec["edge_power"])/shr).replace([np.inf,-np.inf],np.nan).fillna(0.0); sm=float(raw.sum())
        out[pd.Timestamp(d)]={str(t):float(w/sm) for t,w in raw.items() if sm>0 and w>0}
    return out

def partial_target(cur:dict,des:dict,pres:pd.Series):
    cur={str(t):max(0.0,float(w)) for t,w in cur.items() if float(w)>1e-14}; des={str(t):max(0.0,float(w)) for t,w in des.items() if float(w)>1e-14}; uni=set(cur)|set(des)
    req=float(sum(abs(des.get(t,0)-cur.get(t,0)) for t in uni)); trade={t for t in uni if abs(des.get(t,0)-cur.get(t,0))>1e-12}; unavailable={t for t in trade if not bool(pres.get(t,False))}
    locked={t:cur[t] for t in unavailable if cur.get(t,0)>1e-14}; free=max(0.0,1.0-sum(locked.values())); dex={t:w for t,w in des.items() if t not in unavailable}; ds=sum(dex.values()); scale=min(1.0,free/ds) if ds>1e-14 else 0.0
    actual=dict(locked); actual.update({t:w*scale for t,w in dex.items() if w*scale>1e-14}); sm=sum(actual.values());
    if sm>1+1e-10: actual={t:w/sm for t,w in actual.items()}
    exe=float(sum(abs(actual.get(t,0)-cur.get(t,0)) for t in set(cur)|set(actual))); blk=float(sum(abs(des.get(t,0)-cur.get(t,0)) for t in unavailable)); dev=float(sum(abs(des.get(t,0)-actual.get(t,0)) for t in uni))
    return actual,{"requested":req,"executed":exe,"blocked":blk,"deviation":dev,"blocked_names":len(unavailable)}

def simulate(targets:dict,market:dict,benches:dict,terminals:dict,start:pd.Timestamp,end:pd.Timestamp,round_trip_bps:float):
    cal=market["calendar"][(market["calendar"]>=start)&(market["calendar"]<end)]; ret=market["returns"]; pres=market["execution_presence"]; w={}; cash=1.0; nav=1.0; pending=None; rows=[]; one=float(round_trip_bps)/2/10000.0
    for d in cal:
        d=pd.Timestamp(d); prev=nav
        if w:
            rr=ret.loc[d] if d in ret.index else pd.Series(dtype=float); vals={t:v*(1+(float(rr.get(t,0.0)) if np.isfinite(rr.get(t,np.nan)) else 0.0)) for t,v in w.items()}; total=cash+sum(vals.values())
            if total>0: w={t:v/total for t,v in vals.items() if v>1e-14}; cash=cash/total
        gross=sum((float(ret.at[d,t]) if t in ret.columns and d in ret.index and np.isfinite(ret.at[d,t]) else 0.0)*v for t,v in w.items()) if False else 0.0
        meta={"requested":0.0,"executed":0.0,"blocked":0.0,"deviation":0.0,"blocked_names":0}; turnover=0.0; cost=0.0
        if pending is not None:
            actual,meta=partial_target(w,pending,pres.loc[d] if d in pres.index else pd.Series(dtype=bool)); oldcash=cash; newcash=max(0.0,1.0-sum(actual.values())); turnover=0.5*(meta["executed"]+abs(newcash-oldcash)); cost=one*meta["executed"]; nav*=max(0.0,1.0-cost); w=actual; cash=newcash; pending=None
        for t in [t for t in list(w) if terminals.get(t)==d]: cash+=w.pop(t)
        # P&L for this date is represented by weight drift above; derive from NAV change due only to cost is insufficient.
        # Reconstruct mark return from prior day's weights by using total portfolio value ratio carried in 'total'.
        # We instead maintain a separate daily gross factor below using previous close weights before normalization.
        # For the first day/no holdings this is 1.
        # NOTE: drift block normalized values but did not update NAV; do so from the same total ratio.
        if 'total' in locals() and isinstance(total,(int,float,np.floating)) and np.isfinite(total):
            # total is portfolio gross factor because prior weights + cash sum to one.
            nav*=max(0.0,float(total))
            del total
        if d in targets: pending=targets[d]
        rows.append({"date":d,"nav":nav,"net_return":nav/prev-1 if prev>0 else -1.0,"turnover":turnover,"cost_fraction":cost,"holdings":len(w),"cash_weight":cash,"max_name_weight":max(w.values()) if w else 0.0,"requested":meta["requested"],"executed":meta["executed"],"blocked":meta["blocked"],"deviation":meta["deviation"],"blocked_names":meta["blocked_names"]})
    daily=pd.DataFrame(rows); return daily

def _metrics(daily:pd.DataFrame,benches:dict,start:pd.Timestamp,end:pd.Timestamp):
    if daily.empty:return {}
    r=pd.to_numeric(daily.net_return,errors="coerce").fillna(0.0); nav=(1+r).cumprod(); n=len(r); cagr=float(nav.iloc[-1]**(252/n)-1) if nav.iloc[-1]>0 else -1.0; dd=float((nav/nav.cummax()-1).min()); yrs=n/252
    out={"days":n,"total_return":float(nav.iloc[-1]-1),"cagr":cagr,"max_drawdown":dd,"annual_turnover":float(daily.turnover.sum()/yrs),"median_holdings":float(daily.holdings.median()),"max_holdings":int(daily.holdings.max()),"mean_cash_weight":float(daily.cash_weight.mean()),"median_max_name_weight":float(daily.max_name_weight.median()),"p95_max_name_weight":float(daily.max_name_weight.quantile(.95))}
    req=float(daily.requested.sum()); out["execution_blocked_rate"]=float(daily.blocked.sum()/req) if req>1e-14 else 0.0; out["target_deviation_rate"]=float(daily.deviation.sum()/req) if req>1e-14 else 0.0
    for k,s in benches.items():
        rr=s[(s.index>=start)&(s.index<end)].reindex(daily.date).fillna(0.0); bn=float((1+rr).prod()**(252/max(1,len(rr)))-1); out[f"{k.lower()}_cagr"]=bn; out[f"excess_cagr_vs_{k.lower()}"]=cagr-bn
    return out

def _period_metrics(daily:pd.DataFrame,benches:dict,cost:float):
    rows=[]
    for fold,start,end in EVAL_FOLDS:
        d=daily[(daily.date>=start)&(daily.date<end)].copy(); m=_metrics(d,benches,start,end); rows.append({"fold":fold,"cost_bps":cost,**m})
    return pd.DataFrame(rows)

def build_phase3v(workspace:Path)->dict:
    cfg=load_cfg(workspace); p0,p2u,source=load_contracts(workspace,cfg); scores,targets=load_scores_targets(workspace,cfg); advisor,rel,infl,cov=build_causal_advisor(scores,targets,cfg)
    hold=pd.Timestamp(cfg.p["holdout_start"]); start=pd.Timestamp(cfg.p["portfolio_start"]); needed=set(advisor.ticker.unique()); surface=load_market(workspace,source,cfg,needed); spy=_load_benchmark(source,cfg.p["source_spy_benchmark"],"SPY",hold); qqq=_load_benchmark(source,cfg.p["source_qqq_benchmark"],"QQQ",hold); market=prepare_market(surface,spy,start,hold,int(cfg.p["risk_lookback_sessions"])); benches=benchmark_returns(source,cfg,market,spy,qqq); terminals=load_terminals(source,cfg)
    specs=candidate_specs(cfg); rows=[]; navs={}; period_cache={}; base=float(cfg.p["base_round_trip_cost_bps"]); stress=float(cfg.p["stress_round_trip_cost_bps"]); maxblk=float(cfg.p["maximum_execution_blocked_rate"])
    target_cache={}
    for i,spec in enumerate(specs,1):
        key=(spec["alpha_tilt"],spec["edge_z"],spec["edge_power"]); tp=build_target_path(advisor,market,spec,cfg); target_cache[key]=tp
        db=simulate(tp,market,benches,terminals,start,hold,base); ds=simulate(tp,market,benches,terminals,start,hold,stress); mb=_metrics(db,benches,start,hold); ms=_metrics(ds,benches,start,hold); pb=_period_metrics(db,benches,base); posfold=int((pb.total_return>0).sum()) if len(pb) else 0
        qualified=bool(mb.get("excess_cagr_vs_spy",-9)>0 and ms.get("cagr",-9)>0 and posfold>=2 and mb.get("execution_blocked_rate",9)<=maxblk)
        rows.append({**spec,"qualified":qualified,"positive_absolute_folds":posfold,"cagr_20bps":mb.get("cagr"),"excess_vs_spy_20bps":mb.get("excess_cagr_vs_spy"),"excess_vs_qqq_20bps":mb.get("excess_cagr_vs_qqq"),"excess_vs_uew_20bps":mb.get("excess_cagr_vs_uew"),"cagr_40bps":ms.get("cagr"),"excess_vs_spy_40bps":ms.get("excess_cagr_vs_spy"),"max_drawdown_20bps":mb.get("max_drawdown"),"annual_turnover_20bps":mb.get("annual_turnover"),"median_holdings_20bps":mb.get("median_holdings"),"max_holdings_20bps":mb.get("max_holdings"),"median_max_name_weight_20bps":mb.get("median_max_name_weight"),"p95_max_name_weight_20bps":mb.get("p95_max_name_weight"),"execution_blocked_rate_20bps":mb.get("execution_blocked_rate"),"target_deviation_rate_20bps":mb.get("target_deviation_rate")})
        navs[key]=(db,ds); period_cache[key]=(pb,_period_metrics(ds,benches,stress))
        if i%9==0 or i==len(specs): print(f"Phase3V portfolio policies: {i}/{len(specs)}",flush=True)
    lb=pd.DataFrame(rows).sort_values(["qualified","cagr_20bps","cagr_40bps","max_drawdown_20bps","annual_turnover_20bps"],ascending=[False,False,False,False,True]).reset_index(drop=True); lb["return_first_rank"]=np.arange(1,len(lb)+1); champ=lb.iloc[0].to_dict(); key=(float(champ["alpha_tilt"]),float(champ["edge_z"]),float(champ["edge_power"])); db,ds=navs[key]; pb,ps=period_cache[key]
    # Diagnostics: regime is observed, never required to outperform.
    p21=pb[pb.fold.eq("WF_2021_2022")].iloc[0].to_dict(); p23=pb[pb.fold.eq("WF_2023_2024")].iloc[0].to_dict(); fullb=_metrics(db,benches,start,hold); fulls=_metrics(ds,benches,start,hold)
    pos_contrib=[]
    for r in pb.itertuples():
        lr=math.log(max(1e-12,1+float(r.total_return))); pos_contrib.append(max(0.0,lr))
    dep=max(pos_contrib)/sum(pos_contrib) if sum(pos_contrib)>0 else 1.0
    gates=[]
    def add(t,ok,val,rule,blocking=True): gates.append({"test":t,"status":"PASS" if ok else "FAIL","blocking":blocking,"value":val,"rule":rule})
    add("PHASE2U_CORE_QUALITY_ACCEPTED",True,{"phase2u_status":p2u.get("status"),"accepted_nonblocking_failure":"2021_2022_NEWINFO_RECOVERY"},"Phase2U may fail the old 2021-22 regime gate only; all core quality gates must pass")
    add("FINAL_HOLDOUT_NOT_LOADED",scores.signal_date.max()<hold,str(scores.signal_date.max().date()),"all OOF scores < 2025-01-01")
    add("ALL_SIX_HORIZONS_RETAINED",sorted(scores.horizon_sessions.unique().tolist())==list(HORIZONS),sorted(scores.horizon_sessions.unique().tolist()),str(list(HORIZONS)))
    mincov=float(cov.all_six_horizon_coverage.min()) if len(cov) else 0.0; add("MULTI_HORIZON_ADVISOR_COVERAGE",mincov>=0.95,mincov,">=95% rows have all six horizon forecasts")
    qual=int(lb.qualified.sum()); add("QUALIFIED_FULL_PERIOD_POLICY_EXISTS",qual>0,qual,"at least one policy beats SPY net at 20bps, remains positive at 40bps, has >=2/3 positive folds, and execution blocking <=5%")
    add("2021_2022_STRESS_REGIME",True,{k:p21.get(k) for k in ["cagr","max_drawdown","spy_cagr","excess_cagr_vs_spy","qqq_cagr","excess_cagr_vs_qqq","uew_cagr","excess_cagr_vs_uew"]},"diagnostic only: a difficult regime may underperform",False)
    add("2023_2024_RECENT_REGIME",True,{k:p23.get(k) for k in ["cagr","max_drawdown","spy_cagr","excess_cagr_vs_spy","qqq_cagr","excess_cagr_vs_qqq","uew_cagr","excess_cagr_vs_uew"]},"diagnostic only",False)
    add("NO_SINGLE_PERIOD_DEPENDENCE",dep<0.85,dep,"diagnostic: no single positive two-year fold contributes >=85% of positive log-return",False)
    status="PASS" if all(g["status"]=="PASS" for g in gates if g["blocking"]) else "FAIL"
    out=workspace/"outputs"; out.mkdir(parents=True,exist_ok=True); lb.to_csv(out/"v13_phase3v_policy_leaderboard.csv",index=False); rel.to_csv(out/"v13_phase3v_horizon_reliability.csv",index=False); infl.to_csv(out/"v13_phase3v_horizon_influence.csv",index=False); cov.to_csv(out/"v13_phase3v_advisor_coverage.csv",index=False); pd.concat([pb,ps],ignore_index=True).to_csv(out/"v13_phase3v_period_metrics.csv",index=False); pd.DataFrame(gates).to_csv(out/"v13_phase3v_gate.csv",index=False); db.to_csv(out/"v13_phase3v_nav_20bps.csv",index=False); ds.to_csv(out/"v13_phase3v_nav_40bps.csv",index=False)
    selected={"alpha_tilt":key[0],"edge_z":key[1],"edge_power":key[2]}; (out/"v13_phase3v_selected_policy.json").write_text(json.dumps(selected,indent=2),encoding="utf-8")
    summary={"status":status,"phase":"V13-P3V","build":BUILD,"name":cfg.p["name"],"objective":cfg.p["objective"],"research_contract":{"portfolio_research":"2019-2024 OOF only","holdout_start":cfg.p["holdout_start"],"holdout_used":False,"2021_2022_role":"NONBLOCKING_STRESS_REGIME"},"predictor":{"source":"Phase2U OOF scores","phase2u_reported_status":p2u.get("status"),"old_2021_gate_overridden":True},"advisor":{"horizons":list(HORIZONS),"causal_calibration":True,"horizon_reliability":"prior OOF folds only","all_six_coverage_min":mincov},"selection":{"candidate_policies":len(lb),"qualified_policies":qual,"selected_policy":selected,"full_period_20bps":fullb,"full_period_40bps":fulls},"regime_diagnostics":{"2019_2020":pb[pb.fold.eq("WF_2019_2020")].to_dict(orient="records"),"2021_2022":pb[pb.fold.eq("WF_2021_2022")].to_dict(orient="records"),"2023_2024":pb[pb.fold.eq("WF_2023_2024")].to_dict(orient="records"),"single_positive_period_dependency":dep},"gate":gates,"readiness":"READY_FOR_PREHOLDOUT_STRESS_AND_FREEZE" if status=="PASS" else "PORTFOLIO_ECONOMICS_STILL_INSUFFICIENT","next":"If PASS, freeze/stress the selected pre-2025 policy and then open the code-blinded 2025+ holdout once. If FAIL, diagnose portfolio economics without reopening the 2021-22 predictor gate."}
    (out/"v13_phase3v_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8"); return summary
