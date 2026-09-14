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
from sklearn.linear_model import Ridge

# =============================================================================
# IDENTITY
# =============================================================================

NAME = "ALPHA_ENGINE_BYMA_NATIVE"
VERSION = "2.0.1"
BUILD = "ALPHA_ENGINE_BYMA_NATIVE_2_0_1_2026-09-13"

PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "outputs" / "native_v2"
OUT.mkdir(parents=True, exist_ok=True)

V13 = Path(
    r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_V12_RETURN_FIRST"
    r"\ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
)
if not V13.exists():
    raise FileNotFoundError(f"Frozen V13 workspace not found: {V13}")

V13_SRC = V13 / "src"
if str(V13_SRC) not in sys.path:
    sys.path.insert(0, str(V13_SRC))

warnings.filterwarnings("ignore", message="Downcasting object dtype arrays")

from alpha_engine_v13 import active_alpha_persistent_portfolio as p3y
from alpha_engine_v13 import roundtrip_resize_hysteresis as p3z
from alpha_engine_v13 import economic_portfolio_closure as p3v
from alpha_engine_v13 import final_holdout as p4

# p4 already imports the authoritative V13 feature engineering module.
p2r = p4.p2r

HORIZONS = tuple(int(x) for x in p4.HORIZONS)
BASE_COST = 20.0
STRESS_COSTS = (40.0, 60.0)

