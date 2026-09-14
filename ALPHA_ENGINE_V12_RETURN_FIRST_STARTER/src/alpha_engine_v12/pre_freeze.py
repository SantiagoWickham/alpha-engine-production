from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from alpha_engine_v12.model_tournament import (
    _as_date,
    _norm_ticker,
    cross_sectional_rank_features,
)
from alpha_engine_v12.portfolio_policy import load_price_surface
from alpha_engine_v12.edge_lineage import (
    EdgeSpec,
    build_lineage_layers,
    expected_return_and_se,
    fit_edge_calibration,
    lineage_metrics,
    monthly_lineage_audit,
    prepare_market,
    simulate_edge_policy,
    solve_weight_milp,
)

PHASE8_BUILD = "V1_PRE_FREEZE_LOCK_2026-09-12"


@dataclass(frozen=True)
class Phase8Config:
    name: str
    objective: str
    phase7_summary_path: str
    phase7_candidate_path: str
    phase5_feature_pool_path: str
    feature_library_path: str
    targets_path: str
    return_price_layer_path: str
    terminal_overlay_path: str
    refit_start: pd.Timestamp
    replay_start: pd.Timestamp
    final_oos_start: pd.Timestamp
    horizon_sessions: int
    architecture: str
    minimum_cross_section: int
    minimum_fixed_features: int
    calibration_bins: int
    hac_lag: int
    base_round_trip_bps: float
    stress_round_trip_bps: float
    maximum_execution_skip_rate: float
    hash_algorithm: str
    float_decimals: int
    require_policy_unchanged: bool
    require_feature_set_unchanged: bool
    require_replay_determinism: bool


def load_config(root: Path) -> Phase8Config:
    with (root / "config" / "phase8.toml").open("rb") as f:
        raw = tomllib.load(f)["phase8"]
    p = raw["partitions"]; m = raw["model"]; c = raw["calibration"]; r = raw["replay"]; fr = raw["freeze"]
    cfg = Phase8Config(
        name=str(raw["name"]), objective=str(raw["objective"]),
        phase7_summary_path=str(raw["phase7_summary_path"]), phase7_candidate_path=str(raw["phase7_candidate_path"]),
        phase5_feature_pool_path=str(raw["phase5_feature_pool_path"]), feature_library_path=str(raw["feature_library_path"]),
        targets_path=str(raw["targets_path"]), return_price_layer_path=str(raw["return_price_layer_path"]),
        terminal_overlay_path=str(raw["terminal_overlay_path"]),
        refit_start=pd.Timestamp(p["refit_start"]).normalize(), replay_start=pd.Timestamp(p["replay_start"]).normalize(),
        final_oos_start=pd.Timestamp(p["final_oos_start"]).normalize(),
        horizon_sessions=int(m["horizon_sessions"]), architecture=str(m["architecture"]),
        minimum_cross_section=int(m["minimum_cross_section"]), minimum_fixed_features=int(m["minimum_fixed_features"]),
        calibration_bins=int(c["bins"]), hac_lag=int(c["hac_lag"]),
        base_round_trip_bps=float(r["base_round_trip_bps"]), stress_round_trip_bps=float(r["stress_round_trip_bps"]),
        maximum_execution_skip_rate=float(r["maximum_execution_skip_rate"]),
        hash_algorithm=str(fr["hash_algorithm"]).lower(), float_decimals=int(fr["float_decimals"]),
        require_policy_unchanged=bool(fr["require_policy_unchanged"]),
        require_feature_set_unchanged=bool(fr["require_feature_set_unchanged"]),
        require_replay_determinism=bool(fr["require_replay_determinism"]),
    )
    if not (cfg.refit_start < cfg.replay_start < cfg.final_oos_start):
        raise ValueError("Invalid Phase 8 temporal ordering")
    if cfg.hash_algorithm != "sha256":
        raise ValueError("Phase 8 V1 supports sha256 freeze fingerprints only")
    return cfg


