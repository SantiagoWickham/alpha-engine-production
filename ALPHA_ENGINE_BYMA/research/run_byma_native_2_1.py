from __future__ import annotations

from pathlib import Path
import json
import math
import sys
import warnings

import joblib
import numpy as np
import pandas as pd

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import Ridge

# =============================================================================
# IDENTITY / FROZEN CONTRACT
# =============================================================================

NAME = "ALPHA_ENGINE_BYMA_NATIVE"
VERSION = "2.1.2"
BUILD = "ALPHA_ENGINE_BYMA_NATIVE_2_1_2_2026-09-13"

PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "outputs" / "native_v21"
OUT.mkdir(parents=True, exist_ok=True)

V13 = Path(
    r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_V12_RETURN_FIRST"
    r"\ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
)
if not V13.exists():
    raise FileNotFoundError(f"Frozen V13 workspace not found: {V13}")

if str(V13 / "src") not in sys.path:
    sys.path.insert(0, str(V13 / "src"))

warnings.filterwarnings("ignore", message="All-NaN slice encountered")
warnings.filterwarnings("ignore", message="Downcasting object dtype arrays")

from alpha_engine_v13 import active_alpha_persistent_portfolio as p3y
from alpha_engine_v13 import roundtrip_resize_hysteresis as p3z
from alpha_engine_v13 import economic_portfolio_closure as p3v
from alpha_engine_v13 import final_holdout as p4

p2r = p4.p2r
p2u = p4.p2u
HORIZONS = tuple(int(x) for x in p4.HORIZONS)

# No search / no tuning after seeing 2025+.
RIDGE_ALPHA = 10.0
HGB_MAX_ITER = 80
HGB_LEARNING_RATE = 0.04
HGB_MAX_LEAF_NODES = 15
HGB_MIN_SAMPLES_LEAF = 50
HGB_L2 = 2.0

INNER_VALIDATION_FRACTION = 0.25
MIN_META_TRAIN_ROWS = 5000
MIN_META_VALID_ROWS = 1000
MAX_FEATURE_MISSING_SHARE = 0.95
MIN_FEATURE_STD = 1e-12
PRACTICAL_NAVS = (320.42, 1000.0)

PORTFOLIO_FOLDS = [
    ("WF_2019_2020", pd.Timestamp("2019-01-01"), pd.Timestamp("2020-12-31")),
    ("WF_2021_2022", pd.Timestamp("2021-01-01"), pd.Timestamp("2022-12-31")),
    ("WF_2023_2024", pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")),
]

print("=" * 126)
print("ALPHA ENGINE BYMA NATIVE 2.1.2")
print("FINAL NATIVE RESEARCH / V13-STYLE TWO-STAGE ARCHITECTURE / FRESH BYMA META-ALPHA")
print("NO V13 SCORES / NO V13 FITTED MODELS / NO TOP-N / NO 2025+ TUNING")
print("=" * 126)

# =============================================================================
# HELPERS
# =============================================================================

def tk(x):
    return str(x).strip().upper().replace("*", "")

def dates(s):
    return pd.to_datetime(s, errors="coerce").dt.normalize()

def maxdd(nav):
    x = pd.to_numeric(nav, errors="coerce").dropna()
    return float((x / x.cummax() - 1).min())

def sim_metrics(sim):
    if sim.empty:
        raise RuntimeError("Empty simulation")
    n = len(sim)
    years = n / 252.0
    nav = pd.to_numeric(sim["nav"], errors="coerce")
    final = float(nav.iloc[-1])
    return {
        "sessions": int(n),
        "final_nav": final,
        "total_return": final - 1.0,
        "cagr": float(final ** (1/years) - 1) if final > 0 and years > 0 else np.nan,
        "max_drawdown": maxdd(nav),
        "annual_turnover": float(
            pd.to_numeric(sim["turnover"], errors="coerce").fillna(0).sum() / years
        ),
        "median_holdings": float(pd.to_numeric(sim["holdings"], errors="coerce").median()),
        "mean_cash": float(pd.to_numeric(sim["cash_weight"], errors="coerce").mean()),
        "p95_max_name": float(
            pd.to_numeric(sim["max_name_weight"], errors="coerce").quantile(.95)
        ),
    }

def cagr_returns(r):
    x = pd.to_numeric(r, errors="coerce").dropna()
    if x.empty:
        return np.nan
    years = len(x)/252.0
    gross = float((1+x).prod())
    return float(gross**(1/years)-1) if gross > 0 else np.nan

def daily_spearman(df, pred_col, target_col):
    vals = []
    for _, g in df.groupby("signal_date", sort=False):
        q = g[[pred_col,target_col]].dropna()
        if len(q) >= 5 and q[pred_col].nunique() > 1 and q[target_col].nunique() > 1:
            vals.append(q[pred_col].corr(q[target_col], method="spearman"))
    return float(np.nanmean(vals)) if vals else np.nan

def safe_spearman(a, b):
    q = pd.DataFrame({"a":a,"b":b}).dropna()
    if len(q)<20 or q.a.nunique()<2 or q.b.nunique()<2:
        return np.nan
    return float(q.a.corr(q.b,method="spearman"))

def numeric_frame(df, cols):
    return (
        df[cols]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf,-np.inf],np.nan)
    )

def recency_weights(dates_s, half_life=504):
    d = pd.to_datetime(dates_s)
    age = (d.max()-d).dt.days.to_numpy(float) * (252.0/365.25)
    return np.exp(-np.log(2)*age/max(float(half_life),1.0))

def select_features(train, candidates):
    out=[]
    for c in candidates:
        if c not in train.columns:
            continue
        x=pd.to_numeric(train[c],errors="coerce").replace([np.inf,-np.inf],np.nan)
        if x.notna().sum()<100:
            continue
        if float(x.isna().mean())>MAX_FEATURE_MISSING_SHARE:
            continue
        sd=float(x.std(skipna=True))
        if np.isfinite(sd) and sd>MIN_FEATURE_STD:
            out.append(c)
    return out

