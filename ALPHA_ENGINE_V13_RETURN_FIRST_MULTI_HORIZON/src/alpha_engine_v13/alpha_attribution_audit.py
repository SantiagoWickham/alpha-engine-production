from __future__ import annotations

import json, math
from pathlib import Path
import numpy as np
import pandas as pd

from alpha_engine_v13 import economic_portfolio_closure as p3v

BUILD = "V13_P3X_ALPHA_ATTRIBUTION_TURNOVER_AUDIT_2026-09-13"
HORIZONS = p3v.HORIZONS
EVAL_FOLDS = p3v.EVAL_FOLDS


def _ols(y: pd.Series, x: pd.Series) -> dict:
    z = pd.concat([pd.to_numeric(y, errors="coerce"), pd.to_numeric(x, errors="coerce")], axis=1).dropna()
    if len(z) < 50:
        return {"n": len(z), "alpha_ann": np.nan, "beta": np.nan, "r2": np.nan, "corr": np.nan}
    yy = z.iloc[:, 0].to_numpy(float); xx = z.iloc[:, 1].to_numpy(float)
    X = np.column_stack([np.ones(len(xx)), xx])
    b = np.linalg.lstsq(X, yy, rcond=None)[0]
    pred = X @ b; ssr = float(np.sum((yy-pred)**2)); sst=float(np.sum((yy-yy.mean())**2))
    return {"n": len(z), "alpha_ann": float(b[0]*252.0), "beta": float(b[1]), "r2": float(1-ssr/sst) if sst>0 else np.nan, "corr": float(np.corrcoef(yy,xx)[0,1])}


def _capture(strategy: pd.Series, bench: pd.Series) -> dict:
    z = pd.concat([strategy.rename("s"), bench.rename("b")], axis=1).dropna()
    out={}
    for name,mask in [("up",z.b>0),("down",z.b<0)]:
        q=z[mask]
        out[f"{name}_days"]=len(q)
        out[f"{name}_strategy_mean_ann"]=float(q.s.mean()*252) if len(q) else np.nan
        out[f"{name}_bench_mean_ann"]=float(q.b.mean()*252) if len(q) else np.nan
        out[f"{name}_capture_ratio"]=float(q.s.mean()/q.b.mean()) if len(q) and abs(q.b.mean())>1e-15 else np.nan
    return out


def _simulate_with_weights(targets: dict, market: dict, terminals: dict, start: pd.Timestamp, end: pd.Timestamp, round_trip_bps: float, rebalance_every: int=1):
    cal=market["calendar"][(market["calendar"]>=start)&(market["calendar"]<end)]
    ret=market["returns"]; pres=market["execution_presence"]
    w={}; cash=1.0; nav=1.0; pending=None; rows=[]; wh=[]; one=float(round_trip_bps)/2/10000.0; sig_count=0
    for d in cal:
        d=pd.Timestamp(d); prev=nav
        if w:
            rr=ret.loc[d] if d in ret.index else pd.Series(dtype=float)
            vals={t:v*(1+(float(rr.get(t,0.0)) if np.isfinite(rr.get(t,np.nan)) else 0.0)) for t,v in w.items()}
            total=cash+sum(vals.values())
            if total>0:
                w={t:v/total for t,v in vals.items() if v>1e-14}; cash=cash/total
                nav*=max(0.0,float(total))
        meta={"requested":0.0,"executed":0.0,"blocked":0.0,"deviation":0.0,"blocked_names":0}; turnover=0.0; cost=0.0; entry_exit=0.0; resize=0.0
        if pending is not None:
            old=dict(w)
            actual,meta=p3v.partial_target(w,pending,pres.loc[d] if d in pres.index else pd.Series(dtype=bool))
            oldcash=cash; newcash=max(0.0,1.0-sum(actual.values()))
            turnover=0.5*(meta["executed"]+abs(newcash-oldcash)); cost=one*meta["executed"]; nav*=max(0.0,1.0-cost)
            alln=set(old)|set(actual)
            for t in alln:
                a=float(old.get(t,0)); b=float(actual.get(t,0)); ch=abs(b-a)
                if (a<=1e-14) != (b<=1e-14): entry_exit += ch
                else: resize += ch
            w=actual; cash=newcash; pending=None
        for t in [t for t in list(w) if terminals.get(t)==d]: cash+=w.pop(t)
        if d in targets:
            if sig_count % max(1,int(rebalance_every)) == 0: pending=targets[d]
            sig_count += 1
        for t,v in w.items():
            wh.append({"date":d,"ticker":t,"weight":v})
        rows.append({"date":d,"nav":nav,"net_return":nav/prev-1 if prev>0 else -1.0,"turnover":turnover,"entry_exit_notional":entry_exit,"resize_notional":resize,"cost_fraction":cost,"holdings":len(w),"cash_weight":cash,"max_name_weight":max(w.values()) if w else 0.0,"requested":meta["requested"],"executed":meta["executed"],"blocked":meta["blocked"],"deviation":meta["deviation"]})
    return pd.DataFrame(rows), pd.DataFrame(wh)


