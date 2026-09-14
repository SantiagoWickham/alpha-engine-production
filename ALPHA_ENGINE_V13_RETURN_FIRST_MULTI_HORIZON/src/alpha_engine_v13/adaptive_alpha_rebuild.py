from __future__ import annotations

import json, math, tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

BUILD = "V13_P2R_ADAPTIVE_MULTI_EXPERT_ALPHA_REBUILD_2026-09-12"
HORIZONS = (5, 10, 20, 60, 120, 252)
EXPERTS = (
    "RIDGE_RANK_DECAY",
    "HGB_RANK_DECAY",
    "HGB_ABS_RETURN_DECAY",
    "HGB_BENCH_EXCESS_DECAY",
    "HGB_WINNER_DECAY",
)
FOLDS = (
    ("WF_2017_2018", "2017-01-03", "2019-01-02"),
    ("WF_2019_2020", "2019-01-02", "2021-01-04"),
    ("WF_2021_2022", "2021-01-04", "2023-01-03"),
    ("WF_2023_2024", "2023-01-03", "2025-01-01"),
)
ENSEMBLE_SCHEMES = (
    ("EQUAL", 0.0, 0.0),
    ("ADAPTIVE_T075", 0.75, 0.04),
    ("ADAPTIVE_T150", 1.50, 0.04),
    ("ADAPTIVE_T250", 2.50, 0.04),
)

@dataclass(frozen=True)
class Cfg:
    p: dict


def _date(s):
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")


def load_cfg(workspace: Path) -> Cfg:
    with (workspace / "config" / "v13_phase2r.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase2r"])


def load_phase1(workspace: Path) -> dict:
    p = workspace / "outputs" / "v13_phase1_summary.json"
    if not p.exists():
        raise FileNotFoundError(p)
    x = json.loads(p.read_text(encoding="utf-8"))
    if x.get("status") != "PASS":
        raise RuntimeError("V13 Phase 1 must PASS")
    if x.get("research", {}).get("selection_uses_2025_plus") is not False:
        raise RuntimeError("Phase 1 holdout firewall not active")
    return x


def load_inputs(workspace: Path, cfg: Cfg) -> tuple[pd.DataFrame, pd.DataFrame]:
    f = pd.read_parquet(workspace / cfg.p["feature_library"])
    t = pd.read_parquet(workspace / cfg.p["research_targets"])
    for x in (f, t):
        x["signal_date"] = _date(x["signal_date"])
        x["ticker"] = x["ticker"].astype(str).str.upper().str.strip()
    hold = pd.Timestamp(cfg.p["holdout_start"])
    if (f["signal_date"] >= hold).any() or (t["signal_date"] >= hold).any():
        raise RuntimeError("HOLDOUT BREACH: 2025+ loaded")
    return f.sort_values(["signal_date","ticker"]), t.sort_values(["signal_date","ticker"])


def usable_features(features: pd.DataFrame, cfg: Cfg) -> list[str]:
    cols = [c for c in features.columns if c not in {"signal_date","ticker"}]
    x = features[features["signal_date"] >= pd.Timestamp(cfg.p["research_start"])]
    cov = x[cols].notna().mean()
    keep = cov[cov >= float(cfg.p["minimum_feature_coverage"])].index.tolist()
    forbidden = {"close","adj_close","feature_price","target_total_return_price"}
    return [c for c in keep if c not in forbidden]