# =============================================================================
# LOAD 2.0.1 BASE-NATIVE SCORES + BYMA MASTER
# =============================================================================

print("\n[1/12] LOAD NATIVE BASE RANKING + CERTIFIED BYMA MASTER")

BASE_OUT = PROJECT / "outputs" / "native_v2"
OOF_PATH = BASE_OUT / "byma_native_oof_scores.parquet"
HOLD_SCORE_PATH = BASE_OUT / "byma_native_holdout_scores.parquet"
MASTER_PATH = PROJECT / "outputs" / "byma_master.csv"

for p in (OOF_PATH,HOLD_SCORE_PATH,MASTER_PATH):
    if not p.exists():
        raise FileNotFoundError(
            f"Required prior artifact missing: {p}. "
            "Run BYMA Native 2.0.1 and BYMA 1.0.1 first."
        )

oof = pd.read_parquet(OOF_PATH)
hold_scores = pd.read_parquet(HOLD_SCORE_PATH)
master = pd.read_csv(MASTER_PATH)

for x in (oof,hold_scores):
    x["signal_date"]=dates(x["signal_date"])
    x["ticker"]=x["ticker"].map(tk)
    x["horizon_sessions"]=pd.to_numeric(x["horizon_sessions"],errors="raise").astype(int)

master["origin_ticker"]=master["origin_ticker"].map(tk)
master["byma_ticker"]=master["byma_ticker"].map(tk)

LOCAL={
    "CEPU":{"byma_ticker":"CEPU","local_per_adr":10.0},
    "YPF":{"byma_ticker":"YPFD","local_per_adr":10.0},
}
accessible=set(master.origin_ticker)|set(master.byma_ticker)|set(LOCAL)
accessible.discard("")
accessible.discard("NAN")

print(f"  base OOF rows: {len(oof):,}")
print(f"  base holdout score rows: {len(hold_scores):,}")
print(f"  accessible aliases: {len(accessible):,}")

# =============================================================================
# PIT INFRASTRUCTURE / HOLDOUT RAW DATA
# =============================================================================

print("\n[2/12] LOAD PIT TARGETS + BUILD SECTOR/EVENT INFORMATION")

cfg3z=p3z.load_cfg(V13)
_,_,source,_,_=p3y.load_inputs(V13,cfg3z)
hold=pd.Timestamp(cfg3z.p["holdout_start"])
portfolio_start=pd.Timestamp(cfg3z.p["portfolio_start"])

research_features,research_targets=p4._preholdout_inputs(V13,hold)
research_features["ticker"]=research_features["ticker"].map(tk)
research_targets["ticker"]=research_targets["ticker"].map(tk)

cfg1=p4.p1.load_cfg(V13)
cfg1full=p4.p1.Cfg({**cfg1.p,"holdout_start":"2100-01-01"})
market_full,price_meta=p4._load_full_market(source,cfg1full)
market_full["date"]=dates(market_full["date"])
market_full["ticker"]=market_full["ticker"].map(tk)
end=pd.Timestamp(market_full.date.max())

bench_full=p4._load_full_bench(source,cfg1full,market_full)
bench_full["date"]=dates(bench_full["date"])

hold_keys=p4._holdout_target_keys(source,hold,end)
hold_features,_=p4.p1.build_feature_library(
    source,hold_keys,cfg1full,market=market_full,bench=bench_full,price_meta=price_meta
)
hold_features["signal_date"]=dates(hold_features["signal_date"])
hold_features["ticker"]=hold_features["ticker"].map(tk)

hold_targets=p4._load_holdout_targets(source,hold,end,bench_full)
hold_targets["signal_date"]=dates(hold_targets["signal_date"])
hold_targets["ticker"]=hold_targets["ticker"].map(tk)

rf=research_features[research_features.ticker.isin(accessible)].copy()
rt=research_targets[research_targets.ticker.isin(accessible)].copy()
hf=hold_features[hold_features.ticker.isin(accessible)].copy()
ht=hold_targets[hold_targets.ticker.isin(accessible)].copy()

cfg2u=p2u.load_cfg(V13)

pre_keys=oof[["signal_date","ticker"]].drop_duplicates()
hold_meta_keys=hold_scores[["signal_date","ticker"]].drop_duplicates()

pre_info=p4._newinfo_holdout(
    source,cfg2u,pre_keys,rf,market_full,pd.Timestamp("2024-12-31")
)
hold_info=p4._newinfo_holdout(
    source,cfg2u,hold_meta_keys,hf,market_full,end
)
pre_info["signal_date"]=dates(pre_info["signal_date"])
pre_info["ticker"]=pre_info["ticker"].map(tk)
hold_info["signal_date"]=dates(hold_info["signal_date"])
hold_info["ticker"]=hold_info["ticker"].map(tk)

print(f"  pre meta rows: {len(pre_info):,}, columns: {len(pre_info.columns)}")
print(f"  hold meta rows: {len(hold_info):,}, columns: {len(hold_info.columns)}")

# =============================================================================
# ACTIVE RETURN TARGETS
# =============================================================================

print("\n[3/12] BUILD BYMA ACTIVE-ALPHA TARGETS")

bench_px=(
    bench_full[["date","SPY","QQQ"]]
    .drop_duplicates("date")
    .sort_values("date")
    .set_index("date")
)
for h in HORIZONS:
    bench_px[f"SPY_FWD_{h}"]=bench_px["SPY"].shift(-h)/bench_px["SPY"]-1
    bench_px[f"QQQ_FWD_{h}"]=bench_px["QQQ"].shift(-h)/bench_px["QQQ"]-1