def _annual_returns(daily: pd.DataFrame, benches: dict) -> pd.DataFrame:
    z=daily[["date","net_return"]].copy(); z["year"]=pd.to_datetime(z.date).dt.year
    rows=[]
    for y,g in z.groupby("year"):
        r=float((1+g.net_return).prod()-1)
        row={"year":int(y),"strategy_return":r}
        for k,s in benches.items():
            q=s.reindex(pd.DatetimeIndex(g.date)).fillna(0.0)
            row[f"{k.lower()}_return"]=float((1+q).prod()-1)
            row[f"excess_vs_{k.lower()}"]=r-row[f"{k.lower()}_return"]
        rows.append(row)
    return pd.DataFrame(rows)


def _holding_stats(weights: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    if weights.empty:
        return pd.DataFrame(), pd.DataFrame()
    out=[]
    for threshold in [0.0001,0.001,0.005,0.01,0.02,0.05]:
        x=weights[weights.weight>=threshold].sort_values(["ticker","date"])
        lens=[]
        for t,g in x.groupby("ticker"):
            ds=list(pd.to_datetime(g.date).sort_values())
            if not ds: continue
            run=1
            for a,b in zip(ds[:-1],ds[1:]):
                if (b-a).days<=4: run+=1
                else: lens.append(run); run=1
            lens.append(run)
        a=np.array(lens,float)
        out.append({"weight_threshold":threshold,"episodes":len(a),"median_sessions":float(np.median(a)) if len(a) else np.nan,"mean_sessions":float(np.mean(a)) if len(a) else np.nan,"p90_sessions":float(np.quantile(a,.9)) if len(a) else np.nan})
    conc=[]
    for d,g in weights.groupby("date"):
        w=np.array(g.weight,float); w=w[w>0]; sw=w.sum()
        if sw<=0: continue
        w=w/sw; s=np.sort(w)[::-1]
        conc.append({"date":d,"effective_n":float(1/np.sum(w*w)),"top1":float(s[:1].sum()),"top5":float(s[:5].sum()),"top10":float(s[:10].sum()),"n_gt_1pct":int((w>=.01).sum()),"n_gt_2pct":int((w>=.02).sum()),"n_gt_5pct":int((w>=.05).sum())})
    return pd.DataFrame(out),pd.DataFrame(conc)


def _benchmark_integrity(market: dict, benches: dict) -> pd.DataFrame:
    prev=market["research_eligible"].shift(1).eq(True)
    ret=market["returns"]
    eligible=prev.sum(axis=1)
    observed=(ret.notna()&prev).sum(axis=1)
    legacy=ret.where(prev).mean(axis=1,skipna=True)
    zero=ret.where(prev).fillna(0.0).sum(axis=1)/eligible.replace(0,np.nan)
    rows=[]
    for fold,start,end in EVAL_FOLDS:
        m=(eligible.index>=start)&(eligible.index<end)
        for name,s in [("LEGACY_SKIPNA_UEW",legacy),("ZERO_FILL_MISSING_UEW",zero)]:
            q=s[m].fillna(0.0)
            rows.append({"fold":fold,"benchmark_variant":name,"days":len(q),"total_return":float((1+q).prod()-1),"cagr":float((1+q).prod()**(252/max(1,len(q)))-1),"mean_eligible_names":float(eligible[m].mean()),"mean_observed_returns":float(observed[m].mean()),"mean_missing_share":float((1-observed[m]/eligible[m].replace(0,np.nan)).mean()),"p95_missing_share":float((1-observed[m]/eligible[m].replace(0,np.nan)).quantile(.95))})
    return pd.DataFrame(rows)


def _conviction_curve(advisor: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    x=advisor[["signal_date","ticker","expected_abs_per_session","expected_alpha_per_session","uncertainty_per_session"]].copy()
    x["conviction"]=(x.expected_abs_per_session+x.expected_alpha_per_session)/x.uncertainty_per_session.replace(0,np.nan)
    cols=["signal_date","ticker","target_resolved_20d","target_end_date_20d","fwd_return_20d","excess_spy_20d","excess_uew_20d"]
    z=x.merge(targets[cols],on=["signal_date","ticker"],how="inner")
    z=z[z.target_resolved_20d.fillna(False)&z.fwd_return_20d.notna()].copy()
    if len(z):
        pct=z.groupby("signal_date")["conviction"].rank(method="first",pct=True)
        z["decile"]=np.ceil(pct*10).clip(1,10)
    rows=[]
    for dec,g in z.groupby("decile"):
        rows.append({"decile":int(dec),"rows":len(g),"mean_fwd_return_20d":float(g.fwd_return_20d.mean()),"mean_excess_spy_20d":float(g.excess_spy_20d.mean()),"mean_excess_uew_20d":float(g.excess_uew_20d.mean()),"median_conviction":float(g.conviction.median())})
    return pd.DataFrame(rows)


def build_audit(workspace: Path) -> dict:
    cfg=p3v.load_cfg(workspace); p0,p2u,source=p3v.load_contracts(workspace,cfg); scores,targets=p3v.load_scores_targets(workspace,cfg)
    advisor,rel,infl,cov=p3v.build_causal_advisor(scores,targets,cfg)
    hold=pd.Timestamp(cfg.p["holdout_start"]); start=pd.Timestamp(cfg.p["portfolio_start"]); needed=set(advisor.ticker.unique())
    surface=p3v.load_market(workspace,source,cfg,needed); spy=p3v._load_benchmark(source,cfg.p["source_spy_benchmark"],"SPY",hold); qqq=p3v._load_benchmark(source,cfg.p["source_qqq_benchmark"],"QQQ",hold)
    market=p3v.prepare_market(surface,spy,start,hold,int(cfg.p["risk_lookback_sessions"])); benches=p3v.benchmark_returns(source,cfg,market,spy,qqq); terminals=p3v.load_terminals(source,cfg)
    sel=json.loads((workspace/"outputs"/"v13_phase3v_selected_policy.json").read_text(encoding="utf-8")); targets_path=p3v.build_target_path(advisor,market,sel,cfg)
    daily,weights=_simulate_with_weights(targets_path,market,terminals,start,hold,float(cfg.p["base_round_trip_cost_bps"]),1)
    annual=_annual_returns(daily,benches)
    beta=[]
    sr=daily.set_index("date").net_return
    for k,b in benches.items():
        row={"benchmark":k,**_ols(sr,b),**_capture(sr,b)}; beta.append(row)
    beta=pd.DataFrame(beta)
    holdstats,conc=_holding_stats(weights,daily)
    turn={"annual_turnover":float(daily.turnover.sum()/(len(daily)/252)),"entry_exit_share_of_executed_change":float(daily.entry_exit_notional.sum()/max(1e-15,daily.entry_exit_notional.sum()+daily.resize_notional.sum())),"resize_share_of_executed_change":float(daily.resize_notional.sum()/max(1e-15,daily.entry_exit_notional.sum()+daily.resize_notional.sum())),"mean_daily_turnover":float(daily.turnover.mean()),"median_daily_turnover":float(daily.turnover.median())}
    reb=[]
    for n in [1,5,10,20]:
        d,_=_simulate_with_weights(targets_path,market,terminals,start,hold,float(cfg.p["base_round_trip_cost_bps"]),n); m=p3v._metrics(d,benches,start,hold); reb.append({"rebalance_every_sessions":n,**m})
    bench_audit=_benchmark_integrity(market,benches)
    conviction=_conviction_curve(advisor,targets)
    # Horizon influence diagnostics
    h=infl.copy(); h["group"]=np.where(h.horizon_sessions<=20,"SHORT_5_20","LONG_60_252")
    group=h.groupby(["fold","group"],as_index=False).mean(numeric_only=True)[["fold","group","mean_weight","median_weight"]]
    out=workspace/"outputs"; out.mkdir(exist_ok=True)
    annual.to_csv(out/"v13_phase3x_annual_returns.csv",index=False); beta.to_csv(out/"v13_phase3x_beta_attribution.csv",index=False); holdstats.to_csv(out/"v13_phase3x_holding_duration.csv",index=False); conc.to_csv(out/"v13_phase3x_concentration_daily.csv",index=False); pd.DataFrame([turn]).to_csv(out/"v13_phase3x_turnover_decomposition.csv",index=False); pd.DataFrame(reb).to_csv(out/"v13_phase3x_rebalance_frequency_counterfactual.csv",index=False); bench_audit.to_csv(out/"v13_phase3x_uew_integrity_audit.csv",index=False); conviction.to_csv(out/"v13_phase3x_conviction_curve.csv",index=False); infl.to_csv(out/"v13_phase3x_horizon_influence.csv",index=False); group.to_csv(out/"v13_phase3x_horizon_group_influence.csv",index=False)
    # Diagnostics, not optimization gates.
    summary={"status":"PASS","phase":"V13-P3X","build":BUILD,"name":"ALPHA_ATTRIBUTION_AND_TURNOVER_AUDIT","holdout_used":False,"policy_changed":False,"selected_policy":sel,"headline":{"cagr_20bps":float(p3v._metrics(daily,benches,start,hold)["cagr"]),"spy_cagr":float(p3v._metrics(daily,benches,start,hold)["spy_cagr"]),"uew_cagr_legacy":float(p3v._metrics(daily,benches,start,hold)["uew_cagr"]),"annual_turnover":turn["annual_turnover"],"median_holdings":float(daily.holdings.median()),"median_max_weight":float(daily.max_name_weight.median())},"questions":{"market_beta":"See v13_phase3x_beta_attribution.csv","universe_benchmark_bias":"See v13_phase3x_uew_integrity_audit.csv","random_weak_signal_concern":"See v13_phase3x_conviction_curve.csv","micro_churn":"See turnover + rebalance counterfactual","lack_of_concentration":"See concentration_daily + holding_duration","short_horizon_dominance":"See horizon influence outputs"},"next":"Do not open 2025+. Use this audit to decide whether to redesign portfolio conviction/benchmark semantics or whether true active alpha is already present."}
    (out/"v13_phase3x_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    return summary