def cross_sectional_rank_features(features: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = features[["signal_date","ticker"]].copy()
    rr = features.groupby("signal_date", observed=True)[cols].rank(method="average", pct=True)
    for c in cols:
        out[c] = pd.to_numeric(rr[c], errors="coerce").astype("float32")
    return out


def add_regime_features(raw: pd.DataFrame, ranked: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    candidates = [c for c in ["mom_20d","mom_60d","mom_120d","vol_20","vol_60","rel_mom_spy_20","rel_mom_qqq_20"] if c in raw]
    daily = pd.DataFrame(index=pd.DatetimeIndex(sorted(raw["signal_date"].dropna().unique())))
    g = raw.groupby("signal_date", observed=True)
    if "mom_20d" in raw:
        daily["regime_breadth_mom20"] = g["mom_20d"].apply(lambda s: (pd.to_numeric(s,errors="coerce") > 0).mean())
        daily["regime_dispersion_mom20"] = g["mom_20d"].std()
    if "mom_60d" in raw:
        daily["regime_breadth_mom60"] = g["mom_60d"].apply(lambda s: (pd.to_numeric(s,errors="coerce") > 0).mean())
        daily["regime_dispersion_mom60"] = g["mom_60d"].std()
    for c in ["vol_20","vol_60"]:
        if c in raw:
            daily[f"regime_median_{c}"] = g[c].median()
    for c in ["rel_mom_spy_20","rel_mom_qqq_20"]:
        if c in raw:
            daily[f"regime_breadth_{c}"] = g[c].apply(lambda s: (pd.to_numeric(s,errors="coerce") > 0).mean())
    zcols=[]
    for c in list(daily.columns):
        m = daily[c].rolling(252, min_periods=63).mean()
        s = daily[c].rolling(252, min_periods=63).std().replace(0,np.nan)
        z = ((daily[c]-m)/s).clip(-4,4)
        zn = c + "_z252"
        daily[zn] = z
        zcols.append(zn)
    daily = daily[zcols].reset_index().rename(columns={"index":"signal_date"})
    out = ranked.merge(daily, on="signal_date", how="left")
    interactions=[]
    pairs = [
        ("mom_20d","regime_breadth_mom20_z252"),
        ("mom_60d","regime_breadth_mom60_z252"),
        ("mom_20d","regime_median_vol_20_z252"),
        ("mom_60d","regime_median_vol_60_z252"),
        ("rel_mom_spy_20","regime_breadth_rel_mom_spy_20_z252"),
        ("rel_mom_qqq_20","regime_breadth_rel_mom_qqq_20_z252"),
    ]
    for a,b in pairs:
        if a in out and b in out:
            n=f"ix_{a}__{b}"
            out[n]=(pd.to_numeric(out[a],errors="coerce")-0.5)*pd.to_numeric(out[b],errors="coerce")
            interactions.append(n)
    return out, zcols + interactions


def merge_horizon(features: pd.DataFrame, targets: pd.DataFrame, h: int) -> pd.DataFrame:
    cols=["signal_date","ticker",f"target_end_date_{h}d",f"target_resolved_{h}d",f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]
    if f"winner_top_decile_{h}d" in targets:
        cols.append(f"winner_top_decile_{h}d")
    t=targets[cols].copy()
    t[f"target_end_date_{h}d"]=_date(t[f"target_end_date_{h}d"])
    t[f"target_resolved_{h}d"]=t[f"target_resolved_{h}d"].fillna(False).astype(bool)
    return features.merge(t,on=["signal_date","ticker"],how="inner",validate="one_to_one")


def purged_fold(df: pd.DataFrame, h: int, test_start: str, test_end: str, cfg: Cfg) -> tuple[pd.DataFrame,pd.DataFrame]:
    ts,te=pd.Timestamp(test_start),pd.Timestamp(test_end)
    start=max(pd.Timestamp(cfg.p["research_start"]), ts-pd.DateOffset(years=int(cfg.p["max_train_years"])))
    ec=f"target_end_date_{h}d"; rc=f"target_resolved_{h}d"; yc=f"fwd_return_{h}d"
    tr=df[(df.signal_date>=start)&(df.signal_date<ts)&df[rc]&df[ec].notna()&(df[ec]<ts)&df[yc].notna()].copy()
    tef=df[(df.signal_date>=ts)&(df.signal_date<te)&df[rc]&df[ec].notna()&(df[ec]<te)&df[yc].notna()].copy()
    if len(tr) and not (tr[ec]<ts).all(): raise RuntimeError("PURGE BREACH")
    return tr,tef


def _daily_rank(df: pd.DataFrame, col: str) -> np.ndarray:
    return df.groupby("signal_date", observed=True)[col].rank(method="average",pct=True).to_numpy(float)


def _clip_train_apply(train_y: np.ndarray, test_y: np.ndarray|None=None) -> tuple[np.ndarray,np.ndarray|None]:
    y=np.asarray(train_y,float); ok=np.isfinite(y)
    if ok.sum()==0: return y,test_y
    lo,hi=np.nanquantile(y[ok],[0.01,0.99]); yy=np.clip(y,lo,hi)
    return yy, None if test_y is None else np.clip(np.asarray(test_y,float),lo,hi)


def recency_weights(dates: pd.Series, half_life_sessions: int) -> np.ndarray:
    d=pd.DatetimeIndex(pd.to_datetime(dates).dt.normalize())
    uniq=pd.DatetimeIndex(sorted(d.unique()))
    pos=pd.Series(np.arange(len(uniq)),index=uniq)
    age=(len(uniq)-1)-pd.Series(d).map(pos).to_numpy(float)
    return np.power(0.5, age/max(float(half_life_sessions),1.0))


def select_features(train: pd.DataFrame, feature_cols: list[str], h: int, cfg: Cfg) -> tuple[list[str],pd.DataFrame]:
    yr=_daily_rank(train,f"fwd_return_{h}d")
    rows=[]
    for c in feature_cols:
        x=pd.to_numeric(train[c],errors="coerce").to_numpy(float)
        ok=np.isfinite(x)&np.isfinite(yr)
        cc=float(np.corrcoef(x[ok],yr[ok])[0,1]) if ok.sum()>=300 else np.nan
        rows.append((c,abs(cc) if np.isfinite(cc) else 0.0,cc))
    a=pd.DataFrame(rows,columns=["feature","abs_train_ic","train_ic"]).sort_values(["abs_train_ic","feature"],ascending=[False,True])
    pre=a.head(max(int(cfg.p["max_selected_features"])*2,int(cfg.p["minimum_selected_features"]))).feature.tolist()
    if len(pre):
        sample=train[pre]
        if len(sample)>int(cfg.p["correlation_sample_rows"]): sample=sample.sample(int(cfg.p["correlation_sample_rows"]),random_state=int(cfg.p["random_state"]))
        corr=sample.corr().abs()
        keep=[]
        for c in pre:
            if not keep or all((not np.isfinite(corr.loc[c,k])) or corr.loc[c,k]<float(cfg.p["correlation_prune_threshold"]) for k in keep):
                keep.append(c)
            if len(keep)>=int(cfg.p["max_selected_features"]): break
    else: keep=[]
    if len(keep)<int(cfg.p["minimum_selected_features"]):
        for c in a.feature:
            if c not in keep: keep.append(c)
            if len(keep)>=int(cfg.p["minimum_selected_features"]): break
    a["selected"]=a.feature.isin(keep)
    return keep,a


def _mat(df: pd.DataFrame, cols:list[str], fill=0.5) -> np.ndarray:
    x=df[cols].to_numpy(np.float32)
    return np.where(np.isfinite(x),x,fill).astype(np.float32)


def _ridge_predict(train,test,cols,y,w,alpha):
    x=_mat(train,cols); z=_mat(test,cols)
    mu=np.average(x,axis=0,weights=w); var=np.average((x-mu)**2,axis=0,weights=w); sd=np.sqrt(np.maximum(var,1e-8))
    x=(x-mu)/sd; z=(z-mu)/sd
    m=Ridge(alpha=float(alpha)); m.fit(x,y,sample_weight=w); return m.predict(z)


def fit_experts(train: pd.DataFrame, test: pd.DataFrame, cols:list[str], h:int, cfg:Cfg) -> dict[str,np.ndarray]:
    if train.empty or test.empty: return {e:np.full(len(test),np.nan) for e in EXPERTS}
    w=recency_weights(train.signal_date,int(cfg.p["recency_half_life_sessions"]))
    y_rank=_daily_rank(train,f"fwd_return_{h}d")
    y_abs,_=_clip_train_apply(pd.to_numeric(train[f"fwd_return_{h}d"],errors="coerce").to_numpy(float))
    ex=np.nanmin(train[[f"excess_spy_{h}d",f"excess_qqq_{h}d"]].to_numpy(float),axis=1)
    y_ex,_=_clip_train_apply(ex)
    winner=(y_rank>=float(cfg.p["winner_quantile"])).astype(int)
    valid=np.isfinite(y_rank)
    out={}
    out["RIDGE_RANK_DECAY"]=_ridge_predict(train.loc[valid],test,cols,y_rank[valid],w[valid],cfg.p["ridge_alpha"])
    hp=dict(loss="squared_error",learning_rate=float(cfg.p["hgb_learning_rate"]),max_iter=int(cfg.p["hgb_max_iter"]),max_leaf_nodes=int(cfg.p["hgb_max_leaf_nodes"]),min_samples_leaf=int(cfg.p["hgb_min_samples_leaf"]),l2_regularization=float(cfg.p["hgb_l2"]),random_state=int(cfg.p["random_state"]))
    xt=train[cols].to_numpy(np.float32); xv=test[cols].to_numpy(np.float32)
    for name,y in [("HGB_RANK_DECAY",y_rank),("HGB_ABS_RETURN_DECAY",y_abs),("HGB_BENCH_EXCESS_DECAY",y_ex)]:
        ok=np.isfinite(y)
        m=HistGradientBoostingRegressor(**hp); m.fit(xt[ok],y[ok],sample_weight=w[ok]); out[name]=m.predict(xv)
    cp=dict(learning_rate=float(cfg.p["hgb_learning_rate"]),max_iter=int(cfg.p["hgb_max_iter"]),max_leaf_nodes=int(cfg.p["hgb_max_leaf_nodes"]),min_samples_leaf=int(cfg.p["hgb_min_samples_leaf"]),l2_regularization=float(cfg.p["hgb_l2"]),random_state=int(cfg.p["random_state"]))
    ok=np.isfinite(y_rank)
    c=HistGradientBoostingClassifier(**cp); c.fit(xt[ok],winner[ok],sample_weight=w[ok]); out["HGB_WINNER_DECAY"]=c.predict_proba(xv)[:,1]
    return out


def normalize(df:pd.DataFrame,raw:np.ndarray)->np.ndarray:
    q=pd.DataFrame({"d":df.signal_date.to_numpy(),"x":raw})
    return q.groupby("d",observed=True).x.rank(method="average",pct=True).to_numpy(float)


def evaluate(test:pd.DataFrame,score:np.ndarray,h:int,cutoffs:list[float])->dict:
    z=test[["signal_date","ticker",f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]].copy(); z["score"]=score
    z=z[np.isfinite(z.score)&z[f"fwd_return_{h}d"].notna()].copy()
    if z.empty:return {"economic_score":np.nan,"worst_cut_robust_excess":np.nan,"mean_rank_ic":np.nan,"positive_cut_share":0.0,"winner_lift":np.nan}
    z["yr"]=z.groupby("signal_date",observed=True)[f"fwd_return_{h}d"].rank(method="average",pct=True)
    ics=[]
    for _,g in z.groupby("signal_date",observed=True):
        if len(g)>=20 and g.score.nunique()>1 and g.yr.nunique()>1: ics.append(g.score.corr(g.yr))
    cuts=[]
    for q in cutoffs:
        s=z[z.score>=1-float(q)]
        if s.empty:continue
        d=s.groupby("signal_date",observed=True)[[f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]].mean()
        ex=[float(d[c].mean()) for c in d.columns]
        cuts.append(min(ex))
    top=z[z.score>=0.90]
    base=float((z.yr>=0.90).mean()) if len(z) else np.nan
    hit=float((top.yr>=0.90).mean()) if len(top) else np.nan
    return {
        "economic_score":float(np.mean(cuts)) if cuts else np.nan,
        "worst_cut_robust_excess":float(np.min(cuts)) if cuts else np.nan,
        "mean_rank_ic":float(np.nanmean(ics)) if ics else np.nan,
        "positive_cut_share":float(np.mean(np.array(cuts)>0)) if cuts else 0.0,
        "winner_lift":float(hit/base) if np.isfinite(hit) and np.isfinite(base) and base>0 else np.nan,
    }


def expert_weights(prior_evidence:pd.DataFrame, scheme:str, temp:float, floor:float)->dict[str,float]:
    if scheme=="EQUAL" or prior_evidence.empty: return {e:1/len(EXPERTS) for e in EXPERTS}
    a=prior_evidence.groupby("expert",as_index=False).agg(economic_score=("economic_score","mean"),worst=("worst_cut_robust_excess","min"),winner=("winner_lift","mean"))
    a=a.set_index("expert").reindex(EXPERTS)
    skill=a.economic_score.fillna(-1).to_numpy(float)+0.35*np.minimum(a.worst.fillna(-1).to_numpy(float),0)
    med=np.nanmedian(skill); mad=np.nanmedian(np.abs(skill-med)); scale=max(1.4826*mad,1e-6)
    z=np.clip((skill-med)/scale,-5,5)/max(float(temp),1e-6)
    z-=np.max(z); w=np.exp(z); w=w/w.sum()
    if floor>0:
        w=np.maximum(w,float(floor)); w=w/w.sum()
    return {e:float(v) for e,v in zip(EXPERTS,w)}


def blend_scores(score_frame:pd.DataFrame, weights:dict[str,float])->np.ndarray:
    arr=np.column_stack([score_frame[e].to_numpy(float) for e in EXPERTS])
    w=np.array([weights[e] for e in EXPERTS],float)
    ok=np.isfinite(arr)
    denom=(ok*w).sum(axis=1); num=np.nansum(arr*w,axis=1)
    return np.divide(num,denom,out=np.full(len(arr),np.nan),where=denom>0)


def run_horizon(df:pd.DataFrame, all_features:list[str], h:int,cfg:Cfg):
    fold_expert_scores={}; evidence=[]; feature_aud=[]
    for fold,ts,te in FOLDS:
        tr,va=purged_fold(df,h,ts,te,cfg)
        if len(tr)<5000 or len(va)<1000: raise RuntimeError(f"Insufficient rows h={h} {fold}: {len(tr)}/{len(va)}")
        cols,aud=select_features(tr,all_features,h,cfg); aud["horizon_sessions"]=h; aud["fold"]=fold; feature_aud.append(aud)
        preds=fit_experts(tr,va,cols,h,cfg)
        sf=va[["signal_date","ticker"]].copy()
        for e,r in preds.items():
            s=normalize(va,r); sf[e]=s; ev=evaluate(va,s,h,[float(x) for x in cfg.p["evaluation_cutoffs"]]); evidence.append({"horizon_sessions":h,"fold":fold,"expert":e,"train_rows":len(tr),"test_rows":len(va),"selected_features":len(cols),**ev})
        fold_expert_scores[fold]=(va,sf)
    evdf=pd.DataFrame(evidence); nested_candidates=[]; scheme_rows=[]
    for scheme,temp,floor in ENSEMBLE_SCHEMES:
        parts=[]; prior=[]
        for fold,_,_ in FOLDS:
            va,sf=fold_expert_scores[fold]
            p=pd.concat(prior,ignore_index=True) if prior else pd.DataFrame()
            w=expert_weights(p,scheme,temp,floor)
            score=blend_scores(sf,w)
            score=normalize(va,score)
            ev=evaluate(va,score,h,[float(x) for x in cfg.p["evaluation_cutoffs"]])
            scheme_rows.append({"horizon_sessions":h,"scheme":scheme,"fold":fold,"expert_weights":json.dumps(w,sort_keys=True),**ev})
            zz=va[["signal_date","ticker"]].copy(); zz["horizon_sessions"]=h; zz["fold"]=fold; zz["scheme"]=scheme; zz["score"]=score; parts.append(zz)
            prior.append(evdf[evdf.fold.eq(fold)])
        nested_candidates.append(pd.concat(parts,ignore_index=True))
    sr=pd.DataFrame(scheme_rows)
    agg=sr.groupby("scheme",as_index=False).agg(economic_score=("economic_score","mean"),worst_fold=("economic_score","min"),worst_cut=("worst_cut_robust_excess","min"),mean_ic=("mean_rank_ic","mean"),winner_lift=("winner_lift","mean"),positive_cut_share=("positive_cut_share","mean"))
    agg=agg.sort_values(["economic_score","worst_fold","worst_cut","winner_lift","mean_ic","scheme"],ascending=[False,False,False,False,False,True])
    chosen=str(agg.iloc[0].scheme)
    cand=pd.concat(nested_candidates,ignore_index=True); oof=cand[cand.scheme.eq(chosen)].copy()
    spec=next(x for x in ENSEMBLE_SCHEMES if x[0]==chosen)
    final_w=expert_weights(evdf,chosen,spec[1],spec[2])
    return evdf,sr,agg.assign(horizon_sessions=h),oof,{"horizon_sessions":h,"selected_scheme":chosen,"final_expert_weights":final_w},pd.concat(feature_aud,ignore_index=True)


def build_phase2r(workspace:Path)->dict:
    cfg=load_cfg(workspace); p1=load_phase1(workspace); raw,targ=load_inputs(workspace,cfg)
    base=usable_features(raw,cfg); ranked=cross_sectional_rank_features(raw,base); feat,extra=add_regime_features(raw,ranked); all_features=base+extra
    out=workspace/"outputs"; out.mkdir(parents=True,exist_ok=True)
    expert_all=[]; scheme_all=[]; agg_all=[]; oof_all=[]; specs=[]; fa=[]
    for h in HORIZONS:
        print(f"Phase2R horizon {h}D ...",flush=True)
        d=merge_horizon(feat,targ,h)
        e,s,a,o,sp,f=run_horizon(d,all_features,h,cfg)
        expert_all.append(e); scheme_all.append(s); agg_all.append(a); oof_all.append(o); specs.append(sp); fa.append(f)
    expert=pd.concat(expert_all,ignore_index=True); scheme=pd.concat(scheme_all,ignore_index=True); ens=pd.concat(agg_all,ignore_index=True); oof=pd.concat(oof_all,ignore_index=True); feat_aud=pd.concat(fa,ignore_index=True)
    # Join outcomes only for evaluation summaries, never into saved score feature surface.
    evrows=[]
    for h in HORIZONS:
        d=merge_horizon(oof[oof.horizon_sessions.eq(h)][["signal_date","ticker","score"]],targ,h)
        for fold,_,_ in FOLDS:
            q=d[d.signal_date.between(pd.Timestamp(dict((x[0],x[1]) for x in FOLDS)[fold]),pd.Timestamp(dict((x[0],x[2]) for x in FOLDS)[fold]),inclusive="left")]
            if len(q): evrows.append({"horizon_sessions":h,"fold":fold,**evaluate(q,q.score.to_numpy(float),h,[float(x) for x in cfg.p["evaluation_cutoffs"]])})
    oof_evidence=pd.DataFrame(evrows)
    # gate uses all pre-2025 OOF; 2025 remains untouched.
    byh=oof_evidence.groupby("horizon_sessions",as_index=False).agg(economic_score=("economic_score","mean"),worst_fold=("economic_score","min"),winner_lift=("winner_lift","mean"),positive_cut_share=("positive_cut_share","mean"),mean_ic=("mean_rank_ic","mean"))
    reg=oof_evidence[oof_evidence.fold.eq("WF_2021_2022")].copy(); recent=oof_evidence[oof_evidence.fold.eq("WF_2023_2024")].copy()
    rows=[]
    def add(t,ok,val,rule,blocking=True):rows.append({"test":t,"status":"PASS" if ok else "FAIL","blocking":blocking,"value":val,"rule":rule})
    add("PHASE1_INPUT_PASS",p1.get("status")=="PASS",p1.get("status"),"Phase 1 must PASS")
    add("FINAL_HOLDOUT_NOT_LOADED",max(raw.signal_date.max(),targ.signal_date.max())<pd.Timestamp(cfg.p["holdout_start"]),str(max(raw.signal_date.max(),targ.signal_date.max()).date()),"all research data < 2025-01-01")
    add("ALL_SIX_HORIZONS_REBUILT",sorted(byh.horizon_sessions.astype(int).tolist())==list(HORIZONS),byh.horizon_sessions.astype(int).tolist(),str(list(HORIZONS)))
    add("PRE2025_OOF_ALPHA_RECOVERED",int((byh.economic_score>0).sum())>=4 and float(byh.economic_score.median())>0,{"positive_horizons":int((byh.economic_score>0).sum()),"median_economic_score":float(byh.economic_score.median())},">=4/6 positive and median > 0")
    add("2021_2022_REGIME_RECOVERY",int((reg.economic_score>0).sum())>=3 and float(reg.economic_score.median())>0,{"positive_horizons":int((reg.economic_score>0).sum()),"median_economic_score":float(reg.economic_score.median())},">=3/6 positive and median > 0")
    add("2023_2024_RECENT_REGIME_EVIDENCE",int((recent.economic_score>0).sum())>=3 and float(recent.economic_score.median())>0,{"positive_horizons":int((recent.economic_score>0).sum()),"median_economic_score":float(recent.economic_score.median())},">=3/6 positive and median > 0")
    add("WINNER_CAPTURE_PRESENT",float(byh.winner_lift.median())>1.0,float(byh.winner_lift.median()),"median OOF top-decile winner lift > 1")
    gate=pd.DataFrame(rows); status="PASS" if not ((gate.blocking)&(gate.status.eq("FAIL"))).any() else "FAIL"
    expert.to_csv(out/"v13_phase2r_expert_fold_leaderboard.csv",index=False)
    scheme.to_csv(out/"v13_phase2r_scheme_fold_evidence.csv",index=False)
    ens.to_csv(out/"v13_phase2r_ensemble_leaderboard.csv",index=False)
    pd.DataFrame(specs).assign(final_expert_weights=lambda x:x.final_expert_weights.map(json.dumps)).to_csv(out/"v13_phase2r_selected_horizon_ensembles.csv",index=False)
    oof.to_parquet(out/"v13_phase2r_oof_scores.parquet",index=False)
    oof_evidence.to_csv(out/"v13_phase2r_oof_horizon_evidence.csv",index=False)
    reg.to_csv(out/"v13_phase2r_2021_2022_evidence.csv",index=False)
    recent.to_csv(out/"v13_phase2r_2023_2024_evidence.csv",index=False)
    feat_aud.to_csv(out/"v13_phase2r_feature_selection_audit.csv",index=False)
    gate.to_csv(out/"v13_phase2r_gate.csv",index=False)
    spec={"build":BUILD,"research_contract":"ALL_2015_2024_IS_PRE_HOLDOUT_RESEARCH; 2025+ HARD-BLOCKED","horizons":list(HORIZONS),"experts":list(EXPERTS),"folds":[list(x) for x in FOLDS],"ensemble_schemes":[list(x) for x in ENSEMBLE_SCHEMES],"base_feature_count":len(base),"regime_feature_count":len(extra),"selected_horizon_ensembles":specs,"holdout_start":cfg.p["holdout_start"],"holdout_used":False}
    (out/"v13_phase2r_model_spec.json").write_text(json.dumps(spec,indent=2,default=str),encoding="utf-8")
    summary={"status":status,"phase":"V13-P2R","build":BUILD,"name":cfg.p["name"],"objective":cfg.p["objective"],"research_contract":{"pre_holdout_research":"2015-01-02 through 2024-12-31 via purged walk-forward folds","holdout_start":cfg.p["holdout_start"],"holdout_used":False,"portfolio_research_run":False},"features":{"base":len(base),"regime_and_interactions":len(extra),"total":len(all_features)},"oof_rows":int(len(oof)),"selected_ensembles":{str(x['horizon_sessions']):x for x in specs},"oof_horizon_evidence":byh.to_dict(orient="records"),"regime_2021_2022":reg.to_dict(orient="records"),"recent_2023_2024":recent.to_dict(orient="records"),"gate":gate.to_dict(orient="records"),"readiness":"READY_FOR_FAST_PORTFOLIO_RESEARCH" if status=="PASS" else "PREDICTIVE_ENGINE_STILL_INSUFFICIENT","next":"If PASS, build a fast cached portfolio layer from v13_phase2r_oof_scores without retraining. If FAIL, do not optimize portfolio; expand predictive information set/targets before touching 2025+."}
    (out/"v13_phase2r_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    return summary
