from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

PHASE5_BUILD = "V1_FIX2_GATE_SEMANTICS_2026-09-12"
FORBIDDEN_FEATURE_PREFIXES = (
    "fwd_", "winner_", "target_", "mfe_", "mae_", "cs_rank_pct_",
)


@dataclass(frozen=True)
class FoldSpec:
    name: str
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass(frozen=True)
class Phase5Config:
    name: str
    objective: str
    feature_library_path: str
    diagnostics_path: str
    phase4_summary_path: str
    targets_path: str
    output_oof_scores_path: str
    output_validation_scores_path: str
    research_horizons: tuple[int, ...]
    architectures: tuple[str, ...]
    partitions: dict[str, pd.Timestamp]
    cv_folds: tuple[FoldSpec, ...]
    feature_selection: dict[str, object]
    models: dict[str, object]
    evaluation: dict[str, object]


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")


def _norm_ticker(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.replace(".", "-", regex=False).str.strip()


def _require_columns(df: pd.DataFrame, cols: Iterable[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")


def load_config(root: Path) -> Phase5Config:
    path = root / "config" / "phase5.toml"
    with path.open("rb") as f:
        raw = tomllib.load(f)["phase5"]
    p = {k: pd.Timestamp(v).normalize() for k, v in raw["partitions"].items()}
    if not (p["development_start"] < p["validation_start"] < p["final_oos_start"]):
        raise ValueError("Invalid Phase 5 partition ordering")
    folds = tuple(
        FoldSpec(str(x["name"]), pd.Timestamp(x["test_start"]).normalize(), pd.Timestamp(x["test_end"]).normalize())
        for x in raw["cv_folds"]
    )
    for f in folds:
        if not (p["development_start"] < f.test_start < f.test_end <= p["validation_start"]):
            raise ValueError(f"Invalid CV fold {f.name}")
    return Phase5Config(
        name=str(raw["name"]),
        objective=str(raw["objective"]),
        feature_library_path=str(raw["feature_library_path"]),
        diagnostics_path=str(raw["phase4_diagnostics_path"]),
        phase4_summary_path=str(raw["phase4_summary_path"]),
        targets_path=str(raw["targets_path"]),
        output_oof_scores_path=str(raw["output_oof_scores_path"]),
        output_validation_scores_path=str(raw["output_validation_scores_path"]),
        research_horizons=tuple(int(x) for x in raw["research_horizons"]),
        architectures=tuple(str(x) for x in raw["architectures"]),
        partitions=p,
        cv_folds=folds,
        feature_selection=dict(raw["feature_selection"]),
        models=dict(raw["models"]),
        evaluation=dict(raw["evaluation"]),
    )


def validate_phase4_summary(summary: dict) -> None:
    if summary.get("status") != "PASS":
        raise RuntimeError("Phase 4 must PASS before Phase 5")
    pe = summary.get("predictive_evidence") or {}
    if pe.get("readiness") != "READY_FOR_MODEL_RESEARCH":
        raise RuntimeError("Phase 4 predictive evidence is not READY_FOR_MODEL_RESEARCH")
    fw = summary.get("final_oos_firewall") or {}
    if fw.get("used_for_predictive_research") is not False:
        raise RuntimeError("Phase 4 final OOS firewall is not intact")
    if str(fw.get("final_oos_start")) != "2025-01-01":
        raise RuntimeError("Phase 5 expects final OOS start 2025-01-01")


def development_only_feature_pool(diagnostics: pd.DataFrame, horizon: int, cfg: Phase5Config) -> pd.DataFrame:
    """Select features using DEVELOPMENT columns only. Validation columns are ignored by contract."""
    req = [
        "feature", "family", "horizon_sessions", "development_coverage",
        "development_fdr_q", "development_mean_spearman_ic",
    ]
    _require_columns(diagnostics, req, "Phase 4 predictive diagnostics")
    x = diagnostics[diagnostics["horizon_sessions"].astype(int).eq(int(horizon))].copy()
    x["development_coverage"] = pd.to_numeric(x["development_coverage"], errors="coerce")
    x["development_fdr_q"] = pd.to_numeric(x["development_fdr_q"], errors="coerce")
    x["development_mean_spearman_ic"] = pd.to_numeric(x["development_mean_spearman_ic"], errors="coerce")
    fs = cfg.feature_selection
    eligible = (
        (x["development_coverage"] >= float(fs["minimum_development_coverage"]))
        & (x["development_fdr_q"] <= float(fs["maximum_development_fdr_q"]))
        & (x["development_mean_spearman_ic"].abs() >= float(fs["minimum_abs_development_ic"]))
    )
    x = x.loc[eligible, req].copy()
    x["development_direction"] = np.where(x["development_mean_spearman_ic"] >= 0, 1, -1)
    x["abs_development_ic"] = x["development_mean_spearman_ic"].abs()
    x = x.sort_values(
        ["development_fdr_q", "abs_development_ic", "development_coverage", "feature"],
        ascending=[True, False, False, True],
    )
    x = x.head(int(fs["max_features_per_horizon"])).reset_index(drop=True)
    x["development_priority_rank"] = np.arange(1, len(x) + 1)
    return x


def load_feature_library(root: Path, cfg: Phase5Config, feature_union: list[str]) -> pd.DataFrame:
    path = root / cfg.feature_library_path
    if not path.exists():
        raise FileNotFoundError(str(path))
    cols = ["date", "ticker", "feature_allowed"] + feature_union
    df = pd.read_parquet(path, columns=cols)
    df["date"] = _as_date(df["date"])
    df["ticker"] = _norm_ticker(df["ticker"])
    if not df["feature_allowed"].fillna(False).astype(bool).all():
        raise RuntimeError("Phase 4 feature library contains feature-forbidden rows")
    oos0 = cfg.partitions["final_oos_start"]
    return df[df["date"] < oos0].sort_values(["date", "ticker"]).reset_index(drop=True)


def load_targets(root: Path, cfg: Phase5Config) -> pd.DataFrame:
    path = root / cfg.targets_path
    if not path.exists():
        raise FileNotFoundError(str(path))
    cols = ["signal_date", "ticker"]
    for h in cfg.research_horizons:
        cols.extend([
            f"target_end_date_{h}d", f"target_resolved_{h}d", f"fwd_return_{h}d",
            f"cs_rank_pct_{h}d", f"winner_top_decile_{h}d",
        ])
    t = pd.read_parquet(path, columns=cols)
    t["signal_date"] = _as_date(t["signal_date"])
    t["ticker"] = _norm_ticker(t["ticker"])
    for h in cfg.research_horizons:
        t[f"target_end_date_{h}d"] = _as_date(t[f"target_end_date_{h}d"])
        t[f"target_resolved_{h}d"] = t[f"target_resolved_{h}d"].fillna(False).astype(bool)
        t[f"fwd_return_{h}d"] = pd.to_numeric(t[f"fwd_return_{h}d"], errors="coerce")
        t[f"cs_rank_pct_{h}d"] = pd.to_numeric(t[f"cs_rank_pct_{h}d"], errors="coerce")
        t[f"winner_top_decile_{h}d"] = t[f"winner_top_decile_{h}d"].astype("boolean")
    return t[t["signal_date"] < cfg.partitions["final_oos_start"]].copy()


def cross_sectional_rank_features(features: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    out = features[["date", "ticker"]].copy()
    for c in feature_cols:
        v = pd.to_numeric(features[c], errors="coerce")
        out[c] = v.groupby(features["date"], sort=False).rank(method="average", pct=True).astype("float32")
    return out


def prune_correlated_features(
    ranked: pd.DataFrame,
    pool: pd.DataFrame,
    cfg: Phase5Config,
    development_mask: pd.Series,
) -> pd.DataFrame:
    if pool.empty:
        pool = pool.copy()
        pool["kept_after_correlation_prune"] = False
        pool["correlated_with"] = ""
        return pool
    cols = pool["feature"].tolist()
    sample = ranked.loc[development_mask, cols]
    max_rows = int(cfg.feature_selection["correlation_sample_rows"])
    if len(sample) > max_rows:
        sample = sample.sample(n=max_rows, random_state=int(cfg.models["random_seed"]))
    min_periods = min(200, max(3, len(sample) // 2))
    corr = sample.corr(method="pearson", min_periods=min_periods)
    threshold = float(cfg.feature_selection["correlation_prune_threshold"])
    kept: list[str] = []
    related: dict[str, str] = {}
    for c in cols:
        blocker = ""
        for k in kept:
            z = corr.at[c, k] if c in corr.index and k in corr.columns else np.nan
            if np.isfinite(z) and abs(float(z)) >= threshold:
                blocker = k
                break
        if blocker:
            related[c] = blocker
        else:
            kept.append(c)
    out = pool.copy()
    out["kept_after_correlation_prune"] = out["feature"].isin(kept)
    out["correlated_with"] = out["feature"].map(related).fillna("")
    return out


def _sample_train(df: pd.DataFrame, max_rows: int, seed: int) -> pd.DataFrame:
    if len(df) <= max_rows:
        return df
    return df.sample(n=max_rows, random_state=seed).sort_index()


def _composite_score(df: pd.DataFrame, pool: pd.DataFrame) -> np.ndarray:
    cols = pool.loc[pool["kept_after_correlation_prune"], "feature"].tolist()
    if not cols:
        return np.full(len(df), np.nan)
    meta = pool.set_index("feature")
    w = np.array([
        float(meta.at[c, "development_direction"]) * max(abs(float(meta.at[c, "development_mean_spearman_ic"])), 1e-6)
        for c in cols
    ], dtype=float)
    x = df[cols].to_numpy(dtype=float)
    centered = x - 0.5
    ok = np.isfinite(centered)
    num = np.nansum(centered * w[None, :], axis=1)
    den = np.sum(ok * np.abs(w)[None, :], axis=1)
    return np.where(den > 0, num / den, np.nan)


def _ridge_model(cfg: Phase5Config) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value=0.5, add_indicator=True)),
        ("model", Ridge(alpha=float(cfg.models["ridge_alpha"]))),
    ])


def _hgb_rank_model(cfg: Phase5Config) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        learning_rate=float(cfg.models["hgb_learning_rate"]),
        max_iter=int(cfg.models["hgb_max_iter"]),
        max_leaf_nodes=int(cfg.models["hgb_max_leaf_nodes"]),
        min_samples_leaf=int(cfg.models["hgb_min_samples_leaf"]),
        l2_regularization=float(cfg.models["hgb_l2_regularization"]),
        random_state=int(cfg.models["random_seed"]),
    )


def _hgb_winner_model(cfg: Phase5Config) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=float(cfg.models["hgb_learning_rate"]),
        max_iter=int(cfg.models["hgb_max_iter"]),
        max_leaf_nodes=int(cfg.models["hgb_max_leaf_nodes"]),
        min_samples_leaf=int(cfg.models["hgb_min_samples_leaf"]),
        l2_regularization=float(cfg.models["hgb_l2_regularization"]),
        class_weight="balanced",
        random_state=int(cfg.models["random_seed"]),
    )


