from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

BUILD = "V13_P2_NESTED_MULTI_HORIZON_MODELS_2026-09-12"
ARCHITECTURES = (
    "IC_COMPOSITE",
    "RIDGE_RANK",
    "HGB_RANK",
    "HGB_ROBUST_EXCESS",
    "BLEND_RIDGE_HGB",
)

@dataclass(frozen=True)
class Cfg:
    p: dict


def _date(s):
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")


def load_cfg(workspace: Path) -> Cfg:
    with (workspace / "config" / "v13_phase2.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase2"])


def load_phase1(workspace: Path) -> dict:
    p = workspace / "outputs" / "v13_phase1_summary.json"
    if not p.exists():
        raise FileNotFoundError(p)
    x = json.loads(p.read_text(encoding="utf-8"))
    if x.get("status") != "PASS":
        raise RuntimeError("V13 Phase 1 must PASS before Phase 2")
    if x.get("research", {}).get("selection_uses_2025_plus") is not False:
        raise RuntimeError("Phase 1 holdout firewall is not active")
    hs = sorted(int(v) for v in x.get("research", {}).get("horizons", []))
    if hs != [5, 10, 20, 60, 120, 252]:
        raise RuntimeError(f"Unexpected Phase 1 horizons: {hs}")
    return x


def load_inputs(workspace: Path, cfg: Cfg) -> tuple[pd.DataFrame, pd.DataFrame]:
    feat = pd.read_parquet(workspace / cfg.p["feature_library"])
    targ = pd.read_parquet(workspace / cfg.p["research_targets"])
    feat["signal_date"] = _date(feat["signal_date"])
    targ["signal_date"] = _date(targ["signal_date"])
    feat["ticker"] = feat["ticker"].astype(str).str.upper().str.strip()
    targ["ticker"] = targ["ticker"].astype(str).str.upper().str.strip()
    hold = pd.Timestamp(cfg.p["holdout_start"])
    if (feat["signal_date"] >= hold).any() or (targ["signal_date"] >= hold).any():
        raise RuntimeError("HOLDOUT BREACH: Phase 2 input includes 2025+")
    return feat.sort_values(["signal_date", "ticker"]), targ.sort_values(["signal_date", "ticker"])


def usable_features(features: pd.DataFrame, cfg: Cfg) -> list[str]:
    start = pd.Timestamp(cfg.p["research_start"])
    val = pd.Timestamp(cfg.p["validation_start"])
    cols = [c for c in features.columns if c not in {"signal_date", "ticker"}]
    dev = features[(features["signal_date"] >= start) & (features["signal_date"] < val)]
    cov = dev[cols].notna().mean()
    keep = cov[cov >= float(cfg.p["minimum_feature_coverage"])].index.tolist()
    forbidden = {"close", "adj_close", "feature_price", "target_total_return_price"}
    keep = [c for c in keep if c not in forbidden]
    if len(keep) < int(cfg.p["minimum_features"]):
        raise RuntimeError(f"Only {len(keep)} usable features; need >= {cfg.p['minimum_features']}")
    return keep