def active_long(targets):
    parts=[]
    for h in HORIZONS:
        need=[
            "signal_date","ticker",
            f"target_end_date_{h}d",
            f"target_resolved_{h}d",
            f"fwd_return_{h}d",
        ]
        missing=[c for c in need if c not in targets.columns]
        if missing:
            raise RuntimeError(f"Target fields missing h={h}: {missing}")
        q=targets[need].copy()
        q.columns=[
            "signal_date","ticker","target_end_date","resolved","asset_return"
        ]
        q["signal_date"]=dates(q["signal_date"])
        q["target_end_date"]=dates(q["target_end_date"])
        q["resolved"]=q["resolved"].fillna(False).astype(bool)
        q["asset_return"]=pd.to_numeric(q["asset_return"],errors="coerce")
        valid=q.resolved&q.asset_return.notna()

        uew=q.loc[valid].groupby("signal_date")["asset_return"].mean()
        q["byma_uew_return"]=q.signal_date.map(uew)
        q["spy_return"]=q.signal_date.map(bench_px[f"SPY_FWD_{h}"])
        q["qqq_return"]=q.signal_date.map(bench_px[f"QQQ_FWD_{h}"])

        active_total=(
            .50*(q.asset_return-q.byma_uew_return)
            +.25*(q.asset_return-q.spy_return)
            +.25*(q.asset_return-q.qqq_return)
        )
        q["active_ps"]=active_total/float(h)
        q["horizon_sessions"]=h
        parts.append(q)
    return pd.concat(parts,ignore_index=True)

pre_active=active_long(rt)
hold_active=active_long(ht)

# =============================================================================
# META FEATURE SURFACE
# =============================================================================

print("\n[4/12] BUILD META-ALPHA FEATURE SURFACE")

LEAK_PATTERNS=(
    "target_","fwd_","future","forward_return","winner_",
    "resolved","outcome","realized_","active_ps","asset_return",
)

meta_candidates=["base_score"]
for c in pre_info.columns:
    if c in {"signal_date","ticker"}:
        continue
    lc=str(c).lower()
    if any(p in lc for p in LEAK_PATTERNS):
        continue
    if c not in hold_info.columns:
        continue
    meta_candidates.append(c)

meta_candidates=list(dict.fromkeys(meta_candidates))
print(f"  prospective meta candidates: {len(meta_candidates)}")

def horizon_dataset(scores, info, active, h):
    s=scores[scores.horizon_sessions.eq(h)][
        ["signal_date","ticker","score"]
    ].rename(columns={"score":"base_score"})
    a=active[active.horizon_sessions.eq(h)][
        ["signal_date","ticker","target_end_date","resolved","active_ps"]
    ]
    z=(
        s.merge(info,on=["signal_date","ticker"],how="left",validate="one_to_one")
         .merge(a,on=["signal_date","ticker"],how="left",validate="one_to_one")
    )
    return z.sort_values(["signal_date","ticker"]).reset_index(drop=True)

pre_ds={h:horizon_dataset(oof,pre_info,pre_active,h) for h in HORIZONS}
hold_ds={h:horizon_dataset(hold_scores,hold_info,hold_active,h) for h in HORIZONS}

# =============================================================================
# THREE-EXPERT META MODEL
# =============================================================================

def prep_matrix(df,features,median=None,mu=None,sd=None):
    x=numeric_frame(df,features).to_numpy(float)
    if median is None:
        median=np.nanmedian(x,axis=0)
        median[~np.isfinite(median)]=0.0
    xi=np.where(np.isfinite(x),x,median)
    if mu is None:
        mu=np.mean(xi,axis=0)
    if sd is None:
        sd=np.std(xi,axis=0)
        sd[~np.isfinite(sd)|(sd<1e-12)]=1.0
    xz=(xi-mu)/sd
    return xi,xz,median,mu,sd

def fit_two_models(train,features,target_col,weights):
    y=pd.to_numeric(train[target_col],errors="coerce").to_numpy(float)
    xi,xz,median,mu,sd=prep_matrix(train,features)
    ok=np.isfinite(y)
    y=y[ok]; xi=xi[ok]; xz=xz[ok]
    w=np.asarray(weights,float)[ok]

    if y.ndim!=1:
        y=np.asarray(y,float).reshape(-1)
    if len(y)<100:
        raise RuntimeError(
            f"fit_two_models received only {len(y)} finite targets "
            f"for {target_col}"
        )
    if not np.isfinite(y).any():
        raise RuntimeError(
            f"fit_two_models received no finite targets for {target_col}"
        )

    qs=np.asarray(np.nanquantile(y,[.01,.99]),dtype=float).reshape(-1)
    if len(qs)!=2 or not np.isfinite(qs).all():
        raise RuntimeError(
            f"Invalid target quantiles for {target_col}: {qs}"
        )
    lo,hi=float(qs[0]),float(qs[1])
    if hi<=lo:
        eps=max(1e-12,abs(lo)*1e-6)
        lo,hi=lo-eps,hi+eps

    yc=np.clip(y,lo,hi)

    ridge=Ridge(alpha=RIDGE_ALPHA,fit_intercept=True)
    ridge.fit(xz,yc,sample_weight=w)

    hgb=HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=HGB_LEARNING_RATE,
        max_iter=HGB_MAX_ITER,
        max_leaf_nodes=HGB_MAX_LEAF_NODES,
        min_samples_leaf=HGB_MIN_SAMPLES_LEAF,
        l2_regularization=HGB_L2,
        random_state=2109,
    )
    hgb.fit(xi,yc,sample_weight=w)

    iso=IsotonicRegression(
        increasing=True,
        out_of_bounds="clip",
        y_min=float(lo),
        y_max=float(hi),
    )
    iso.fit(
        pd.to_numeric(train.loc[ok,"base_score"],errors="coerce").to_numpy(float),
        yc,
        sample_weight=w,
    )

    return {
        "features":features,"median":median,"mu":mu,"sd":sd,
        "ridge":ridge,"hgb":hgb,"iso":iso,
        "y_lo":float(lo),"y_hi":float(hi),
    }

def expert_predict(bundle,df):
    xi,xz,_,_,_=prep_matrix(
        df,bundle["features"],
        bundle["median"],bundle["mu"],bundle["sd"]
    )
    r=bundle["ridge"].predict(xz)
    h=bundle["hgb"].predict(xi)
    s=pd.to_numeric(df.base_score,errors="coerce").fillna(.5).to_numpy(float)
    i=bundle["iso"].predict(s)
    lo,hi=bundle["y_lo"],bundle["y_hi"]
    return {
        "ridge":np.clip(r,lo,hi),
        "hgb":np.clip(h,lo,hi),
        "isotonic":np.clip(i,lo,hi),
    }

