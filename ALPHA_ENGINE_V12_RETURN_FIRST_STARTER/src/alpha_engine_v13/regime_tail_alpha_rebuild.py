from __future__ import annotations

import json, math, tomllib, time, urllib.request, urllib.parse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

BUILD = "V13_P2S_REGIME_TAIL_RESIDUAL_ALPHA_2026-09-12"
HORIZONS = (5, 10, 20, 60, 120, 252)
EXPERTS = (
    "RIDGE_RESIDUAL_RANK",
    "HGB_RESIDUAL_RANK",
    "HGB_RESIDUAL_RETURN",
    "HGB_UPSIDE_TAIL",
    "HGB_DOWNSIDE_AVOID",
)
FOLDS = (
    ("WF_2017_2018", "2017-01-03", "2019-01-02"),
    ("WF_2019_2020", "2019-01-02", "2021-01-04"),
    ("WF_2021_2022", "2021-01-04", "2023-01-03"),
    ("WF_2023_2024", "2023-01-03", "2025-01-01"),
)

@dataclass(frozen=True)
class Cfg:
    p: dict


def _date(s):
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")


def load_cfg(workspace: Path) -> Cfg:
    with (workspace / "config" / "v13_phase2s.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase2s"])


def load_contracts(workspace: Path) -> tuple[dict, dict, Path]:
    p0p = workspace / "outputs" / "v13_phase0_summary.json"
    p1p = workspace / "outputs" / "v13_phase1_summary.json"
    if not p0p.exists() or not p1p.exists():
        raise FileNotFoundError("Phase 0/1 outputs are required")
    p0 = json.loads(p0p.read_text(encoding="utf-8"))
    p1 = json.loads(p1p.read_text(encoding="utf-8"))
    if p0.get("status") != "PASS" or p1.get("status") != "PASS":
        raise RuntimeError("Phase 0 and Phase 1 must PASS")
    if p1.get("research", {}).get("selection_uses_2025_plus") is not False:
        raise RuntimeError("Holdout firewall is not active")
    src = p0.get("source_manifest", {}).get("source_v12_root")
    if not src:
        raise RuntimeError("Phase 0 source_v12_root not found")
    return p0, p1, Path(src)


def load_inputs(workspace: Path, cfg: Cfg) -> tuple[pd.DataFrame, pd.DataFrame]:
    f = pd.read_parquet(workspace / cfg.p["feature_library"])
    t = pd.read_parquet(workspace / cfg.p["research_targets"])
    for x in (f, t):
        x["signal_date"] = _date(x["signal_date"])
        x["ticker"] = x["ticker"].astype(str).str.upper().str.strip()
    hold = pd.Timestamp(cfg.p["holdout_start"])
    if (f.signal_date >= hold).any() or (t.signal_date >= hold).any():
        raise RuntimeError("HOLDOUT BREACH: 2025+ loaded")
    return f.sort_values(["signal_date", "ticker"]), t.sort_values(["signal_date", "ticker"])


def _sanitize_symbol(s: str) -> str:
    return s.replace("^", "IDX_").replace("/", "_")


def _yahoo_raw_close(symbol: str, start: str, end: str) -> pd.DataFrame:
    p1 = int(pd.Timestamp(start, tz="UTC").timestamp())
    p2 = int(pd.Timestamp(end, tz="UTC").timestamp())
    q = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?period1={p1}&period2={p2}&interval=1d&events=history&includeAdjustedClose=false"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AlphaEngineV13/1.0"})
    last = None
    for k in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                payload = json.loads(r.read().decode("utf-8"))
            res = payload["chart"]["result"][0]
            ts = res.get("timestamp", [])
            close = res["indicators"]["quote"][0].get("close", [])
            out = pd.DataFrame({"date": pd.to_datetime(ts, unit="s", utc=True).tz_convert(None).normalize(), symbol: close})
            out[symbol] = pd.to_numeric(out[symbol], errors="coerce")
            return out.dropna().drop_duplicates("date", keep="last").sort_values("date")
        except Exception as e:
            last = e
            time.sleep(1.0 + k)
    raise RuntimeError(f"Yahoo raw-close download failed for {symbol}: {last}")