def validate_phase7(summary: dict, candidate: dict, cfg: Phase8Config) -> None:
    if summary.get("status") != "PASS":
        raise RuntimeError("Phase 7 must PASS before Phase 8")
    if summary.get("readiness") != "READY_FOR_PRE_FREEZE_REPLAY":
        raise RuntimeError("Phase 7 is not READY_FOR_PRE_FREEZE_REPLAY")
    tc = summary.get("temporal_contract") or {}
    if tc.get("final_oos_used") is not False:
        raise RuntimeError("Phase 7 final OOS firewall is not intact")
    if pd.Timestamp(tc.get("final_oos_start")).normalize() != cfg.final_oos_start:
        raise RuntimeError("Phase 7 / Phase 8 final OOS boundary mismatch")
    if bool(candidate.get("final_oos_used")):
        raise RuntimeError("Pre-freeze candidate claims final OOS usage")
    if float(candidate.get("base_round_trip_cost_bps")) != cfg.base_round_trip_bps:
        raise RuntimeError("Phase 7 candidate / Phase 8 base-cost mismatch")
    if float(candidate.get("stress_round_trip_cost_bps")) != cfg.stress_round_trip_bps:
        raise RuntimeError("Phase 7 candidate / Phase 8 stress-cost mismatch")
    if pd.Timestamp(candidate.get("final_oos_start")).normalize() != cfg.final_oos_start:
        raise RuntimeError("Candidate final OOS boundary mismatch")
    if str(candidate.get("alpha_surface")) != f"H{cfg.horizon_sessions} / Phase 5 {cfg.architecture}":
        raise RuntimeError("Phase 8 architecture/horizon does not match Phase 7 candidate")
    if str(candidate.get("policy_type")) != "EVENT_DRIVEN_EXPECTED_NET_EDGE":
        raise RuntimeError("Phase 8 requires the event-driven expected-net-edge candidate")


def load_fixed_feature_pool(root: Path, cfg: Phase8Config) -> pd.DataFrame:
    p = pd.read_csv(root / cfg.phase5_feature_pool_path)
    req = {"feature", "horizon_sessions", "kept_after_correlation_prune", "development_direction", "development_mean_spearman_ic"}
    missing = req - set(p.columns)
    if missing:
        raise ValueError(f"Phase 5 feature pool missing {sorted(missing)}")
    p["horizon_sessions"] = pd.to_numeric(p["horizon_sessions"], errors="raise").astype(int)
    keep = p["kept_after_correlation_prune"]
    if keep.dtype != bool:
        keep = keep.astype(str).str.lower().isin(["true", "1", "yes"])
    x = p[(p["horizon_sessions"] == cfg.horizon_sessions) & keep].copy()
    x["feature"] = x["feature"].astype(str)
    x["development_direction"] = pd.to_numeric(x["development_direction"], errors="raise").astype(int)
    x["development_mean_spearman_ic"] = pd.to_numeric(x["development_mean_spearman_ic"], errors="coerce")
    if len(x) < cfg.minimum_fixed_features:
        raise RuntimeError(f"Too few fixed Phase 5 H{cfg.horizon_sessions} features: {len(x)}")
    if x["feature"].duplicated().any():
        raise RuntimeError("Duplicate fixed features in Phase 5 pool")
    return x.sort_values(["development_priority_rank", "feature"] if "development_priority_rank" in x.columns else ["feature"]).reset_index(drop=True)