def _score_rank_by_date(keys: pd.DataFrame, score: np.ndarray) -> np.ndarray:
    tmp = pd.DataFrame({"date": keys["signal_date"].to_numpy(), "score": score})
    return tmp["score"].groupby(tmp["date"], sort=False).rank(method="average", pct=True).to_numpy(dtype=float)


def fit_predict_architectures(
    train: pd.DataFrame,
    test: pd.DataFrame,
    feature_cols: list[str],
    pool: pd.DataFrame,
    horizon: int,
    cfg: Phase5Config,
) -> dict[str, np.ndarray]:
    y_rank = f"cs_rank_pct_{horizon}d"
    y_win = f"winner_top_decile_{horizon}d"
    max_rows = int(cfg.models["max_train_rows"])
    seed = int(cfg.models["random_seed"]) + int(horizon)
    train_fit = _sample_train(train, max_rows, seed)
    Xtr = train_fit[feature_cols]
    Xte = test[feature_cols]
    out: dict[str, np.ndarray] = {}

    out["DEV_IC_COMPOSITE"] = _composite_score(test, pool)

    ridge = _ridge_model(cfg)
    ridge.fit(Xtr, pd.to_numeric(train_fit[y_rank], errors="coerce"))
    out["RIDGE_RANK"] = ridge.predict(Xte)

    hgb = _hgb_rank_model(cfg)
    hgb.fit(Xtr, pd.to_numeric(train_fit[y_rank], errors="coerce"))
    out["HGB_RANK"] = hgb.predict(Xte)

    win_train = train_fit[train_fit[y_win].notna()].copy()
    if win_train.empty or win_train[y_win].astype(int).nunique() < 2:
        out["HGB_WINNER"] = np.full(len(test), np.nan)
    else:
        clf = _hgb_winner_model(cfg)
        clf.fit(win_train[feature_cols], win_train[y_win].astype(int))
        out["HGB_WINNER"] = clf.predict_proba(Xte)[:, 1]

    r1 = _score_rank_by_date(test[["signal_date"]], out["RIDGE_RANK"])
    r2 = _score_rank_by_date(test[["signal_date"]], out["HGB_RANK"])
    out["BLEND_RIDGE_HGB"] = np.nanmean(np.column_stack([r1, r2]), axis=1)
    return out