def load_macro_raw(workspace: Path, cfg: Cfg) -> tuple[pd.DataFrame, pd.DataFrame]:
    cache = workspace / "data" / "v13" / "macro_regime"
    cache.mkdir(parents=True, exist_ok=True)
    hold = pd.Timestamp(cfg.p["holdout_start"])
    start = "2013-01-01"
    end = "2025-01-02"
    frames = []
    audit = []
    for sym in cfg.p["macro_symbols"]:
        path = cache / f"{_sanitize_symbol(sym)}_raw_close.parquet"
        source = "CACHE"
        x = None
        if path.exists():
            try:
                x = pd.read_parquet(path)
                x["date"] = _date(x["date"])
                if sym not in x.columns or x.date.min() > pd.Timestamp("2014-01-15") or x.date.max() < pd.Timestamp("2024-12-20"):
                    x = None
            except Exception:
                x = None
        if x is None:
            source = "YAHOO_RAW_CLOSE"
            x = _yahoo_raw_close(sym, start, end)
            x = x[x.date < hold].copy()
            x.to_parquet(path, index=False)
        else:
            x = x[x.date < hold].copy()
        frames.append(x[["date", sym]])
        audit.append({"symbol": sym, "source": source, "rows": int(len(x)), "first_date": str(x.date.min().date()) if len(x) else "", "last_date": str(x.date.max().date()) if len(x) else "", "coverage_value": float(x[sym].notna().mean()) if len(x) else 0.0})
    m = frames[0]
    for x in frames[1:]:
        m = m.merge(x, on="date", how="outer", validate="one_to_one")
    m = m.sort_values("date").reset_index(drop=True)
    if (m.date >= hold).any():
        raise RuntimeError("HOLDOUT BREACH in macro data")
    return m, pd.DataFrame(audit)


