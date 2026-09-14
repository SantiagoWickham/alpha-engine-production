from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine_v12.edge_lineage import EdgeSpec
from alpha_engine_v12.execution_parity import (
    calibration_from_spec,
    simulate_execution_parity,
)
from alpha_engine_v12.portfolio_policy import _portfolio_metrics
from alpha_engine_v12.pre_freeze import canonicalize, hash_file, sha256_payload

PHASE9_BUILD = "V1_FINAL_OOS_ONE_SHOT_2026-09-12"


@dataclass(frozen=True)
class Phase9Config:
    name: str
    objective: str
    phase8b_summary_path: str
    phase8b_execution_model_spec_path: str
    phase8b_freeze_manifest_path: str
    phase8_freeze_manifest_path: str
    phase8_pre_oos_scores_path: str
    feature_library_path: str
    targets_path: str
    return_price_layer_path: str
    terminal_overlay_path: str
    receipt_path: str
    expected_final_freeze_fingerprint_sha256: str
    expected_execution_parity_source_sha256: str
    carry_state_start: pd.Timestamp
    score_fidelity_start: pd.Timestamp
    final_oos_start: pd.Timestamp
    minimum_oos_sessions: int
    maximum_oos_drawdown: float
    maximum_execution_skip_rate: float
    require_milp_success_rate: float
    require_positive_base_cagr: bool
    require_positive_stress_cagr: bool
    minimum_score_fidelity_correlation: float
    float_decimals: int


def load_config(root: Path) -> Phase9Config:
    with (root / "config" / "phase9.toml").open("rb") as f:
        raw = tomllib.load(f)["phase9"]
    p = raw["partitions"]
    a = raw["acceptance"]
    cfg = Phase9Config(
        name=str(raw["name"]), objective=str(raw["objective"]),
        phase8b_summary_path=str(raw["phase8b_summary_path"]),
        phase8b_execution_model_spec_path=str(raw["phase8b_execution_model_spec_path"]),
        phase8b_freeze_manifest_path=str(raw["phase8b_freeze_manifest_path"]),
        phase8_freeze_manifest_path=str(raw["phase8_freeze_manifest_path"]),
        phase8_pre_oos_scores_path=str(raw["phase8_pre_oos_scores_path"]),
        feature_library_path=str(raw["feature_library_path"]), targets_path=str(raw["targets_path"]),
        return_price_layer_path=str(raw["return_price_layer_path"]), terminal_overlay_path=str(raw["terminal_overlay_path"]),
        receipt_path=str(raw["receipt_path"]),
        expected_final_freeze_fingerprint_sha256=str(raw["expected_final_freeze_fingerprint_sha256"]),
        expected_execution_parity_source_sha256=str(raw["expected_execution_parity_source_sha256"]),
        carry_state_start=pd.Timestamp(p["carry_state_start"]).normalize(),
        score_fidelity_start=pd.Timestamp(p["score_fidelity_start"]).normalize(),
        final_oos_start=pd.Timestamp(p["final_oos_start"]).normalize(),
        minimum_oos_sessions=int(a["minimum_oos_sessions"]), maximum_oos_drawdown=float(a["maximum_oos_drawdown"]),
        maximum_execution_skip_rate=float(a["maximum_execution_skip_rate"]), require_milp_success_rate=float(a["require_milp_success_rate"]),
        require_positive_base_cagr=bool(a["require_positive_base_cagr"]), require_positive_stress_cagr=bool(a["require_positive_stress_cagr"]),
        minimum_score_fidelity_correlation=float(a["minimum_score_fidelity_correlation"]), float_decimals=int(a["float_decimals"]),
    )
    if not (cfg.carry_state_start < cfg.score_fidelity_start < cfg.final_oos_start):
        raise ValueError("Invalid Phase 9 temporal ordering")
    return cfg


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.normalize()


