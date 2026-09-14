from __future__ import annotations

import json, math, tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

BUILD = "V13_P3R_FAST_CACHED_EXECUTION_HORIZON_SPARSITY_2026-09-12"
HORIZONS = (5,10,20,60,120,252)

@dataclass(frozen=True)
class Cfg:
    p: dict

def _date(s):
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")

def _ticker(s):
    return s.astype(str).str.upper().str.strip()

def load_cfg(workspace: Path) -> Cfg:
    with (workspace/"config"/"v13_phase3_fast.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase3_fast"])

def _load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))

def source_root(workspace: Path, cfg: Cfg) -> Path:
    p0=_load_json(workspace/cfg.p["phase0_summary"])
    if p0.get("status")!="PASS": raise RuntimeError("Phase 0 must PASS")
    return Path(p0["source_manifest"]["source_v12_root"])

def _rank_architecture(evidence: pd.DataFrame) -> str:
    if evidence.empty: return "IC_COMPOSITE"
    agg=evidence.groupby("architecture",as_index=False).agg(
        economic_score=("economic_score","mean"),
        worst_period_score=("economic_score","min"),
        worst_cut_robust_excess=("worst_cut_robust_excess","min"),
        mean_rank_ic=("mean_rank_ic","mean"),
    )
    agg=agg.sort_values(["economic_score","worst_period_score","worst_cut_robust_excess","mean_rank_ic","architecture"],ascending=[False,False,False,False,True])
    return str(agg.iloc[0]["architecture"])