def macro_features(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    x = raw.sort_values("date").copy()
    symbols = [c for c in x.columns if c != "date"]
    out = pd.DataFrame({"signal_date": x.date})
    rets = {}
    for s in symbols:
        p = pd.to_numeric(x[s], errors="coerce")
        r1 = p.pct_change(fill_method=None)
        rets[s] = r1
        for h in (5, 20, 60, 120):
            z = p / p.shift(h) - 1.0
            out[f"macro_{_sanitize_symbol(s).lower()}_ret{h}"] = z
        out[f"macro_{_sanitize_symbol(s).lower()}_vol20"] = r1.rolling(20, min_periods=15).std() * np.sqrt(252)
        out[f"macro_{_sanitize_symbol(s).lower()}_vol60"] = r1.rolling(60, min_periods=45).std() * np.sqrt(252)
    def spread(a, b, h):
        ca=f"macro_{_sanitize_symbol(a).lower()}_ret{h}"; cb=f"macro_{_sanitize_symbol(b).lower()}_ret{h}"
        if ca in out and cb in out: out[f"macro_spread_{_sanitize_symbol(a).lower()}_{_sanitize_symbol(b).lower()}_{h}"] = out[ca]-out[cb]
    for h in (20,60,120):
        spread("IWM","SPY",h); spread("QQQ","SPY",h); spread("HYG","TLT",h)
    # PIT rolling z-scores for all macro levels/returns; level z-score especially useful for VIX/rates proxies.
    for s in symbols:
        p = pd.to_numeric(x[s], errors="coerce")
        lp = np.log(p.where(p>0))
        mu = lp.rolling(252, min_periods=63).mean(); sd = lp.rolling(252, min_periods=63).std().replace(0,np.nan)
        out[f"macro_{_sanitize_symbol(s).lower()}_level_z252"] = ((lp-mu)/sd).clip(-5,5)
    base_cols=[c for c in out.columns if c!="signal_date"]
    # Standardize return/vol/spread features only with trailing data, not future information.
    zextra={}
    for c in list(base_cols):
        if c.endswith("level_z252"): continue
        s=pd.to_numeric(out[c],errors="coerce")
        mu=s.rolling(252,min_periods=63).mean(); sd=s.rolling(252,min_periods=63).std().replace(0,np.nan)
        zextra[c+"_z252"] = ((s-mu)/sd).clip(-5,5)
    if zextra:
        out=pd.concat([out,pd.DataFrame(zextra,index=out.index)],axis=1)
    keep=[c for c in out.columns if c=="signal_date" or c.endswith("_z252")]
    return out[keep], [c for c in keep if c!="signal_date"]


def load_canonical_market(source: Path, cfg: Cfg) -> pd.DataFrame:
    p = source / cfg.p["canonical_panel"]
    if not p.exists(): raise FileNotFoundError(p)
    x = pd.read_parquet(p)
    dcol = "date" if "date" in x.columns else "signal_date"
    if dcol not in x or "ticker" not in x or "close" not in x:
        raise RuntimeError("Canonical panel lacks date/ticker/close")
    x=x.rename(columns={dcol:"date"})
    x["date"]=_date(x["date"]); x["ticker"]=x["ticker"].astype(str).str.upper().str.strip(); x["close"]=pd.to_numeric(x["close"],errors="coerce")
    x=x[(x.date<pd.Timestamp(cfg.p["holdout_start"])) & x.close.gt(0)].copy()
    return x[["date","ticker","close"]].drop_duplicates(["date","ticker"],keep="last").sort_values(["ticker","date"])


def beta_exposure_features(market: pd.DataFrame, macro_raw: pd.DataFrame, keys: pd.DataFrame) -> pd.DataFrame:
    m=macro_raw.sort_values("date").copy()
    syms=[s for s in ["SPY","QQQ","IWM","TLT","HYG","UUP","^VIX"] if s in m]
    for s in syms: m[f"{_sanitize_symbol(s).lower()}_r1"] = pd.to_numeric(m[s],errors="coerce").pct_change(fill_method=None)
    rcols=[f"{_sanitize_symbol(s).lower()}_r1" for s in syms]
    z=market.merge(m[["date"]+rcols],on="date",how="left")
    frames=[]
    for _,g in z.groupby("ticker",sort=False):
        g=g.sort_values("date").copy(); r=g.close.pct_change(fill_method=None)
        o=g[["date","ticker"]].copy()
        for s in syms:
            c=f"{_sanitize_symbol(s).lower()}_r1"; mr=pd.to_numeric(g[c],errors="coerce")
            var=mr.rolling(60,min_periods=45).var().replace(0,np.nan)
            cov=r.rolling(60,min_periods=45).cov(mr)
            o[f"beta_{_sanitize_symbol(s).lower()}_60"]=(cov/var).clip(-3,5)
        # Longer beta only for main benchmarks.
        for s in [q for q in ["SPY","QQQ"] if q in syms]:
            c=f"{_sanitize_symbol(s).lower()}_r1"; mr=pd.to_numeric(g[c],errors="coerce")
            var=mr.rolling(120,min_periods=90).var().replace(0,np.nan); cov=r.rolling(120,min_periods=90).cov(mr)
            o[f"beta_{s.lower()}_120"]=(cov/var).clip(-3,5)
        frames.append(o)
    b=pd.concat(frames,ignore_index=True)
    k=keys.rename(columns={"signal_date":"date"})[["date","ticker"]].drop_duplicates()
    return k.merge(b,on=["date","ticker"],how="left",validate="one_to_one").rename(columns={"date":"signal_date"})


def usable_features(features: pd.DataFrame, cfg: Cfg) -> list[str]:
    cols=[c for c in features.columns if c not in {"signal_date","ticker"} and not c.startswith("_")]
    x=features[features.signal_date>=pd.Timestamp(cfg.p["research_start"])]
    cov=x[cols].notna().mean()
    forbidden={"close","adj_close","feature_price","target_total_return_price"}
    return [c for c in cov[cov>=float(cfg.p["minimum_feature_coverage"])].index.tolist() if c not in forbidden]


def build_enriched_features(workspace: Path, source: Path, base: pd.DataFrame, cfg: Cfg) -> tuple[pd.DataFrame,list[str],pd.DataFrame]:
    macro_raw,audit=load_macro_raw(workspace,cfg); mf,macro_cols=macro_features(macro_raw)
    market=load_canonical_market(source,cfg)
    betas=beta_exposure_features(market,macro_raw,base[["signal_date","ticker"]])
    x=base.merge(betas,on=["signal_date","ticker"],how="left",validate="one_to_one")
    beta_cols=[c for c in betas.columns if c not in {"signal_date","ticker"}]
    stock_cols=usable_features(x,cfg)
    ranked=x[["signal_date","ticker"]].copy()
    rr=x.groupby("signal_date",observed=True)[stock_cols].rank(method="average",pct=True)
    for c in stock_cols: ranked[c]=pd.to_numeric(rr[c],errors="coerce").astype("float32")
    # Keep raw benchmark betas hidden for residual-target construction.
    if "beta_spy_60" in x: ranked["_beta_spy_60_raw"]=pd.to_numeric(x["beta_spy_60"],errors="coerce")
    if "beta_qqq_60" in x: ranked["_beta_qqq_60_raw"]=pd.to_numeric(x["beta_qqq_60"],errors="coerce")
    ranked=ranked.merge(mf,on="signal_date",how="left",validate="many_to_one")
    interactions=[]
    pairs=[
        ("mom_20d","macro_tlt_ret20_z252"),
        ("mom_60d","macro_tlt_ret60_z252"),
        ("rel_mom_spy_20","macro_iwm_ret20_z252"),
        ("rel_mom_qqq_20","macro_qqq_ret20_z252"),
        ("size_log_market_cap","macro_spread_iwm_spy_20_z252"),
        ("downside_vol_60","macro_idx_vix_level_z252"),
        ("earnings_yield","macro_tlt_ret60_z252"),
        ("cash_assets","macro_hyg_ret20_z252"),
        ("mom_120d","macro_uup_ret60_z252"),
    ]
    for a,b in pairs:
        if a in ranked and b in ranked:
            n=f"ix_{a}__{b}"; ranked[n]=(pd.to_numeric(ranked[a],errors="coerce")-0.5)*pd.to_numeric(ranked[b],errors="coerce"); interactions.append(n)
    model_cols=[c for c in ranked.columns if c not in {"signal_date","ticker"} and not c.startswith("_")]
    return ranked.sort_values(["signal_date","ticker"]),model_cols,audit


def _weighted_row_mean(vals: np.ndarray, weights: np.ndarray) -> np.ndarray:
    ok=np.isfinite(vals); w=ok*weights.reshape(1,-1); d=w.sum(axis=1); n=np.nansum(vals*weights.reshape(1,-1),axis=1)
    return np.divide(n,d,out=np.full(len(vals),np.nan),where=d>0)


def merge_horizon(features: pd.DataFrame, targets: pd.DataFrame, h: int) -> pd.DataFrame:
    cols=["signal_date","ticker",f"target_end_date_{h}d",f"target_resolved_{h}d",f"fwd_return_{h}d",f"spy_fwd_return_{h}d",f"qqq_fwd_return_{h}d",f"uew_fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]
    t=targets[cols].copy(); t[f"target_end_date_{h}d"]=_date(t[f"target_end_date_{h}d"]); t[f"target_resolved_{h}d"]=t[f"target_resolved_{h}d"].fillna(False).astype(bool)
    z=features.merge(t,on=["signal_date","ticker"],how="inner",validate="one_to_one")
    r=pd.to_numeric(z[f"fwd_return_{h}d"],errors="coerce").to_numpy(float)
    bs=pd.to_numeric(z.get("_beta_spy_60_raw",1.0),errors="coerce").fillna(1.0).clip(-1,3).to_numpy(float)
    bq=pd.to_numeric(z.get("_beta_qqq_60_raw",1.0),errors="coerce").fillna(1.0).clip(-1,3).to_numpy(float)
    spy=pd.to_numeric(z[f"spy_fwd_return_{h}d"],errors="coerce").to_numpy(float); qqq=pd.to_numeric(z[f"qqq_fwd_return_{h}d"],errors="coerce").to_numpy(float); uew=pd.to_numeric(z[f"uew_fwd_return_{h}d"],errors="coerce").to_numpy(float)
    vals=np.column_stack([r-uew, r-bs*spy, r-bq*qqq])
    z["_alpha_residual"]=_weighted_row_mean(vals,np.array([0.40,0.30,0.30]))
    z["_alpha_rank"]=z.groupby("signal_date",observed=True)["_alpha_residual"].rank(method="average",pct=True)
    z["_upside_tail"]=(z["_alpha_rank"]>=0.90).astype(int); z["_downside_tail"]=(z["_alpha_rank"]<=0.20).astype(int)
    return z


def purged_fold(df: pd.DataFrame, h: int, test_start: str, test_end: str, cfg: Cfg) -> tuple[pd.DataFrame,pd.DataFrame]:
    ts,te=pd.Timestamp(test_start),pd.Timestamp(test_end); start=max(pd.Timestamp(cfg.p["research_start"]),ts-pd.DateOffset(years=int(cfg.p["max_train_years"])))
    ec=f"target_end_date_{h}d"; rc=f"target_resolved_{h}d"
    tr=df[(df.signal_date>=start)&(df.signal_date<ts)&df[rc]&df[ec].notna()&(df[ec]<ts)&df["_alpha_residual"].notna()].copy()
    va=df[(df.signal_date>=ts)&(df.signal_date<te)&df[rc]&df[ec].notna()&(df[ec]<te)&df["_alpha_residual"].notna()].copy()
    if len(tr) and not (tr[ec]<ts).all(): raise RuntimeError("PURGE BREACH")
    return tr,va


def recency_weights(dates: pd.Series, half_life_sessions: int) -> np.ndarray:
    d=pd.DatetimeIndex(pd.to_datetime(dates).dt.normalize()); uniq=pd.DatetimeIndex(sorted(d.unique())); pos=pd.Series(np.arange(len(uniq)),index=uniq); age=(len(uniq)-1)-pd.Series(d).map(pos).to_numpy(float)
    return np.power(0.5,age/max(float(half_life_sessions),1.0))


def select_features(train: pd.DataFrame, feature_cols: list[str], cfg: Cfg) -> tuple[list[str],pd.DataFrame]:
    y=pd.to_numeric(train["_alpha_rank"],errors="coerce").to_numpy(float); rows=[]
    for c in feature_cols:
        x=pd.to_numeric(train[c],errors="coerce").to_numpy(float); ok=np.isfinite(x)&np.isfinite(y); cc=float(np.corrcoef(x[ok],y[ok])[0,1]) if ok.sum()>=300 else np.nan
        rows.append((c,abs(cc) if np.isfinite(cc) else 0.0,cc))
    a=pd.DataFrame(rows,columns=["feature","abs_train_ic","train_ic"]).sort_values(["abs_train_ic","feature"],ascending=[False,True])
    pre=a.head(max(int(cfg.p["max_selected_features"])*2,int(cfg.p["minimum_selected_features"]))).feature.tolist(); keep=[]
    if pre:
        sample=train[pre]
        if len(sample)>int(cfg.p["correlation_sample_rows"]): sample=sample.sample(int(cfg.p["correlation_sample_rows"]),random_state=int(cfg.p["random_state"]))
        corr=sample.corr().abs()
        for c in pre:
            if not keep or all((not np.isfinite(corr.loc[c,k])) or corr.loc[c,k]<float(cfg.p["correlation_prune_threshold"]) for k in keep): keep.append(c)
            if len(keep)>=int(cfg.p["max_selected_features"]): break
    if len(keep)<int(cfg.p["minimum_selected_features"]):
        for c in a.feature:
            if c not in keep: keep.append(c)
            if len(keep)>=int(cfg.p["minimum_selected_features"]): break
    a["selected"]=a.feature.isin(keep); return keep,a


def _mat(df:pd.DataFrame,cols:list[str],fill=0.5)->np.ndarray:
    x=df[cols].to_numpy(np.float32); return np.where(np.isfinite(x),x,fill).astype(np.float32)


def _clip(y):
    y=np.asarray(y,float); ok=np.isfinite(y)
    if ok.sum()==0:return y
    lo,hi=np.nanquantile(y[ok],[.01,.99]); return np.clip(y,lo,hi)


def fit_experts(train:pd.DataFrame,test:pd.DataFrame,cols:list[str],cfg:Cfg)->dict[str,np.ndarray]:
    w=recency_weights(train.signal_date,int(cfg.p["recency_half_life_sessions"])); xt=_mat(train,cols); xv=_mat(test,cols)
    yr=pd.to_numeric(train["_alpha_rank"],errors="coerce").to_numpy(float); ya=_clip(pd.to_numeric(train["_alpha_residual"],errors="coerce").to_numpy(float)); up=train["_upside_tail"].to_numpy(int); dn=train["_downside_tail"].to_numpy(int)
    # Ridge rank expert
    mu=np.average(xt,axis=0,weights=w); var=np.average((xt-mu)**2,axis=0,weights=w); sd=np.sqrt(np.maximum(var,1e-8)); xr=(xt-mu)/sd; xvr=(xv-mu)/sd
    ok=np.isfinite(yr); rg=Ridge(alpha=float(cfg.p["ridge_alpha"])); rg.fit(xr[ok],yr[ok],sample_weight=w[ok]); out={"RIDGE_RESIDUAL_RANK":rg.predict(xvr)}
    hp=dict(loss="squared_error",learning_rate=float(cfg.p["hgb_learning_rate"]),max_iter=int(cfg.p["hgb_max_iter"]),max_leaf_nodes=int(cfg.p["hgb_max_leaf_nodes"]),min_samples_leaf=int(cfg.p["hgb_min_samples_leaf"]),l2_regularization=float(cfg.p["hgb_l2"]),random_state=int(cfg.p["random_state"]))
    for name,y in [("HGB_RESIDUAL_RANK",yr),("HGB_RESIDUAL_RETURN",ya)]:
        ok=np.isfinite(y); m=HistGradientBoostingRegressor(**hp); m.fit(xt[ok],y[ok],sample_weight=w[ok]); out[name]=m.predict(xv)
    cp=dict(learning_rate=float(cfg.p["hgb_learning_rate"]),max_iter=int(cfg.p["hgb_max_iter"]),max_leaf_nodes=int(cfg.p["hgb_max_leaf_nodes"]),min_samples_leaf=int(cfg.p["hgb_min_samples_leaf"]),l2_regularization=float(cfg.p["hgb_l2"]),random_state=int(cfg.p["random_state"]))
    cu=HistGradientBoostingClassifier(**cp); cu.fit(xt,up,sample_weight=w); out["HGB_UPSIDE_TAIL"]=cu.predict_proba(xv)[:,1]
    cd=HistGradientBoostingClassifier(**cp); cd.fit(xt,dn,sample_weight=w); out["HGB_DOWNSIDE_AVOID"]=1.0-cd.predict_proba(xv)[:,1]
    return out


def normalize(df:pd.DataFrame,raw:np.ndarray)->np.ndarray:
    q=pd.DataFrame({"d":df.signal_date.to_numpy(),"x":raw}); return q.groupby("d",observed=True).x.rank(method="average",pct=True).to_numpy(float)


def evaluate(test:pd.DataFrame,score:np.ndarray,h:int,cfg:Cfg)->dict:
    cols=["signal_date","ticker",f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d","_alpha_rank","_alpha_residual"]
    z=test[cols].copy(); z["score"]=score; z=z[np.isfinite(z.score)&z[f"fwd_return_{h}d"].notna()&z._alpha_rank.notna()].copy()
    if z.empty:return {"economic_score":np.nan,"worst_cut_robust_excess":np.nan,"mean_rank_ic":np.nan,"positive_cut_share":0.0,"winner_lift":np.nan,"loser_avoidance":np.nan,"residual_tail_spread":np.nan}
    ics=[]
    for _,g in z.groupby("signal_date",observed=True):
        if len(g)>=20 and g.score.nunique()>1 and g._alpha_rank.nunique()>1: ics.append(g.score.corr(g._alpha_rank))
    cuts=[]
    for q in [float(x) for x in cfg.p["evaluation_cutoffs"]]:
        s=z[z.score>=1-q]
        if s.empty:continue
        d=s.groupby("signal_date",observed=True)[[f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]].mean(); cuts.append(min(float(d[c].mean()) for c in d.columns))
    top=z[z.score>=0.90]
    base_win=float((z._alpha_rank>=float(cfg.p["winner_quantile"])).mean()); hit=float((top._alpha_rank>=float(cfg.p["winner_quantile"])).mean()) if len(top) else np.nan
    base_loss=float((z._alpha_rank<=float(cfg.p["loser_quantile"])).mean()); sel_loss=float((top._alpha_rank<=float(cfg.p["loser_quantile"])).mean()) if len(top) else np.nan
    broad=z[z.score>=1-float(cfg.p["broad_cutoff"])]
    return {"economic_score":float(np.mean(cuts)) if cuts else np.nan,"worst_cut_robust_excess":float(np.min(cuts)) if cuts else np.nan,"mean_rank_ic":float(np.nanmean(ics)) if ics else np.nan,"positive_cut_share":float(np.mean(np.array(cuts)>0)) if cuts else 0.0,"winner_lift":float(hit/base_win) if np.isfinite(hit) and base_win>0 else np.nan,"loser_avoidance":float(base_loss/sel_loss) if np.isfinite(sel_loss) and sel_loss>0 else (10.0 if sel_loss==0 else np.nan),"residual_tail_spread":float(top._alpha_residual.mean()) if len(top) else np.nan,"broad20_robust_excess":float(min(broad[[f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]].mean())) if len(broad) else np.nan}


def _rz(x:np.ndarray)->np.ndarray:
    x=np.asarray(x,float); med=np.nanmedian(x); mad=np.nanmedian(np.abs(x-med)); sc=max(1.4826*mad,1e-9); return np.clip((x-med)/sc,-4,4)


def expert_weights(prior:pd.DataFrame,cfg:Cfg)->dict[str,float]:
    if prior.empty:return {e:1/len(EXPERTS) for e in EXPERTS}
    a=prior.groupby("expert",as_index=False).agg(econ=("economic_score","mean"),worst=("worst_cut_robust_excess","min"),winner=("winner_lift","mean"),avoid=("loser_avoidance","mean"),ic=("mean_rank_ic","mean")).set_index("expert").reindex(EXPERTS)
    skill=.45*_rz(a.econ.to_numpy(float))+.20*_rz(a.worst.to_numpy(float))+.15*_rz(a.winner.to_numpy(float))+.15*_rz(a.avoid.to_numpy(float))+.05*_rz(a.ic.to_numpy(float))
    temp=max(float(cfg.p["expert_weight_temperature"]),1e-6); q=skill/temp; q-=np.nanmax(q); w=np.exp(np.nan_to_num(q,nan=-5.0)); w=w/w.sum(); floor=float(cfg.p["expert_weight_floor"]); w=np.maximum(w,floor); w=w/w.sum(); return {e:float(v) for e,v in zip(EXPERTS,w)}


def blend(sf:pd.DataFrame,w:dict[str,float])->np.ndarray:
    a=np.column_stack([sf[e].to_numpy(float) for e in EXPERTS]); ww=np.array([w[e] for e in EXPERTS]); ok=np.isfinite(a); d=(ok*ww).sum(1); n=np.nansum(a*ww,axis=1); return np.divide(n,d,out=np.full(len(a),np.nan),where=d>0)


def run_horizon(df:pd.DataFrame,features:list[str],h:int,cfg:Cfg):
    prior=[]; expert_rows=[]; ensemble_rows=[]; oof_parts=[]; feature_aud=[]; weight_rows=[]
    for fold,ts,te in FOLDS:
        tr,va=purged_fold(df,h,ts,te,cfg)
        if len(tr)<5000 or len(va)<1000: raise RuntimeError(f"Insufficient rows h={h} {fold}: {len(tr)}/{len(va)}")
        cols,aud=select_features(tr,features,cfg); aud["horizon_sessions"]=h; aud["fold"]=fold; feature_aud.append(aud)
        preds=fit_experts(tr,va,cols,cfg); sf=va[["signal_date","ticker"]].copy(); fold_e=[]
        for e,r in preds.items():
            s=normalize(va,r); sf[e]=s; ev=evaluate(va,s,h,cfg); row={"horizon_sessions":h,"fold":fold,"expert":e,"train_rows":len(tr),"test_rows":len(va),"selected_features":len(cols),**ev}; expert_rows.append(row); fold_e.append(row)
        p=pd.DataFrame(prior); w=expert_weights(p,cfg); weight_rows.extend([{"horizon_sessions":h,"fold":fold,"expert":e,"weight":v} for e,v in w.items()])
        sc=normalize(va,blend(sf,w)); ev=evaluate(va,sc,h,cfg); ensemble_rows.append({"horizon_sessions":h,"fold":fold,**ev})
        z=va[["signal_date","ticker"]].copy(); z["horizon_sessions"]=h; z["fold"]=fold; z["score"]=sc; oof_parts.append(z)
        prior.extend(fold_e)
    final_w=expert_weights(pd.DataFrame(expert_rows),cfg)
    return pd.DataFrame(expert_rows),pd.DataFrame(ensemble_rows),pd.concat(oof_parts,ignore_index=True),pd.concat(feature_aud,ignore_index=True),pd.DataFrame(weight_rows),final_w


def build_phase2s(workspace:Path)->dict:
    cfg=load_cfg(workspace); p0,p1,source=load_contracts(workspace); base,targ=load_inputs(workspace,cfg)
    feat,model_features,macro_audit=build_enriched_features(workspace,source,base,cfg)
    out=workspace/"outputs"; out.mkdir(parents=True,exist_ok=True)
    feat.to_parquet(out/"v13_phase2s_enriched_feature_surface.parquet",index=False); macro_audit.to_csv(out/"v13_phase2s_macro_source_audit.csv",index=False)
    expert_all=[]; ens_all=[]; oof_all=[]; faud_all=[]; w_all=[]; final=[]
    for h in HORIZONS:
        print(f"Phase2S horizon {h}D ...",flush=True); d=merge_horizon(feat,targ,h); e,en,o,fa,w,fw=run_horizon(d,model_features,h,cfg)
        expert_all.append(e); ens_all.append(en); oof_all.append(o); faud_all.append(fa); w_all.append(w); final.extend([{"horizon_sessions":h,"expert":k,"weight":v} for k,v in fw.items()])
    expert=pd.concat(expert_all,ignore_index=True); ens=pd.concat(ens_all,ignore_index=True); oof=pd.concat(oof_all,ignore_index=True); faud=pd.concat(faud_all,ignore_index=True); weights=pd.concat(w_all,ignore_index=True); finalw=pd.DataFrame(final)
    byh=ens.groupby("horizon_sessions",as_index=False).agg(economic_score=("economic_score","mean"),worst_fold=("economic_score","min"),worst_cut=("worst_cut_robust_excess","min"),mean_ic=("mean_rank_ic","mean"),winner_lift=("winner_lift","mean"),loser_avoidance=("loser_avoidance","mean"),positive_cut_share=("positive_cut_share","mean"),broad20_excess=("broad20_robust_excess","mean"))
    reg=ens[ens.fold.eq("WF_2021_2022")].copy(); recent=ens[ens.fold.eq("WF_2023_2024")].copy()
    rows=[]
    def add(t,ok,val,rule,blocking=True): rows.append({"test":t,"status":"PASS" if ok else "FAIL","blocking":blocking,"value":val,"rule":rule})
    hold=pd.Timestamp(cfg.p["holdout_start"])
    add("PHASE1_INPUT_PASS",p1.get("status")=="PASS",p1.get("status"),"Phase 1 must PASS")
    add("FINAL_HOLDOUT_NOT_LOADED",max(base.signal_date.max(),targ.signal_date.max(),feat.signal_date.max())<hold,str(max(base.signal_date.max(),targ.signal_date.max(),feat.signal_date.max()).date()),"all research data < 2025-01-01")
    macro_ok=bool((macro_audit.rows>=2500).all() and (pd.to_datetime(macro_audit.last_date)>=pd.Timestamp("2024-12-20")).all())
    add("MACRO_REGIME_DATA_READY",macro_ok,macro_audit[["symbol","rows","last_date"]].to_dict(orient="records"),"all regime proxies have long pre-2025 history")
    add("ALL_SIX_HORIZONS_REBUILT",sorted(byh.horizon_sessions.astype(int).tolist())==list(HORIZONS),byh.horizon_sessions.astype(int).tolist(),str(list(HORIZONS)))
    add("PRE2025_RESIDUAL_ALPHA",int((byh.economic_score>0).sum())>=4 and float(byh.economic_score.median())>0,{"positive_horizons":int((byh.economic_score>0).sum()),"median_economic_score":float(byh.economic_score.median())},">=4/6 positive and median > 0")
    add("2021_2022_REGIME_RECOVERY",int((reg.economic_score>0).sum())>=3 and float(reg.economic_score.median())>0,{"positive_horizons":int((reg.economic_score>0).sum()),"median_economic_score":float(reg.economic_score.median())},">=3/6 positive and median > 0")
    add("2023_2024_RECENT_REGIME_EVIDENCE",int((recent.economic_score>0).sum())>=3 and float(recent.economic_score.median())>0,{"positive_horizons":int((recent.economic_score>0).sum()),"median_economic_score":float(recent.economic_score.median())},">=3/6 positive and median > 0")
    add("TAIL_ASYMMETRY_PRESENT",float(byh.winner_lift.median())>1.2 and float(byh.loser_avoidance.median())>1.05,{"winner_lift_median":float(byh.winner_lift.median()),"loser_avoidance_median":float(byh.loser_avoidance.median())},"median winner lift >1.2 and loser avoidance >1.05")
    gate=pd.DataFrame(rows); status="PASS" if not ((gate.blocking)&(gate.status.eq("FAIL"))).any() else "FAIL"
    expert.to_csv(out/"v13_phase2s_expert_fold_evidence.csv",index=False); ens.to_csv(out/"v13_phase2s_oof_horizon_evidence.csv",index=False); byh.to_csv(out/"v13_phase2s_horizon_summary.csv",index=False); reg.to_csv(out/"v13_phase2s_2021_2022_evidence.csv",index=False); recent.to_csv(out/"v13_phase2s_2023_2024_evidence.csv",index=False); weights.to_csv(out/"v13_phase2s_nested_expert_weights.csv",index=False); finalw.to_csv(out/"v13_phase2s_final_expert_weights.csv",index=False); faud.to_csv(out/"v13_phase2s_feature_selection_audit.csv",index=False); oof.to_parquet(out/"v13_phase2s_oof_scores.parquet",index=False); gate.to_csv(out/"v13_phase2s_gate.csv",index=False)
    summary={"status":status,"phase":"V13-P2S","build":BUILD,"name":cfg.p["name"],"objective":cfg.p["objective"],"research_contract":{"pre_holdout_research":"2015-2024 purged walk-forward","holdout_start":cfg.p["holdout_start"],"holdout_used":False,"portfolio_run":False},"information_set":{"phase1_features":int(len([c for c in base.columns if c not in {'signal_date','ticker'}])),"model_features_after_regime_beta_expansion":int(len(model_features)),"macro_symbols":list(cfg.p["macro_symbols"]),"new_target":"40% cross-sectional excess + 30% beta-SPY residual + 30% beta-QQQ residual; upside/downside tails"},"horizon_summary":byh.to_dict(orient="records"),"regime_2021_2022":reg.to_dict(orient="records"),"recent_2023_2024":recent.to_dict(orient="records"),"final_expert_weights":finalw.to_dict(orient="records"),"gate":gate.to_dict(orient="records"),"readiness":"READY_FOR_FAST_CACHED_PORTFOLIO" if status=="PASS" else "PREDICTIVE_INFORMATION_SET_STILL_INSUFFICIENT","next":"If PASS, use v13_phase2s_oof_scores for one cached portfolio research block. If FAIL, stop tuning this price/fundamental information set and add genuinely new predictive sources before touching 2025+."}
    (out/"v13_phase2s_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    return summary