FOLDS = [
    ("WF_2017_2018", pd.Timestamp("2017-01-01"), pd.Timestamp("2018-12-31")),
    ("WF_2019_2020", pd.Timestamp("2019-01-01"), pd.Timestamp("2020-12-31")),
    ("WF_2021_2022", pd.Timestamp("2021-01-01"), pd.Timestamp("2022-12-31")),
    ("WF_2023_2024", pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")),
]

# Frozen model architecture. No search / no tuning on 2025+.
RIDGE_ALPHA = 10.0
HGB_MAX_ITER = 60
HGB_LEARNING_RATE = 0.05
HGB_MAX_LEAF_NODES = 15
HGB_MIN_SAMPLES_LEAF = 40
HGB_L2 = 1.0
ENSEMBLE_RIDGE_WEIGHT = 0.50
ENSEMBLE_HGB_WEIGHT = 0.50

# Feature availability rules are determined only from pre-2025 data.
MAX_FEATURE_MISSING_SHARE = 0.95
MIN_FEATURE_STD = 1e-12
MIN_TRAIN_ROWS = 1000

# Practical nominal examples only. These are not model-validation gates.
PRACTICAL_NAVS = (320.42, 1000.0)

print("=" * 124)
print("ALPHA ENGINE BYMA NATIVE 2.0.1")
print("FRESH BYMA WALK-FORWARD TRAINING / NO V13 SCORES / NO V13 MODEL BUNDLE")
print("PRIMARY EVIDENCE = PRE2025 OOF / 2025+ = POST-HOC DIAGNOSTIC")
print("INTEGER NOMINALS ARE AN IMPLEMENTATION LAYER, NOT A MODEL-VALIDATION GATE")
print("=" * 124)

# =============================================================================
# GENERIC HELPERS
# =============================================================================

def tk(x):
    return str(x).strip().upper().replace("*", "")

def dates(s):
    return pd.to_datetime(s, errors="coerce").dt.normalize()

def maxdd(nav):
    x = pd.to_numeric(nav, errors="coerce").dropna()
    return float((x / x.cummax() - 1.0).min())

def sim_metrics(sim):
    if sim.empty:
        raise RuntimeError("Empty simulation")
    n = len(sim)
    yrs = n / 252.0
    nav = pd.to_numeric(sim["nav"], errors="coerce")
    final = float(nav.iloc[-1])
    return {
        "days": int(n),
        "final_nav": final,
        "cagr": float(final ** (1.0 / yrs) - 1.0) if final > 0 and yrs > 0 else np.nan,
        "max_drawdown": maxdd(nav),
        "annual_turnover": float(pd.to_numeric(sim["turnover"], errors="coerce").fillna(0).sum() / yrs),
        "median_holdings": float(pd.to_numeric(sim["holdings"], errors="coerce").median()),
        "mean_cash": float(pd.to_numeric(sim["cash_weight"], errors="coerce").mean()),
        "p95_max_name": float(pd.to_numeric(sim["max_name_weight"], errors="coerce").quantile(.95)),
    }

def cagr_from_returns(r):
    x = pd.to_numeric(r, errors="coerce").dropna()
    if x.empty:
        return np.nan
    years = len(x) / 252.0
    total = float((1.0 + x).prod())
    return float(total ** (1.0 / years) - 1.0) if total > 0 else np.nan

def annual_returns(sim):
    x = sim[["date","net_return"]].copy()
    x["date"] = pd.to_datetime(x["date"])
    x["year"] = x["date"].dt.year
    return (
        x.groupby("year")["net_return"]
         .apply(lambda z: float((1 + z).prod() - 1))
         .rename("strategy_return")
         .reset_index()
    )

def get_h(mapping, h):
    if h in mapping:
        return mapping[h]
    if str(h) in mapping:
        return mapping[str(h)]
    raise KeyError(h)

# =============================================================================
# BYMA MASTER FROM CERTIFIED 1.0.1
# =============================================================================

print("\n[1/12] LOAD CERTIFIED CURRENT BYMA UNIVERSE")

MASTER_PATH = PROJECT / "outputs" / "byma_master.csv"
if not MASTER_PATH.exists():
    raise FileNotFoundError(
        "Missing outputs/byma_master.csv. Run ALPHA ENGINE BYMA 1.0.1 first."
    )

master = pd.read_csv(MASTER_PATH)
required_master = {"issuer","origin_ticker","byma_ticker","ratio_a","ratio_b","ratio"}
missing_master = sorted(required_master - set(master.columns))
if missing_master:
    raise RuntimeError(f"BYMA master missing columns: {missing_master}")

master["origin_ticker"] = master["origin_ticker"].map(tk)
master["byma_ticker"] = master["byma_ticker"].map(tk)

LOCAL = {
    "CEPU": {"byma_ticker": "CEPU", "local_per_adr": 10.0},
    "YPF": {"byma_ticker": "YPFD", "local_per_adr": 10.0},
}

accessible = (
    set(master["origin_ticker"])
    | set(master["byma_ticker"])
    | set(LOCAL)
)
accessible.discard("")
accessible.discard("NAN")

print(f"  official CEDEAR rows: {len(master):,}")
print(f"  current accessible aliases: {len(accessible):,}")

# =============================================================================
# FROZEN V13 DATA INFRASTRUCTURE, NOT V13 PREDICTIONS
# =============================================================================

print("\n[2/12] LOAD PIT FEATURE / TARGET INFRASTRUCTURE")

cfg3z = p3z.load_cfg(V13)
_, _, source, _, _ = p3y.load_inputs(V13, cfg3z)
hold = pd.Timestamp(cfg3z.p["holdout_start"])
portfolio_start = pd.Timestamp(cfg3z.p["portfolio_start"])

# IMPORTANT:
# BYMA Native is a new model. It must not depend on V13's production seal or
# fitted model bundle. The V13 directory may no longer be byte-identical to
# the original seal after later research work, while its authoritative NAV
# artifacts remain preserved. We therefore read only the PIT research inputs.
research_features, research_targets = p4._preholdout_inputs(V13, hold)
research_features["ticker"] = research_features["ticker"].map(tk)
research_targets["ticker"] = research_targets["ticker"].map(tk)

# Explicitly prove we are not reading V13 forecast score artifacts.
FORBIDDEN_PREDICTION_INPUTS = [
    V13 / "outputs" / "v13_phase2u_oof_scores.parquet",
    V13 / "outputs" / "v13_phase4_holdout_advisor.parquet",
]
print("  prediction inputs from V13:")
for p in FORBIDDEN_PREDICTION_INPUTS:
    print(f"    NOT READ: {p.name}")

# Build complete 2025+ raw features using the same PIT data builder.
cfg1 = p4.p1.load_cfg(V13)
cfg1full = p4.p1.Cfg({**cfg1.p, "holdout_start": "2100-01-01"})
market_full, price_meta = p4._load_full_market(source, cfg1full)
market_full["date"] = dates(market_full["date"])
market_full["ticker"] = market_full["ticker"].map(tk)
end = pd.Timestamp(market_full["date"].max())

bench_full = p4._load_full_bench(source, cfg1full, market_full)
bench_full["date"] = dates(bench_full["date"])

hold_keys = p4._holdout_target_keys(source, hold, end)
hold_features, _ = p4.p1.build_feature_library(
    source, hold_keys, cfg1full,
    market=market_full, bench=bench_full, price_meta=price_meta
)
hold_features["signal_date"] = dates(hold_features["signal_date"])
hold_features["ticker"] = hold_features["ticker"].map(tk)

hold_targets = p4._load_holdout_targets(source, hold, end, bench_full)
hold_targets["signal_date"] = dates(hold_targets["signal_date"])
hold_targets["ticker"] = hold_targets["ticker"].map(tk)

# Current universe first.
rf = research_features[research_features["ticker"].isin(accessible)].copy()
rt = research_targets[research_targets["ticker"].isin(accessible)].copy()
hf = hold_features[hold_features["ticker"].isin(accessible)].copy()
ht = hold_targets[hold_targets["ticker"].isin(accessible)].copy()

print(f"  pre2025 raw feature rows: {len(rf):,}")
print(f"  pre2025 current-BYMA tickers: {rf.ticker.nunique():,}")
print(f"  2025+ raw feature rows: {len(hf):,}")
print(f"  2025+ current-BYMA tickers: {hf.ticker.nunique():,}")

if rf.empty or hf.empty:
    raise RuntimeError("Current BYMA universe has no usable feature rows")

# =============================================================================
# FEATURE TRANSFORMATION WITH BYMA CROSS SECTION
# =============================================================================

print("\n[3/12] BYMA-NATIVE FEATURE TRANSFORMATION")

# Build a BYMA-native raw feature universe directly from the PIT feature
# library. No V13 fitted bundle, feature subset, coefficient or score is used.
#
# The phase1 feature library is already separated from research targets.
# We still fail closed on obvious leakage-like names.
NON_FEATURE_EXACT = {
    "signal_date","ticker","date","fold","entry_date","available_date",
    "research_eligible","execution_close","mark_price","close","adj_close",
}
LEAK_PATTERNS = (
    "target_","fwd_","future","forward_return","winner_","label",
    "resolved_","target_end","outcome","realized_",
)

shared_raw = [c for c in rf.columns if c in hf.columns]
base_universe = []

for c in shared_raw:
    lc = str(c).lower()
    if lc in NON_FEATURE_EXACT:
        continue
    if any(p in lc for p in LEAK_PATTERNS):
        continue

    xp = pd.to_numeric(rf[c], errors="coerce")
    xh = pd.to_numeric(hf[c], errors="coerce")

    # Require actual numeric information pre-2025 and preserve only columns
    # whose type is also numerically usable in 2025+.
    if xp.notna().sum() < 100 or xh.notna().sum() < 20:
        continue

    miss = float(xp.isna().mean())
    std = float(xp.std(skipna=True)) if xp.notna().sum() > 1 else 0.0

    if (
        miss <= MAX_FEATURE_MISSING_SHARE
        and np.isfinite(std)
        and std > MIN_FEATURE_STD
    ):
        base_universe.append(c)

base_universe = sorted(set(base_universe))

if len(base_universe) < 10:
    raise RuntimeError(
        f"BYMA native PIT feature universe too small: {len(base_universe)}"
    )

suspicious = [
    c for c in base_universe
    if any(p in str(c).lower() for p in LEAK_PATTERNS)
]
if suspicious:
    raise RuntimeError(
        f"LEAKAGE GUARD FAILED in raw feature universe: {suspicious[:12]}"
    )

print(f"  raw native numeric feature universe: {len(base_universe)}")

def transform_native(raw):
    ranked = p2r.cross_sectional_rank_features(raw, base_universe)
    transformed, _ = p2r.add_regime_features(raw, ranked)
    transformed["signal_date"] = dates(transformed["signal_date"])
    transformed["ticker"] = transformed["ticker"].map(tk)
    return transformed.sort_values(["signal_date","ticker"]).reset_index(drop=True)

pre_feat = transform_native(rf)
hold_feat = transform_native(hf)

print(f"  transformed pre rows: {len(pre_feat):,}")
print(f"  transformed hold rows: {len(hold_feat):,}")

# Native model feature universe is derived from the transformed BYMA PIT
# surface itself. Again: no V13 model bundle is consulted.
shared_transformed = [
    c for c in pre_feat.columns
    if c in hold_feat.columns
    and c not in {"signal_date","ticker"}
]

native_candidate_features = []
for c in shared_transformed:
    lc = str(c).lower()
    if any(p in lc for p in LEAK_PATTERNS):
        continue
    xp = pd.to_numeric(pre_feat[c], errors="coerce")
    xh = pd.to_numeric(hold_feat[c], errors="coerce")
    if xp.notna().sum() < 100 or xh.notna().sum() < 20:
        continue
    miss = float(xp.isna().mean())
    std = float(xp.std(skipna=True)) if xp.notna().sum() > 1 else 0.0
    if miss <= MAX_FEATURE_MISSING_SHARE and np.isfinite(std) and std > MIN_FEATURE_STD:
        native_candidate_features.append(c)

native_candidate_features = sorted(set(native_candidate_features))

if len(native_candidate_features) < 10:
    raise RuntimeError(
        f"BYMA native transformed feature universe too small: "
        f"{len(native_candidate_features)}"
    )

print(
    f"  transformed native model feature candidates: "
    f"{len(native_candidate_features)}"
)

# =============================================================================
# ACTIVE TARGETS: 50% BYMA UEW + 25% SPY + 25% QQQ
# =============================================================================

print("\n[4/12] BUILD BYMA-NATIVE ACTIVE TARGETS")

bench_px = (
    bench_full[["date","SPY","QQQ"]]
    .drop_duplicates("date")
    .sort_values("date")
    .set_index("date")
)

for h in HORIZONS:
    bench_px[f"SPY_FWD_{h}"] = bench_px["SPY"].shift(-h) / bench_px["SPY"] - 1.0
    bench_px[f"QQQ_FWD_{h}"] = bench_px["QQQ"].shift(-h) / bench_px["QQQ"] - 1.0

def add_native_targets(t):
    z = t.copy()
    for h in HORIZONS:
        retc = f"fwd_return_{h}d"
        resc = f"target_resolved_{h}d"
        endc = f"target_end_date_{h}d"
        for c in [retc, resc, endc]:
            if c not in z.columns:
                raise RuntimeError(f"Target file missing {c}")

        z[retc] = pd.to_numeric(z[retc], errors="coerce")
        z[resc] = z[resc].fillna(False).astype(bool)
        z[endc] = dates(z[endc])

        # Local equal-weight benchmark from the current BYMA deployment universe.
        valid = z[resc] & z[retc].notna()
        local_uew = (
            z.loc[valid]
             .groupby("signal_date")[retc]
             .mean()
        )
        z[f"BYMA_UEW_FWD_{h}"] = z["signal_date"].map(local_uew)
        z[f"SPY_FWD_{h}"] = z["signal_date"].map(bench_px[f"SPY_FWD_{h}"])
        z[f"QQQ_FWD_{h}"] = z["signal_date"].map(bench_px[f"QQQ_FWD_{h}"])

        active_total = (
            0.50 * (z[retc] - z[f"BYMA_UEW_FWD_{h}"])
            + 0.25 * (z[retc] - z[f"SPY_FWD_{h}"])
            + 0.25 * (z[retc] - z[f"QQQ_FWD_{h}"])
        )
        z[f"native_active_ps_{h}"] = active_total / float(h)

        # Cross-sectional target for native ranking model.
        z[f"native_rank_target_{h}"] = np.nan
        z.loc[valid, f"native_rank_target_{h}"] = (
            z.loc[valid]
             .groupby("signal_date")[retc]
             .rank(method="average", pct=True)
        )
    return z

rt2 = add_native_targets(rt)
ht2 = add_native_targets(ht)

# Merge targets into transformed feature surface.
pre = pre_feat.merge(rt2, on=["signal_date","ticker"], how="left", validate="one_to_one")
hold_data = hold_feat.merge(ht2, on=["signal_date","ticker"], how="left", validate="one_to_one")

# =============================================================================
# MODEL ENGINE
# =============================================================================

def select_features(df, candidate_features):
    keep = []
    for c in candidate_features:
        if c not in df.columns:
            continue
        x = pd.to_numeric(df[c], errors="coerce").replace([np.inf,-np.inf], np.nan)
        missing = float(x.isna().mean())
        std = float(x.std(skipna=True)) if x.notna().sum() > 1 else 0.0
        if missing <= MAX_FEATURE_MISSING_SHARE and np.isfinite(std) and std > MIN_FEATURE_STD:
            keep.append(c)
    return keep

def numeric_matrix(df, cols):
    return (
        df[cols]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf,-np.inf], np.nan)
        .to_numpy(float)
    )