def pre2021_horizon_skill(leader: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for h in HORIZONS:
        ev=leader[(leader.horizon_sessions.astype(int)==h)&leader.period.isin(["EVIDENCE_2017_2018","OUTER_2019_2020"])].copy()
        arch=_rank_architecture(ev)
        use=ev[ev.architecture.eq(arch)]
        econ=float(use.economic_score.mean())
        worst=float(use.worst_cut_robust_excess.min())
        skill=0.5*econ+0.5*worst
        rows.append({"horizon_sessions":h,"architecture":arch,"pre2021_economic_score":econ,"pre2021_worst_cut_robust_excess":worst,"pre2021_skill":skill})
    out=pd.DataFrame(rows)
    z=(out.pre2021_skill-out.pre2021_skill.mean())/(out.pre2021_skill.std(ddof=0)+1e-12)
    out["skill_z"]=z
    return out

def horizon_weights(skill: pd.DataFrame, beta: float) -> dict[int,float]:
    z=skill.set_index("horizon_sessions")["skill_z"].reindex(HORIZONS).to_numpy(float)
    logits=float(beta)*z
    logits=logits-np.nanmax(logits)
    w=np.exp(logits); w=w/w.sum()
    return {h:float(v) for h,v in zip(HORIZONS,w)}

def reaggregate_advisor(base: pd.DataFrame, weights: dict[int,float], mode_name: str) -> pd.DataFrame:
    out=base.copy()
    W=np.asarray([weights[h] for h in HORIZONS],float)
    mus=np.column_stack([pd.to_numeric(out[f"mu_day_{h}d"],errors="coerce").to_numpy(float) for h in HORIZONS])
    ses=np.column_stack([pd.to_numeric(out[f"se_day_{h}d"],errors="coerce").to_numpy(float) for h in HORIZONS])
    al=np.column_stack([pd.to_numeric(out[f"alpha_day_{h}d"],errors="coerce").to_numpy(float) for h in HORIZONS])
    ase=np.column_stack([pd.to_numeric(out[f"alpha_se_day_{h}d"],errors="coerce").to_numpy(float) for h in HORIZONS])
    mu=np.sum(mus*W[None,:],axis=1)
    stat=np.sqrt(np.sum((W[None,:]**2)*(ses**2),axis=1))
    disagreement=np.sqrt(np.sum(W[None,:]*(mus-mu[:,None])**2,axis=1))
    aa=np.sum(al*W[None,:],axis=1)
    astat=np.sqrt(np.sum((W[None,:]**2)*(ase**2),axis=1))
    adis=np.sqrt(np.sum(W[None,:]*(al-aa[:,None])**2,axis=1))
    out["expected_return_per_session"]=mu
    out["uncertainty_per_session"]=stat+disagreement
    out["expected_robust_alpha_per_session"]=aa
    out["alpha_uncertainty_per_session"]=astat+adis
    out["effective_horizon_sessions"]=float(sum(weights[h]*h for h in HORIZONS))
    out["horizon_agreement"]=np.sum(W[None,:]*(mus>0),axis=1)
    out["alpha_horizon_agreement"]=np.sum(W[None,:]*(al>0),axis=1)
    out["term_dispersion"]=disagreement
    out["advisor_conviction_z"]=mu/np.where(out["uncertainty_per_session"].to_numpy(float)>0,out["uncertainty_per_session"].to_numpy(float),np.nan)
    out["advisor_alpha_z"]=aa/np.where(out["alpha_uncertainty_per_session"].to_numpy(float)>0,out["alpha_uncertainty_per_session"].to_numpy(float),np.nan)
    for h in HORIZONS: out[f"return_horizon_weight_{h}d"]=weights[h]
    for name,idx in [("tactical",[0,1,2]),("strategic",[3,4,5])]:
        ww=W[idx]; ww=ww/ww.sum()
        out[f"{name}_expected_return_per_session"]=np.sum(mus[:,idx]*ww[None,:],axis=1)
        out[f"{name}_positive_share"]=np.sum((mus[:,idx]>0)*ww[None,:],axis=1)
        out[f"{name}_expected_robust_alpha_per_session"]=np.sum(al[:,idx]*ww[None,:],axis=1)
    out["horizon_weight_mode"]=mode_name
    return out

def load_cached_advisor(workspace: Path, cfg: Cfg) -> pd.DataFrame:
    p=workspace/cfg.p["cached_advisor_surface"]
    if not p.exists():
        raise FileNotFoundError(f"Cached advisor surface missing: {p}. Run Phase 3 FIX2 once; do not rebuild models.")
    x=pd.read_parquet(p)
    x["signal_date"]=_date(x["signal_date"]); x["ticker"]=_ticker(x["ticker"])
    hold=pd.Timestamp(cfg.p["holdout_start"])
    if (x.signal_date>=hold).any(): raise RuntimeError("HOLDOUT BREACH in cached advisor")
    need={"POLICY_SELECTION_2021_2022","VALIDATION_2023_2024"}
    if not need.issubset(set(x.role.unique())): raise RuntimeError(f"Cached advisor roles missing: {need-set(x.role.unique())}")
    return x

def load_terminals(source: Path, cfg: Cfg):
    p=source/cfg.p["source_terminal_overlay"]
    if not p.exists(): return {}
    x=pd.read_csv(p)
    if x.empty or "ticker" not in x or "terminal_price_date" not in x: return {}
    x["ticker"]=_ticker(x.ticker); x["terminal_price_date"]=_date(x.terminal_price_date)
    if "overlay_validated" in x:
        v=x["overlay_validated"]
        if v.dtype!=bool: v=v.astype(str).str.lower().isin(["true","1","yes"])
        x=x[v]
    return {str(r.ticker):pd.Timestamp(r.terminal_price_date) for r in x.dropna(subset=["terminal_price_date"]).itertuples()}

def load_surfaces(source: Path, cfg: Cfg):
    cols=["date","ticker","research_eligible","close","target_total_return_price"]
    p=pd.read_parquet(source/cfg.p["source_return_price_layer"],columns=cols)
    p["date"]=_date(p.date); p["ticker"]=_ticker(p.ticker)
    p["close"]=pd.to_numeric(p.close,errors="coerce")
    p["target_total_return_price"]=pd.to_numeric(p.target_total_return_price,errors="coerce")
    p=p[p.date<pd.Timestamp(cfg.p["holdout_start"])].copy()  # IMPORTANT: no research_eligible execution filter
    return p

def prepare_market(p: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, lookback: int):
    dates=pd.DatetimeIndex(sorted(p.date.dropna().unique()))
    prior=dates[dates<start]; lb=prior[max(0,len(prior)-lookback-3)] if len(prior) else start
    x=p[(p.date>=lb)&(p.date<end)].copy(); cal=pd.DatetimeIndex(sorted(x.date.unique()))
    tr=x.pivot_table(index="date",columns="ticker",values="target_total_return_price",aggfunc="last").reindex(cal)
    cl=x.pivot_table(index="date",columns="ticker",values="close",aggfunc="last").reindex(cal)
    elig=x.pivot_table(index="date",columns="ticker",values="research_eligible",aggfunc="last").reindex(cal).fillna(False).astype(bool)
    tr_ff=tr.ffill(); cl_ff=cl.ffill()
    tr_ret=tr_ff.pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan).where(tr.notna())
    cl_ret=cl_ff.pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan).where(cl.notna())
    ret=tr_ret.combine_first(cl_ret)
    return {"calendar":cal,"returns":ret,"execution_presence":cl.notna(),"research_eligible":elig,"close":cl,"tr":tr}