def _daily_spearman(df: pd.DataFrame, score_col: str, target_col: str, min_cs: int) -> pd.Series:
    vals: list[tuple[pd.Timestamp, float]] = []
    for d, g in df.groupby("signal_date", sort=False):
        x = pd.to_numeric(g[score_col], errors="coerce")
        y = pd.to_numeric(g[target_col], errors="coerce")
        ok = x.notna() & y.notna()
        if int(ok.sum()) < min_cs:
            continue
        xr = x[ok].rank(method="average")
        yr = y[ok].rank(method="average")
        c = xr.corr(yr)
        if pd.notna(c):
            vals.append((pd.Timestamp(d), float(c)))
    return pd.Series({d: v for d, v in vals}, dtype=float).sort_index()


def evaluate_predictions(test: pd.DataFrame, score: np.ndarray, horizon: int, cfg: Phase5Config) -> dict[str, float]:
    x = test[["signal_date", "ticker", f"fwd_return_{horizon}d", f"cs_rank_pct_{horizon}d", f"winner_top_decile_{horizon}d"]].copy()
    x["score"] = score
    x = x[np.isfinite(pd.to_numeric(x["score"], errors="coerce"))].copy()
    if x.empty:
        return {"rows_scored": 0, "mean_daily_spearman_ic": math.nan}
    min_cs = int(cfg.evaluation["minimum_cross_section_size"])
    daily_ic = _daily_spearman(x, "score", f"cs_rank_pct_{horizon}d", min_cs)
    q = float(cfg.evaluation["top_quantile"])
    x["score_rank_pct"] = x["score"].groupby(x["signal_date"], sort=False).rank(method="average", pct=True)
    top = x[x["score_rank_pct"] > 1.0 - q]
    bot = x[x["score_rank_pct"] <= q]
    ret = f"fwd_return_{horizon}d"
    w = f"winner_top_decile_{horizon}d"
    top_mean = float(pd.to_numeric(top[ret], errors="coerce").mean()) if len(top) else math.nan
    bot_mean = float(pd.to_numeric(bot[ret], errors="coerce").mean()) if len(bot) else math.nan
    universe_mean = float(pd.to_numeric(x[ret], errors="coerce").mean()) if len(x) else math.nan
    cost = float(cfg.evaluation["round_trip_cost_bps"]) / 10000.0
    top_net = top_mean - cost if np.isfinite(top_mean) else math.nan
    top_vs_universe_net = top_net - universe_mean if np.isfinite(top_net) and np.isfinite(universe_mean) else math.nan
    spread = top_mean - bot_mean if np.isfinite(top_mean) and np.isfinite(bot_mean) else math.nan
    all_win = pd.to_numeric(x[w].astype("Float64"), errors="coerce")
    top_win = pd.to_numeric(top[w].astype("Float64"), errors="coerce")
    base_rate = float(all_win.mean()) if len(all_win) else math.nan
    top_rate = float(top_win.mean()) if len(top_win) else math.nan
    lift = top_rate / base_rate if np.isfinite(top_rate) and np.isfinite(base_rate) and base_rate > 0 else math.nan
    monthly_positive = math.nan
    if len(daily_ic):
        m = daily_ic.groupby(daily_ic.index.to_period("M")).mean()
        monthly_positive = float((m > 0).mean()) if len(m) else math.nan
    # Diagnostic score turnover: not a trading policy, only ranking stability.
    top_sets = []
    for d, g in x.groupby("signal_date", sort=True):
        s = set(g.loc[g["score_rank_pct"] > 1.0 - q, "ticker"].astype(str))
        if s:
            top_sets.append(s)
    turns = []
    for a, b in zip(top_sets[:-1], top_sets[1:]):
        denom = max(1, min(len(a), len(b)))
        turns.append(1.0 - len(a & b) / denom)
    return {
        "rows_scored": int(len(x)),
        "score_dates": int(x["signal_date"].nunique()),
        "mean_daily_spearman_ic": float(daily_ic.mean()) if len(daily_ic) else math.nan,
        "median_daily_spearman_ic": float(daily_ic.median()) if len(daily_ic) else math.nan,
        "positive_month_ic_share": monthly_positive,
        "top_decile_return_mean": top_mean,
        "top_decile_net_return_proxy": top_net,
        "universe_return_mean": universe_mean,
        "top_vs_universe_net_spread": top_vs_universe_net,
        "top_bottom_return_spread": spread,
        "winner_top_decile_base_rate": base_rate,
        "winner_top_decile_precision": top_rate,
        "winner_top_decile_lift": lift,
        "daily_top_set_turnover_proxy": float(np.mean(turns)) if turns else math.nan,
    }