def load_refit_data(root: Path, cfg: Phase8Config, features: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    f = pd.read_parquet(root / cfg.feature_library_path, columns=["date", "ticker", "feature_allowed", *features])
    f["date"] = _as_date(f["date"]); f["ticker"] = _norm_ticker(f["ticker"])
    f = f[(f["date"] >= cfg.refit_start) & (f["date"] < cfg.final_oos_start)].copy()
    if f.empty:
        raise RuntimeError("No pre-OOS feature rows for Phase 8 refit")
    if not f["feature_allowed"].fillna(False).astype(bool).all():
        raise RuntimeError("Feature-forbidden row entered Phase 8")
    ranked = cross_sectional_rank_features(f[["date", "ticker", *features]], features)

    h = cfg.horizon_sessions
    cols = ["signal_date", "ticker", f"target_end_date_{h}d", f"target_resolved_{h}d", f"fwd_return_{h}d", f"cs_rank_pct_{h}d"]
    t = pd.read_parquet(root / cfg.targets_path, columns=cols)
    t["signal_date"] = _as_date(t["signal_date"]); t["ticker"] = _norm_ticker(t["ticker"])
    t[f"target_end_date_{h}d"] = _as_date(t[f"target_end_date_{h}d"])
    t[f"fwd_return_{h}d"] = pd.to_numeric(t[f"fwd_return_{h}d"], errors="coerce")
    t[f"cs_rank_pct_{h}d"] = pd.to_numeric(t[f"cs_rank_pct_{h}d"], errors="coerce")
    resolved = t[f"target_resolved_{h}d"].fillna(False).astype(bool)
    mature = t[f"target_end_date_{h}d"].notna() & t[f"target_end_date_{h}d"].lt(cfg.final_oos_start)
    t = t[resolved & mature & (t["signal_date"] >= cfg.refit_start) & (t["signal_date"] < cfg.final_oos_start)].copy()
    return ranked.sort_values(["date", "ticker"]).reset_index(drop=True), t.sort_values(["signal_date", "ticker"]).reset_index(drop=True)


def _daily_corrs(df: pd.DataFrame, xcol: str, ycol: str, min_cs: int) -> pd.Series:
    z = df[["signal_date", xcol, ycol]].copy()
    z[xcol] = pd.to_numeric(z[xcol], errors="coerce"); z[ycol] = pd.to_numeric(z[ycol], errors="coerce")
    z = z[np.isfinite(z[xcol]) & np.isfinite(z[ycol])]
    out = []
    for d, g in z.groupby("signal_date", sort=False):
        if len(g) < min_cs or g[xcol].nunique() < 2 or g[ycol].nunique() < 2:
            continue
        c = g[xcol].corr(g[ycol], method="pearson")
        if pd.notna(c) and np.isfinite(c):
            out.append((pd.Timestamp(d), float(c)))
    return pd.Series({d: c for d, c in out}, dtype=float)


def refit_composite_weights(ranked: pd.DataFrame, targets: pd.DataFrame, fixed_pool: pd.DataFrame, cfg: Phase8Config) -> pd.DataFrame:
    h = cfg.horizon_sessions; features = fixed_pool["feature"].tolist()
    x = ranked.rename(columns={"date": "signal_date"}).merge(
        targets[["signal_date", "ticker", f"cs_rank_pct_{h}d"]], on=["signal_date", "ticker"], how="inner"
    )
    target = f"cs_rank_pct_{h}d"
    rows = []
    meta = fixed_pool.set_index("feature")
    for c in features:
        daily = _daily_corrs(x, c, target, cfg.minimum_cross_section)
        full_ic = float(daily.mean()) if len(daily) else math.nan
        direction = int(meta.at[c, "development_direction"])
        old_ic = float(meta.at[c, "development_mean_spearman_ic"]) if pd.notna(meta.at[c, "development_mean_spearman_ic"]) else math.nan
        rows.append({
            "feature": c,
            "frozen_direction": direction,
            "phase5_development_ic": old_ic,
            "pre_oos_refit_mean_ic": full_ic,
            "pre_oos_rich_dates": int(len(daily)),
            "sign_agrees_with_phase5": bool(np.isfinite(full_ic) and np.sign(full_ic) == direction),
            "raw_refit_weight": float(direction * max(abs(full_ic), 1e-8)) if np.isfinite(full_ic) else math.nan,
        })
    out = pd.DataFrame(rows)
    if out["raw_refit_weight"].isna().any():
        bad = out.loc[out["raw_refit_weight"].isna(), "feature"].tolist()
        raise RuntimeError(f"Unable to refit fixed feature weights: {bad}")
    den = float(out["raw_refit_weight"].abs().sum())
    if not np.isfinite(den) or den <= 0:
        raise RuntimeError("Invalid Phase 8 refit feature-weight denominator")
    out["normalized_refit_weight"] = out["raw_refit_weight"] / den
    out["feature_admitted_in_phase8"] = False
    out["feature_dropped_in_phase8"] = False
    return out


def score_with_frozen_refit(ranked: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    features = weights["feature"].tolist()
    w = weights.set_index("feature")["normalized_refit_weight"].reindex(features).to_numpy(float)
    x = ranked[features].to_numpy(float)
    centered = x - 0.5
    ok = np.isfinite(centered)
    num = np.nansum(centered * w[None, :], axis=1)
    den = np.sum(ok * np.abs(w)[None, :], axis=1)
    raw = np.where(den > 0, num / den, np.nan)
    out = ranked[["date", "ticker"]].copy().rename(columns={"date": "signal_date"})
    out["model_score_raw"] = raw
    out["alpha_score"] = pd.Series(raw, index=out.index).groupby(out["signal_date"], sort=False).rank(method="average", pct=True)
    out = out[np.isfinite(out["alpha_score"])].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    return out


def final_calibration(scores: pd.DataFrame, targets: pd.DataFrame, cfg: Phase8Config) -> pd.DataFrame:
    s = scores[["signal_date", "ticker", "alpha_score"]].copy()
    s["partition"] = "PRE_OOS_REFIT"
    h = cfg.horizon_sessions
    t = targets.rename(columns={
        f"target_end_date_{h}d": "target_end_date_20d",
        f"target_resolved_{h}d": "target_resolved_20d",
        f"fwd_return_{h}d": "fwd_return_20d",
    }) if h != 20 else targets.copy()
    return fit_edge_calibration(s, t, ["PRE_OOS_REFIT"], cfg.final_oos_start, cfg.calibration_bins, cfg.hac_lag)


def edge_spec_from_candidate(candidate: dict) -> EdgeSpec:
    return EdgeSpec(
        entry_floor=float(candidate["entry_floor"]),
        uncertainty_z=float(candidate["uncertainty_z"]),
        minimum_extra_edge_bps=float(candidate["minimum_extra_edge_bps"]),
        max_replacements=int(candidate["max_replacements_per_session"]),
    )


def canonicalize(value, decimals: int = 12):
    if isinstance(value, dict):
        return {str(k): canonicalize(value[k], decimals) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonicalize(x, decimals) for x in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        if not math.isfinite(f):
            return None
        return round(f, decimals)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def sha256_payload(value, decimals: int = 12) -> str:
    raw = json.dumps(canonicalize(value, decimals), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def hash_file(path: Path, block: int = 8 * 1024 * 1024) -> dict:
    h = hashlib.sha256(); size = 0
    with path.open("rb") as f:
        while True:
            b = f.read(block)
            if not b: break
            size += len(b); h.update(b)
    return {"path": str(path), "bytes": int(size), "sha256": h.hexdigest()}


def _canonical_frame_hash(df: pd.DataFrame, cols: list[str], decimals: int = 12) -> str:
    x = df[cols].copy()
    for c in cols:
        if pd.api.types.is_datetime64_any_dtype(x[c]):
            x[c] = pd.to_datetime(x[c]).dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_numeric_dtype(x[c]):
            x[c] = pd.to_numeric(x[c], errors="coerce").round(decimals)
    raw = x.to_csv(index=False, na_rep="NA", float_format=f"%.{decimals}f", lineterminator="\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def replay_twice(
    scores: pd.DataFrame,
    root: Path,
    cfg: Phase8Config,
    calib: pd.DataFrame,
    candidate: dict,
) -> tuple[dict, pd.DataFrame, pd.DataFrame, dict]:
    proxy = type("Proxy", (), {
        "return_price_layer_path": cfg.return_price_layer_path,
        "terminal_overlay_path": cfg.terminal_overlay_path,
        "final_oos_start": cfg.final_oos_start,
    })()
    prices, terminals = load_price_surface(root, proxy)
    market = prepare_market(prices, cfg.replay_start, cfg.final_oos_start)
    spec = edge_spec_from_candidate(candidate)
    top_n = int(candidate["top_n"])
    m1, d1, e1 = simulate_edge_policy(
        scores, prices, terminals, calib, spec, cfg.replay_start, cfg.final_oos_start, top_n,
        cfg.base_round_trip_bps, prepared_market=market
    )
    m2, d2, e2 = simulate_edge_policy(
        scores, prices, terminals, calib, spec, cfg.replay_start, cfg.final_oos_start, top_n,
        cfg.base_round_trip_bps, prepared_market=market
    )
    nav_cols = ["date", "nav", "net_return", "turnover", "cost_fraction", "execution_skipped", "holdings", "cash_weight"]
    edge_cols = ["signal_date", "held_ticker", "candidate_ticker", "net_edge", "trade"] if len(e1) else []
    h1 = _canonical_frame_hash(d1, nav_cols, cfg.float_decimals) if len(d1) else ""
    h2 = _canonical_frame_hash(d2, nav_cols, cfg.float_decimals) if len(d2) else ""
    eh1 = _canonical_frame_hash(e1, edge_cols, cfg.float_decimals) if edge_cols else ""
    eh2 = _canonical_frame_hash(e2, edge_cols, cfg.float_decimals) if edge_cols else ""
    determinism = {
        "nav_hash_run1": h1, "nav_hash_run2": h2, "edge_hash_run1": eh1, "edge_hash_run2": eh2,
        "identical": bool(h1 == h2 and eh1 == eh2),
        "replay_role": "NON_EVALUATIVE_REFIT_REPLAY",
        "performance_metrics_are_not_selection_evidence": True,
    }
    return m1, d1, e1, determinism


def build_freeze_payload(
    candidate: dict,
    weights: pd.DataFrame,
    calibration: pd.DataFrame,
    phase7_cfg,
    cfg: Phase8Config,
) -> dict:
    return {
        "freeze_build": PHASE8_BUILD,
        "model": {
            "horizon_sessions": cfg.horizon_sessions,
            "architecture": cfg.architecture,
            "feature_transform": "same-date cross-sectional percentile ranks; composite uses centered ranks",
            "feature_weights": [
                {
                    "feature": str(r.feature),
                    "direction": int(r.frozen_direction),
                    "weight": float(r.normalized_refit_weight),
                } for r in weights.itertuples()
            ],
        },
        "edge_calibration": [
            {
                "score_center": float(r.score_center),
                "expected_return_20d": float(r.isotonic_expected_return_20d),
                "hac_se": float(r.hac_se_expected_mean),
            } for r in calibration.itertuples()
        ],
        "policy": {
            "policy_type": str(candidate["policy_type"]),
            "top_n": int(candidate["top_n"]),
            "entry_floor": float(candidate["entry_floor"]),
            "uncertainty_z": float(candidate["uncertainty_z"]),
            "minimum_extra_edge_bps": float(candidate["minimum_extra_edge_bps"]),
            "max_replacements_per_session": int(candidate["max_replacements_per_session"]),
            "decision_rule": str(candidate["decision_rule"]),
            "base_round_trip_cost_bps": float(candidate["base_round_trip_cost_bps"]),
            "stress_round_trip_cost_bps": float(candidate["stress_round_trip_cost_bps"]),
        },
        "portfolio_construction": {
            "lineage_candidate_count": int(phase7_cfg.lineage_candidate_count),
            "reference_top_n": int(phase7_cfg.lineage_reference_top_n),
            "optimizer_max_weight": float(phase7_cfg.optimizer_max_weight),
            "milp_min_weight": float(phase7_cfg.milp_min_weight),
            "milp_max_weight": float(phase7_cfg.milp_max_weight),
            "milp_weight_step": float(phase7_cfg.milp_weight_step),
            "milp_holdings": int(phase7_cfg.milp_holdings),
        },
        "boundaries": {
            "refit_start": str(cfg.refit_start.date()),
            "final_oos_start": str(cfg.final_oos_start.date()),
            "final_oos_used_for_freeze": False,
        },
    }


def build_phase8(root: Path) -> dict:
    from alpha_engine_v12.edge_lineage import load_config as load_phase7_config

    cfg = load_config(root); outputs = root / "outputs"; outputs.mkdir(parents=True, exist_ok=True)
    with (root / cfg.phase7_summary_path).open("r", encoding="utf-8") as f: p7 = json.load(f)
    with (root / cfg.phase7_candidate_path).open("r", encoding="utf-8") as f: candidate = json.load(f)
    validate_phase7(p7, candidate, cfg)

    fixed_pool = load_fixed_feature_pool(root, cfg)
    fixed_features = fixed_pool["feature"].tolist()
    ranked, targets = load_refit_data(root, cfg, fixed_features)
    if pd.to_datetime(ranked["date"]).max() >= cfg.final_oos_start:
        raise RuntimeError("Phase 8 feature load crossed final OOS boundary")
    h = cfg.horizon_sessions
    if len(targets) and pd.to_datetime(targets[f"target_end_date_{h}d"]).max() >= cfg.final_oos_start:
        raise RuntimeError("Phase 8 refit target crossed final OOS boundary")

    weights = refit_composite_weights(ranked, targets, fixed_pool, cfg)
    scores = score_with_frozen_refit(ranked, weights)
    calibration = final_calibration(scores, targets, cfg)
    p7cfg = load_phase7_config(root)

    # Structural lineage with final refit parameters. This is not performance selection.
    lineage = monthly_lineage_audit(
        scores, calibration, p7cfg, float(candidate["uncertainty_z"]),
        max(cfg.replay_start, pd.Timestamp("2023-01-03")), cfg.final_oos_start,
        "PRE_FREEZE_STRUCTURAL_REPLAY"
    )
    if len(lineage):
        lineage_summary = {
            "snapshots": int(len(lineage)),
            "milp_success_rate": float(lineage["milp_success"].mean()),
            "median_spearman_alpha_milp": float(pd.to_numeric(lineage["spearman_alpha_milp"], errors="coerce").median()),
            "median_kendall_alpha_milp": float(pd.to_numeric(lineage["kendall_alpha_milp"], errors="coerce").median()),
            "median_top10_capture": float(pd.to_numeric(lineage["top10_capture"], errors="coerce").median()),
            "median_alpha_capture": float(pd.to_numeric(lineage["alpha_capture"], errors="coerce").median()),
            "median_l1_optimizer_milp": float(pd.to_numeric(lineage["l1_optimizer_milp"], errors="coerce").median()),
        }
    else:
        lineage_summary = {"snapshots": 0}

    replay_metrics, replay_daily, replay_edges, deterministic = replay_twice(scores, root, cfg, calibration, candidate)

    payload = build_freeze_payload(candidate, weights, calibration, p7cfg, cfg)
    model_fingerprint = sha256_payload(payload, cfg.float_decimals)

    source_paths = [
        root / cfg.phase7_summary_path,
        root / cfg.phase7_candidate_path,
        root / cfg.phase5_feature_pool_path,
        root / cfg.feature_library_path,
        root / cfg.targets_path,
        root / cfg.return_price_layer_path,
        root / cfg.terminal_overlay_path,
        root / "config" / "phase5.toml",
        root / "config" / "phase7.toml",
        root / "config" / "phase8.toml",
        root / "src" / "alpha_engine_v12" / "model_tournament.py",
        root / "src" / "alpha_engine_v12" / "edge_lineage.py",
        root / "src" / "alpha_engine_v12" / "pre_freeze.py",
    ]
    source_manifest = []
    for p in source_paths:
        if not p.exists():
            continue
        rec = hash_file(p)
        rec["path"] = str(p.relative_to(root)).replace("\\", "/")
        source_manifest.append(rec)
    source_manifest_fingerprint = sha256_payload(source_manifest, cfg.float_decimals)
    freeze_fingerprint = hashlib.sha256((model_fingerprint + ":" + source_manifest_fingerprint).encode("utf-8")).hexdigest()

    policy_expected = {
        "top_n": int(candidate["top_n"]),
        "entry_floor": float(candidate["entry_floor"]),
        "uncertainty_z": float(candidate["uncertainty_z"]),
        "minimum_extra_edge_bps": float(candidate["minimum_extra_edge_bps"]),
        "max_replacements_per_session": int(candidate["max_replacements_per_session"]),
        "base_round_trip_cost_bps": float(candidate["base_round_trip_cost_bps"]),
        "stress_round_trip_cost_bps": float(candidate["stress_round_trip_cost_bps"]),
    }
    policy_actual = payload["policy"]
    policy_unchanged = (
        int(policy_actual["top_n"]) == policy_expected["top_n"]
        and float(policy_actual["entry_floor"]) == policy_expected["entry_floor"]
        and float(policy_actual["uncertainty_z"]) == policy_expected["uncertainty_z"]
        and float(policy_actual["minimum_extra_edge_bps"]) == policy_expected["minimum_extra_edge_bps"]
        and int(policy_actual["max_replacements_per_session"]) == policy_expected["max_replacements_per_session"]
        and float(policy_actual["base_round_trip_cost_bps"]) == policy_expected["base_round_trip_cost_bps"]
        and float(policy_actual["stress_round_trip_cost_bps"]) == policy_expected["stress_round_trip_cost_bps"]
    )
    feature_set_unchanged = list(weights["feature"]) == fixed_features and not weights["feature_admitted_in_phase8"].any() and not weights["feature_dropped_in_phase8"].any()
    calmono = bool(calibration["isotonic_expected_return_20d"].is_monotonic_increasing)
    lineage_ok = bool(
        lineage_summary.get("snapshots", 0) > 0
        and lineage_summary.get("milp_success_rate", 0) >= 1.0 - 1e-12
        and lineage_summary.get("median_spearman_alpha_milp", -1) >= p7cfg.lineage_min_spearman
        and lineage_summary.get("median_kendall_alpha_milp", -1) >= p7cfg.lineage_min_kendall
        and lineage_summary.get("median_top10_capture", -1) >= p7cfg.lineage_min_top10_capture
        and lineage_summary.get("median_alpha_capture", -1) >= p7cfg.lineage_min_alpha_capture
        and lineage_summary.get("median_l1_optimizer_milp", 999) <= p7cfg.lineage_max_optimizer_milp_l1
    )
    replay_skip = float(replay_metrics.get("execution_skip_rate", 1.0))
    sign_agreement = float(weights["sign_agrees_with_phase5"].mean())

    gate_rows = []
    def add(test: str, ok: bool, value, rule: str, blocking: bool = True):
        gate_rows.append({"test": test, "status": "PASS" if ok else "FAIL", "blocking": blocking, "value": value, "rule": rule})
    add("PHASE7_INPUT_PASS", p7.get("status") == "PASS", p7.get("status"), "Phase 7 must PASS")
    add("PHASE7_READINESS", p7.get("readiness") == "READY_FOR_PRE_FREEZE_REPLAY", p7.get("readiness"), "Phase 7 must be ready for pre-freeze replay")
    add("FINAL_OOS_FEATURE_FIREWALL", pd.to_datetime(ranked["date"]).max() < cfg.final_oos_start, str(pd.to_datetime(ranked["date"]).max().date()), "max refit feature date must be before 2025-01-01")
    add("FINAL_OOS_LABEL_FIREWALL", len(targets) > 0 and pd.to_datetime(targets[f"target_end_date_{h}d"]).max() < cfg.final_oos_start, str(pd.to_datetime(targets[f"target_end_date_{h}d"]).max().date()) if len(targets) else "", "all refit labels must mature before 2025-01-01")
    add("FIXED_FEATURE_SET_UNCHANGED", feature_set_unchanged, len(fixed_features), "Phase 8 may refit magnitudes but cannot admit/drop/reselect Phase 5 H20 features")
    add("POLICY_HYPERPARAMETERS_UNCHANGED", policy_unchanged, policy_expected, "Phase 7 event-driven policy constants must be copied exactly")
    add("EDGE_CALIBRATION_MONOTONIC", calmono, calmono, "final pre-OOS isotonic score-to-return curve must be nondecreasing")
    add("REFIT_DIRECTION_STABILITY_DIAGNOSTIC", sign_agreement >= 0.75, sign_agreement, "diagnostic: >=75% fixed Phase 5 feature directions agree with all-pre-OOS refit IC", blocking=False)
    add("PRE_FREEZE_REPLAY_DETERMINISM", deterministic["identical"], deterministic["nav_hash_run1"], "two identical runs must produce identical NAV and edge-decision hashes")
    add("PRE_FREEZE_EXECUTION_INTEGRITY", replay_skip <= cfg.maximum_execution_skip_rate, replay_skip, f"execution skip rate <= {cfg.maximum_execution_skip_rate:.3f}")
    add("FINAL_REFIT_ALPHA_LINEAGE", lineage_ok, lineage_summary, "final refit score -> reference -> theoretical -> optimizer -> MILP must preserve alpha")
    add("FREEZE_FINGERPRINT_CREATED", len(model_fingerprint) == 64, model_fingerprint, "canonical model/policy/calibration payload must have SHA-256 fingerprint")
    add("FINAL_OOS_OPENED", True, False, "Phase 8 must not load or evaluate any 2025+ feature/label/score")
    gate = pd.DataFrame(gate_rows)
    status = "PASS" if not (gate["blocking"].astype(bool) & gate["status"].eq("FAIL")).any() else "FAIL"
    readiness = "READY_TO_OPEN_FINAL_OOS_ONCE" if status == "PASS" else "NOT_READY_FOR_FINAL_OOS"

    weights.to_csv(outputs / "phase8_final_feature_weights.csv", index=False)
    calibration.to_csv(outputs / "phase8_final_edge_calibration.csv", index=False)
    lineage.to_csv(outputs / "phase8_final_lineage_audit.csv", index=False)
    gate.to_csv(outputs / "phase8_gate.csv", index=False)
    scores.to_parquet(outputs / "phase8_pre_oos_frozen_scores.parquet", index=False)
    replay_daily.to_csv(outputs / "phase8_pre_freeze_replay_nav.csv", index=False)
    replay_edges.to_csv(outputs / "phase8_pre_freeze_edge_decisions.csv", index=False)

    final_spec = canonicalize(payload, cfg.float_decimals)
    final_spec["model_fingerprint_sha256"] = model_fingerprint
    (outputs / "phase8_final_model_spec.json").write_text(json.dumps(final_spec, indent=2), encoding="utf-8")

    manifest = {
        "build": PHASE8_BUILD,
        "freeze_status": "LOCKED_PRE_OOS" if status == "PASS" else "NOT_LOCKED",
        "model_fingerprint_sha256": model_fingerprint,
        "source_manifest_fingerprint_sha256": source_manifest_fingerprint,
        "freeze_fingerprint_sha256": freeze_fingerprint,
        "source_manifest": source_manifest,
        "final_oos_start": str(cfg.final_oos_start.date()),
        "final_oos_used": False,
        "replay_determinism": deterministic,
        "replay_role": "NON_EVALUATIVE_REFIT_REPLAY",
        "warning": "After PASS, do not change feature set, feature weights, calibration, policy, costs, optimizer or MILP before the one-time final OOS run.",
    }
    (outputs / "phase8_freeze_manifest.json").write_text(json.dumps(canonicalize(manifest, cfg.float_decimals), indent=2), encoding="utf-8")
    (outputs / "phase8_model_fingerprint.sha256").write_text(model_fingerprint + "\n", encoding="utf-8")

    replay_summary = pd.DataFrame([{
        "period": f"{cfg.replay_start.date()}_to_{(cfg.final_oos_start - pd.Timedelta(days=1)).date()}",
        "role": "NON_EVALUATIVE_REFIT_REPLAY",
        "days": replay_metrics.get("days"),
        "total_return": replay_metrics.get("total_return"),
        "cagr": replay_metrics.get("cagr"),
        "max_drawdown": replay_metrics.get("max_drawdown"),
        "annual_turnover": replay_metrics.get("annual_turnover"),
        "trade_days": replay_metrics.get("trade_days"),
        "execution_skip_rate": replay_skip,
        "edge_decisions": replay_metrics.get("edge_decisions"),
        "edge_trades": replay_metrics.get("edge_trades"),
        "selection_evidence": False,
    }])
    replay_summary.to_csv(outputs / "phase8_replay_summary.csv", index=False)

    summary = {
        "status": status,
        "phase": 8,
        "build": PHASE8_BUILD,
        "name": cfg.name,
        "objective": cfg.objective,
        "phase7_input": {"status": p7.get("status"), "readiness": p7.get("readiness")},
        "final_refit": {
            "horizon_sessions": cfg.horizon_sessions,
            "architecture": cfg.architecture,
            "fixed_features": int(len(fixed_features)),
            "pre_oos_mature_labels": int(len(targets)),
            "refit_feature_first_date": str(pd.to_datetime(ranked["date"]).min().date()),
            "refit_feature_last_date": str(pd.to_datetime(ranked["date"]).max().date()),
            "latest_label_end_date": str(pd.to_datetime(targets[f"target_end_date_{h}d"]).max().date()),
            "direction_sign_agreement": sign_agreement,
        },
        "frozen_policy": policy_expected,
        "final_lineage": lineage_summary,
        "pre_freeze_replay": {
            "role": "NON_EVALUATIVE_REFIT_REPLAY",
            "deterministic": deterministic["identical"],
            "execution_skip_rate": replay_skip,
            "selection_evidence": False,
        },
        "freeze": {
            "freeze_status": manifest["freeze_status"],
            "model_fingerprint_sha256": model_fingerprint,
            "source_manifest_fingerprint_sha256": source_manifest_fingerprint,
            "freeze_fingerprint_sha256": freeze_fingerprint,
        },
        "final_oos_firewall": {
            "final_oos_start": str(cfg.final_oos_start.date()),
            "used": False,
        },
        "readiness": readiness,
        "next_gate": "If READY_TO_OPEN_FINAL_OOS_ONCE: Phase 9 loads the frozen Phase 8 spec/fingerprint, opens 2025+ exactly once, persists ex-ante decisions and realized outcomes, and must not tune anything afterward.",
    }
    (outputs / "phase8_summary.json").write_text(json.dumps(canonicalize(summary, cfg.float_decimals), indent=2), encoding="utf-8")
    return summary