def benchmark_series(source: Path,cfg:Cfg,market:dict):
    out={}
    for sym,key in [("SPY","source_spy_benchmark"),("QQQ","source_qqq_benchmark")]:
        x=pd.read_parquet(source/cfg.p[key]); x["date"]=_date(x.date); x[sym]=pd.to_numeric(x[sym],errors="coerce")
        out[sym]=x.set_index("date")[sym].sort_index().pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan)
    # Causal daily equal-weight benchmark: today's return uses yesterday's investable set.
    r=market["returns"]; ep=market["research_eligible"].shift(1).fillna(False)
    out["UNIVERSE_EQUAL_WEIGHT"]=r.where(ep).mean(axis=1,skipna=True)
    return out

def benchmark_metrics(s,start,end):
    x=s[(s.index>=start)&(s.index<end)].dropna()
    if x.empty:return {"cagr":math.nan,"total_return":math.nan}
    nav=(1+x).cumprod(); return {"cagr":float(nav.iloc[-1]**(252/len(nav))-1),"total_return":float(nav.iloc[-1]-1)}

def prepare_risk(market,spy_ret,lookback,min_obs):
    r=market["returns"]; m=spy_ret.reindex(r.index)
    mv=m.rolling(lookback,min_periods=min_obs).var().clip(lower=1e-8)
    beta=pd.DataFrame(index=r.index,columns=r.columns,dtype="float32"); idio=beta.copy()
    for t in r.columns:
        rr=r[t]; cov=rr.rolling(lookback,min_periods=min_obs).cov(m); vr=rr.rolling(lookback,min_periods=min_obs).var(); b=(cov/mv).replace([np.inf,-np.inf],np.nan); iv=(vr-b*b*mv).clip(lower=1e-6)
        beta[t]=b.astype("float32"); idio[t]=iv.astype("float32")
    return {"beta":beta,"idio":idio,"market_var":mv}

def risk_stats(risk,d,names):
    b=risk["beta"].loc[d].reindex(names).to_numpy(float) if d in risk["beta"].index else np.full(len(names),np.nan)
    iv=risk["idio"].loc[d].reindex(names).to_numpy(float) if d in risk["idio"].index else np.full(len(names),np.nan)
    vm=float(risk["market_var"].get(d,np.nan)); b=np.where(np.isfinite(b),b,1.0); iv=np.where(np.isfinite(iv),np.maximum(iv,1e-6),0.0004); vm=vm if np.isfinite(vm) and vm>0 else 0.0001
    return b,iv,vm

def kelly(edge,beta,idio,vm):
    names=list(edge); mu=np.asarray([max(0,float(edge[t])) for t in names])
    if not names or not np.any(mu>0):return {}
    di=1/np.maximum(np.asarray(idio,float),1e-8); b=np.asarray(beta,float); vm=max(float(vm),1e-8)
    dm=di*mu; db=di*b; den=1/vm+float(np.dot(b,db)); raw=dm-db*(float(np.dot(b,dm))/den); raw=np.maximum(raw,0)
    if raw.sum()<=0:raw=np.maximum(dm,0)
    if raw.sum()<=0:return {}
    if raw.sum()>1:raw=raw/raw.sum()
    return {t:float(w) for t,w in zip(names,raw) if w>1e-10}