def _prepare_horizon_frame(
    ranked: pd.DataFrame,
    targets: pd.DataFrame,
    feature_cols: list[str],
    horizon: int,
) -> pd.DataFrame:
    tcols = [
        "signal_date", "ticker", f"target_end_date_{horizon}d", f"target_resolved_{horizon}d",
        f"fwd_return_{horizon}d", f"cs_rank_pct_{horizon}d", f"winner_top_decile_{horizon}d",
    ]
    x = ranked.rename(columns={"date": "signal_date"}).merge(targets[tcols], on=["signal_date", "ticker"], how="inner")
    y = f"cs_rank_pct_{horizon}d"
    resolved = f"target_resolved_{horizon}d"
    x = x[x[resolved].fillna(False).astype(bool) & x[y].notna()].copy()
    return x


def _mask_train_test(frame: pd.DataFrame, cfg: Phase5Config, horizon: int, fold: FoldSpec) -> tuple[pd.Series, pd.Series]:
    end = f"target_end_date_{horizon}d"
    dev0 = cfg.partitions["development_start"]
    train = (
        frame["signal_date"].ge(dev0)
        & frame["signal_date"].lt(fold.test_start)
        & frame[end].notna()
        & frame[end].lt(fold.test_start)
    )
    test = (
        frame["signal_date"].ge(fold.test_start)
        & frame["signal_date"].lt(fold.test_end)
        & frame[end].notna()
        & frame[end].lt(fold.test_end)
    )
    return train, test