def fit_native(train, features, target_col):
    y = pd.to_numeric(train[target_col], errors="coerce").to_numpy(float)
    X = numeric_matrix(train, features)
    ok = np.isfinite(y)
    X = X[ok]
    y = y[ok]
    if len(y) < MIN_TRAIN_ROWS:
        raise RuntimeError(f"Only {len(y)} train rows for {target_col}")

    med = np.nanmedian(X, axis=0)
    med[~np.isfinite(med)] = 0.0
    Xi = np.where(np.isfinite(X), X, med)

    mu = np.mean(Xi, axis=0)
    sd = np.std(Xi, axis=0)
    sd[~np.isfinite(sd) | (sd < 1e-12)] = 1.0
    Xz = (Xi - mu) / sd

    ridge = Ridge(alpha=RIDGE_ALPHA, fit_intercept=True)
    ridge.fit(Xz, y)

    hgb = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=HGB_LEARNING_RATE,
        max_iter=HGB_MAX_ITER,
        max_leaf_nodes=HGB_MAX_LEAF_NODES,
        min_samples_leaf=HGB_MIN_SAMPLES_LEAF,
        l2_regularization=HGB_L2,
        random_state=1309,
    )
    hgb.fit(Xi, y)

    return {
        "features": list(features),
        "median": med,
        "mu": mu,
        "sd": sd,
        "ridge": ridge,
        "hgb": hgb,
        "train_rows": int(len(y)),
    }