def build_target_path(advisor,risk,z,entry_bps,sparsity_bps):
    out={}; hurdle=entry_bps/10000; sparse=sparsity_bps/10000
    for d,g in advisor.groupby("signal_date",sort=False):
        q=g.set_index("ticker"); mu=pd.to_numeric(q.expected_return_per_session,errors="coerce"); se=pd.to_numeric(q.uncertainty_per_session,errors="coerce"); eff=pd.to_numeric(q.effective_horizon_sessions,errors="coerce").clip(lower=1)
        lcb_cum=(mu-z*se)*eff-hurdle
        elig=lcb_cum[np.isfinite(lcb_cum)&(lcb_cum>0)].index
        # L1-like opportunity cost; no fixed cardinality. Marginal names fall out endogenously.
        edge={str(t):float(mu.loc[t]-sparse/float(eff.loc[t])) for t in elig if np.isfinite(mu.loc[t]) and float(mu.loc[t]-sparse/float(eff.loc[t]))>0}
        if edge:
            names=list(edge); b,iv,vm=risk_stats(risk,pd.Timestamp(d),names); out[pd.Timestamp(d)]=kelly(edge,b,iv,vm)
        else: out[pd.Timestamp(d)]={}
    return out

def partial_target(cur,des,pres):
    cur={str(t):max(0,float(w)) for t,w in cur.items() if w>1e-14}; des={str(t):max(0,float(w)) for t,w in des.items() if w>1e-14}; uni=set(cur)|set(des)
    requested=sum(abs(des.get(t,0)-cur.get(t,0)) for t in uni)
    if requested<=1e-14:return dict(cur),{"requested":0,"executed":0,"blocked_requested":0,"target_deviation":0,"blocked_names":0,"full_skip":False,"partial":False}
    trade={t for t in uni if abs(des.get(t,0)-cur.get(t,0))>1e-12}; unavailable={t for t in trade if not bool(pres.get(t,False))}
    blocked_requested=sum(abs(des.get(t,0)-cur.get(t,0)) for t in unavailable)
    locked={t:cur[t] for t in unavailable if cur.get(t,0)>1e-14}; free=max(0,1-sum(locked.values()))
    dex={t:w for t,w in des.items() if t not in unavailable}; ds=sum(dex.values()); scale=min(1,free/ds) if ds>1e-14 else 0
    actual=dict(locked); actual.update({t:w*scale for t,w in dex.items() if w*scale>1e-14}); sm=sum(actual.values())
    if sm>1+1e-10: actual={t:w/sm for t,w in actual.items()}
    executed=sum(abs(actual.get(t,0)-cur.get(t,0)) for t in set(cur)|set(actual)); deviation=sum(abs(des.get(t,0)-actual.get(t,0)) for t in uni)
    return actual,{"requested":float(requested),"executed":float(executed),"blocked_requested":float(blocked_requested),"target_deviation":float(deviation),"blocked_names":len(unavailable),"full_skip":executed<=1e-12 and requested>1e-12,"partial":blocked_requested>1e-12}