def _mask_development_validation(frame: pd.DataFrame, cfg: Phase5Config, horizon: int) -> tuple[pd.Series, pd.Series]:
    end = f"target_end_date_{horizon}d"
    dev0 = cfg.partitions["development_start"]
    val0 = cfg.partitions["validation_start"]
    oos0 = cfg.partitions["final_oos_start"]
    train = frame["signal_date"].ge(dev0) & frame["signal_date"].lt(val0) & frame[end].notna() & frame[end].lt(val0)
    val = frame["signal_date"].ge(val0) & frame["signal_date"].lt(oos0) & frame[end].notna() & frame[end].lt(oos0)
    return train, val


def _validation_selection_table(val: pd.DataFrame, cv_agg: pd.DataFrame, cfg: Phase5Config) -> pd.DataFrame:
    if val.empty:
        return val
    x = val.merge(cv_agg[["horizon_sessions", "architecture", "cv_mean_ic"]], on=["horizon_sessions", "architecture"], how="left")
    e = cfg.evaluation
    x["qualified"] = (
        (x["cv_mean_ic"] > float(e["minimum_cv_ic"]))
        & (x["mean_daily_spearman_ic"] > float(e["minimum_validation_ic"]))
        & (x["winner_top_decile_lift"] > float(e["minimum_validation_winner_lift"]))
        & (x["top_vs_universe_net_spread"] > float(e["minimum_validation_top_vs_universe_net_spread"]))
    )
    x["selection_score"] = np.nan
    for h, idx in x.groupby("horizon_sessions").groups.items():
        ix = list(idx)
        sub = x.loc[ix]
        def pct(c: str) -> pd.Series:
            return pd.to_numeric(sub[c], errors="coerce").rank(pct=True, method="average")
        score = (
            0.40 * pct("top_vs_universe_net_spread")
            + 0.30 * pct("mean_daily_spearman_ic")
            + 0.20 * pct("winner_top_decile_lift")
            + 0.10 * pct("positive_month_ic_share")
        )
        x.loc[ix, "selection_score"] = score.to_numpy()
    x.loc[~x["qualified"], "selection_score"] = x.loc[~x["qualified"], "selection_score"] - 10.0
    x["horizon_rank"] = x.groupby("horizon_sessions")["selection_score"].rank(ascending=False, method="min")
    return x.sort_values(["horizon_sessions", "horizon_rank", "architecture"]).reset_index(drop=True)