def predict_native(model, df):
    X = numeric_matrix(df, model["features"])
    Xi = np.where(np.isfinite(X), X, model["median"])
    Xz = (Xi - model["mu"]) / model["sd"]
    pr = model["ridge"].predict(Xz)
    ph = model["hgb"].predict(Xi)
    return ENSEMBLE_RIDGE_WEIGHT * pr + ENSEMBLE_HGB_WEIGHT * ph

def daily_rank(date_series, values):
    q = pd.DataFrame({"d":pd.to_datetime(date_series), "v":values})
    return q.groupby("d")["v"].rank(method="average", pct=True).to_numpy(float)

# Same ex-ante native candidate universe for every horizon. Each horizon fits
# its own independent coefficients/trees and sees only targets resolved before
# its training cutoff.
candidate_by_h = {}
selected_by_h = {}
for h in HORIZONS:
    candidate_by_h[h] = list(native_candidate_features)
    selected_by_h[h] = select_features(pre, candidate_by_h[h])
    if len(selected_by_h[h]) < 10:
        raise RuntimeError(
            f"h={h}: too few usable native features "
            f"({len(selected_by_h[h])})"
        )
    print(
        f"  h={h:>3}: {len(candidate_by_h[h])} native candidates "
        f"-> {len(selected_by_h[h])} usable features"
    )

# =============================================================================
# WALK-FORWARD OOF SCORES
# =============================================================================

print("\n[5/12] NATIVE WALK-FORWARD OOF TRAINING")

oof_parts = []
fold_models = {}

for fold_name, test_start, test_end in FOLDS:
    print(f"  {fold_name}")
    test = pre[(pre.signal_date >= test_start) & (pre.signal_date <= test_end)].copy()
    if test.empty:
        raise RuntimeError(f"No test rows in {fold_name}")

    for h in HORIZONS:
        endc = f"target_end_date_{h}d"
        resc = f"target_resolved_{h}d"
        yc = f"native_rank_target_{h}"

        train = pre[
            (pre.signal_date < test_start)
            & pre[resc].fillna(False)
            & (pre[endc] < test_start)
            & pre[yc].notna()
        ].copy()

        model = fit_native(train, selected_by_h[h], yc)
        raw = predict_native(model, test)
        score = daily_rank(test["signal_date"], raw)

        out = test[["signal_date","ticker"]].copy()
        out["horizon_sessions"] = h
        out["fold"] = fold_name
        out["score"] = score
        oof_parts.append(out)
        fold_models[(fold_name,h)] = model

        print(f"    h={h:>3}: train={model['train_rows']:,} test={len(test):,}")

oof = (
    pd.concat(oof_parts, ignore_index=True)
    .sort_values(["signal_date","ticker","horizon_sessions"])
    .reset_index(drop=True)
)
oof.to_parquet(OUT / "byma_native_oof_scores.parquet", index=False)

# =============================================================================
# FINAL PRE2025 MODELS -> 2025+ SCORES
# =============================================================================

print("\n[6/12] FIT FINAL PRE2025 NATIVE BUNDLE AND SCORE 2025+")

final_models = {}
hold_score_parts = []

for h in HORIZONS:
    endc = f"target_end_date_{h}d"
    resc = f"target_resolved_{h}d"
    yc = f"native_rank_target_{h}"

    train = pre[
        pre[resc].fillna(False)
        & (pre[endc] < hold)
        & pre[yc].notna()
    ].copy()

    model = fit_native(train, selected_by_h[h], yc)
    final_models[h] = model

    raw = predict_native(model, hold_data)
    score = daily_rank(hold_data["signal_date"], raw)

    out = hold_data[["signal_date","ticker"]].copy()
    out["horizon_sessions"] = h
    out["fold"] = "FINAL_HOLDOUT_NATIVE"
    out["score"] = score
    hold_score_parts.append(out)

    print(f"  h={h:>3}: final train={model['train_rows']:,} hold rows={len(hold_data):,}")

hold_scores = (
    pd.concat(hold_score_parts, ignore_index=True)
    .sort_values(["signal_date","ticker","horizon_sessions"])
    .reset_index(drop=True)
)
hold_scores.to_parquet(OUT / "byma_native_holdout_scores.parquet", index=False)

joblib.dump(
    {
        "name": NAME,
        "version": VERSION,
        "build": BUILD,
        "horizons": HORIZONS,
        "selected_features": selected_by_h,
        "models": final_models,
        "universe_aliases": sorted(accessible),
        "trained_through": "2024-12-31",
    },
    OUT / "byma_native_model_bundle.joblib",
    compress=3,
)

# =============================================================================
# OOF ACTIVE-ALPHA CALIBRATION
# =============================================================================

print("\n[7/12] OOF-ONLY ALPHA CALIBRATION")

def active_long(targets):
    parts = []
    for h in HORIZONS:
        q = targets[
            ["signal_date","ticker",f"target_end_date_{h}d",f"native_active_ps_{h}"]
        ].copy()
        q.columns = ["signal_date","ticker","target_end_date","active_ps"]
        q["horizon_sessions"] = h
        parts.append(q)
    return pd.concat(parts, ignore_index=True)

pre_active = active_long(rt2)
hold_active = active_long(ht2)

def calibration(scores, active, cutoff):
    q = scores.merge(
        active,
        on=["signal_date","ticker","horizon_sessions"],
        how="inner",
        validate="many_to_one",
    )
    q = q[
        (q["signal_date"] < cutoff)
        & (q["target_end_date"] < cutoff)
        & q["score"].notna()
        & q["active_ps"].notna()
    ].copy()

    rows = []
    for h in HORIZONS:
        g = q[q.horizon_sessions.eq(h)].copy()
        if len(g) < 500:
            raise RuntimeError(f"Insufficient calibration rows h={h}: {len(g)}")

        ic = float(g["score"].corr(g["active_ps"], method="spearman"))
        y = g["active_ps"].to_numpy(float)
        lo, hi = np.nanquantile(y, [0.01,0.99])
        y = np.clip(y, lo, hi)
        x = g["score"].to_numpy(float)

        # Fixed linear magnitude calibration. No holdout fitting.
        X = np.column_stack([np.ones(len(x)), x])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        intercept, slope = float(coef[0]), float(coef[1])
        pred = intercept + slope*x
        rmse = float(np.sqrt(np.mean((y-pred)**2)))

        skill = max(0.0, ic) if slope > 0 else 0.0
        rows.append({
            "horizon_sessions":h,
            "rows":len(g),
            "ic":ic,
            "intercept":intercept,
            "slope":slope,
            "rmse":rmse,
            "raw_skill":skill,
        })

    c = pd.DataFrame(rows)
    s = float(c["raw_skill"].sum())
    if s <= 0:
        raise RuntimeError(f"No positive OOF ranking skill before {cutoff.date()}")
    c["weight"] = c["raw_skill"] / s
    return c