def temporal_inner_split(train):
    """
    Purged inner temporal split.

    The long horizons (especially 252d) need a later validation start than
    short horizons because every inner-training target must be fully resolved
    before validation begins. 2.1.0 used one fixed fractional split and could
    therefore create an empty inner train even when the outer training sample
    itself was large.

    This routine searches only inside the OUTER TRAINING SAMPLE. It never sees
    the outer test period or 2025+.
    """
    q=train[
        train.resolved
        &train.active_ps.notna()
        &train.signal_date.notna()
        &train.target_end_date.notna()
    ].copy()

    ds=np.sort(pd.to_datetime(q.signal_date.dropna().unique()))
    if len(ds)<20:
        raise RuntimeError(
            f"Too few unique dates for inner validation: {len(ds)}"
        )

    # Frozen search grid. This is an engineering feasibility search for a
    # purged split, NOT hyperparameter tuning. Prefer a split near the original
    # 75% train / 25% validation design when several are feasible.
    fractions=(0.55,0.60,0.65,0.70,0.75,0.80,0.85,0.90)
    feasible=[]

    for frac in fractions:
        idx=max(1,min(len(ds)-1,int(len(ds)*frac)))
        val_start=pd.Timestamp(ds[idx])

        tr=q[
            (q.signal_date<val_start)
            &(q.target_end_date<val_start)
        ].copy()
        va=q[q.signal_date>=val_start].copy()

        # Keep validation observations whose outcomes are already contained in
        # the outer training sample (q was outer-cutoff filtered upstream).
        if len(tr)>=MIN_META_TRAIN_ROWS and len(va)>=MIN_META_VALID_ROWS:
            feasible.append(
                (abs(frac-(1-INNER_VALIDATION_FRACTION)),
                 -len(tr), frac, val_start, tr, va)
            )

    if not feasible:
        diagnostics=[]
        for frac in fractions:
            idx=max(1,min(len(ds)-1,int(len(ds)*frac)))
            val_start=pd.Timestamp(ds[idx])
            tr=q[
                (q.signal_date<val_start)
                &(q.target_end_date<val_start)
            ]
            va=q[q.signal_date>=val_start]
            diagnostics.append(
                f"{frac:.2f}:train={len(tr)},valid={len(va)},"
                f"start={val_start.date()}"
            )
        raise RuntimeError(
            "No feasible PURGED inner validation split. "
            f"Need train>={MIN_META_TRAIN_ROWS}, "
            f"valid>={MIN_META_VALID_ROWS}. "
            + " | ".join(diagnostics)
        )

    feasible.sort(key=lambda x:(x[0],x[1],x[2]))
    _,_,frac,val_start,tr,va=feasible[0]

    return tr.copy(),va.copy(),val_start

def fit_meta(train,candidates,outer_cutoff):
    q=train[
        train.resolved
        &train.active_ps.notna()
        &(train.target_end_date<outer_cutoff)
        &(train.signal_date<outer_cutoff)
    ].copy()
    if len(q)<MIN_META_TRAIN_ROWS:
        raise RuntimeError(
            f"Only {len(q)} meta rows before {outer_cutoff.date()}"
        )

    features=select_features(q,candidates)
    if len(features)<5:
        raise RuntimeError(f"Only {len(features)} usable meta features")

    inner,valid,val_start=temporal_inner_split(q)
    w_inner=recency_weights(inner.signal_date)
    temp=fit_two_models(inner,features,"active_ps",w_inner)
    vp=expert_predict(temp,valid)
    vy=pd.to_numeric(valid.active_ps,errors="coerce")

    stats={}
    raw_weights={}
    for name,pred in vp.items():
        ic=safe_spearman(pred,vy)
        rmse=float(np.sqrt(np.nanmean((np.asarray(pred)-vy.to_numpy(float))**2)))
        score=max(0.0,ic if np.isfinite(ic) else 0.0)/max(rmse,1e-8)
        stats[name]={"ic":ic,"rmse":rmse,"quality":score}
        raw_weights[name]=score

    sw=sum(raw_weights.values())
    if sw<=0:
        # Preserve base-ranking monotonic information rather than inventing
        # a winner: isotonic only, but mark horizon skill as zero.
        expert_weights={"ridge":0.0,"hgb":0.0,"isotonic":1.0}
        skill=0.0
    else:
        expert_weights={k:v/sw for k,v in raw_weights.items()}
        blend=sum(expert_weights[k]*vp[k] for k in expert_weights)
        skill=max(0.0,safe_spearman(blend,vy))
        rmse_blend=float(np.sqrt(np.nanmean((blend-vy.to_numpy(float))**2)))
        stats["blend"]={"ic":skill,"rmse":rmse_blend}
    if "blend" not in stats:
        blend=vp["isotonic"]
        stats["blend"]={
            "ic":safe_spearman(blend,vy),
            "rmse":float(np.sqrt(np.nanmean((blend-vy.to_numpy(float))**2)))
        }

    full=fit_two_models(q,features,"active_ps",recency_weights(q.signal_date))
    full["expert_weights"]=expert_weights
    full["skill"]=float(skill)
    full["sigma"]=float(max(stats["blend"]["rmse"],1e-8))
    full["inner_validation_start"]=str(val_start.date())
    full["inner_train_rows"]=int(len(inner))
    full["inner_valid_rows"]=int(len(valid))
    full["expert_validation"]=stats
    full["train_rows"]=int(len(q))
    return full

def predict_meta(model,df):
    ep=expert_predict(model,df)
    pred=sum(model["expert_weights"][k]*ep[k] for k in model["expert_weights"])
    return np.asarray(pred,float)

# =============================================================================
# OUTER WALK-FORWARD META OOF
# =============================================================================

print("\n[5/12] WALK-FORWARD META-ALPHA TRAINING")

meta_score_parts=[]
models_by_fold={}