def simulate(advisor,market,benches,terminals,start,end,z,entry_bps,sparsity_bps,rebalance_bps,round_trip_bps,risk,target_path=None,initial_weights=None,initial_cash=1.0):
    cal=market["calendar"][(market["calendar"]>=start)&(market["calendar"]<end)]; ret=market["returns"]; pres=market["execution_presence"]
    by={pd.Timestamp(d):g.set_index("ticker") for d,g in advisor[(advisor.signal_date>=start)&(advisor.signal_date<end)].groupby("signal_date",sort=False)}
    w=dict(initial_weights or {}); cash=float(initial_cash); nav=1.0; pending=None; one=round_trip_bps/2/10000; extra=rebalance_bps/10000; rows=[]
    for d in cal:
        d=pd.Timestamp(d); prev=nav; gross=0
        if w:
            rr=ret.loc[d]; gross=sum(v*(float(rr.get(t,0)) if np.isfinite(rr.get(t,np.nan)) else 0) for t,v in w.items())
        nav*=max(0,1+gross)
        if w:
            vals={t:v*(1+(float(ret.at[d,t]) if t in ret.columns and np.isfinite(ret.at[d,t]) else 0)) for t,v in w.items()}; total=cash+sum(vals.values())
            if total>0: w={t:v/total for t,v in vals.items() if v>1e-14}; cash=cash/total
        meta={"requested":0,"executed":0,"blocked_requested":0,"target_deviation":0,"blocked_names":0,"full_skip":False,"partial":False}; turnover=0; cost=0
        if pending is not None:
            actual,meta=partial_target(w,pending,pres.loc[d] if d in pres.index else pd.Series(dtype=bool));
            if meta["executed"]>1e-12:
                turnover=.5*meta["executed"]; cost=one*meta["executed"]; nav*=max(0,1-cost); w={t:float(v) for t,v in actual.items() if v>1e-10}; cash=max(0,1-sum(w.values()))
            pending=None
        # Validated terminal event: realize the last observed marked value into cash.
        for t in [t for t in list(w) if terminals.get(t)==d]:
            cash += w.pop(t)
        g=by.get(d); decision=False; benefit=0
        if g is not None and len(g):
            target=(target_path or {}).get(d,{}) if target_path is not None else build_target_path(g.reset_index(),risk,z,entry_bps,sparsity_bps).get(d,{})
            uni=set(w)|set(target); delta={t:target.get(t,0)-w.get(t,0) for t in uni}; mu={t:(float(g.expected_return_per_session.get(t,0)) if t in g.index and np.isfinite(g.expected_return_per_session.get(t,np.nan)) else 0) for t in uni}; eff={t:(float(g.effective_horizon_sessions.get(t,1)) if t in g.index and np.isfinite(g.effective_horizon_sessions.get(t,np.nan)) else 1) for t in uni}
            benefit=sum(delta[t]*mu[t]*eff[t] for t in uni); est=one*sum(abs(v) for v in delta.values())
            forced_exit=any(t not in g.index for t in w)
            if sum(abs(v) for v in delta.values())>1e-10 and (forced_exit or benefit>est+extra): pending=target; decision=True
        rows.append({"date":d,"nav":nav,"net_return":nav/prev-1 if prev>0 else -1,"turnover":turnover,"cost_fraction":cost,"holdings":len(w),"cash_weight":cash,"max_name_weight":max(w.values()) if w else 0,"rebalance_scheduled":int(decision),"requested_trade_notional":meta["requested"],"executed_trade_notional":meta["executed"],"blocked_requested_notional":meta["blocked_requested"],"target_deviation_notional":meta["target_deviation"],"blocked_trade_names":meta["blocked_names"],"partial_execution":int(meta["partial"]),"full_skip":int(meta["full_skip"]),"expected_incremental_return":benefit})
    d=pd.DataFrame(rows); n=len(d); nv=float(d.nav.iloc[-1]) if n else np.nan; yrs=n/252 if n else np.nan
    m={"days":n,"total_return":nv-1 if n else np.nan,"cagr":nv**(252/n)-1 if n and nv>0 else np.nan,"max_drawdown":float((d.nav/d.nav.cummax()-1).min()) if n else np.nan,"annual_turnover":float(d.turnover.sum()/yrs) if n else np.nan,"trade_days":int((d.turnover>1e-12).sum()) if n else 0,"median_holdings":float(d.holdings.median()) if n else 0,"max_holdings":int(d.holdings.max()) if n else 0,"mean_cash_weight":float(d.cash_weight.mean()) if n else 1,"median_max_name_weight":float(d.max_name_weight.median()) if n else 0,"p95_max_name_weight":float(d.max_name_weight.quantile(.95)) if n else 0,"scheduled_rebalances":int(d.rebalance_scheduled.sum()) if n else 0,"partial_execution_days":int(d.partial_execution.sum()) if n else 0,"full_execution_skip_days":int(d.full_skip.sum()) if n else 0,"blocked_trade_names":int(d.blocked_trade_names.sum()) if n else 0}
    req=float(d.requested_trade_notional.sum()) if n else 0; exe=float(d.executed_trade_notional.sum()) if n else 0; blk=float(d.blocked_requested_notional.sum()) if n else 0; dev=float(d.target_deviation_notional.sum()) if n else 0
    m.update({"requested_trade_notional":req,"executed_trade_notional":exe,"blocked_requested_notional":blk,"target_deviation_notional":dev,"execution_blocked_requested_rate":blk/req if req>1e-14 else 0,"target_deviation_rate":dev/req if req>1e-14 else 0})
    for k,s in benches.items():
        bm=benchmark_metrics(s,start,end); m[f"{k.lower()}_cagr"]=bm["cagr"]; m[f"excess_cagr_vs_{k.lower()}"]=m["cagr"]-bm["cagr"] if np.isfinite(m["cagr"]) and np.isfinite(bm["cagr"]) else np.nan
    ex=[m.get("excess_cagr_vs_spy"),m.get("excess_cagr_vs_qqq"),m.get("excess_cagr_vs_universe_equal_weight")]; m["robust_excess_cagr"]=float(np.nanmin(ex))
    return m,d,w,cash