def cross_sectional_rank_features(features: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = features[["signal_date", "ticker"]].copy()
    # Rank transforms are same-date only and therefore causal.
    ranked = features.groupby("signal_date", observed=True)[cols].rank(method="average", pct=True)
    for c in cols:
        out[c] = pd.to_numeric(ranked[c], errors="coerce").astype("float32")
    return out


def _merge_horizon(ranked: pd.DataFrame, targets: pd.DataFrame, h: int) -> pd.DataFrame:
    need = [
        "signal_date", "ticker", f"target_end_date_{h}d", f"target_resolved_{h}d",
        f"fwd_return_{h}d", f"excess_spy_{h}d", f"excess_qqq_{h}d", f"excess_uew_{h}d",
    ]
    t = targets[need].copy()
    t[f"target_end_date_{h}d"] = _date(t[f"target_end_date_{h}d"])
    t[f"target_resolved_{h}d"] = t[f"target_resolved_{h}d"].fillna(False).astype(bool)
    return ranked.merge(t, on=["signal_date", "ticker"], how="inner", validate="one_to_one")


def purged_split(df: pd.DataFrame, h: int, train_start: str, test_start: str, test_end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_start = pd.Timestamp(train_start)
    test_start = pd.Timestamp(test_start)
    test_end = pd.Timestamp(test_end)
    endcol = f"target_end_date_{h}d"
    rescol = f"target_resolved_{h}d"
    ycol = f"fwd_return_{h}d"
    train_mask = (
        (df["signal_date"] >= train_start)
        & (df["signal_date"] < test_start)
        & df[rescol]
        & df[endcol].notna()
        & (df[endcol] < test_start)
        & df[ycol].notna()
    )
    test_mask = (
        (df["signal_date"] >= test_start)
        & (df["signal_date"] < test_end)
        & df[rescol]
        & df[endcol].notna()
        & (df[endcol] < test_end)
        & df[ycol].notna()
    )
    train = df.loc[train_mask].copy()
    test = df.loc[test_mask].copy()
    if len(train) and not (train[endcol] < test_start).all():
        raise RuntimeError("PURGE BREACH in train")
    if len(test) and not (test[endcol] < test_end).all():
        raise RuntimeError("PURGE BREACH in test")
    return train, test


def _daily_target_rank(df: pd.DataFrame, ycol: str) -> np.ndarray:
    return df.groupby("signal_date", observed=True)[ycol].rank(method="average", pct=True).to_numpy(float)


def _robust_excess_target(df: pd.DataFrame, h: int) -> np.ndarray:
    cols = [f"excess_spy_{h}d", f"excess_qqq_{h}d", f"excess_uew_{h}d"]
    a = df[cols].to_numpy(float)
    # We reward returns that survive all three benchmark comparisons, not a single favorable benchmark.
    y = np.nanmin(a, axis=1)
    finite = np.isfinite(y)
    if finite.any():
        lo, hi = np.nanquantile(y[finite], [0.01, 0.99])
        y = np.clip(y, lo, hi)
    return y


def _feature_ic_weights(train: pd.DataFrame, feature_cols: list[str], h: int) -> np.ndarray:
    ycol = f"fwd_return_{h}d"
    yr = _daily_target_rank(train, ycol)
    weights = np.zeros(len(feature_cols), float)
    for j, c in enumerate(feature_cols):
        x = train[c].to_numpy(float)
        ok = np.isfinite(x) & np.isfinite(yr)
        if ok.sum() < 100:
            continue
        # Since features are already same-date percentile ranks, pooled correlation is a stable train-only IC proxy.
        cc = np.corrcoef(x[ok], yr[ok])[0, 1]
        if np.isfinite(cc):
            weights[j] = cc
    # Shrink weak features instead of hard data-mined inclusion/exclusion.
    scale = np.abs(weights).sum()
    return weights / scale if scale > 0 else weights


def _matrix(df: pd.DataFrame, feature_cols: list[str], impute: bool) -> np.ndarray:
    x = df[feature_cols].to_numpy(dtype=np.float32)
    if impute:
        x = np.where(np.isfinite(x), x, 0.5).astype(np.float32)
    return x


def fit_architectures(train: pd.DataFrame, test: pd.DataFrame, feature_cols: list[str], h: int, cfg: Cfg) -> dict[str, np.ndarray]:
    if train.empty or test.empty:
        return {a: np.full(len(test), np.nan) for a in ARCHITECTURES}
    ycol = f"fwd_return_{h}d"
    yr = _daily_target_rank(train, ycol)
    valid_y = np.isfinite(yr)

    # IC composite: all train-eligible features, with weights estimated only on this fold's training set.
    w = _feature_ic_weights(train, feature_cols, h)
    xt = _matrix(test, feature_cols, impute=True)
    composite = (xt - 0.5) @ w

    x_train_imp = _matrix(train, feature_cols, impute=True)
    ridge = Ridge(alpha=float(cfg.p["ridge_alpha"]), fit_intercept=True)
    ridge.fit(x_train_imp[valid_y], yr[valid_y])
    ridge_pred = ridge.predict(xt)

    hgb_params = dict(
        loss="squared_error",
        learning_rate=float(cfg.p["hgb_learning_rate"]),
        max_iter=int(cfg.p["hgb_max_iter"]),
        max_leaf_nodes=int(cfg.p["hgb_max_leaf_nodes"]),
        min_samples_leaf=int(cfg.p["hgb_min_samples_leaf"]),
        l2_regularization=float(cfg.p["hgb_l2"]),
        random_state=int(cfg.p["random_state"]),
    )
    x_train = _matrix(train, feature_cols, impute=False)
    x_test = _matrix(test, feature_cols, impute=False)
    hgb_rank = HistGradientBoostingRegressor(**hgb_params)
    hgb_rank.fit(x_train[valid_y], yr[valid_y])
    hgb_rank_pred = hgb_rank.predict(x_test)

    robust_y = _robust_excess_target(train, h)
    ok_ex = np.isfinite(robust_y)
    hgb_ex = HistGradientBoostingRegressor(**hgb_params)
    hgb_ex.fit(x_train[ok_ex], robust_y[ok_ex])
    hgb_ex_pred = hgb_ex.predict(x_test)

    # Blend rank and nonlinear rank surfaces. Cross-sectional normalization happens downstream.
    blend = 0.5 * ridge_pred + 0.5 * hgb_rank_pred
    return {
        "IC_COMPOSITE": composite,
        "RIDGE_RANK": ridge_pred,
        "HGB_RANK": hgb_rank_pred,
        "HGB_ROBUST_EXCESS": hgb_ex_pred,
        "BLEND_RIDGE_HGB": blend,
    }


def normalize_scores(df: pd.DataFrame, raw: np.ndarray) -> np.ndarray:
    tmp = pd.DataFrame({"signal_date": df["signal_date"].to_numpy(), "raw": raw})
    return tmp.groupby("signal_date", observed=True)["raw"].rank(method="average", pct=True).to_numpy(float)


def evaluate_scores(test: pd.DataFrame, score: np.ndarray, h: int, cutoffs: list[float]) -> dict:
    cols = ["signal_date", "ticker", f"fwd_return_{h}d", f"excess_spy_{h}d", f"excess_qqq_{h}d", f"excess_uew_{h}d"]
    z = test[cols].copy()
    z["score"] = score
    ycol = f"fwd_return_{h}d"
    z = z[np.isfinite(z["score"]) & z[ycol].notna()].copy()
    if z.empty:
        return {"economic_score": math.nan, "worst_cut_robust_excess": math.nan, "mean_rank_ic": math.nan, "rich_dates": 0}

    # Fast daily rank-IC. Scores are already same-date percentile ranks.
    z["_yr"] = z.groupby("signal_date", observed=True)[ycol].rank(method="average", pct=True)
    z["_x2"] = z["score"] * z["score"]
    z["_y2"] = z["_yr"] * z["_yr"]
    z["_xy"] = z["score"] * z["_yr"]
    g = z.groupby("signal_date", observed=True).agg(
        n=("score", "count"), sx=("score", "sum"), sy=("_yr", "sum"),
        sxx=("_x2", "sum"), syy=("_y2", "sum"), sxy=("_xy", "sum"),
    )
    g = g[g["n"] >= 20].copy()
    if len(g):
        cov = g["sxy"] - g["sx"] * g["sy"] / g["n"]
        vx = g["sxx"] - g["sx"] * g["sx"] / g["n"]
        vy = g["syy"] - g["sy"] * g["sy"] / g["n"]
        den = np.sqrt(np.maximum(vx * vy, 0.0))
        ic = (cov / den.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        mean_ic = float(ic.mean()) if ic.notna().any() else math.nan
    else:
        mean_ic = math.nan

    cut_rows = []
    retcols = [ycol, f"excess_spy_{h}d", f"excess_qqq_{h}d", f"excess_uew_{h}d"]
    for q in cutoffs:
        # Because score is a same-date percentile rank, this implements top-q without per-date quantile loops.
        s = z[z["score"] >= (1.0 - float(q))]
        if s.empty:
            continue
        d = s.groupby("signal_date", observed=True)[retcols].mean()
        d = d[d[ycol].notna()]
        if d.empty:
            continue
        ex = [float(d[c].mean()) for c in retcols[1:]]
        cut_rows.append({
            "cutoff": float(q),
            "mean_return": float(d[ycol].mean()),
            "excess_spy": ex[0],
            "excess_qqq": ex[1],
            "excess_uew": ex[2],
            "robust_excess": float(min(ex)),
            "dates": int(len(d)),
        })
    if not cut_rows:
        return {"economic_score": math.nan, "worst_cut_robust_excess": math.nan, "mean_rank_ic": mean_ic, "rich_dates": 0}
    cdf = pd.DataFrame(cut_rows)
    return {
        "economic_score": float(cdf["robust_excess"].mean()),
        "worst_cut_robust_excess": float(cdf["robust_excess"].min()),
        "mean_rank_ic": mean_ic,
        "positive_cut_share": float((cdf["robust_excess"] > 0).mean()),
        "rich_dates": int(cdf["dates"].min()),
        "cut_detail": cut_rows,
    }

def _rank_architecture(evidence: pd.DataFrame) -> str:
    if evidence.empty:
        return "IC_COMPOSITE"
    agg = evidence.groupby("architecture", as_index=False).agg(
        economic_score=("economic_score", "mean"),
        worst_period_score=("economic_score", "min"),
        worst_cut_robust_excess=("worst_cut_robust_excess", "min"),
        mean_rank_ic=("mean_rank_ic", "mean"),
    )
    agg = agg.sort_values(
        ["economic_score", "worst_period_score", "worst_cut_robust_excess", "mean_rank_ic", "architecture"],
        ascending=[False, False, False, False, True],
    )
    return str(agg.iloc[0]["architecture"])


def run_horizon(df: pd.DataFrame, feature_cols: list[str], h: int, cfg: Cfg) -> tuple[pd.DataFrame, pd.DataFrame, dict, pd.DataFrame]:
    periods = [
        ("EVIDENCE_2017_2018", "2017-01-03", "2019-01-02"),
        ("OUTER_2019_2020", "2019-01-02", "2021-01-04"),
        ("OUTER_2021_2022", "2021-01-04", "2023-01-03"),
    ]
    all_eval = []
    raw_scores: dict[str, dict[str, pd.DataFrame]] = {}
    nested_rows = []

    for label, ts, te in periods:
        train, test = purged_split(df, h, cfg.p["research_start"], ts, te)
        if len(train) < int(cfg.p["minimum_train_rows"]) or len(test) < int(cfg.p["minimum_test_rows"]):
            raise RuntimeError(f"Insufficient rows h={h} {label}: train={len(train)}, test={len(test)}")
        preds = fit_architectures(train, test, feature_cols, h, cfg)
        raw_scores[label] = {}
        for arch, raw in preds.items():
            score = normalize_scores(test, raw)
            ev = evaluate_scores(test, score, h, [float(x) for x in cfg.p["evaluation_cutoffs"]])
            row = {
                "horizon_sessions": h,
                "period": label,
                "test_start": ts,
                "test_end": te,
                "architecture": arch,
                "train_rows": len(train),
                "test_rows": len(test),
                "economic_score": ev.get("economic_score"),
                "worst_cut_robust_excess": ev.get("worst_cut_robust_excess"),
                "mean_rank_ic": ev.get("mean_rank_ic"),
                "positive_cut_share": ev.get("positive_cut_share"),
                "rich_dates": ev.get("rich_dates"),
            }
            all_eval.append(row)
            sf = test[["signal_date", "ticker"]].copy()
            sf["score"] = score
            sf["architecture"] = arch
            sf["period"] = label
            raw_scores[label][arch] = sf

        # Nested score architecture is selected strictly from evidence available BEFORE this outer period.
        if label == "OUTER_2019_2020":
            prior = pd.DataFrame(all_eval)
            prior = prior[(prior["horizon_sessions"] == h) & (prior["period"] == "EVIDENCE_2017_2018")]
            chosen = _rank_architecture(prior)
            s = raw_scores[label][chosen].copy()
            s["architecture_selected_before_period"] = chosen
            nested_rows.append(s)
        elif label == "OUTER_2021_2022":
            prior = pd.DataFrame(all_eval)
            prior = prior[(prior["horizon_sessions"] == h) & (prior["period"].isin(["EVIDENCE_2017_2018", "OUTER_2019_2020"]))]
            chosen = _rank_architecture(prior)
            s = raw_scores[label][chosen].copy()
            s["architecture_selected_before_period"] = chosen
            nested_rows.append(s)

    eval_df = pd.DataFrame(all_eval)
    # Final champion is selected only after all development evidence through 2022 is available.
    champion = _rank_architecture(eval_df)

    # Validation 2023-2024 is confirmation only. Fit champion on all matured development rows.
    train, val = purged_split(df, h, cfg.p["research_start"], cfg.p["validation_start"], cfg.p["holdout_start"])
    preds = fit_architectures(train, val, feature_cols, h, cfg)
    val_score = normalize_scores(val, preds[champion])
    val_eval = evaluate_scores(val, val_score, h, [float(x) for x in cfg.p["evaluation_cutoffs"]])
    val_scores = val[["signal_date", "ticker"]].copy()
    val_scores["horizon_sessions"] = h
    val_scores["score"] = val_score
    val_scores["champion_architecture"] = champion
    val_scores["role"] = "VALIDATION_CONFIRMATION_ONLY"

    nested = pd.concat(nested_rows, ignore_index=True) if nested_rows else pd.DataFrame()
    if len(nested):
        nested["horizon_sessions"] = h
        nested["role"] = "NESTED_OOF_POLICY_RESEARCH"

    champ = {
        "horizon_sessions": h,
        "champion_architecture": champion,
        "selection_periods": ["EVIDENCE_2017_2018", "OUTER_2019_2020", "OUTER_2021_2022"],
        "validation_used_for_selection": False,
        "validation_economic_score": val_eval.get("economic_score"),
        "validation_worst_cut_robust_excess": val_eval.get("worst_cut_robust_excess"),
        "validation_mean_rank_ic": val_eval.get("mean_rank_ic"),
        "validation_positive_cut_share": val_eval.get("positive_cut_share"),
        "train_rows_final": int(len(train)),
        "validation_rows": int(len(val)),
    }
    return eval_df, nested, champ, val_scores


def evaluate_gate(summary_parts: dict, cfg: Cfg) -> tuple[pd.DataFrame, str]:
    rows = []
    def add(test, ok, value, rule, blocking=True):
        rows.append({"test": test, "status": "PASS" if ok else "FAIL", "blocking": blocking, "value": value, "rule": rule})
    hs = [int(x) for x in cfg.p["horizons"]]
    add("PHASE1_INPUT_PASS", summary_parts["phase1_status"] == "PASS", summary_parts["phase1_status"], "Phase 1 must PASS")
    add("FINAL_HOLDOUT_NOT_LOADED", summary_parts["max_loaded_date"] < pd.Timestamp(cfg.p["holdout_start"]), str(summary_parts["max_loaded_date"].date()), "max loaded date < 2025-01-01")
    add("ALL_SIX_HORIZONS_HAVE_CHAMPIONS", sorted(summary_parts["champions"].keys()) == hs, sorted(summary_parts["champions"].keys()), str(hs))
    add("NESTED_OOF_AVAILABLE_ALL_HORIZONS", all(summary_parts["nested_counts"].get(h, 0) > 0 for h in hs), summary_parts["nested_counts"], "each horizon has 2019-2022 nested OOF scores")
    add("VALIDATION_NOT_USED_FOR_MODEL_SELECTION", all(not v["validation_used_for_selection"] for v in summary_parts["champions"].values()), False, "must be false for every horizon")
    add("PURGED_CHRONOLOGY", summary_parts["purge_violations"] == 0, summary_parts["purge_violations"], "0 train target_end_date leaks across test start")
    add("MULTI_HORIZON_PRESERVED", len(set(summary_parts["champions"])) == 6, len(set(summary_parts["champions"])), "no horizon may be discarded")
    # Informative only: weak horizons remain active but confidence can be lower in Phase 3.
    val_scores = {h: v["validation_economic_score"] for h, v in summary_parts["champions"].items()}
    add("VALIDATION_ECONOMIC_CONFIRMATION", all(np.isfinite(v) for v in val_scores.values()), val_scores, "diagnostic only; validation does not select or discard horizons", blocking=False)
    g = pd.DataFrame(rows)
    status = "PASS" if not ((g["blocking"] == True) & (g["status"] == "FAIL")).any() else "FAIL"
    return g, status


def build_phase2(workspace: Path) -> dict:
    cfg = load_cfg(workspace)
    p1 = load_phase1(workspace)
    features, targets = load_inputs(workspace, cfg)
    feature_cols = usable_features(features, cfg)
    ranked = cross_sectional_rank_features(features, feature_cols)

    out = workspace / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    all_leader = []
    all_nested = []
    all_val = []
    champions: dict[int, dict] = {}

    max_loaded_date = max(features["signal_date"].max(), targets["signal_date"].max())
    hold = pd.Timestamp(cfg.p["holdout_start"])
    if max_loaded_date >= hold:
        raise RuntimeError("HOLDOUT BREACH before model tournament")

    for h in [int(x) for x in cfg.p["horizons"]]:
        df = _merge_horizon(ranked, targets, h)
        leader, nested, champ, val_scores = run_horizon(df, feature_cols, h, cfg)
        all_leader.append(leader)
        all_nested.append(nested)
        all_val.append(val_scores)
        champions[h] = champ

    leaderboard = pd.concat(all_leader, ignore_index=True)
    nested_scores = pd.concat(all_nested, ignore_index=True)
    validation_scores = pd.concat(all_val, ignore_index=True)

    # Defensive firewall on every emitted score surface.
    if (nested_scores["signal_date"] >= hold).any() or (validation_scores["signal_date"] >= hold).any():
        raise RuntimeError("HOLDOUT BREACH in Phase 2 score surfaces")

    purge_violations = 0  # purged_split raises immediately on any violation
    parts = {
        "phase1_status": p1.get("status"),
        "max_loaded_date": max_loaded_date,
        "champions": champions,
        "nested_counts": nested_scores.groupby("horizon_sessions").size().to_dict(),
        "purge_violations": purge_violations,
    }
    gate, status = evaluate_gate(parts, cfg)

    leaderboard.to_csv(out / "v13_phase2_model_leaderboard.csv", index=False)
    nested_scores.to_parquet(out / "v13_phase2_nested_oof_scores.parquet", index=False)
    validation_scores.to_parquet(out / "v13_phase2_validation_scores.parquet", index=False)
    gate.to_csv(out / "v13_phase2_gate.csv", index=False)
    pd.DataFrame([
        {"horizon_sessions": h, **v} for h, v in champions.items()
    ]).to_csv(out / "v13_phase2_champion_summary.csv", index=False)

    champion_spec = {
        "build": BUILD,
        "holdout_start": cfg.p["holdout_start"],
        "holdout_used": False,
        "feature_transform": "same-date cross-sectional percentile ranks",
        "feature_pool_rule": f"development coverage >= {cfg.p['minimum_feature_coverage']}; no outcome-based global pre-screen",
        "features": feature_cols,
        "architectures": list(ARCHITECTURES),
        "champions": {str(h): v for h, v in champions.items()},
        "selection_objective": "PRIMARY: worst-benchmark future excess return across top 5/10/20% score cuts; IC secondary",
        "nested_oof_contract": {
            "2019_2020_architecture_selected_from": "2017_2018_ONLY",
            "2021_2022_architecture_selected_from": "2017_2020_ONLY",
            "final_2023_2024_champion_selected_from": "2017_2022_ONLY",
            "validation_used_for_selection": False,
        },
    }
    (out / "v13_phase2_champions.json").write_text(json.dumps(champion_spec, indent=2, default=str), encoding="utf-8")

    summary = {
        "status": status,
        "phase": "V13-P2",
        "build": BUILD,
        "name": cfg.p["name"],
        "objective": cfg.p["objective"],
        "phase1_input": {"status": p1.get("status"), "build": p1.get("build")},
        "research_contract": {
            "research_start": cfg.p["research_start"],
            "validation_start": cfg.p["validation_start"],
            "holdout_start": cfg.p["holdout_start"],
            "holdout_used": False,
            "horizons": [int(x) for x in cfg.p["horizons"]],
            "validation_used_for_model_selection": False,
            "portfolio_cardinality_selected": False,
            "portfolio_weights_selected": False,
        },
        "feature_pool": {"count": len(feature_cols), "features": feature_cols},
        "champions": {str(h): v for h, v in champions.items()},
        "nested_oof_rows": int(len(nested_scores)),
        "validation_score_rows": int(len(validation_scores)),
        "max_score_date": str(max(nested_scores["signal_date"].max(), validation_scores["signal_date"].max()).date()),
        "gate": gate.to_dict(orient="records"),
        "readiness": "READY_FOR_MULTI_HORIZON_CONVICTION_AND_DYNAMIC_PORTFOLIO_RESEARCH" if status == "PASS" else "NOT_READY",
        "next_gate": "If PASS: V13 Phase 3 learns cross-horizon conviction plus dynamic cardinality and endogenous sizing from NESTED OOF 2019-2022 only; 2023-2024 is confirmation; 2025+ remains blocked.",
    }
    (out / "v13_phase2_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