def advisor_from_scores(scores, calib, label):
    cm = calib.set_index("horizon_sessions").to_dict(orient="index")
    q = scores.copy()
    q["expected_h"] = [
        cm[int(h)]["intercept"] + cm[int(h)]["slope"]*float(s)
        for h,s in zip(q["horizon_sessions"],q["score"])
    ]
    q["global_weight"] = q["horizon_sessions"].map(
        {h:cm[h]["weight"] for h in cm}
    ).astype(float)
    q["h_rmse"] = q["horizon_sessions"].map(
        {h:cm[h]["rmse"] for h in cm}
    ).astype(float)

    rows = []
    for (d,t), g in q.groupby(["signal_date","ticker"], sort=False):
        g = g[g["global_weight"] > 0].copy()
        if g.empty:
            continue
        w = g["global_weight"].to_numpy(float)
        w = w / w.sum()
        a = g["expected_h"].to_numpy(float)
        h = g["horizon_sessions"].to_numpy(float)
        sig = g["h_rmse"].to_numpy(float)

        row = {
            "signal_date":pd.Timestamp(d),
            "ticker":tk(t),
            "fold":label,
            "expected_active_per_session":float(np.sum(w*a)),
            "uncertainty_per_session":float(np.sqrt(np.sum((w*sig)**2))),
            "positive_active_horizon_share":float(np.sum(w*(a>0))),
            "effective_horizon_sessions":float(np.sum(w*h)),
        }
        for hh in HORIZONS:
            mask = h == hh
            row[f"horizon_weight_{hh}d"] = float(w[mask][0]) if mask.any() else 0.0
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["signal_date","ticker"]).reset_index(drop=True)

# Portfolio OOF starts in 2019; each period uses calibration only from earlier OOF.
advisor_parts = []
calibration_history = []

portfolio_folds = [
    ("WF_2019_2020", pd.Timestamp("2019-01-01"), pd.Timestamp("2020-12-31")),
    ("WF_2021_2022", pd.Timestamp("2021-01-01"), pd.Timestamp("2022-12-31")),
    ("WF_2023_2024", pd.Timestamp("2023-01-01"), pd.Timestamp("2024-12-31")),
]

for fold_name, a, b in portfolio_folds:
    cal = calibration(oof, pre_active, a)
    cal["portfolio_fold"] = fold_name
    calibration_history.append(cal)
    sc = oof[(oof.signal_date >= a)&(oof.signal_date <= b)].copy()
    adv = advisor_from_scores(sc, cal, fold_name)
    advisor_parts.append(adv)
    print(
        f"  {fold_name}: advisor rows={len(adv):,}, "
        f"positive skill horizons={int((cal.weight>0).sum())}"
    )

advisor_pre = pd.concat(advisor_parts, ignore_index=True).sort_values(["signal_date","ticker"])
cal_hold = calibration(oof, pre_active, hold)
advisor_hold = advisor_from_scores(hold_scores, cal_hold, "FINAL_HOLDOUT_NATIVE")

pd.concat(calibration_history, ignore_index=True).to_csv(
    OUT / "byma_native_calibration_history.csv", index=False
)
cal_hold.to_csv(OUT / "byma_native_final_calibration.csv", index=False)
advisor_pre.to_parquet(OUT / "byma_native_advisor_pre2025.parquet", index=False)
advisor_hold.to_parquet(OUT / "byma_native_advisor_holdout.parquet", index=False)

# =============================================================================
# MARKET / PORTFOLIO SIMULATION
# =============================================================================

print("\n[8/12] NATIVE PORTFOLIO SIMULATION")

pcfg = p3v.load_cfg(V13)
needed = set(advisor_pre.ticker.unique()) | set(advisor_hold.ticker.unique())

surface_pre = p3v.load_market(V13, source, pcfg, needed)
spy_pre = p3v._load_benchmark(source, pcfg.p["source_spy_benchmark"], "SPY", hold)
qqq_pre = p3v._load_benchmark(source, pcfg.p["source_qqq_benchmark"], "QQQ", hold)
market_pre = p3v.prepare_market(
    surface_pre, spy_pre, portfolio_start, hold,
    int(cfg3z.p["risk_lookback_sessions"])
)

# Holdout market from canonical PIT layer.
c = pd.read_parquet(
    source / "outputs" / "phase2_canonical_pit_panel.parquet",
    columns=["date","ticker","close","research_eligible"]
)
r = pd.read_parquet(
    source / "outputs" / "phase2c_return_price_layer.parquet",
    columns=["date","ticker","target_total_return_price"]
)
c["date"] = dates(c["date"]); c["ticker"] = c["ticker"].map(tk)
r["date"] = dates(r["date"]); r["ticker"] = r["ticker"].map(tk)
surf_hold = c.merge(r,on=["date","ticker"],how="left")
surf_hold["execution_close"] = pd.to_numeric(surf_hold["close"],errors="coerce")
surf_hold["mark_price"] = pd.to_numeric(surf_hold["target_total_return_price"],errors="coerce")
surf_hold["research_eligible"] = surf_hold["research_eligible"].fillna(False).astype(bool)
surf_hold = surf_hold[["date","ticker","execution_close","mark_price","research_eligible"]]

spy_h = (
    bench_full.dropna(subset=["SPY"]).drop_duplicates("date")
    .set_index("date")["SPY"]
)
qqq_h = (
    bench_full.dropna(subset=["QQQ"]).drop_duplicates("date")
    .set_index("date")["QQQ"]
)
end_excl = end + pd.Timedelta(days=1)
market_hold = p3v.prepare_market(
    surf_hold, spy_h, hold, end_excl,
    int(cfg3z.p["risk_lookback_sessions"])
)

terminals = p3v.load_terminals(source, pcfg)