for fold_name,a,b in PORTFOLIO_FOLDS:
    fold_pred=[]
    models_by_fold[fold_name]={}
    print(f"  {fold_name}")
    for h in HORIZONS:
        ds=pre_ds[h]
        train=ds[ds.signal_date<a].copy()
        test=ds[(ds.signal_date>=a)&(ds.signal_date<=b)].copy()

        try:
            model=fit_meta(train,meta_candidates,a)
        except RuntimeError as e:
            msg=str(e)
            if "No feasible PURGED inner validation split" in msg:
                # Horizon-maturity rule:
                # a long horizon cannot be used prospectively until there is
                # enough prior META history to create a purged train/validation
                # split. We do not lower minimums and do not borrow future data.
                print(
                    f"    h={h:>3}: SKIP_NOT_MATURE_FOR_META_VALIDATION "
                    f"| outer_cutoff={a.date()}"
                )
                models_by_fold[fold_name][h]=None
                continue
            raise

        pred=predict_meta(model,test)

        q=test[["signal_date","ticker"]].copy()
        q["horizon_sessions"]=h
        q["fold"]=fold_name
        q["expected_active_ps"]=pred
        q["sigma"]=model["sigma"]
        q["horizon_skill"]=model["skill"]
        meta_score_parts.append(q)
        models_by_fold[fold_name][h]=model

        print(
            f"    h={h:>3}: train={model['train_rows']:,} "
            f"features={len(model['features'])} "
            f"skillIC={model['skill']:.4f} sigma={model['sigma']:.6f} "
            f"inner={model['inner_train_rows']:,}/{model['inner_valid_rows']:,}"
        )

if not meta_score_parts:
    raise RuntimeError("No mature meta horizons were available in any OOF fold")

meta_oof=pd.concat(meta_score_parts,ignore_index=True)

for fold_name,_,_ in PORTFOLIO_FOLDS:
    hh=sorted(
        meta_oof.loc[meta_oof.fold.eq(fold_name),"horizon_sessions"]
        .dropna().astype(int).unique().tolist()
    )
    if not hh:
        raise RuntimeError(f"{fold_name}: no mature meta horizons")
    print(f"  {fold_name}: mature meta horizons={hh}")

meta_oof.to_parquet(OUT/"byma_native21_meta_oof.parquet",index=False)

# =============================================================================
# FINAL PRE2025 META BUNDLE -> 2025+
# =============================================================================

print("\n[6/12] FIT FINAL PRE2025 META BUNDLE + SCORE 2025+")

final_models={}
hold_meta_parts=[]

for h in HORIZONS:
    try:
        model=fit_meta(pre_ds[h],meta_candidates,hold)
    except RuntimeError as e:
        raise RuntimeError(
            f"FINAL PRE2025 horizon h={h} is still not mature; "
            "native 2.1 cannot be production-frozen. "
            + str(e)
        ) from e
    pred=predict_meta(model,hold_ds[h])
    final_models[h]=model

    q=hold_ds[h][["signal_date","ticker"]].copy()
    q["horizon_sessions"]=h
    q["fold"]="FINAL_HOLDOUT_NATIVE21"
    q["expected_active_ps"]=pred
    q["sigma"]=model["sigma"]
    q["horizon_skill"]=model["skill"]
    hold_meta_parts.append(q)

    print(
        f"  h={h:>3}: train={model['train_rows']:,} "
        f"features={len(model['features'])} "
        f"skillIC={model['skill']:.4f} sigma={model['sigma']:.6f}"
    )

hold_meta=pd.concat(hold_meta_parts,ignore_index=True)
hold_meta.to_parquet(OUT/"byma_native21_holdout_meta_scores.parquet",index=False)

joblib.dump(
    {
        "name":NAME,"version":VERSION,"build":BUILD,
        "trained_through":"2024-12-31",
        "final_models":final_models,
        "meta_candidates":meta_candidates,
        "base_model_source":"BYMA_NATIVE_2.0.1 OOF/final scores",
        "v13_fitted_models_used":False,
    },
    OUT/"byma_native21_model_bundle.joblib",
    compress=3,
)

# =============================================================================
# BUILD MULTI-HORIZON ADVISOR
# =============================================================================

print("\n[7/12] MULTI-HORIZON ADVISOR")

def build_advisor(meta,label):
    # Weights come from prospective inner-validation quality, not the test set.
    hs=(
        meta[["horizon_sessions","horizon_skill","sigma"]]
        .drop_duplicates("horizon_sessions")
        .copy()
    )
    hs["quality"]=(
        hs.horizon_skill.clip(lower=0)
        /hs.sigma.clip(lower=1e-8)
    )
    if float(hs.quality.sum())<=0:
        raise RuntimeError(f"{label}: no positive prospective horizon skill")
    hw=(hs.set_index("horizon_sessions").quality/hs.quality.sum()).to_dict()

    rows=[]
    for (d,t),g in meta.groupby(["signal_date","ticker"],sort=False):
        g=g.copy()
        h=g.horizon_sessions.to_numpy(int)
        w=np.array([hw.get(int(x),0.0) for x in h],float)
        if w.sum()<=0:
            continue
        w=w/w.sum()
        a=g.expected_active_ps.to_numpy(float)
        s=g.sigma.to_numpy(float)

        row={
            "signal_date":pd.Timestamp(d),
            "ticker":tk(t),
            "fold":label,
            "expected_active_per_session":float(np.sum(w*a)),
            "uncertainty_per_session":float(np.sqrt(np.sum((w*s)**2))),
            "positive_active_horizon_share":float(np.sum(w*(a>0))),
            "effective_horizon_sessions":float(np.sum(w*h)),
        }
        for hh in HORIZONS:
            m=h==hh
            row[f"horizon_weight_{hh}d"]=float(w[m][0]) if m.any() else 0.0
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["signal_date","ticker"]),hw

advisor_parts=[]
fold_horizon_weights={}
for fold_name,a,b in PORTFOLIO_FOLDS:
    q=meta_oof[(meta_oof.signal_date>=a)&(meta_oof.signal_date<=b)].copy()
    adv,hw=build_advisor(q,fold_name)
    advisor_parts.append(adv)
    fold_horizon_weights[fold_name]=hw
    print(f"  {fold_name}: advisor rows={len(adv):,}, horizon weights={hw}")