def _norm_ticker(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.upper()


def _sha256_file(path: Path, block: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _recompute_execution_fingerprint(spec: dict, phase8_freeze_fp: str, decimals: int) -> tuple[str, str]:
    payload = {k: v for k, v in spec.items() if k not in {"execution_fingerprint_sha256", "final_freeze_fingerprint_sha256"}}
    execution_fp = sha256_payload(payload, decimals)
    final_fp = hashlib.sha256((phase8_freeze_fp + ":" + execution_fp).encode()).hexdigest()
    return execution_fp, final_fp


def validate_locked_freeze(root: Path, cfg: Phase9Config, p8b: dict, spec: dict, manifest8b: dict, manifest8: dict) -> dict:
    if p8b.get("status") != "PASS" or p8b.get("readiness") != "READY_TO_OPEN_FINAL_OOS_ONCE":
        raise RuntimeError("Phase 8B must PASS and be READY_TO_OPEN_FINAL_OOS_ONCE")
    if manifest8b.get("freeze_status") != "LOCKED_PRE_OOS_EXECUTION_PARITY":
        raise RuntimeError("Phase 8B is not execution-parity locked")
    if bool(manifest8b.get("final_oos_used")) or bool(spec.get("final_oos_used")):
        raise RuntimeError("Final OOS is already marked used before Phase 9")
    if str(manifest8b.get("final_freeze_fingerprint_sha256")) != cfg.expected_final_freeze_fingerprint_sha256:
        raise RuntimeError("Unexpected final freeze fingerprint; Phase 9 package is bound to the reviewed Phase 8B freeze")
    if str(spec.get("final_freeze_fingerprint_sha256")) != cfg.expected_final_freeze_fingerprint_sha256:
        raise RuntimeError("Execution model spec / expected final freeze mismatch")
    if pd.Timestamp(manifest8b.get("final_oos_start")).normalize() != cfg.final_oos_start:
        raise RuntimeError("Final OOS boundary mismatch")
    phase8_fp = str(manifest8b.get("phase8_freeze_fingerprint_sha256") or "")
    if phase8_fp != str(manifest8.get("freeze_fingerprint_sha256") or ""):
        raise RuntimeError("Phase 8 fingerprint referenced by Phase 8B no longer matches")
    execution_fp, final_fp = _recompute_execution_fingerprint(spec, phase8_fp, cfg.float_decimals)
    if execution_fp != str(manifest8b.get("execution_fingerprint_sha256") or ""):
        raise RuntimeError("Phase 8B execution fingerprint does not recompute")
    if final_fp != cfg.expected_final_freeze_fingerprint_sha256:
        raise RuntimeError("Phase 8B final freeze fingerprint does not recompute")

    source_mismatches = []
    for r in manifest8.get("source_manifest", []):
        rel = str(r.get("path") or "")
        expected = str(r.get("sha256") or "")
        path = root / rel
        if not path.exists():
            source_mismatches.append({"path": rel, "reason": "MISSING"})
            continue
        actual = _sha256_file(path)
        if actual != expected:
            source_mismatches.append({"path": rel, "reason": "SHA256_MISMATCH", "expected": expected, "actual": actual})
    if source_mismatches:
        raise RuntimeError(f"Frozen Phase 8 source manifest changed: {source_mismatches[:3]}")

    execution_source = root / "src" / "alpha_engine_v12" / "execution_parity.py"
    if _sha256_file(execution_source) != cfg.expected_execution_parity_source_sha256:
        raise RuntimeError("execution_parity.py differs from the source reviewed before final OOS")
    return {
        "final_freeze_fingerprint_sha256": final_fp,
        "execution_fingerprint_sha256": execution_fp,
        "phase8_source_manifest_files_verified": int(len(manifest8.get("source_manifest", []))),
        "execution_parity_source_sha256": cfg.expected_execution_parity_source_sha256,
    }


def _frozen_model(spec: dict) -> dict:
    frozen = spec.get("frozen_model_spec") or {}
    if not frozen or "model" not in frozen or "policy" not in frozen:
        raise RuntimeError("Phase 8B execution model spec is incomplete")
    return frozen


def model_features_and_weights(spec: dict) -> tuple[list[str], np.ndarray]:
    rows = _frozen_model(spec)["model"].get("feature_weights", [])
    features = [str(r["feature"]) for r in rows]
    weights = np.asarray([float(r["weight"]) for r in rows], dtype=float)
    if len(features) == 0 or len(features) != len(set(features)) or not np.isfinite(weights).all():
        raise RuntimeError("Frozen feature weights invalid")
    if abs(float(np.abs(weights).sum()) - 1.0) > 1e-6:
        raise RuntimeError("Frozen feature weights no longer sum to unit absolute mass")
    return features, weights


def rank_and_score(features: pd.DataFrame, feature_cols: list[str], weights: np.ndarray) -> pd.DataFrame:
    ranked = features[["date", "ticker"]].copy()
    for c in feature_cols:
        v = pd.to_numeric(features[c], errors="coerce")
        ranked[c] = v.groupby(features["date"], sort=False).rank(method="average", pct=True).astype("float32")
    x = ranked[feature_cols].to_numpy(float) - 0.5
    ok = np.isfinite(x)
    num = np.nansum(x * weights[None, :], axis=1)
    den = np.sum(ok * np.abs(weights)[None, :], axis=1)
    raw = np.where(den > 0, num / den, np.nan)
    out = ranked[["date", "ticker"]].rename(columns={"date": "signal_date"}).copy()
    out["model_score_raw"] = raw
    out["alpha_score"] = pd.Series(raw, index=out.index).groupby(out["signal_date"], sort=False).rank(method="average", pct=True)
    return out[np.isfinite(out["alpha_score"])].sort_values(["signal_date", "ticker"]).reset_index(drop=True)


def _load_feature_window(root: Path, cfg: Phase9Config, feature_cols: list[str], start: pd.Timestamp, end: pd.Timestamp | None) -> pd.DataFrame:
    f = pd.read_parquet(root / cfg.feature_library_path, columns=["date", "ticker", "feature_allowed", *feature_cols])
    f["date"] = _as_date(f["date"]); f["ticker"] = _norm_ticker(f["ticker"])
    mask = f["date"].ge(start)
    if end is not None:
        mask &= f["date"].lt(end)
    f = f.loc[mask].copy()
    if f.empty:
        raise RuntimeError(f"No feature rows in requested Phase 9 window starting {start.date()}")
    if not f["feature_allowed"].fillna(False).astype(bool).all():
        raise RuntimeError("Feature-forbidden row entered Phase 9")
    return f[["date", "ticker", *feature_cols]].sort_values(["date", "ticker"]).reset_index(drop=True)


def verify_frozen_score_fidelity(root: Path, cfg: Phase9Config, feature_cols: list[str], weights: np.ndarray) -> dict:
    f = _load_feature_window(root, cfg, feature_cols, cfg.score_fidelity_start, cfg.final_oos_start)
    regen = rank_and_score(f, feature_cols, weights)[["signal_date", "ticker", "alpha_score"]].rename(columns={"alpha_score": "regen"})
    stored = pd.read_parquet(root / cfg.phase8_pre_oos_scores_path, columns=["signal_date", "ticker", "alpha_score"])
    stored["signal_date"] = _as_date(stored["signal_date"]); stored["ticker"] = _norm_ticker(stored["ticker"])
    stored = stored[(stored["signal_date"] >= cfg.score_fidelity_start) & (stored["signal_date"] < cfg.final_oos_start)][["signal_date", "ticker", "alpha_score"]].rename(columns={"alpha_score": "stored"})
    m = regen.merge(stored, on=["signal_date", "ticker"], how="inner")
    x = pd.to_numeric(m["regen"], errors="coerce"); y = pd.to_numeric(m["stored"], errors="coerce")
    ok = np.isfinite(x) & np.isfinite(y)
    if int(ok.sum()) < 100:
        raise RuntimeError("Insufficient overlap to verify frozen score fidelity")
    corr = float(x[ok].corr(y[ok]))
    mad = float(np.mean(np.abs(x[ok] - y[ok])))
    return {"overlap_rows": int(ok.sum()), "correlation": corr, "mean_abs_diff": mad}


def generate_oos_scores(root: Path, cfg: Phase9Config, feature_cols: list[str], weights: np.ndarray) -> pd.DataFrame:
    f = _load_feature_window(root, cfg, feature_cols, cfg.final_oos_start, None)
    out = rank_and_score(f, feature_cols, weights)
    if out.empty or out["signal_date"].min() < cfg.final_oos_start:
        raise RuntimeError("Invalid final OOS score surface")
    out["partition"] = "FINAL_OOS_2025_PLUS"
    out["freeze_fingerprint_sha256"] = cfg.expected_final_freeze_fingerprint_sha256
    return out


def load_prices_and_terminals(root: Path, cfg: Phase9Config) -> tuple[pd.DataFrame, dict[str, pd.Timestamp]]:
    p = pd.read_parquet(root / cfg.return_price_layer_path, columns=["date", "ticker", "research_eligible", "target_total_return_price"])
    p["date"] = _as_date(p["date"]); p["ticker"] = _norm_ticker(p["ticker"])
    p["target_total_return_price"] = pd.to_numeric(p["target_total_return_price"], errors="coerce")
    p = p[(p["date"] >= cfg.carry_state_start) & p["research_eligible"].fillna(False).astype(bool) & (p["target_total_return_price"] > 0)].copy()
    if p.empty or p["date"].max() < cfg.final_oos_start:
        raise RuntimeError("No final OOS return-price observations")
    terminals: dict[str, pd.Timestamp] = {}
    ov = root / cfg.terminal_overlay_path
    if ov.exists():
        t = pd.read_csv(ov)
        if not t.empty:
            t["ticker"] = _norm_ticker(t["ticker"]); t["terminal_price_date"] = _as_date(t["terminal_price_date"])
            valid = t.get("overlay_validated", True)
            if not isinstance(valid, pd.Series):
                valid = pd.Series(True, index=t.index)
            if valid.dtype != bool:
                valid = valid.astype(str).str.lower().isin(["true", "1", "yes"])
            terminals = {str(r.ticker): pd.Timestamp(r.terminal_price_date) for r in t.loc[valid].itertuples() if pd.notna(r.terminal_price_date)}
    return p.sort_values(["date", "ticker"]).reset_index(drop=True), terminals


def _pre_oos_carry_scores(root: Path, cfg: Phase9Config) -> pd.DataFrame:
    s = pd.read_parquet(root / cfg.phase8_pre_oos_scores_path, columns=["signal_date", "ticker", "alpha_score"])
    s["signal_date"] = _as_date(s["signal_date"]); s["ticker"] = _norm_ticker(s["ticker"])
    s["alpha_score"] = pd.to_numeric(s["alpha_score"], errors="coerce")
    s = s[(s["signal_date"] >= cfg.carry_state_start) & (s["signal_date"] < cfg.final_oos_start) & np.isfinite(s["alpha_score"])].copy()
    if s.empty:
        raise RuntimeError("Missing pre-OOS frozen scores needed to carry portfolio state into final OOS")
    return s.sort_values(["signal_date", "ticker"]).reset_index(drop=True)


def _edge_spec(spec: dict) -> EdgeSpec:
    p = _frozen_model(spec)["policy"]
    return EdgeSpec(
        entry_floor=float(p["entry_floor"]), uncertainty_z=float(p["uncertainty_z"]),
        minimum_extra_edge_bps=float(p["minimum_extra_edge_bps"]), max_replacements=int(p["max_replacements_per_session"]),
    )


def _p7_proxy(spec: dict):
    pc = _frozen_model(spec)["portfolio_construction"]
    return type("FrozenPortfolioConstruction", (), {
        "milp_holdings": int(pc["milp_holdings"]),
        "optimizer_max_weight": float(pc["optimizer_max_weight"]),
        "milp_min_weight": float(pc["milp_min_weight"]),
        "milp_max_weight": float(pc["milp_max_weight"]),
        "milp_weight_step": float(pc["milp_weight_step"]),
    })()


def _oos_rebase(daily: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    x = daily[pd.to_datetime(daily["date"]).dt.normalize().ge(start)].copy().reset_index(drop=True)
    if x.empty:
        return x
    x["nav"] = (1.0 + pd.to_numeric(x["net_return"], errors="coerce").fillna(0.0)).cumprod()
    return x


def _metrics_with_execution(daily: pd.DataFrame, edges: pd.DataFrame, milp: pd.DataFrame, start: pd.Timestamp) -> dict:
    x = _oos_rebase(daily, start)
    met = _portfolio_metrics(x)
    attempts = int((x["turnover"] > 1e-12).sum() + x["execution_skipped"].sum()) if len(x) else 0
    met["execution_skip_rate"] = float(x["execution_skipped"].sum() / attempts) if attempts else 0.0
    e = edges[pd.to_datetime(edges.get("signal_date", pd.Series(dtype="datetime64[ns]")).astype("datetime64[ns]"), errors="coerce").dt.normalize().ge(start)] if len(edges) else edges
    m = milp[pd.to_datetime(milp.get("signal_date", pd.Series(dtype="datetime64[ns]")).astype("datetime64[ns]"), errors="coerce").dt.normalize().ge(start)] if len(milp) else milp
    met["edge_decisions"] = int(len(e)); met["edge_trades"] = int(e["trade"].sum()) if len(e) and "trade" in e else 0
    met["milp_calls"] = int(len(m)); met["milp_success_rate"] = float(m["success"].mean()) if len(m) else 0.0
    return met


def _frame_hash(df: pd.DataFrame, cols: list[str], decimals: int) -> str:
    if df.empty:
        return hashlib.sha256(b"").hexdigest()
    x = df[cols].copy()
    for c in cols:
        if pd.api.types.is_datetime64_any_dtype(x[c]):
            x[c] = pd.to_datetime(x[c]).dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_numeric_dtype(x[c]):
            x[c] = pd.to_numeric(x[c], errors="coerce").round(decimals)
    raw = x.to_csv(index=False, na_rep="NA", float_format=f"%.{decimals}f", lineterminator="\n").encode()
    return hashlib.sha256(raw).hexdigest()


def _optional_spy_benchmark(prices: pd.DataFrame, start: pd.Timestamp, end_exclusive: pd.Timestamp) -> dict | None:
    x = prices[(prices["ticker"] == "SPY") & (prices["date"] >= start) & (prices["date"] < end_exclusive)].sort_values("date")
    if len(x) < 2:
        return None
    px = pd.to_numeric(x["target_total_return_price"], errors="coerce")
    r = px.pct_change(fill_method=None).fillna(0.0)
    daily = pd.DataFrame({"date": x["date"].to_numpy(), "net_return": r.to_numpy()})
    daily["nav"] = (1.0 + daily["net_return"]).cumprod(); daily["turnover"] = 0.0; daily["cost_fraction"] = 0.0; daily["execution_skipped"] = 0
    return _portfolio_metrics(daily)


def _daily_ic(df: pd.DataFrame, score: str, target: str, min_cs: int = 20) -> tuple[int, float]:
    vals = []
    for _, g in df[["signal_date", score, target]].dropna().groupby("signal_date", sort=False):
        if len(g) < min_cs or g[score].nunique() < 2 or g[target].nunique() < 2:
            continue
        c = g[score].corr(g[target], method="pearson")
        if pd.notna(c) and np.isfinite(c):
            vals.append(float(c))
    return len(vals), float(np.mean(vals)) if vals else math.nan


def predictive_diagnostics(root: Path, cfg: Phase9Config, scores: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    horizons = [1, 5, 20, 60, 120, 252]
    cols = ["signal_date", "ticker"]
    for h in horizons:
        cols += [f"target_resolved_{h}d", f"fwd_return_{h}d", f"cs_rank_pct_{h}d"]
    t = pd.read_parquet(root / cfg.targets_path, columns=cols)
    t["signal_date"] = _as_date(t["signal_date"]); t["ticker"] = _norm_ticker(t["ticker"])
    t = t[t["signal_date"] >= cfg.final_oos_start].copy()
    s = scores[["signal_date", "ticker", "alpha_score"]].copy()
    merged = s.merge(t, on=["signal_date", "ticker"], how="left")
    rows = []
    for h in horizons:
        resolved = merged[f"target_resolved_{h}d"].fillna(False).astype(bool)
        z = merged[resolved].copy()
        z[f"fwd_return_{h}d"] = pd.to_numeric(z[f"fwd_return_{h}d"], errors="coerce")
        z[f"cs_rank_pct_{h}d"] = pd.to_numeric(z[f"cs_rank_pct_{h}d"], errors="coerce")
        n_dates, ic = _daily_ic(z, "alpha_score", f"cs_rank_pct_{h}d")
        top = z[z["alpha_score"] >= 0.90]
        rows.append({
            "horizon_sessions": h, "resolved_rows": int(len(z)), "rich_dates": int(n_dates),
            "mean_daily_rank_ic": ic,
            "top_decile_mean_return": float(top[f"fwd_return_{h}d"].mean()) if len(top) else math.nan,
            "all_mean_return": float(z[f"fwd_return_{h}d"].mean()) if len(z) else math.nan,
            "top_decile_minus_all": float(top[f"fwd_return_{h}d"].mean() - z[f"fwd_return_{h}d"].mean()) if len(top) and len(z) else math.nan,
        })
    return pd.DataFrame(rows), merged


def edge_realization(edges: pd.DataFrame, targets_merged: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if edges.empty:
        return pd.DataFrame(), {"resolved_edge_decisions_20d": 0}
    base = targets_merged[["signal_date", "ticker", "target_resolved_20d", "fwd_return_20d"]].copy()
    base["fwd_return_20d"] = pd.to_numeric(base["fwd_return_20d"], errors="coerce")
    cand = base.rename(columns={"ticker": "candidate_ticker", "target_resolved_20d": "candidate_resolved_20d", "fwd_return_20d": "candidate_realized_20d"})
    held = base.rename(columns={"ticker": "held_ticker", "target_resolved_20d": "held_resolved_20d", "fwd_return_20d": "held_realized_20d"})
    x = edges.merge(cand, on=["signal_date", "candidate_ticker"], how="left").merge(held, on=["signal_date", "held_ticker"], how="left")
    both = x["candidate_resolved_20d"].fillna(False).astype(bool) & x["held_resolved_20d"].fillna(False).astype(bool)
    x["realized_incremental_return_20d"] = np.where(both, x["candidate_realized_20d"] - x["held_realized_20d"], np.nan)
    r = x[both].copy(); trades = r[r["trade"].astype(bool)] if len(r) else r
    summary = {
        "resolved_edge_decisions_20d": int(len(r)),
        "resolved_trade_decisions_20d": int(len(trades)),
        "mean_realized_incremental_return_all_decisions": float(r["realized_incremental_return_20d"].mean()) if len(r) else math.nan,
        "mean_realized_incremental_return_trades": float(trades["realized_incremental_return_20d"].mean()) if len(trades) else math.nan,
        "trade_realized_positive_share": float((trades["realized_incremental_return_20d"] > 0).mean()) if len(trades) else math.nan,
    }
    return x, summary


def _acceptance_verdict(base: dict, stress: dict, cfg: Phase9Config) -> tuple[str, list[dict]]:
    rows = []
    def add(test, ok, value, rule):
        rows.append({"test": test, "status": "PASS" if ok else "FAIL", "value": value, "rule": rule})
    add("MINIMUM_OOS_SESSIONS", int(base.get("days", 0)) >= cfg.minimum_oos_sessions, base.get("days"), f">= {cfg.minimum_oos_sessions} OOS sessions")
    add("BASE_NET_CAGR_POSITIVE", (not cfg.require_positive_base_cagr) or float(base.get("cagr", -1)) > 0, base.get("cagr"), "frozen portfolio net CAGR > 0 at base costs")
    add("STRESS_NET_CAGR_POSITIVE", (not cfg.require_positive_stress_cagr) or float(stress.get("cagr", -1)) > 0, stress.get("cagr"), "frozen portfolio net CAGR > 0 at stress costs")
    add("BASE_MAX_DRAWDOWN", float(base.get("max_drawdown", -1)) >= -cfg.maximum_oos_drawdown, base.get("max_drawdown"), f"max drawdown >= -{cfg.maximum_oos_drawdown:.2f}")
    add("STRESS_MAX_DRAWDOWN", float(stress.get("max_drawdown", -1)) >= -cfg.maximum_oos_drawdown, stress.get("max_drawdown"), f"stress max drawdown >= -{cfg.maximum_oos_drawdown:.2f}")
    ok = all(r["status"] == "PASS" for r in rows)
    return ("PASS_FOR_SHADOW_FORWARD" if ok else "FAIL_FINAL_OOS_DO_NOT_TUNE_ON_THIS_HOLDOUT"), rows


def build_phase9(root: Path) -> dict:
    cfg = load_config(root); out = root / "outputs"; out.mkdir(parents=True, exist_ok=True)
    receipt_path = root / cfg.receipt_path
    if receipt_path.exists():
        raise RuntimeError("FINAL_OOS_ALREADY_CONSUMED: Phase 9 receipt exists. Do not rerun/tune on the same holdout.")

    with (root / cfg.phase8b_summary_path).open("r", encoding="utf-8") as f: p8b = json.load(f)
    with (root / cfg.phase8b_execution_model_spec_path).open("r", encoding="utf-8") as f: spec = json.load(f)
    with (root / cfg.phase8b_freeze_manifest_path).open("r", encoding="utf-8") as f: manifest8b = json.load(f)
    with (root / cfg.phase8_freeze_manifest_path).open("r", encoding="utf-8") as f: manifest8 = json.load(f)
    freeze_validation = validate_locked_freeze(root, cfg, p8b, spec, manifest8b, manifest8)

    feature_cols, weights = model_features_and_weights(spec)
    fidelity = verify_frozen_score_fidelity(root, cfg, feature_cols, weights)
    if not np.isfinite(fidelity["correlation"]) or fidelity["correlation"] < cfg.minimum_score_fidelity_correlation:
        raise RuntimeError(f"Frozen scorer fidelity failed before OOS: {fidelity}")

    # This call is the one-time opening of the holdout score surface.
    oos_scores = generate_oos_scores(root, cfg, feature_cols, weights)
    prices, terminals = load_prices_and_terminals(root, cfg)
    max_price_date = pd.Timestamp(prices["date"].max()).normalize()
    end_exclusive = max_price_date + pd.Timedelta(days=1)
    if oos_scores["signal_date"].max() > max_price_date:
        oos_scores = oos_scores[oos_scores["signal_date"] <= max_price_date].copy()

    carry = _pre_oos_carry_scores(root, cfg)
    combined = pd.concat([carry, oos_scores[["signal_date", "ticker", "alpha_score"]]], ignore_index=True).sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    calibration = calibration_from_spec(_frozen_model(spec))
    edge = _edge_spec(spec); p7cfg = _p7_proxy(spec); policy = _frozen_model(spec)["policy"]
    top_n = int(policy["top_n"])

    base_full, nav1, edges1, milp1 = simulate_execution_parity(
        combined, prices, terminals, calibration, edge, cfg.carry_state_start, end_exclusive, top_n,
        float(policy["base_round_trip_cost_bps"]), p7cfg,
    )
    _, nav2, edges2, milp2 = simulate_execution_parity(
        combined, prices, terminals, calibration, edge, cfg.carry_state_start, end_exclusive, top_n,
        float(policy["base_round_trip_cost_bps"]), p7cfg,
    )
    _, nav_stress, edges_stress, milp_stress = simulate_execution_parity(
        combined, prices, terminals, calibration, edge, cfg.carry_state_start, end_exclusive, top_n,
        float(policy["stress_round_trip_cost_bps"]), p7cfg,
    )

    nav_cols = ["date","nav","net_return","turnover","cost_fraction","execution_skipped","holdings","cash_weight"]
    edge_cols = ["signal_date","held_ticker","candidate_ticker","net_edge","trade"] if len(edges1) else []
    milp_cols = ["signal_date","success","members_before","members_after","membership_changes"] if len(milp1) else []
    hashes1 = {
        "nav": _frame_hash(nav1, nav_cols, cfg.float_decimals),
        "edges": _frame_hash(edges1, edge_cols, cfg.float_decimals) if edge_cols else hashlib.sha256(b"").hexdigest(),
        "milp": _frame_hash(milp1, milp_cols, cfg.float_decimals) if milp_cols else hashlib.sha256(b"").hexdigest(),
    }
    hashes2 = {
        "nav": _frame_hash(nav2, nav_cols, cfg.float_decimals),
        "edges": _frame_hash(edges2, edge_cols, cfg.float_decimals) if edge_cols else hashlib.sha256(b"").hexdigest(),
        "milp": _frame_hash(milp2, milp_cols, cfg.float_decimals) if milp_cols else hashlib.sha256(b"").hexdigest(),
    }
    deterministic = hashes1 == hashes2

    base = _metrics_with_execution(nav1, edges1, milp1, cfg.final_oos_start)
    stress = _metrics_with_execution(nav_stress, edges_stress, milp_stress, cfg.final_oos_start)
    benchmark_spy = _optional_spy_benchmark(prices, cfg.final_oos_start, end_exclusive)
    predictive, target_merged = predictive_diagnostics(root, cfg, oos_scores)
    edge_realized, edge_realized_summary = edge_realization(edges1[edges1["signal_date"] >= cfg.final_oos_start].copy() if len(edges1) else edges1, target_merged)
    verdict, acceptance_rows = _acceptance_verdict(base, stress, cfg)

    integrity_rows = []
    def add(test, ok, value, rule, blocking=True):
        integrity_rows.append({"test": test, "status": "PASS" if ok else "FAIL", "blocking": bool(blocking), "value": value, "rule": rule})
    add("FINAL_FREEZE_FINGERPRINT", freeze_validation["final_freeze_fingerprint_sha256"] == cfg.expected_final_freeze_fingerprint_sha256, freeze_validation["final_freeze_fingerprint_sha256"], "must equal reviewed Phase 8B final freeze")
    add("FROZEN_SOURCE_MANIFEST", freeze_validation["phase8_source_manifest_files_verified"] > 0, freeze_validation["phase8_source_manifest_files_verified"], "all Phase 8 frozen source hashes must match")
    add("FROZEN_SCORER_FIDELITY", fidelity["correlation"] >= cfg.minimum_score_fidelity_correlation, fidelity["correlation"], f"pre-OOS regenerated score correlation >= {cfg.minimum_score_fidelity_correlation}")
    add("FINAL_OOS_SCORE_BOUNDARY", oos_scores["signal_date"].min() >= cfg.final_oos_start, str(oos_scores["signal_date"].min().date()), "all newly generated scores are 2025+")
    add("DETERMINISTIC_FINAL_OOS_REPLAY", deterministic, hashes1, "two internal frozen OOS runs must produce identical NAV/edge/MILP hashes")
    milp_calls = int(base.get("milp_calls", 0) or 0)
    milp_rate = float(base.get("milp_success_rate", 0) or 0)
    milp_ok = (milp_calls == 0) or (milp_rate >= cfg.require_milp_success_rate)
    add("FINAL_OOS_MILP_SUCCESS", milp_ok, {"calls": milp_calls, "success_rate": milp_rate}, f"if MILP is called, success rate >= {cfg.require_milp_success_rate:.3f}; zero calls is valid HOLD behavior")
    add("FINAL_OOS_EXECUTION_SKIP_RATE", float(base.get("execution_skip_rate", 1)) <= cfg.maximum_execution_skip_rate, base.get("execution_skip_rate"), f"<= {cfg.maximum_execution_skip_rate:.3f}")
    gate = pd.DataFrame(integrity_rows)
    status = "PASS" if not (gate["blocking"].astype(bool) & gate["status"].eq("FAIL")).any() else "FAIL"
    readiness = "READY_FOR_SHADOW_FORWARD" if status == "PASS" and verdict == "PASS_FOR_SHADOW_FORWARD" else "DO_NOT_DEPLOY_FROZEN_OOS_RESULT_RETAINED"

    oos_nav = _oos_rebase(nav1, cfg.final_oos_start); oos_nav_stress = _oos_rebase(nav_stress, cfg.final_oos_start)
    oos_edges = edges1[edges1["signal_date"] >= cfg.final_oos_start].copy() if len(edges1) else edges1
    oos_milp = milp1[milp1["signal_date"] >= cfg.final_oos_start].copy() if len(milp1) else milp1
    oos_scores.to_parquet(out / "phase9_oos_scores.parquet", index=False)
    oos_nav.to_csv(out / "phase9_oos_nav_base.csv", index=False)
    oos_nav_stress.to_csv(out / "phase9_oos_nav_stress.csv", index=False)
    oos_edges.to_csv(out / "phase9_oos_edge_decisions.csv", index=False)
    oos_milp.to_csv(out / "phase9_oos_milp_audit.csv", index=False)
    predictive.to_csv(out / "phase9_predictive_diagnostics.csv", index=False)
    edge_realized.to_csv(out / "phase9_edge_realization_20d.csv", index=False)
    gate.to_csv(out / "phase9_gate.csv", index=False)
    pd.DataFrame(acceptance_rows).to_csv(out / "phase9_acceptance_gate.csv", index=False)
    pd.DataFrame([
        {"cost_bps": float(policy["base_round_trip_cost_bps"]), **base},
        {"cost_bps": float(policy["stress_round_trip_cost_bps"]), **stress},
    ]).to_csv(out / "phase9_performance_summary.csv", index=False)

    summary = {
        "status": status,
        "phase": 9,
        "build": PHASE9_BUILD,
        "name": cfg.name,
        "objective": cfg.objective,
        "one_shot_contract": {
            "final_freeze_fingerprint_sha256": cfg.expected_final_freeze_fingerprint_sha256,
            "final_oos_start": str(cfg.final_oos_start.date()),
            "parameter_tuning_after_open": False,
            "reselection_after_open": False,
            "carry_in_state_reconstructed_from": f"{cfg.carry_state_start.date()} through 2024-12-31 frozen scores",
        },
        "oos_window": {
            "first_score_date": str(pd.Timestamp(oos_scores["signal_date"].min()).date()),
            "last_score_date": str(pd.Timestamp(oos_scores["signal_date"].max()).date()),
            "last_price_date": str(max_price_date.date()),
            "score_rows": int(len(oos_scores)),
            "tickers": int(oos_scores["ticker"].nunique()),
        },
        "score_fidelity": fidelity,
        "base_cost_performance": base,
        "stress_cost_performance": stress,
        "spy_benchmark_diagnostic": benchmark_spy,
        "edge_realization_20d": edge_realized_summary,
        "oos_verdict": verdict,
        "acceptance_gate": acceptance_rows,
        "determinism": {"identical": deterministic, "hashes": hashes1},
        "integrity_gate": integrity_rows,
        "readiness": readiness,
        "warning": "Final OOS is now consumed. These 2025+ results may never be used to retune and then relabeled as out-of-sample.",
        "next_gate": "If READY_FOR_SHADOW_FORWARD: connect the frozen model to live PIT ingestion and run shadow forward/champion monitoring without changing the frozen historical OOS result.",
    }
    (out / "phase9_summary.json").write_text(json.dumps(canonicalize(summary, cfg.float_decimals), indent=2), encoding="utf-8")

    receipt = {
        "status": "CONSUMED",
        "phase": 9,
        "build": PHASE9_BUILD,
        "consumed_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_freeze_fingerprint_sha256": cfg.expected_final_freeze_fingerprint_sha256,
        "final_oos_start": str(cfg.final_oos_start.date()),
        "final_oos_last_observation": str(max_price_date.date()),
        "oos_verdict": verdict,
        "summary_sha256": _sha256_file(out / "phase9_summary.json"),
        "tuning_permitted_after_consumption": False,
        "rerun_permitted": False,
    }
    receipt_path.write_text(json.dumps(canonicalize(receipt, cfg.float_decimals), indent=2), encoding="utf-8")
    return summary