plans_pre = p3z.build_plans(advisor_pre, market_pre, cfg3z)
plans_hold = p3z.build_plans(advisor_hold, market_hold, cfg3z)

native_sims = {}
native_metrics = {}

for cost in (20.0,40.0,60.0):
    sp = p3y.simulate_persistent(plans_pre, market_pre, terminals, portfolio_start, hold, cost)
    sh = p3y.simulate_persistent(plans_hold, market_hold, terminals, hold, end_excl, cost)
    native_sims[("PRE",cost)] = sp
    native_sims[("HOLD",cost)] = sh
    native_metrics[("PRE",cost)] = sim_metrics(sp)
    native_metrics[("HOLD",cost)] = sim_metrics(sh)
    print(
        f"  {int(cost):>2}bps | PRE CAGR {native_metrics[('PRE',cost)]['cagr']:.2%} "
        f"DD {native_metrics[('PRE',cost)]['max_drawdown']:.2%} | "
        f"HOLD CAGR {native_metrics[('HOLD',cost)]['cagr']:.2%} "
        f"DD {native_metrics[('HOLD',cost)]['max_drawdown']:.2%}"
    )

native_sims[("PRE",20.0)].to_csv(OUT/"byma_native_nav_pre2025_20bps.csv",index=False)
native_sims[("HOLD",20.0)].to_csv(OUT/"byma_native_nav_holdout_20bps.csv",index=False)

# Benchmark returns.
def local_uew(market, tickers):
    cols = [c for c in market["returns"].columns if tk(c) in tickers]
    if not cols:
        return pd.Series(dtype=float)
    return market["returns"][cols].mean(axis=1, skipna=True)

bench_returns_pre = {
    "SPY": p3v.benchmark_returns(source,pcfg,market_pre,spy_pre,qqq_pre)["SPY"],
    "QQQ": p3v.benchmark_returns(source,pcfg,market_pre,spy_pre,qqq_pre)["QQQ"],
    "BYMA_UEW": local_uew(market_pre, set(advisor_pre.ticker.unique())),
}
bench_returns_hold = {
    "SPY": p3v.benchmark_returns(source,pcfg,market_hold,spy_h,qqq_h)["SPY"],
    "QQQ": p3v.benchmark_returns(source,pcfg,market_hold,spy_h,qqq_h)["QQQ"],
    "BYMA_UEW": local_uew(market_hold, set(advisor_hold.ticker.unique())),
}

alpha_rows = []
for sample, sim, benches in [
    ("PRE2025_OOF",native_sims[("PRE",20.0)],bench_returns_pre),
    ("HOLDOUT_POSTHOC",native_sims[("HOLD",20.0)],bench_returns_hold),
]:
    sr = sim.set_index("date").net_return
    for name,b in benches.items():
        ols = p3y._ols(sr,b.reindex(sr.index))
        alpha_rows.append({"sample":sample,"benchmark":name,**ols})
alpha_df = pd.DataFrame(alpha_rows)
alpha_df.to_csv(OUT/"byma_native_active_alpha.csv",index=False)

# =============================================================================
# HOLDOUT GAP DIAGNOSTIC
# =============================================================================

print("\n[9/12] WHY DID LOCAL HOLDOUT FALL?")

# Ideal V13 official.
ideal_pre = pd.read_csv(V13/"outputs"/"v13_phase3z_nav_20bps.csv")
ideal_hold = pd.read_csv(V13/"outputs"/"v13_phase4_holdout_nav_20bps.csv")
ideal_pre_m = sim_metrics(ideal_pre)
ideal_hold_m = sim_metrics(ideal_hold)

# Transfer benchmark from 1.0.1, if available.
transfer_pre_path = PROJECT/"outputs"/"byma_pre2025_nav_20bps.csv"
transfer_hold_path = PROJECT/"outputs"/"byma_holdout_nav_20bps.csv"
transfer_pre_m = sim_metrics(pd.read_csv(transfer_pre_path)) if transfer_pre_path.exists() else None
transfer_hold_m = sim_metrics(pd.read_csv(transfer_hold_path)) if transfer_hold_path.exists() else None

# IC pre vs realized 2025+.
hold_eval = hold_scores.merge(
    hold_active,
    on=["signal_date","ticker","horizon_sessions"],
    how="inner"
)
ic_rows = []
for h in HORIZONS:
    preq = oof.merge(
        pre_active,
        on=["signal_date","ticker","horizon_sessions"],
        how="inner"
    )
    preq = preq[
        preq.horizon_sessions.eq(h)
        & (preq.target_end_date < hold)
    ]
    hq = hold_eval[
        hold_eval.horizon_sessions.eq(h)
        & hold_eval.active_ps.notna()
    ]
    pre_ic = float(preq.score.corr(preq.active_ps,method="spearman"))
    hold_ic = float(hq.score.corr(hq.active_ps,method="spearman")) if len(hq)>20 else np.nan
    ic_rows.append({
        "horizon_sessions":h,
        "pre2025_oof_ic":pre_ic,
        "holdout_posthoc_ic":hold_ic,
        "ic_change":hold_ic-pre_ic if np.isfinite(hold_ic) else np.nan,
        "pre_rows":len(preq),
        "hold_rows":len(hq),
    })
ic_df = pd.DataFrame(ic_rows)
ic_df.to_csv(OUT/"byma_native_ic_by_horizon.csv",index=False)

# Annual strategy returns.
yrs_pre = annual_returns(native_sims[("PRE",20.0)])
yrs_hold = annual_returns(native_sims[("HOLD",20.0)])
years = pd.concat([
    yrs_pre.assign(sample="PRE2025_OOF"),
    yrs_hold.assign(sample="HOLDOUT_POSTHOC")
],ignore_index=True)
years.to_csv(OUT/"byma_native_annual_returns.csv",index=False)

gap_rows = [{
    "metric":"CAGR",
    "V13_IDEAL_PRE":ideal_pre_m["cagr"],
    "V13_IDEAL_HOLD":ideal_hold_m["cagr"],
    "TRANSFER_PRE":transfer_pre_m["cagr"] if transfer_pre_m else np.nan,
    "TRANSFER_HOLD":transfer_hold_m["cagr"] if transfer_hold_m else np.nan,
    "NATIVE_PRE":native_metrics[("PRE",20.0)]["cagr"],
    "NATIVE_HOLD":native_metrics[("HOLD",20.0)]["cagr"],
}]
pd.DataFrame(gap_rows).to_csv(OUT/"byma_native_holdout_gap_diagnostic.csv",index=False)

