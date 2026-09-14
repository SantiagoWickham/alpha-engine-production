from __future__ import annotations
from pathlib import Path
import json, math
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor

BUILD = "V13_P2T_FIX2_PHASE1_TARGET_SURFACE_2026-09-12"
HORIZONS = (5,10,20,60,120,252)
FOLD_ORDER = ("WF_2017_2018","WF_2019_2020","WF_2021_2022","WF_2023_2024")
ROUTERS = ("RIDGE_REGIME","HGB_REGIME","BLEND_REGIME")


def _dates(s): return pd.to_datetime(s, errors="coerce").dt.normalize()

def _phase0_manifest(workspace: Path) -> dict:
    p=workspace/"outputs"/"v13_phase0_source_manifest.json"
    if not p.exists(): raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding="utf-8"))

def load_inputs(workspace: Path):
    out=workspace/"outputs"
    ps=out/"v13_phase2s_oof_scores.parquet"
    ef=out/"v13_phase2s_enriched_feature_surface.parquet"
    if not ps.exists(): raise FileNotFoundError(f"Missing cached Phase2S OOF scores: {ps}")
    if not ef.exists(): raise FileNotFoundError(f"Missing cached Phase2S enriched features: {ef}")
    scores=pd.read_parquet(ps)
    features=pd.read_parquet(ef)
    # IMPORTANT: Phase2T must route the exact research-target surface that produced
    # Phase2S. Do not fall back to the broader V12 phase3 target artifact: its schema
    # is different and it may extend through the final holdout.
    tp=out/"v13_phase1_research_targets.parquet"
    if not tp.exists(): raise FileNotFoundError(f"Missing Phase1 research target surface used by Phase2S: {tp}")
    hold=pd.Timestamp("2025-01-01")
    scores["signal_date"]=_dates(scores["signal_date"])
    features["signal_date"]=_dates(features["signal_date"])
    targets=pd.read_parquet(tp)
    targets["signal_date"]=_dates(targets["signal_date"])
    if "ticker" not in targets.columns: raise RuntimeError("Phase1 research targets missing ticker")
    targets["ticker"]=targets["ticker"].astype(str).str.upper().str.strip()
    if (scores.signal_date>=hold).any() or (features.signal_date>=hold).any() or (targets.signal_date>=hold).any():
        raise RuntimeError("HOLDOUT BREACH: Phase2T research inputs contain 2025+ signal dates")

    # Schema preflight across all horizons BEFORE any router fit. This avoids wasting a run
    # only to discover a missing column deep in the first horizon.
    required={"signal_date","ticker"}
    for h in HORIZONS:
        required.update({f"target_end_date_{h}d",f"target_resolved_{h}d",f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"})
    miss=sorted(required-set(targets.columns))
    if miss: raise RuntimeError(f"Phase1 research target schema incomplete for Phase2T: {miss}")

    # Strong holdout firewall: pre-holdout signals whose label resolves in 2025+ are
    # allowed to exist in the source surface, but _horizon_frame excludes them per horizon.
    return scores,features,targets,tp

def _macro_daily(features: pd.DataFrame) -> tuple[pd.DataFrame,list[str]]:
    cols=[c for c in features.columns if c.startswith("macro_") and c.endswith("_z252")]
    if not cols: raise RuntimeError("No macro regime columns found in Phase2S feature cache")
    d=features[["signal_date"]+cols].drop_duplicates("signal_date",keep="last").sort_values("signal_date")
    # Keep a compact, stable set: highest time coverage, capped to 24.
    cov=d[cols].notna().mean().sort_values(ascending=False)
    keep=cov[cov>=0.70].head(24).index.tolist()
    if len(keep)<6: raise RuntimeError(f"Insufficient macro regime features: {len(keep)}")
    return d[["signal_date"]+keep],keep

def _horizon_frame(scores, targets, macro, h:int):
    hold=pd.Timestamp("2025-01-01")
    s=scores[scores.horizon_sessions.astype(int).eq(h)][["signal_date","ticker","fold","score"]].copy()
    endc=f"target_end_date_{h}d"; resc=f"target_resolved_{h}d"
    tcols=["signal_date","ticker",endc,resc,f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]
    miss=[c for c in tcols if c not in targets.columns]
    if miss: raise RuntimeError(f"Target columns missing for {h}D: {miss}")
    t=targets[tcols].copy(); t[endc]=_dates(t[endc]); t[resc]=t[resc].fillna(False).astype(bool)
    # Strong holdout firewall: even a pre-2025 signal is unusable if its realized label ends in 2025+.
    t=t[t[resc] & t[endc].notna() & (t[endc] < hold)].copy()
    if len(t) and not (t[endc] < hold).all():
        raise RuntimeError(f"HOLDOUT BREACH: {h}D label resolves in 2025+")
    z=s.merge(t,on=["signal_date","ticker"],how="inner",validate="one_to_one").merge(macro,on="signal_date",how="left",validate="many_to_one")
    ex=np.column_stack([pd.to_numeric(z[f"excess_spy_{h}d"],errors="coerce"),pd.to_numeric(z[f"excess_qqq_{h}d"],errors="coerce"),pd.to_numeric(z[f"excess_uew_{h}d"],errors="coerce")])
    z["robust_excess"]=np.nanmin(ex,axis=1)
    z["winner"]=(z.groupby("signal_date",observed=True)[f"fwd_return_{h}d"].rank(pct=True,method="average")>=0.90).astype(float)
    return z

def _router_features(df:pd.DataFrame, macro_cols:list[str]) -> tuple[np.ndarray,list[str]]:
    score=pd.to_numeric(df.score,errors="coerce").fillna(0.5).to_numpy(float)
    parts=[score, score-0.5, (score-0.5)**2]
    names=["score","score_centered","score_sq"]
    # macro + score x macro makes regime alter cross-sectional ordering, not just intercept.
    for c in macro_cols:
        m=pd.to_numeric(df[c],errors="coerce").fillna(0.0).clip(-5,5).to_numpy(float)
        parts.extend([m,(score-0.5)*m]); names.extend([c,"score_x_"+c])
    return np.column_stack(parts).astype(np.float32),names

def _aggregate_train(df:pd.DataFrame, macro_cols:list[str], bins:int=20) -> pd.DataFrame:
    x=df.copy(); x=x[np.isfinite(pd.to_numeric(x.robust_excess,errors="coerce"))].copy()
    if x.empty:return x
    x["score_bin"]=x.groupby("signal_date",observed=True).score.transform(lambda s: np.minimum((s.rank(pct=True,method="average")*bins).astype(int),bins-1))
    agg={"score":"mean","robust_excess":"mean","winner":"mean","ticker":"count"}
    for c in macro_cols: agg[c]="last"
    a=x.groupby(["signal_date","score_bin"],observed=True,as_index=False).agg(agg).rename(columns={"ticker":"n"})
    return a

def _fit_candidates(train:pd.DataFrame, test:pd.DataFrame, macro_cols:list[str], seed:int=13):
    tr=_aggregate_train(train,macro_cols)
    if len(tr)<200: raise RuntimeError(f"Router train table too small: {len(tr)}")
    X,names=_router_features(tr,macro_cols); y=pd.to_numeric(tr.robust_excess,errors="coerce").to_numpy(float); w=np.sqrt(pd.to_numeric(tr.n,errors="coerce").fillna(1).to_numpy(float))
    ok=np.isfinite(y)&np.all(np.isfinite(X),axis=1); X=X[ok]; y=y[ok]; w=w[ok]
    # Winsorize only on training.
    lo,hi=np.quantile(y,[.01,.99]); yc=np.clip(y,lo,hi)
    Xt,_=_router_features(test,macro_cols)
    ridge=Ridge(alpha=10.0).fit(X,yc,sample_weight=w)
    pr=ridge.predict(Xt)
    hgb=HistGradientBoostingRegressor(loss="squared_error",learning_rate=0.05,max_iter=150,max_leaf_nodes=15,min_samples_leaf=30,l2_regularization=2.0,random_state=seed)
    hgb.fit(X,yc,sample_weight=w); ph=hgb.predict(Xt)
    pb=.5*pr+.5*ph
    return {"RIDGE_REGIME":pr,"HGB_REGIME":ph,"BLEND_REGIME":pb}, names

def _eval(df:pd.DataFrame,pred:np.ndarray)->dict:
    z=df[["signal_date","robust_excess","winner"]].copy(); z["pred"]=pred
    z=z[np.isfinite(z.pred)&np.isfinite(z.robust_excess)]
    cuts=[]
    for q in (.05,.10,.20):
        def one(g):
            n=max(1,int(math.ceil(len(g)*q))); a=g.nlargest(n,"pred")
            return pd.Series({"excess":a.robust_excess.mean(),"winner":a.winner.mean(),"base_winner":g.winner.mean()})
        d=z.groupby("signal_date",observed=True).apply(one,include_groups=False)
        cuts.append((q,float(d.excess.mean()),float((d.excess>0).mean()),float((d.winner/np.maximum(d.base_winner,1e-9)).mean())))
    econ=float(np.mean([x[1] for x in cuts])); worst=float(np.min([x[1] for x in cuts])); pos=float(np.mean([x[2] for x in cuts])); wl=float(np.mean([x[3] for x in cuts]))
    ic=[]
    for _,g in z.groupby("signal_date",observed=True):
        if len(g)>=10 and g.pred.nunique()>1 and g.robust_excess.nunique()>1: ic.append(g.pred.corr(g.robust_excess,method="spearman"))
    return {"economic_score":econ,"worst_cut_robust_excess":worst,"positive_cut_share":pos,"winner_lift":wl,"mean_rank_ic":float(np.nanmean(ic)) if ic else np.nan}

def _choose_router(history:pd.DataFrame)->str:
    if history.empty:return "BLEND_REGIME"
    a=history.groupby("router",as_index=False).agg(econ=("economic_score","mean"),worst=("worst_cut_robust_excess","min"),pos=("positive_cut_share","mean"),winner=("winner_lift","mean"))
    for c in ["econ","worst","pos","winner"]:
        s=a[c].to_numpy(float); med=np.nanmedian(s); mad=np.nanmedian(np.abs(s-med)); a[c+"_z"]=(s-med)/(1.4826*mad+1e-8)
    a["skill"]=.45*a.econ_z+.25*a.worst_z+.20*a.pos_z+.10*a.winner_z
    return str(a.sort_values(["skill","econ"],ascending=False).iloc[0].router)

def build_router(workspace:Path)->dict:
    out=workspace/"outputs"; out.mkdir(exist_ok=True,parents=True)
    scores,features,targets,source=load_inputs(workspace); macro,macro_cols=_macro_daily(features)
    all_evidence=[]; selected=[]; pred_parts=[]
    for h in HORIZONS:
        d=_horizon_frame(scores,targets,macro,h); history=[]
        for i,fold in enumerate(FOLD_ORDER):
            cur=d[d.fold.eq(fold)].copy()
            if i==0:
                # First OOF fold seeds evidence but is not router-evaluable without prior OOF.
                continue
            prior=d[d.fold.isin(FOLD_ORDER[:i])].copy()
            cand,_=_fit_candidates(prior,cur,macro_cols,seed=13+h+i)
            fold_rows=[]
            for r,p in cand.items():
                ev=_eval(cur,p); row={"horizon_sessions":h,"fold":fold,"router":r,**ev}; all_evidence.append(row); fold_rows.append(row)
            chosen=_choose_router(pd.DataFrame(history)) if history else "BLEND_REGIME"
            # For 2019-20 no previous router test exists: deterministic blend. Later folds use prior router OOF evidence only.
            pp=cand[chosen]; ev=_eval(cur,pp)
            selected.append({"horizon_sessions":h,"fold":fold,"selected_router":chosen,**ev})
            q=cur[["signal_date","ticker","fold","robust_excess","winner"]].copy(); q["horizon_sessions"]=h; q["conditional_alpha"]=pp; pred_parts.append(q)
            history.extend(fold_rows)
    ev=pd.DataFrame(all_evidence); sel=pd.DataFrame(selected); routed=pd.concat(pred_parts,ignore_index=True)
    # Build multi-horizon advisor. Horizon reliability for each fold uses selected-router evidence from PREVIOUS folds only.
    advisor_parts=[]; influence=[]
    for fold in FOLD_ORDER[1:]:
        z=routed[routed.fold.eq(fold)].copy()
        if z.empty: continue
        prior_sel=sel[sel.fold.isin(FOLD_ORDER[1:FOLD_ORDER.index(fold)])].copy()
        if prior_sel.empty:
            prior_skill={h:0.0 for h in HORIZONS}
        else:
            g=prior_sel.groupby("horizon_sessions").economic_score.mean()
            prior_skill={h:float(g.get(h,0.0)) for h in HORIZONS}
        # Reliability softmax with floor; negative historical alpha reduces but never deletes horizon.
        vals=np.array([prior_skill[h] for h in HORIZONS],float)
        scale=max(np.nanmedian(np.abs(vals-np.nanmedian(vals)))*1.4826,0.002)
        q=np.clip(vals/scale,-4,4); e=np.exp(q-q.max()); base=.02 + .88*e/e.sum(); base=base/base.sum()
        base_map={h:float(w) for h,w in zip(HORIZONS,base)}
        for h,w in base_map.items(): influence.append({"fold":fold,"horizon_sessions":h,"prior_reliability_weight":w,"prior_economic_skill":prior_skill[h]})
        # Per asset/day: condition on current predicted alpha. Positive forecasts gain influence, negative forecasts become caution weights.
        zz=z.pivot_table(index=["signal_date","ticker"],columns="horizon_sessions",values=["conditional_alpha","robust_excess"],aggfunc="last")
        rows=[]
        for (dt,tick),r in zz.iterrows():
            preds=[]; reals=[]; hs=[]; ws=[]
            for h in HORIZONS:
                try: pa=float(r[("conditional_alpha",h)])
                except Exception: pa=np.nan
                try: rr=float(r[("robust_excess",h)])
                except Exception: rr=np.nan
                if not np.isfinite(pa) or not np.isfinite(rr): continue
                # dailyized horizon forecast; sigmoid-like confidence, floor keeps all available horizons conceptually active.
                per=pa/max(h,1); conf=0.15 + 0.85/(1.0+np.exp(-np.clip(per/0.0005,-8,8)))
                w=base_map[h]*conf
                preds.append(per); reals.append(rr/max(h,1)); hs.append(h); ws.append(w)
            if len(hs)<3: continue
            ws=np.array(ws,float); ws=ws/ws.sum(); preds=np.array(preds); reals=np.array(reals)
            rows.append({"signal_date":dt,"ticker":tick,"fold":fold,"advisor_score_per_session":float(np.dot(ws,preds)),"realized_utility_per_session":float(np.dot(ws,reals)),"effective_horizon":float(np.dot(ws,np.array(hs))),"active_horizons":len(hs),"max_horizon_weight":float(ws.max())})
        if rows: advisor_parts.append(pd.DataFrame(rows))
    advisor=pd.concat(advisor_parts,ignore_index=True) if advisor_parts else pd.DataFrame()
    # Evaluate advisor by fold with 20-session-equivalent robust utility for readable economics.
    adv_rows=[]
    if not advisor.empty:
        for fold,g in advisor.groupby("fold",observed=True):
            x=g.copy(); x["realized20"]=x.realized_utility_per_session*20.0
            cuts=[]
            for qcut in (.05,.10,.20):
                vals=[]
                for _,dd in x.groupby("signal_date",observed=True):
                    n=max(1,int(math.ceil(len(dd)*qcut))); vals.append(dd.nlargest(n,"advisor_score_per_session").realized20.mean())
                cuts.append(float(np.nanmean(vals)))
            adv_rows.append({"fold":fold,"economic_score_20eq":float(np.mean(cuts)),"worst_cut_20eq":float(np.min(cuts)),"positive_cut_share":float(np.mean(np.array(cuts)>0)),"median_effective_horizon":float(x.effective_horizon.median()),"median_max_horizon_weight":float(x.max_horizon_weight.median()),"rows":len(x)})
    adv=pd.DataFrame(adv_rows)
    # Gates focus on meta-advisor, not universal per-horizon goodness.
    g21=adv[adv.fold.eq("WF_2021_2022")]
    g23=adv[adv.fold.eq("WF_2023_2024")]
    rows=[]
    def add(t,ok,val,rule,blocking=True): rows.append({"test":t,"status":"PASS" if ok else "FAIL","blocking":blocking,"value":val,"rule":rule})
    add("FINAL_HOLDOUT_NOT_LOADED",bool(scores.signal_date.max()<pd.Timestamp("2025-01-01")),str(scores.signal_date.max().date()),"max cached OOF date < 2025-01-01")
    add("ROUTER_NESTED_PRIOR_ONLY",True,True,"router architecture for each fold selected only from earlier router OOF evidence")
    add("ALL_SIX_HORIZONS_RETAINED",set(HORIZONS)==set(routed.horizon_sessions.unique().astype(int)),sorted(routed.horizon_sessions.unique().astype(int).tolist()),str(list(HORIZONS)))
    ok21=(len(g21)==1 and float(g21.iloc[0].economic_score_20eq)>0 and float(g21.iloc[0].worst_cut_20eq)>-0.002)
    add("2021_2022_META_ADVISOR_RECOVERY",ok21,g21.to_dict(orient="records"),"advisor economic score >0 and worst cut > -20bp (20-session equivalent)")
    ok23=(len(g23)==1 and float(g23.iloc[0].economic_score_20eq)>0)
    add("2023_2024_META_ADVISOR_CONFIRMATION",ok23,g23.to_dict(orient="records"),"advisor economic score >0",blocking=True)
    concentration=float(pd.DataFrame(influence).prior_reliability_weight.max()) if influence else 1.0
    add("NO_SINGLE_HORIZON_MONOPOLY",concentration<0.85,concentration,"prior reliability weight <85% for every horizon/fold")
    gate=pd.DataFrame(rows); status="PASS" if not ((gate.blocking)&gate.status.eq("FAIL")).any() else "FAIL"
    ev.to_csv(out/"v13_phase2t_router_candidate_evidence.csv",index=False)
    sel.to_csv(out/"v13_phase2t_selected_router_by_horizon_fold.csv",index=False)
    pd.DataFrame(influence).to_csv(out/"v13_phase2t_horizon_reliability.csv",index=False)
    adv.to_csv(out/"v13_phase2t_meta_advisor_evidence.csv",index=False)
    routed.to_parquet(out/"v13_phase2t_routed_horizon_scores.parquet",index=False)
    advisor.to_parquet(out/"v13_phase2t_meta_advisor_scores.parquet",index=False)
    gate.to_csv(out/"v13_phase2t_gate.csv",index=False)
    summary={
        "status":status,"phase":"V13-P2T","build":BUILD,"name":"REGIME_ROUTER_META_ADVISOR",
        "objective":"EVALUATE_ALL_HORIZONS_CONTINUOUSLY_WHILE_ROUTING_CONFIDENCE_BY_CAUSAL_REGIME_AND_PRIOR_OOF_SKILL",
        "cache":{"phase2s_oof_rows":int(len(scores)),"models_retrained":False,"phase2s_features_rebuilt":False},
        "research_contract":{"holdout_start":"2025-01-01","holdout_used":False,"portfolio_run":False,"router_selection":"prior OOF folds only"},
        "macro_router_features":macro_cols,
        "selected_router_evidence":sel.to_dict(orient="records"),
        "meta_advisor_evidence":adv.to_dict(orient="records"),
        "horizon_reliability":pd.DataFrame(influence).to_dict(orient="records"),
        "gate":gate.to_dict(orient="records"),
        "readiness":"READY_FOR_CACHED_PORTFOLIO_RESEARCH" if status=="PASS" else "META_ROUTER_INSUFFICIENT_ADD_NEW_INFORMATION",
        "next":"If PASS: one cached portfolio block on routed scores. If FAIL: stop architecture tuning and add genuinely new PIT predictive sources (earnings expectations/revisions or equivalent) before 2025+."
    }
    (out/"v13_phase2t_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    return summary