def candidate_specs(cfg):
    rows=[]
    for beta in cfg.p["horizon_skill_beta_grid"]:
      for z in cfg.p["uncertainty_z_grid"]:
       for e in cfg.p["entry_hurdle_bps_grid"]:
        for s in cfg.p["sparsity_bps_grid"]:
         for r in cfg.p["rebalance_extra_edge_bps_grid"]:
          rows.append({"horizon_skill_beta":float(beta),"uncertainty_z":float(z),"entry_hurdle_bps":float(e),"sparsity_bps":float(s),"rebalance_extra_edge_bps":float(r)})
    return rows

def build_fast(workspace: Path):
    cfg=load_cfg(workspace); source=source_root(workspace,cfg); p2=_load_json(workspace/cfg.p["phase2_summary"])
    if p2.get("status")!="PASS": raise RuntimeError("Phase 2 must PASS")
    cached=load_cached_advisor(workspace,cfg)
    leader=pd.read_csv(workspace/cfg.p["phase2_leaderboard"]); skill=pre2021_horizon_skill(leader)
    surf=load_surfaces(source,cfg); terminals=load_terminals(source,cfg); start=pd.Timestamp(cfg.p["selection_start"]); val=pd.Timestamp(cfg.p["validation_start"]); hold=pd.Timestamp(cfg.p["holdout_start"])
    market=prepare_market(surf,start,hold,int(cfg.p["risk_lookback_sessions"])); benches=benchmark_series(source,cfg,market); risk=prepare_risk(market,benches["SPY"],int(cfg.p["risk_lookback_sessions"]),int(cfg.p["minimum_risk_observations"]))
    sel0=cached[cached.role.eq("POLICY_SELECTION_2021_2022")].copy(); val0=cached[cached.role.eq("VALIDATION_2023_2024")].copy()
    modes={float(b):horizon_weights(skill,float(b)) for b in cfg.p["horizon_skill_beta_grid"]}
    sel_modes={b:reaggregate_advisor(sel0,w,f"PRE2021_SKILL_BETA_{b:g}") for b,w in modes.items()}; val_modes={b:reaggregate_advisor(val0,w,f"PRE2021_SKILL_BETA_{b:g}") for b,w in modes.items()}
    rows=[]; target_cache={}
    specs=candidate_specs(cfg)
    for i,spec in enumerate(specs,1):
        beta=spec["horizon_skill_beta"]; a=sel_modes[beta]; key=(beta,spec["uncertainty_z"],spec["entry_hurdle_bps"],spec["sparsity_bps"])
        if key not in target_cache: target_cache[key]=build_target_path(a,risk,key[1],key[2],key[3])
        tp=target_cache[key]
        common=dict(advisor=a,market=market,benches=benches,terminals=terminals,start=start,end=val,z=spec["uncertainty_z"],entry_bps=spec["entry_hurdle_bps"],sparsity_bps=spec["sparsity_bps"],rebalance_bps=spec["rebalance_extra_edge_bps"],risk=risk,target_path=tp)
        b,_,_,_=simulate(round_trip_bps=float(cfg.p["base_round_trip_cost_bps"]),**common); st,_,_,_=simulate(round_trip_bps=float(cfg.p["stress_round_trip_cost_bps"]),**common)
        qualified=(b["robust_excess_cagr"]>0 and st["robust_excess_cagr"]>0 and b["execution_blocked_requested_rate"]<=float(cfg.p["maximum_execution_blocked_rate"]))
        rows.append({**spec,"cagr_20bps":b["cagr"],"robust_excess_cagr_20bps":b["robust_excess_cagr"],"excess_vs_spy_20bps":b["excess_cagr_vs_spy"],"excess_vs_qqq_20bps":b["excess_cagr_vs_qqq"],"excess_vs_uew_20bps":b["excess_cagr_vs_universe_equal_weight"],"cagr_40bps":st["cagr"],"robust_excess_cagr_40bps":st["robust_excess_cagr"],"max_drawdown_20bps":b["max_drawdown"],"annual_turnover_20bps":b["annual_turnover"],"median_holdings_20bps":b["median_holdings"],"max_holdings_20bps":b["max_holdings"],"median_max_name_weight_20bps":b["median_max_name_weight"],"p95_max_name_weight_20bps":b["p95_max_name_weight"],"mean_cash_weight_20bps":b["mean_cash_weight"],"execution_blocked_rate_20bps":b["execution_blocked_requested_rate"],"target_deviation_rate_20bps":b["target_deviation_rate"],"qualified":bool(qualified)})
        if i%24==0 or i==len(specs): print(f"FAST replay policies: {i}/{len(specs)}")
    lb=pd.DataFrame(rows).sort_values(["qualified","robust_excess_cagr_20bps","cagr_20bps","robust_excess_cagr_40bps","max_drawdown_20bps","annual_turnover_20bps"],ascending=[False,False,False,False,False,True]).reset_index(drop=True); lb["return_first_rank"]=np.arange(1,len(lb)+1)
    champ=lb.iloc[0].to_dict(); spec={k:float(champ[k]) for k in ["horizon_skill_beta","uncertainty_z","entry_hurdle_bps","sparsity_bps","rebalance_extra_edge_bps"]}; beta=spec["horizon_skill_beta"]
    a_sel=sel_modes[beta]; a_val=val_modes[beta]; tp_sel=build_target_path(a_sel,risk,spec["uncertainty_z"],spec["entry_hurdle_bps"],spec["sparsity_bps"]); tp_val=build_target_path(a_val,risk,spec["uncertainty_z"],spec["entry_hurdle_bps"],spec["sparsity_bps"])
    _,_,cw,cc=simulate(a_sel,market,benches,terminals,start,val,spec["uncertainty_z"],spec["entry_hurdle_bps"],spec["sparsity_bps"],spec["rebalance_extra_edge_bps"],float(cfg.p["base_round_trip_cost_bps"]),risk,tp_sel)
    vb,vnav,_,_=simulate(a_val,market,benches,terminals,val,hold,spec["uncertainty_z"],spec["entry_hurdle_bps"],spec["sparsity_bps"],spec["rebalance_extra_edge_bps"],float(cfg.p["base_round_trip_cost_bps"]),risk,tp_val,cw,cc)
    _,_,cws,ccs=simulate(a_sel,market,benches,terminals,start,val,spec["uncertainty_z"],spec["entry_hurdle_bps"],spec["sparsity_bps"],spec["rebalance_extra_edge_bps"],float(cfg.p["stress_round_trip_cost_bps"]),risk,tp_sel)
    vs,_,_,_=simulate(a_val,market,benches,terminals,val,hold,spec["uncertainty_z"],spec["entry_hurdle_bps"],spec["sparsity_bps"],spec["rebalance_extra_edge_bps"],float(cfg.p["stress_round_trip_cost_bps"]),risk,tp_val,cws,ccs)
    qual=int(lb.qualified.sum()); confirmed=bool(vb["robust_excess_cagr"]>0 and vs["robust_excess_cagr"]>0)
    maxw=max(modes[beta].values()); reasons=[]
    if champ["execution_blocked_rate_20bps"]>float(cfg.p["maximum_execution_blocked_rate"]): reasons.append("EXECUTION_MAPPING_STILL_BLOCKING")
    if champ["median_holdings_20bps"]>float(cfg.p["overdiversification_diagnostic_holdings"]): reasons.append("OVERDIVERSIFIED_SELECTION")
    if maxw>0.60: reasons.append("HORIZON_DOMINANCE")
    if champ["robust_excess_cagr_20bps"]<=0: reasons.append("INSUFFICIENT_SELECTION_ALPHA")
    if vb["robust_excess_cagr"]<=0: reasons.append("VALIDATION_ALPHA_NOT_CONFIRMED")
    gates=[
        {"test":"CACHED_ADVISOR_REUSED","status":"PASS","blocking":True,"value":str(workspace/cfg.p["cached_advisor_surface"]),"rule":"no model retraining"},
        {"test":"FINAL_HOLDOUT_NOT_LOADED","status":"PASS" if cached.signal_date.max()<hold else "FAIL","blocking":True,"value":str(cached.signal_date.max().date()),"rule":"< 2025-01-01"},
        {"test":"EXECUTION_USES_RAW_CLOSE_NOT_RESEARCH_ELIGIBILITY","status":"PASS","blocking":True,"value":True,"rule":"exit availability comes from observable close on all rows"},
        {"test":"ALL_SIX_HORIZONS_NONZERO","status":"PASS" if min(modes[beta].values())>0 else "FAIL","blocking":True,"value":modes[beta],"rule":"all six remain active"},
        {"test":"QUALIFIED_POLICY_EXISTS","status":"PASS" if qual>0 else "FAIL","blocking":True,"value":qual,"rule":"positive robust excess base/stress and executable"},
        {"test":"VALIDATION_CONFIRMATION","status":"PASS" if confirmed else "FAIL","blocking":False,"value":confirmed,"rule":"2023-2024 diagnostic only"},
    ]
    status="PASS" if all(g["status"]=="PASS" for g in gates if g["blocking"]) else "FAIL"
    out=workspace/"outputs"; out.mkdir(parents=True,exist_ok=True)
    lb.to_csv(out/"v13_phase3_fast_leaderboard.csv",index=False); skill.to_csv(out/"v13_phase3_fast_pre2021_horizon_skill.csv",index=False); vnav.to_csv(out/"v13_phase3_fast_validation_nav.csv",index=False); pd.DataFrame(gates).to_csv(out/"v13_phase3_fast_gate.csv",index=False)
    pd.DataFrame([{"cost_bps":cfg.p["base_round_trip_cost_bps"],**vb},{"cost_bps":cfg.p["stress_round_trip_cost_bps"],**vs}]).to_csv(out/"v13_phase3_fast_validation.csv",index=False)
    pd.DataFrame([{"horizon_sessions":h,"selected_weight":modes[beta][h]} for h in HORIZONS]).to_csv(out/"v13_phase3_fast_selected_horizon_weights.csv",index=False)
    summary={"status":status,"phase":"V13-P3R","build":BUILD,"mode":"FAST_CACHED_PORTFOLIO_RESEARCH","cache":{"advisor_rows":int(len(cached)),"models_retrained":False,"dense_scores_rebuilt":False},"selection":{"candidate_policies":len(lb),"qualified_policies":qual,"selected_policy":spec,"metrics":{k:champ.get(k) for k in ["cagr_20bps","robust_excess_cagr_20bps","cagr_40bps","robust_excess_cagr_40bps","median_holdings_20bps","max_holdings_20bps","median_max_name_weight_20bps","p95_max_name_weight_20bps","execution_blocked_rate_20bps","target_deviation_rate_20bps"]}},"horizon_weights":modes[beta],"pre2021_horizon_skill":skill.to_dict(orient="records"),"validation":{"base":vb,"stress":vs,"confirmed":confirmed,"used_for_selection":False},"holdout":{"start":cfg.p["holdout_start"],"used":False},"diagnosis":reasons,"gate":gates,"next":"If selection qualifies, use this fast architecture as the Phase 3 candidate; if validation also confirms, freeze/stress without reopening model research. If it fails, diagnosis identifies whether execution, dilution, horizon aggregation, or alpha is the bottleneck."}
    (out/"v13_phase3_fast_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    return summary