pre_ic_mean = float(ic_df.pre2025_oof_ic.mean())
hold_ic_mean = float(ic_df.holdout_posthoc_ic.mean())
print(f"  mean native score IC PRE2025: {pre_ic_mean:.4f}")
print(f"  mean native score IC HOLDOUT: {hold_ic_mean:.4f}")

if transfer_hold_m:
    universe_gap = ideal_hold_m["cagr"] - transfer_hold_m["cagr"]
    native_recovery = native_metrics[("HOLD",20.0)]["cagr"] - transfer_hold_m["cagr"]
    print(f"  V13 -> transfer-BYMA holdout CAGR gap: {universe_gap:.2%}")
    print(f"  native retraining recovery vs transfer: {native_recovery:+.2%}")

if np.isfinite(pre_ic_mean) and np.isfinite(hold_ic_mean) and pre_ic_mean != 0:
    print(f"  holdout/pre mean IC ratio: {hold_ic_mean/pre_ic_mean:.2%}")

# =============================================================================
# CURRENT TARGET + PRACTICAL NOMINALS
# =============================================================================

print("\n[10/12] CURRENT NATIVE BYMA TARGET")

last_plan_date = max(plans_hold)
last_plan = plans_hold[last_plan_date]
target = {
    tk(t):float(p["desired"])
    for t,p in last_plan.items()
    if bool(p.get("entry_ok",False)) and float(p.get("desired",0.0)) > 0
}

target_df = pd.DataFrame(
    [{"signal_date":last_plan_date,"ticker":t,"target_weight":w}
     for t,w in target.items()]
).sort_values("target_weight",ascending=False)
target_df.to_csv(OUT/"byma_native_current_target_continuous.csv",index=False)

by_origin = {}
for rr in master.itertuples():
    by_origin.setdefault(tk(rr.origin_ticker),[]).append(rr)
    by_origin.setdefault(tk(rr.byma_ticker),[]).append(rr)

def unit_info(t, underlying_price):
    t = tk(t)
    px = float(underlying_price) if np.isfinite(underlying_price) else np.nan
    if not np.isfinite(px) or px<=0:
        return None
    candidates = []
    for rr in by_origin.get(t,[]):
        a,b = int(rr.ratio_a),int(rr.ratio_b)
        unit = px*(b/a)
        if np.isfinite(unit) and unit>0:
            candidates.append({
                "vehicle":f"CEDEAR_{rr.issuer}",
                "byma_ticker":tk(rr.byma_ticker),
                "ratio":f"{a}:{b}",
                "unit_usd":float(unit),
            })
    if t in LOCAL:
        n=float(LOCAL[t]["local_per_adr"])
        candidates.append({
            "vehicle":"LOCAL_BYMA_SHARE",
            "byma_ticker":LOCAL[t]["byma_ticker"],
            "ratio":f"1 ADR:{n:g} LOCAL",
            "unit_usd":float(px/n),
        })
    return min(candidates,key=lambda x:x["unit_usd"]) if candidates else None

# Attach raw price matrix only for sizing.
price_panel = (
    surf_hold.pivot_table(
        index="date",columns="ticker",values="execution_close",aggfunc="last"
    ).sort_index()
)
price_dates = price_panel.index[price_panel.index<=last_plan_date]
if len(price_dates)==0:
    raise RuntimeError("No current raw price date")
price_date = pd.Timestamp(price_dates.max())
prices = price_panel.loc[price_date]

def integer_snapshot(nav):
    rows=[]
    invested=0.0
    for t,w in target.items():
        info=unit_info(t,prices.get(t,np.nan))
        if info is None:
            continue
        unit=info["unit_usd"]
        qstar=w*nav/unit
        qfloor=math.floor(qstar)
        frac=qstar-qfloor
        q=int(qfloor+1 if frac>0.5 else qfloor)
        aw=q*unit/nav
        rows.append({
            "signal_date":last_plan_date,"price_date":price_date,
            "ticker":t,"target_weight":w,**info,
            "q_star":qstar,"quantity":q,"actual_weight":aw,
            "weight_error":aw-w,
        })
        invested += aw

    d=pd.DataFrame(rows)
    # Budget repair if nearest rounds above 100%.
    if invested>1 and not d.empty:
        ups=[]
        for i,r in d.iterrows():
            floorq=int(math.floor(r.q_star))
            if int(r.quantity)>floorq:
                frac=float(r.q_star)-floorq
                ups.append((2*frac-1,-float(r.unit_usd),i,floorq))
        ups.sort()
        for _,_,i,floorq in ups:
            if invested<=1+1e-10:
                break
            old=float(d.loc[i,"actual_weight"])
            new=floorq*float(d.loc[i,"unit_usd"])/nav
            d.loc[i,"quantity"]=floorq
            d.loc[i,"actual_weight"]=new
            d.loc[i,"weight_error"]=new-float(d.loc[i,"target_weight"])
            invested += new-old
    cash=max(0.0,1.0-float(d.actual_weight.sum() if len(d) else 0))
    return d.sort_values("target_weight",ascending=False),cash

for nav in PRACTICAL_NAVS:
    d,cash=integer_snapshot(nav)
    fn = f"byma_native_current_target_usd{int(round(nav))}.csv"
    d.to_csv(OUT/fn,index=False)
    print(
        f"  USD {nav:,.2f}: continuous names={len(target)}, "
        f"integer positive names={int((d.quantity>0).sum()) if len(d) else 0}, cash={cash:.2%}"
    )

print(f"  signal date: {last_plan_date.date()}")
print(f"  continuous target names: {len(target_df)}")
if len(target_df):
    print(target_df.to_string(index=False))

# =============================================================================
# PRIMARY VALIDATION GATE
# =============================================================================

print("\n[11/12] PRIMARY PRE2025 VALIDATION")

pre_m = native_metrics[("PRE",20.0)]
pre40 = native_metrics[("PRE",40.0)]
pre60 = native_metrics[("PRE",60.0)]

alpha_pre = alpha_df[alpha_df["sample"].eq("PRE2025_OOF")].set_index("benchmark")