def build_phase5(root: Path) -> dict:
    cfg = load_config(root)
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    with (root / cfg.phase4_summary_path).open("r", encoding="utf-8") as f:
        phase4_summary = json.load(f)
    validate_phase4_summary(phase4_summary)

    diagnostics = pd.read_csv(root / cfg.diagnostics_path)
    pools_raw: dict[int, pd.DataFrame] = {}
    feature_union: set[str] = set()
    for h in cfg.research_horizons:
        p = development_only_feature_pool(diagnostics, h, cfg)
        pools_raw[h] = p
        feature_union.update(p["feature"].astype(str).tolist())
    feature_union_list = sorted(feature_union)
    forbidden = [c for c in feature_union_list if c.startswith(FORBIDDEN_FEATURE_PREFIXES) or "adj_close" in c or "target_total_return_price" in c]
    if forbidden:
        raise RuntimeError(f"Forbidden features entered Phase 5 pool: {forbidden[:10]}")

    features = load_feature_library(root, cfg, feature_union_list)
    ranked = cross_sectional_rank_features(features, feature_union_list)
    targets = load_targets(root, cfg)

    dev_mask_ranked = ranked["date"].ge(cfg.partitions["development_start"]) & ranked["date"].lt(cfg.partitions["validation_start"])
    pools: dict[int, pd.DataFrame] = {}
    pool_rows: list[pd.DataFrame] = []
    for h in cfg.research_horizons:
        p = prune_correlated_features(ranked, pools_raw[h], cfg, dev_mask_ranked)
        # development_only_feature_pool already carries horizon_sessions.
        # Overwrite defensively instead of inserting a duplicate column.
        p = p.copy()
        p["horizon_sessions"] = int(h)
        pools[h] = p
        pool_rows.append(p)
    pool_manifest = pd.concat(pool_rows, ignore_index=True) if pool_rows else pd.DataFrame()

    cv_rows: list[dict] = []
    oof_score_frames: list[pd.DataFrame] = []
    validation_rows: list[dict] = []
    validation_prediction_store: dict[tuple[int, str], pd.DataFrame] = {}
    purge_violations = 0

    for h in cfg.research_horizons:
        pool = pools[h]
        feature_cols = pool.loc[pool["kept_after_correlation_prune"], "feature"].astype(str).tolist()
        if not feature_cols:
            continue
        frame = _prepare_horizon_frame(ranked[["date", "ticker"] + feature_cols], targets, feature_cols, h)

        for fold in cfg.cv_folds:
            tr_mask, te_mask = _mask_train_test(frame, cfg, h, fold)
            train = frame.loc[tr_mask].copy()
            test = frame.loc[te_mask].copy()
            end_col = f"target_end_date_{h}d"
            purge_violations += int((train[end_col] >= fold.test_start).sum())
            purge_violations += int((test[end_col] >= fold.test_end).sum())
            if len(train) < 1000 or len(test) < 500:
                continue
            preds = fit_predict_architectures(train, test, feature_cols, pool, h, cfg)
            for arch in cfg.architectures:
                score = preds.get(arch)
                if score is None:
                    continue
                met = evaluate_predictions(test, score, h, cfg)
                cv_rows.append({
                    "horizon_sessions": h, "fold": fold.name, "architecture": arch,
                    "train_rows": int(len(train)), "test_rows": int(len(test)), **met,
                })
                sf = test[["signal_date", "ticker"]].copy()
                sf["horizon_sessions"] = h
                sf["architecture"] = arch
                sf["fold"] = fold.name
                sf["score"] = score
                sf["score_rank_pct"] = _score_rank_by_date(sf[["signal_date"]], score)
                oof_score_frames.append(sf)

        tr_mask, va_mask = _mask_development_validation(frame, cfg, h)
        train = frame.loc[tr_mask].copy()
        val = frame.loc[va_mask].copy()
        end_col = f"target_end_date_{h}d"
        purge_violations += int((train[end_col] >= cfg.partitions["validation_start"]).sum())
        purge_violations += int((val[end_col] >= cfg.partitions["final_oos_start"]).sum())
        if len(train) < 1000 or len(val) < 500:
            continue
        preds = fit_predict_architectures(train, val, feature_cols, pool, h, cfg)
        for arch in cfg.architectures:
            score = preds.get(arch)
            if score is None:
                continue
            met = evaluate_predictions(val, score, h, cfg)
            validation_rows.append({
                "horizon_sessions": h, "architecture": arch,
                "train_rows": int(len(train)), "validation_rows": int(len(val)), **met,
            })
            sf = val[["signal_date", "ticker"]].copy()
            sf["horizon_sessions"] = h
            sf["architecture"] = arch
            sf["score"] = score
            sf["score_rank_pct"] = _score_rank_by_date(sf[["signal_date"]], score)
            validation_prediction_store[(h, arch)] = sf

    cv = pd.DataFrame(cv_rows)
    validation = pd.DataFrame(validation_rows)
    if cv.empty or validation.empty:
        raise RuntimeError("Phase 5 produced no model evaluation results")
    cv_agg = cv.groupby(["horizon_sessions", "architecture"], as_index=False).agg(
        cv_folds=("fold", "nunique"),
        cv_mean_ic=("mean_daily_spearman_ic", "mean"),
        cv_median_ic=("mean_daily_spearman_ic", "median"),
        cv_mean_top_vs_universe_net_spread=("top_vs_universe_net_spread", "mean"),
        cv_mean_winner_lift=("winner_top_decile_lift", "mean"),
        cv_mean_positive_month_ic_share=("positive_month_ic_share", "mean"),
    )
    leaderboard = _validation_selection_table(validation, cv_agg, cfg)

    champions: list[dict] = []
    champ_score_frames: list[pd.DataFrame] = []
    for h in cfg.research_horizons:
        sub = leaderboard[leaderboard["horizon_sessions"].eq(h)].sort_values("horizon_rank")
        if sub.empty:
            continue
        best = sub.iloc[0]
        champions.append({
            "horizon_sessions": int(h),
            "architecture": str(best["architecture"]),
            "qualified": bool(best["qualified"]),
            "selection_score": float(best["selection_score"]),
            "cv_mean_ic": float(best["cv_mean_ic"]) if pd.notna(best["cv_mean_ic"]) else math.nan,
            "validation_ic": float(best["mean_daily_spearman_ic"]) if pd.notna(best["mean_daily_spearman_ic"]) else math.nan,
            "validation_top_vs_universe_net_spread": float(best["top_vs_universe_net_spread"]) if pd.notna(best["top_vs_universe_net_spread"]) else math.nan,
            "validation_winner_lift": float(best["winner_top_decile_lift"]) if pd.notna(best["winner_top_decile_lift"]) else math.nan,
        })
        sf = validation_prediction_store.get((h, str(best["architecture"])))
        if sf is not None:
            champ_score_frames.append(sf)

    ready_horizons = int(sum(bool(x["qualified"]) for x in champions))
    model_readiness = "READY_FOR_PORTFOLIO_POLICY_RESEARCH" if ready_horizons >= int(cfg.evaluation["minimum_ready_horizons"]) else "NEEDS_MODEL_RESEARCH"

    oof = pd.concat(oof_score_frames, ignore_index=True) if oof_score_frames else pd.DataFrame()
    val_scores = pd.concat(champ_score_frames, ignore_index=True) if champ_score_frames else pd.DataFrame()

    gate_rows: list[dict] = []
    def add(test: str, ok: bool, value: object, rule: str, blocking: bool = True) -> None:
        gate_rows.append({"test": test, "status": "PASS" if ok else "FAIL", "blocking": blocking, "value": value, "rule": rule})
    phase4_status = str(phase4_summary.get("status") or "")
    phase4_readiness = str((phase4_summary.get("predictive_evidence") or {}).get("readiness") or "")
    add("PHASE4_INPUT_PASS", phase4_status == "PASS", phase4_status, "Phase 4 must be PASS")
    add("PHASE4_READINESS", phase4_readiness == "READY_FOR_MODEL_RESEARCH", phase4_readiness, "Phase 4 must be READY_FOR_MODEL_RESEARCH")
    add("DEVELOPMENT_ONLY_FEATURE_SELECTION", True, 0, "feature pool uses only development coverage, IC and FDR; validation fields are ignored")
    add("FORBIDDEN_FEATURES", len(forbidden) == 0, len(forbidden), "0 target/adjusted-level/future columns in model feature pool")
    min_feat = int(cfg.feature_selection["minimum_features_per_horizon"])
    feature_shortfalls = int(sum(int(p["kept_after_correlation_prune"].sum()) < min_feat for p in pools.values()))
    gate_rows.append({
        "test": "FEATURE_BREADTH_DIAGNOSTIC",
        "status": "PASS" if feature_shortfalls == 0 else "WARN",
        "blocking": False,
        "value": feature_shortfalls,
        "rule": f"diagnostic only: count horizons with fewer than {min_feat} post-prune features; model qualification remains the economic gate",
    })
    add("PURGED_WALK_FORWARD", purge_violations == 0, purge_violations, "0 train/test or train/validation target_end_date boundary violations")
    max_score_date = pd.to_datetime(val_scores["signal_date"], errors="coerce").max() if len(val_scores) else pd.NaT
    add("FINAL_OOS_SCORE_FIREWALL", pd.isna(max_score_date) or max_score_date < cfg.partitions["final_oos_start"], str(max_score_date.date()) if pd.notna(max_score_date) else "", "all model-selection scores must be before 2025-01-01")
    add("FINAL_OOS_USED_FOR_SELECTION", True, False, "final OOS labels/features are not loaded into model selection")
    add("READY_HORIZONS", ready_horizons >= int(cfg.evaluation["minimum_ready_horizons"]), ready_horizons, f">= {int(cfg.evaluation['minimum_ready_horizons'])} horizons with qualified champion", blocking=True)
    add("MODEL_READINESS", model_readiness == "READY_FOR_PORTFOLIO_POLICY_RESEARCH", model_readiness, "Phase 5 must produce sufficient qualified champions before Phase 6", blocking=True)
    gate = pd.DataFrame(gate_rows)
    blocking_fail = gate["blocking"].astype(bool) & gate["status"].eq("FAIL")
    status = "PASS" if not blocking_fail.any() else "FAIL"

    pool_manifest.to_csv(outputs / "phase5_feature_pool.csv", index=False)
    cv.to_csv(outputs / "phase5_cv_results.csv", index=False)
    cv_agg.to_csv(outputs / "phase5_cv_aggregate.csv", index=False)
    validation.to_csv(outputs / "phase5_validation_results.csv", index=False)
    leaderboard.to_csv(outputs / "phase5_leaderboard.csv", index=False)
    gate.to_csv(outputs / "phase5_gate.csv", index=False)
    if len(oof):
        oof.to_parquet(root / cfg.output_oof_scores_path, index=False)
    if len(val_scores):
        val_scores.to_parquet(root / cfg.output_validation_scores_path, index=False)

    spec = {
        "build": PHASE5_BUILD,
        "target": "cross-sectional future-return rank, plus direct top-decile winner probability architecture",
        "feature_transform": "same-date cross-sectional percentile rank; no future data; missing values preserved except ridge median-rank imputation",
        "feature_selection_contract": "DEVELOPMENT ONLY: coverage/FDR/IC; Phase 4 validation labels are not used to define the Phase 5 pool",
        "research_horizons": list(cfg.research_horizons),
        "architectures": list(cfg.architectures),
        "champions": champions,
        "partitions": {k: str(v.date()) for k, v in cfg.partitions.items()},
        "cv_folds": [{"name": f.name, "test_start": str(f.test_start.date()), "test_end": str(f.test_end.date())} for f in cfg.cv_folds],
        "round_trip_cost_bps_proxy": float(cfg.evaluation["round_trip_cost_bps"]),
        "warning": "Phase 5 chooses predictive architecture only. It does not choose rebalance cadence, event thresholds, portfolio weights, execution rules or final OOS performance.",
    }
    (outputs / "phase5_model_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")

    summary = {
        "status": status,
        "phase": 5,
        "build": PHASE5_BUILD,
        "name": cfg.name,
        "objective": cfg.objective,
        "phase4_input": {"status": phase4_summary.get("status"), "readiness": (phase4_summary.get("predictive_evidence") or {}).get("readiness")},
        "feature_selection": {
            "validation_fields_used": False,
            "horizons": {str(h): {
                "development_candidates": int(len(pools[h])),
                "post_correlation_prune": int(pools[h]["kept_after_correlation_prune"].sum()),
            } for h in cfg.research_horizons},
        },
        "walk_forward": {
            "folds": [f.name for f in cfg.cv_folds],
            "purge_violations": purge_violations,
        },
        "champions": champions,
        "ready_horizons": ready_horizons,
        "model_readiness": model_readiness,
        "final_oos_firewall": {
            "final_oos_start": str(cfg.partitions["final_oos_start"].date()),
            "used_for_model_selection": False,
        },
        "next_gate": "If model_readiness is READY_FOR_PORTFOLIO_POLICY_RESEARCH, Phase 6 may compare horizon ensembles and Monthly/Weekly/Daily/EventDriven decision policies using only purged OOF + pre-OOS validation scores. Final OOS remains untouched.",
    }
    (outputs / "phase5_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