advisor_pre=pd.concat(advisor_parts,ignore_index=True).sort_values(["signal_date","ticker"])
advisor_hold,hold_hw=build_advisor(hold_meta,"FINAL_HOLDOUT_NATIVE21")

advisor_pre.to_parquet(OUT/"byma_native21_advisor_pre2025.parquet",index=False)
advisor_hold.to_parquet(OUT/"byma_native21_advisor_holdout.parquet",index=False)

# =============================================================================
# MARKET + PORTFOLIO
# =============================================================================

print("\n[8/12] PORTFOLIO SIMULATION 20/40/60 BPS")

pcfg=p3v.load_cfg(V13)
needed=set(advisor_pre.ticker.unique())|set(advisor_hold.ticker.unique())
surface_pre=p3v.load_market(V13,source,pcfg,needed)
spy_pre=p3v._load_benchmark(source,pcfg.p["source_spy_benchmark"],"SPY",hold)
qqq_pre=p3v._load_benchmark(source,pcfg.p["source_qqq_benchmark"],"QQQ",hold)

market_pre=p3v.prepare_market(
    surface_pre,spy_pre,portfolio_start,hold,
    int(cfg3z.p["risk_lookback_sessions"])
)

c=pd.read_parquet(
    source/"outputs"/"phase2_canonical_pit_panel.parquet",
    columns=["date","ticker","close","research_eligible"]
)
r=pd.read_parquet(
    source/"outputs"/"phase2c_return_price_layer.parquet",
    columns=["date","ticker","target_total_return_price"]
)
c["date"]=dates(c.date);c["ticker"]=c.ticker.map(tk)
r["date"]=dates(r.date);r["ticker"]=r.ticker.map(tk)
surf_hold=c.merge(r,on=["date","ticker"],how="left")
surf_hold["execution_close"]=pd.to_numeric(surf_hold.close,errors="coerce")
surf_hold["mark_price"]=pd.to_numeric(
    surf_hold.target_total_return_price,errors="coerce"
)
surf_hold["research_eligible"]=surf_hold.research_eligible.fillna(False).astype(bool)
surf_hold=surf_hold[
    ["date","ticker","execution_close","mark_price","research_eligible"]
]

spy_h=bench_full.dropna(subset=["SPY"]).drop_duplicates("date").set_index("date")["SPY"]
qqq_h=bench_full.dropna(subset=["QQQ"]).drop_duplicates("date").set_index("date")["QQQ"]
end_excl=end+pd.Timedelta(days=1)

market_hold=p3v.prepare_market(
    surf_hold,spy_h,hold,end_excl,int(cfg3z.p["risk_lookback_sessions"])
)
terminals=p3v.load_terminals(source,pcfg)

plans_pre=p3z.build_plans(advisor_pre,market_pre,cfg3z)
plans_hold=p3z.build_plans(advisor_hold,market_hold,cfg3z)

sims={}
mets={}
for cost in (20.0,40.0,60.0):
    sp=p3y.simulate_persistent(
        plans_pre,market_pre,terminals,portfolio_start,hold,cost
    )
    sh=p3y.simulate_persistent(
        plans_hold,market_hold,terminals,hold,end_excl,cost
    )
    sims[("PRE",cost)]=sp
    sims[("HOLD",cost)]=sh
    mets[("PRE",cost)]=sim_metrics(sp)
    mets[("HOLD",cost)]=sim_metrics(sh)
    print(
        f"  {int(cost):>2}bps | PRE CAGR {mets[('PRE',cost)]['cagr']:.2%} "
        f"DD {mets[('PRE',cost)]['max_drawdown']:.2%} "
        f"holdings {mets[('PRE',cost)]['median_holdings']:.0f} | "
        f"HOLD CAGR {mets[('HOLD',cost)]['cagr']:.2%} "
        f"DD {mets[('HOLD',cost)]['max_drawdown']:.2%} "
        f"holdings {mets[('HOLD',cost)]['median_holdings']:.0f}"
    )

sims[("PRE",20.0)].to_csv(OUT/"byma_native21_nav_pre2025_20bps.csv",index=False)
sims[("HOLD",20.0)].to_csv(OUT/"byma_native21_nav_holdout_20bps.csv",index=False)

# =============================================================================
# BENCHMARK / SUBPERIOD EVIDENCE
# =============================================================================

print("\n[9/12] PRIMARY PRE2025 EVIDENCE")

bench_pre=p3v.benchmark_returns(source,pcfg,market_pre,spy_pre,qqq_pre)
bench_hold=p3v.benchmark_returns(source,pcfg,market_hold,spy_h,qqq_h)

def local_uew(market,tickers):
    cols=[c for c in market["returns"].columns if tk(c) in set(tickers)]
    return market["returns"][cols].mean(axis=1,skipna=True)

bench_pre["BYMA_UEW"]=local_uew(market_pre,advisor_pre.ticker.unique())
bench_hold["BYMA_UEW"]=local_uew(market_hold,advisor_hold.ticker.unique())

sr=sims[("PRE",20.0)].set_index("date").net_return
alpha_rows=[]
for name,b in bench_pre.items():
    alpha_rows.append({"sample":"PRE2025_OOF","benchmark":name,**p3y._ols(sr,b.reindex(sr.index))})
shr=sims[("HOLD",20.0)].set_index("date").net_return
for name,b in bench_hold.items():
    alpha_rows.append({"sample":"HOLDOUT_POSTHOC","benchmark":name,**p3y._ols(shr,b.reindex(shr.index))})
alpha_df=pd.DataFrame(alpha_rows)
alpha_df.to_csv(OUT/"byma_native21_active_alpha.csv",index=False)

bench_cagr={k:cagr_returns(v[(v.index>=portfolio_start)&(v.index<hold)]) for k,v in bench_pre.items()}
alpha_pre=alpha_df[alpha_df["sample"].eq("PRE2025_OOF")].set_index("benchmark")