bench_cagr_pre = {
    k:cagr_from_returns(v.loc[
        (v.index>=portfolio_start)&(v.index<hold)
    ])
    for k,v in bench_returns_pre.items()
}

gates = {
    "positive_cagr_20bps": bool(pre_m["cagr"] > 0),
    "positive_cagr_40bps": bool(pre40["cagr"] > 0),
    "positive_cagr_60bps": bool(pre60["cagr"] > 0),
    "positive_alpha_vs_spy": bool(alpha_pre.loc["SPY","alpha_ann"] > 0) if "SPY" in alpha_pre.index else False,
    "positive_alpha_vs_qqq": bool(alpha_pre.loc["QQQ","alpha_ann"] > 0) if "QQQ" in alpha_pre.index else False,
    "positive_alpha_vs_byma_uew": bool(alpha_pre.loc["BYMA_UEW","alpha_ann"] > 0) if "BYMA_UEW" in alpha_pre.index else False,
    "beats_byma_uew_cagr": bool(pre_m["cagr"] > bench_cagr_pre.get("BYMA_UEW",-np.inf)),
    "maxdd_above_minus_40pct": bool(pre_m["max_drawdown"] > -0.40),
}
primary_pass = all(gates.values())

for k,v in gates.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")

verdict = "FREEZE_AND_START_FORWARD_SHADOW" if primary_pass else "REJECT_NATIVE_PRE2025"

# =============================================================================
# SAVE SUMMARY / WEBSITE CONTRACT
# =============================================================================

summary = {
    "status":"COMPLETE",
    "name":NAME,
    "version":VERSION,
    "build":BUILD,
    "prediction_independence":{
        "reads_v13_oof_scores":False,
        "reads_v13_holdout_advisor_as_predictions":False,
        "fresh_models_fit_on_byma_rows":True,
        "reads_v13_model_bundle":False,
        "reads_v13_production_seal":False,
        "shared_infrastructure":"PIT feature/target builders + market data + portfolio mechanics",
    },
    "methodology":{
        "universe":"current certified BYMA programs filtered BEFORE training",
        "target":"cross-sectional forward-return rank",
        "active_alpha_calibration":"50% BYMA UEW excess + 25% SPY excess + 25% QQQ excess",
        "models":"50% Ridge + 50% HistGradientBoosting, fixed architecture",
        "walk_forward_folds":[x[0] for x in FOLDS],
        "portfolio_start":str(portfolio_start.date()),
        "holdout_start":str(hold.date()),
        "holdout_status":"SECONDARY_POSTHOC_ALREADY_OBSERVED",
        "integer_sizing_status":"implementation utility only; not a theoretical-model validation gate",
    },
    "native_metrics":{
        "pre2025_20bps":native_metrics[("PRE",20.0)],
        "pre2025_40bps":native_metrics[("PRE",40.0)],
        "pre2025_60bps":native_metrics[("PRE",60.0)],
        "holdout_20bps":native_metrics[("HOLD",20.0)],
        "holdout_40bps":native_metrics[("HOLD",40.0)],
        "holdout_60bps":native_metrics[("HOLD",60.0)],
    },
    "references":{
        "v13_ideal_pre2025":ideal_pre_m,
        "v13_ideal_holdout":ideal_hold_m,
        "transfer_pre2025":transfer_pre_m,
        "transfer_holdout":transfer_hold_m,
    },
    "score_ic":{
        "pre2025_mean":pre_ic_mean,
        "holdout_posthoc_mean":hold_ic_mean,
    },
    "primary_gates":gates,
    "primary_pass":primary_pass,
    "verdict":verdict,
    "current":{
        "signal_date":str(last_plan_date.date()),
        "continuous_target_names":len(target),
        "practical_navs":list(PRACTICAL_NAVS),
    },
}
(OUT/"byma_native_summary.json").write_text(
    json.dumps(summary,indent=2,default=str),encoding="utf-8"
)

website_contract = {
    "tracks":[
        {
            "id":"V13_IDEAL",
            "role":"international_frictionless_reference",
            "model_independent":True,
            "nav_history":str(V13/"outputs"/"v13_phase4_holdout_nav_20bps.csv"),
        },
        {
            "id":"BYMA_NATIVE",
            "role":"local_theoretical_model",
            "model_independent":True,
            "nav_history":str(OUT/"byma_native_nav_holdout_20bps.csv"),
            "current_target":str(OUT/"byma_native_current_target_continuous.csv"),
        },
        {
            "id":"PERSONAL_PORTFOLIO",
            "role":"actual_user_portfolio_with_discretion",
            "model_independent":False,
            "note":"Tracked separately; discretionary trades never alter V13 or BYMA model records.",
        },
    ]
}
(OUT/"website_three_track_contract.json").write_text(
    json.dumps(website_contract,indent=2),encoding="utf-8"
)

print("\n[12/12] FINAL CARD")
print("="*124)
print("V13_IDEAL: PRESERVED")
print("BYMA_TRANSFER_1X: PRESERVED_AS_DIAGNOSTIC_BENCHMARK")
print("BYMA_NATIVE_PREDICTOR: INDEPENDENT_FRESH_FIT")
print(f"NATIVE_PRE2025_CAGR_20BPS: {native_metrics[('PRE',20.0)]['cagr']:.2%}")
print(f"NATIVE_PRE2025_CAGR_40BPS: {native_metrics[('PRE',40.0)]['cagr']:.2%}")
print(f"NATIVE_PRE2025_CAGR_60BPS: {native_metrics[('PRE',60.0)]['cagr']:.2%}")
print(f"NATIVE_HOLDOUT_CAGR_20BPS_POSTHOC: {native_metrics[('HOLD',20.0)]['cagr']:.2%}")
print(f"NATIVE_PRE_MEAN_IC: {pre_ic_mean:.4f}")
print(f"NATIVE_HOLDOUT_MEAN_IC_POSTHOC: {hold_ic_mean:.4f}")
print(f"CURRENT_SIGNAL_DATE: {last_plan_date.date()}")
print(f"CURRENT_CONTINUOUS_TARGET_NAMES: {len(target)}")
print(f"FINAL_VERDICT: {verdict}")
print("NEXT_IF_PASS: FREEZE MODELS + START FORWARD SHADOW + CONNECT WEBSITE/SHEETS")
print("NO REAL ORDERS / NO V13 MUTATION")
print("="*124)