subrows=[]
for fold_name,a,b in PORTFOLIO_FOLDS:
    sim=sims[("PRE",20.0)]
    q=sim[(pd.to_datetime(sim.date)>=a)&(pd.to_datetime(sim.date)<=b)]
    strat=cagr_returns(q.net_return)
    br=bench_pre["BYMA_UEW"]
    bb=br[(br.index>=a)&(br.index<=b)]
    bc=cagr_returns(bb)
    subrows.append({
        "period":fold_name,
        "strategy_cagr":strat,
        "byma_uew_cagr":bc,
        "excess":strat-bc,
        "positive_strategy":bool(strat>0),
        "beats_byma_uew":bool(strat>bc),
    })
sub=pd.DataFrame(subrows)
sub.to_csv(OUT/"byma_native21_subperiod_evidence.csv",index=False)

positive_periods=int(sub.positive_strategy.sum())
beat_periods=int(sub.beats_byma_uew.sum())

gates={
    "positive_cagr_20bps":bool(mets[("PRE",20.0)]["cagr"]>0),
    "positive_cagr_40bps":bool(mets[("PRE",40.0)]["cagr"]>0),
    "positive_cagr_60bps":bool(mets[("PRE",60.0)]["cagr"]>0),
    "positive_alpha_vs_spy":bool(alpha_pre.loc["SPY","alpha_ann"]>0),
    "positive_alpha_vs_qqq":bool(alpha_pre.loc["QQQ","alpha_ann"]>0),
    "positive_alpha_vs_byma_uew":bool(alpha_pre.loc["BYMA_UEW","alpha_ann"]>0),
    "beats_byma_uew_cagr":bool(mets[("PRE",20.0)]["cagr"]>bench_cagr["BYMA_UEW"]),
    "maxdd_above_minus_40pct":bool(mets[("PRE",20.0)]["max_drawdown"]>-0.40),
    "positive_in_at_least_2_of_3_subperiods":bool(positive_periods>=2),
    "beats_byma_uew_in_at_least_2_of_3":bool(beat_periods>=2),
}
primary_pass=all(gates.values())

for k,v in gates.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
print("\n  OOF subperiods:")
print(sub.to_string(index=False))

# =============================================================================
# HOLDOUT DIAGNOSTIC, NOT A GATE
# =============================================================================

print("\n[10/12] HOLDOUT / TRANSFER DIAGNOSTIC — NO TUNING")

transfer_summary=PROJECT/"outputs"/"byma_summary.json"
transfer={}
if transfer_summary.exists():
    transfer=json.loads(transfer_summary.read_text(encoding="utf-8"))

v13_hold=sim_metrics(pd.read_csv(V13/"outputs"/"v13_phase4_holdout_nav_20bps.csv"))
v13_pre=sim_metrics(pd.read_csv(V13/"outputs"/"v13_phase3z_nav_20bps.csv"))

print(f"  V13 IDEAL PRE CAGR: {v13_pre['cagr']:.2%}")
print(f"  V13 IDEAL HOLD CAGR: {v13_hold['cagr']:.2%}")
if transfer:
    tp=transfer.get("continuous_byma",{}).get("pre2025",{}).get("cagr")
    th=transfer.get("continuous_byma",{}).get("holdout",{}).get("cagr")
    if tp is not None: print(f"  BYMA TRANSFER PRE CAGR: {float(tp):.2%}")
    if th is not None: print(f"  BYMA TRANSFER HOLD CAGR: {float(th):.2%}")
print(f"  NATIVE 2.1 PRE CAGR: {mets[('PRE',20.0)]['cagr']:.2%}")
print(f"  NATIVE 2.1 HOLD CAGR: {mets[('HOLD',20.0)]['cagr']:.2%}")

# =============================================================================
# CURRENT TARGET + INTEGER SNAPSHOTS
# =============================================================================

print("\n[11/12] CURRENT TARGET")

last_date=max(plans_hold)
last_plan=plans_hold[last_date]
target={
    tk(t):float(p["desired"])
    for t,p in last_plan.items()
    if bool(p.get("entry_ok",False)) and float(p.get("desired",0))>0
}
tdf=pd.DataFrame([
    {"signal_date":last_date,"ticker":t,"target_weight":w}
    for t,w in target.items()
]).sort_values("target_weight",ascending=False)
tdf.to_csv(OUT/"byma_native21_current_target_continuous.csv",index=False)

by_origin={}
for rr in master.itertuples():
    by_origin.setdefault(tk(rr.origin_ticker),[]).append(rr)
    by_origin.setdefault(tk(rr.byma_ticker),[]).append(rr)

def unit_info(t,px):
    t=tk(t)
    if not np.isfinite(px) or px<=0:return None
    cand=[]
    for rr in by_origin.get(t,[]):
        a,b=int(rr.ratio_a),int(rr.ratio_b)
        u=float(px)*(b/a)
        if u>0:
            cand.append({
                "vehicle":f"CEDEAR_{rr.issuer}",
                "byma_ticker":tk(rr.byma_ticker),
                "ratio":f"{a}:{b}",
                "unit_usd":u,
            })
    if t in LOCAL:
        n=float(LOCAL[t]["local_per_adr"])
        cand.append({
            "vehicle":"LOCAL_BYMA_SHARE",
            "byma_ticker":LOCAL[t]["byma_ticker"],
            "ratio":f"1 ADR:{n:g} LOCAL",
            "unit_usd":float(px)/n,
        })
    return min(cand,key=lambda x:x["unit_usd"]) if cand else None

price_panel=surf_hold.pivot_table(
    index="date",columns="ticker",values="execution_close",aggfunc="last"
).sort_index()
pdates=price_panel.index[price_panel.index<=last_date]
price_date=pd.Timestamp(pdates.max())
prices=price_panel.loc[price_date]

def integer_snapshot(nav):
    rows=[]
    for t,w in target.items():
        info=unit_info(t,prices.get(t,np.nan))
        if info is None:continue
        u=info["unit_usd"]
        qs=w*nav/u
        qf=math.floor(qs)
        q=int(qf+1 if qs-qf>.5 else qf)
        aw=q*u/nav
        rows.append({
            "signal_date":last_date,"price_date":price_date,
            "ticker":t,"target_weight":w,**info,
            "q_star":qs,"quantity":q,
            "actual_weight":aw,"weight_error":aw-w,
        })
    d=pd.DataFrame(rows)
    if d.empty:return d,1.0
    invested=float(d.actual_weight.sum())
    if invested>1:
        ups=[]
        for i,r in d.iterrows():
            floorq=math.floor(r.q_star)
            if int(r.quantity)>floorq:
                frac=float(r.q_star)-floorq
                ups.append((2*frac-1,-float(r.unit_usd),i,floorq))
        ups.sort()
        for _,_,i,floorq in ups:
            if invested<=1+1e-10:break
            old=float(d.loc[i,"actual_weight"])
            new=floorq*float(d.loc[i,"unit_usd"])/nav
            d.loc[i,"quantity"]=floorq
            d.loc[i,"actual_weight"]=new
            d.loc[i,"weight_error"]=new-float(d.loc[i,"target_weight"])
            invested+=new-old
    return d.sort_values("target_weight",ascending=False),max(0.0,1-float(d.actual_weight.sum()))

for nav in PRACTICAL_NAVS:
    d,cash=integer_snapshot(nav)
    d.to_csv(OUT/f"byma_native21_current_target_usd{int(round(nav))}.csv",index=False)
    print(
        f"  USD {nav:,.2f}: continuous names={len(target)}, "
        f"integer positive={(d.quantity>0).sum() if len(d) else 0}, "
        f"cash={cash:.2%}"
    )

print(f"  signal date: {last_date.date()}")
print(f"  continuous target names: {len(tdf)}")
if len(tdf):
    print(tdf.head(30).to_string(index=False))

# =============================================================================
# FINAL DECISION
# =============================================================================

print("\n[12/12] FINAL DECISION")

verdict=(
    "FREEZE_NATIVE_2_1_AND_START_FORWARD_SHADOW"
    if primary_pass
    else "REJECT_NATIVE_FINAL_USE_TRANSFER"
)

summary={
    "status":"COMPLETE",
    "name":NAME,"version":VERSION,"build":BUILD,
    "research_contract":{
        "this_is_final_native_structural_attempt":True,
        "2025_plus_used_for_tuning":False,
        "v13_scores_used":False,
        "v13_fitted_models_used":False,
        "byma_native20_base_scores_used":True,
        "stage2_models_fit_fresh":True,
        "top_n":False,
        "horizon_maturity_rule":"a horizon participates only after a purged inner meta train/validation split is feasible using prior data only",
    },
    "architecture":{
        "stage1":"BYMA Native 2.0.1 cross-sectional ranking",
        "stage2":"fresh BYMA meta-alpha magnitude model",
        "meta_information":"state + sector/rotation + event features",
        "experts":["Ridge","HistGradientBoosting","Isotonic"],
        "expert_weighting":"inner temporal validation only",
        "target":"50% BYMA UEW excess + 25% SPY excess + 25% QQQ excess",
        "portfolio":"Phase3Z cost-aware persistent allocator",
    },
    "primary_pre2025":{
        "metrics_20bps":mets[("PRE",20.0)],
        "metrics_40bps":mets[("PRE",40.0)],
        "metrics_60bps":mets[("PRE",60.0)],
        "benchmark_cagr":bench_cagr,
        "gates":gates,
        "pass":primary_pass,
        "subperiods":sub.to_dict(orient="records"),
    },
    "holdout_posthoc":{
        "metrics_20bps":mets[("HOLD",20.0)],
        "metrics_40bps":mets[("HOLD",40.0)],
        "metrics_60bps":mets[("HOLD",60.0)],
        "gating":False,
    },
    "references":{
        "v13_ideal_pre":v13_pre,
        "v13_ideal_hold":v13_hold,
        "transfer_summary_available":bool(transfer),
    },
    "current":{
        "signal_date":str(last_date.date()),
        "continuous_target_names":len(target),
    },
    "verdict":verdict,
    "next_if_pass":"Freeze 2.1; start forward shadow; then GitHub + Sheets + website.",
    "next_if_fail":"Stop native research. Operate/track V13 IDEAL + BYMA TRANSFER; improve only transfer execution and production plumbing.",
}
(OUT/"byma_native21_summary.json").write_text(
    json.dumps(summary,indent=2,default=str),encoding="utf-8"
)

website={
    "tracks":[
        {"id":"V13_IDEAL","role":"international_ideal_reference"},
        {"id":"BYMA_TRANSFER","role":"local_transfer_reference"},
        {
            "id":"BYMA_NATIVE_2_1",
            "role":"local_native_model",
            "active_only_if_primary_pass":primary_pass,
        },
        {"id":"PERSONAL","role":"actual_discretionary_portfolio"},
    ],
    "native21_verdict":verdict,
}
(OUT/"website_track_decision.json").write_text(
    json.dumps(website,indent=2),encoding="utf-8"
)

print("="*126)
print(f"NATIVE21_PRE_CAGR_20BPS: {mets[('PRE',20.0)]['cagr']:.2%}")
print(f"NATIVE21_PRE_CAGR_40BPS: {mets[('PRE',40.0)]['cagr']:.2%}")
print(f"NATIVE21_PRE_CAGR_60BPS: {mets[('PRE',60.0)]['cagr']:.2%}")
print(f"NATIVE21_PRE_MAXDD: {mets[('PRE',20.0)]['max_drawdown']:.2%}")
print(f"NATIVE21_HOLDOUT_CAGR_POSTHOC: {mets[('HOLD',20.0)]['cagr']:.2%}")
print(f"CURRENT_TARGET_NAMES: {len(target)}")
print(f"PRIMARY_GATES_PASS: {primary_pass}")
print(f"FINAL_VERDICT: {verdict}")
print("NO REAL ORDERS / NO V13 MUTATION / NO FURTHER NATIVE TUNING AFTER THIS VERDICT")
print("="*126)
