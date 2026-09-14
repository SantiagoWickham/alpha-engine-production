from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.stats import kendalltau, spearmanr
from sklearn.isotonic import IsotonicRegression

from alpha_engine_v12.portfolio_policy import (
    _as_date,
    _norm_ticker,
    _portfolio_metrics,
    load_price_surface,
    simulate_policy,
)

PHASE7_BUILD = "V1_EDGE_LINEAGE_2026-09-12"


@dataclass(frozen=True)
class EdgeSpec:
    entry_floor: float
    uncertainty_z: float
    minimum_extra_edge_bps: float
    max_replacements: int


@dataclass(frozen=True)
class Phase7Config:
    name: str
    objective: str
    phase6_summary_path: str
    phase6_champion_spec_path: str
    phase6_policy_scores_path: str
    phase3_targets_path: str
    return_price_layer_path: str
    terminal_overlay_path: str
    final_oos_start: pd.Timestamp
    selection_start: pd.Timestamp
    validation_start: pd.Timestamp
    base_round_trip_bps: float
    stress_round_trip_bps: float
    calibration_bins: int
    hac_lag: int
    top_n: int
    max_allowed_drawdown: float
    max_execution_skip_rate: float
    selection_entry_floors: tuple[float, ...]
    selection_uncertainty_z: tuple[float, ...]
    selection_extra_edge_bps: tuple[float, ...]
    selection_max_replacements: tuple[int, ...]
    lineage_candidate_count: int
    lineage_reference_top_n: int
    optimizer_max_weight: float
    milp_min_weight: float
    milp_max_weight: float
    milp_weight_step: float
    milp_holdings: int
    lineage_min_spearman: float
    lineage_min_kendall: float
    lineage_min_top10_capture: float
    lineage_min_alpha_capture: float
    lineage_max_optimizer_milp_l1: float


@dataclass(frozen=True)
class PreparedMarket:
    calendar: pd.DatetimeIndex
    presence: pd.DataFrame
    returns: pd.DataFrame


def load_config(root: Path) -> Phase7Config:
    with (root / "config" / "phase7.toml").open("rb") as f:
        raw = tomllib.load(f)["phase7"]
    p = raw["partitions"]
    s = raw["selection_grid"]
    l = raw["lineage"]
    return Phase7Config(
        name=str(raw["name"]),
        objective=str(raw["objective"]),
        phase6_summary_path=str(raw["phase6_summary_path"]),
        phase6_champion_spec_path=str(raw["phase6_champion_spec_path"]),
        phase6_policy_scores_path=str(raw["phase6_policy_scores_path"]),
        phase3_targets_path=str(raw["phase3_targets_path"]),
        return_price_layer_path=str(raw["return_price_layer_path"]),
        terminal_overlay_path=str(raw["terminal_overlay_path"]),
        final_oos_start=pd.Timestamp(p["final_oos_start"]).normalize(),
        selection_start=pd.Timestamp(p["selection_start"]).normalize(),
        validation_start=pd.Timestamp(p["validation_start"]).normalize(),
        base_round_trip_bps=float(raw["costs"]["base_round_trip_bps"]),
        stress_round_trip_bps=float(raw["costs"]["stress_round_trip_bps"]),
        calibration_bins=int(raw["calibration"]["bins"]),
        hac_lag=int(raw["calibration"]["hac_lag"]),
        top_n=int(raw["policy"]["top_n"]),
        max_allowed_drawdown=float(raw["policy"]["max_allowed_drawdown"]),
        max_execution_skip_rate=float(raw["policy"]["max_execution_skip_rate"]),
        selection_entry_floors=tuple(float(x) for x in s["entry_floors"]),
        selection_uncertainty_z=tuple(float(x) for x in s["uncertainty_z"]),
        selection_extra_edge_bps=tuple(float(x) for x in s["minimum_extra_edge_bps"]),
        selection_max_replacements=tuple(int(x) for x in s["max_replacements"]),
        lineage_candidate_count=int(l["candidate_count"]),
        lineage_reference_top_n=int(l["reference_top_n"]),
        optimizer_max_weight=float(l["optimizer_max_weight"]),
        milp_min_weight=float(l["milp_min_weight"]),
        milp_max_weight=float(l["milp_max_weight"]),
        milp_weight_step=float(l["milp_weight_step"]),
        milp_holdings=int(l["milp_holdings"]),
        lineage_min_spearman=float(l["minimum_spearman"]),
        lineage_min_kendall=float(l["minimum_kendall"]),
        lineage_min_top10_capture=float(l["minimum_top10_capture"]),
        lineage_min_alpha_capture=float(l["minimum_alpha_capture"]),
        lineage_max_optimizer_milp_l1=float(l["maximum_optimizer_milp_l1"]),
    )


def validate_phase6(summary: dict, spec: dict, cfg: Phase7Config) -> None:
    if summary.get("status") != "PASS":
        raise RuntimeError("Phase 6 must PASS before Phase 7")
    if summary.get("policy_readiness") != "READY_FOR_EXPECTED_EDGE_CALIBRATION":
        raise RuntimeError("Phase 6 is not READY_FOR_EXPECTED_EDGE_CALIBRATION")
    sc = summary.get("selection_contract") or {}
    if sc.get("final_oos_used") is not False:
        raise RuntimeError("Phase 6 final OOS firewall is not intact")
    if pd.Timestamp(sc.get("final_oos_start")).normalize() != cfg.final_oos_start:
        raise RuntimeError("Phase 6 / Phase 7 final OOS boundary mismatch")
    champ = (spec.get("research_champion") or {})
    if str(champ.get("ensemble")) != "H20":
        raise RuntimeError("Phase 7 V1 is calibrated for the Phase 6 H20 research champion")
    if int(champ.get("top_n", -1)) != cfg.top_n:
        raise RuntimeError("Phase 6 / Phase 7 top_n mismatch")


def load_h20_scores(root: Path, cfg: Phase7Config) -> pd.DataFrame:
    p = pd.read_parquet(
        root / cfg.phase6_policy_scores_path,
        columns=["signal_date", "ticker", "horizon_sessions", "partition", "score_rank_pct"],
    )
    p["signal_date"] = _as_date(p["signal_date"])
    p["ticker"] = _norm_ticker(p["ticker"])
    p["horizon_sessions"] = pd.to_numeric(p["horizon_sessions"], errors="raise").astype(int)
    p["alpha_score"] = pd.to_numeric(p["score_rank_pct"], errors="coerce")
    p = p[(p["horizon_sessions"] == 20) & (p["signal_date"] < cfg.final_oos_start)].copy()
    p = p[np.isfinite(p["alpha_score"])].copy()
    if p.empty:
        raise RuntimeError("No pre-OOS H20 score surface found")
    return p[["signal_date", "ticker", "partition", "alpha_score"]].sort_values(["signal_date", "ticker"]).reset_index(drop=True)


def load_20d_targets(root: Path, cfg: Phase7Config) -> pd.DataFrame:
    cols = ["signal_date", "ticker", "target_end_date_20d", "target_resolved_20d", "fwd_return_20d"]
    t = pd.read_parquet(root / cfg.phase3_targets_path, columns=cols)
    t["signal_date"] = _as_date(t["signal_date"])
    t["ticker"] = _norm_ticker(t["ticker"])
    t["target_end_date_20d"] = _as_date(t["target_end_date_20d"])
    t["fwd_return_20d"] = pd.to_numeric(t["fwd_return_20d"], errors="coerce")
    t = t[t["target_resolved_20d"].fillna(False).astype(bool) & np.isfinite(t["fwd_return_20d"])].copy()
    return t


def _hac_mean_se(x: Iterable[float], lag: int) -> tuple[float, float]:
    a = np.asarray([float(v) for v in x if np.isfinite(v)], dtype=float)
    n = len(a)
    if n == 0:
        return math.nan, math.nan
    mu = float(a.mean())
    if n < 3:
        return mu, math.nan
    z = a - mu
    gamma0 = float(np.dot(z, z) / n)
    lrv = gamma0
    L = min(int(lag), n - 1)
    for k in range(1, L + 1):
        g = float(np.dot(z[k:], z[:-k]) / n)
        w = 1.0 - k / (L + 1.0)
        lrv += 2.0 * w * g
    return mu, float(math.sqrt(max(lrv, 0.0) / n))


def fit_edge_calibration(
    scores: pd.DataFrame,
    targets: pd.DataFrame,
    partitions: Iterable[str],
    target_end_before: pd.Timestamp,
    bins: int,
    hac_lag: int,
) -> pd.DataFrame:
    x = scores[scores["partition"].isin(list(partitions))].merge(targets, on=["signal_date", "ticker"], how="inner")
    x = x[x["target_end_date_20d"] < pd.Timestamp(target_end_before).normalize()].copy()
    if x.empty:
        raise RuntimeError("No rows available for expected-edge calibration")
    b = np.minimum((pd.to_numeric(x["alpha_score"], errors="coerce").clip(0, 1) * bins).astype(int), bins - 1)
    x["score_bin"] = b
    daily = x.groupby(["signal_date", "score_bin"], observed=True)["fwd_return_20d"].mean().reset_index()
    rows = []
    for k in range(bins):
        d = daily[daily["score_bin"] == k]
        raw_mean, se = _hac_mean_se(d["fwd_return_20d"], hac_lag)
        obs = x[x["score_bin"] == k]
        rows.append({
            "score_bin": k,
            "score_lo": k / bins,
            "score_hi": (k + 1) / bins,
            "score_center": (k + 0.5) / bins,
            "raw_expected_return_20d": raw_mean,
            "hac_se_expected_mean": se,
            "rich_dates": int(d["signal_date"].nunique()),
            "observations": int(len(obs)),
        })
    out = pd.DataFrame(rows)
    valid = np.isfinite(out["raw_expected_return_20d"])
    if valid.sum() < max(5, bins // 4):
        raise RuntimeError("Too few score bins for isotonic expected-return calibration")
    fitx = out.loc[valid, "score_center"].to_numpy(float)
    fity = out.loc[valid, "raw_expected_return_20d"].to_numpy(float)
    weights = np.maximum(out.loc[valid, "rich_dates"].to_numpy(float), 1.0)
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
    iso.fit(fitx, fity, sample_weight=weights)
    out["isotonic_expected_return_20d"] = iso.predict(out["score_center"].to_numpy(float))
    se = pd.to_numeric(out["hac_se_expected_mean"], errors="coerce")
    if se.notna().any():
        se = se.interpolate(limit_direction="both").fillna(float(se.dropna().median()))
    else:
        se = pd.Series(np.full(len(out), 0.01), index=out.index)
    out["hac_se_expected_mean"] = se.clip(lower=1e-6)
    out["calibration_rows"] = int(len(x))
    out["calibration_first_signal"] = str(x["signal_date"].min().date())
    out["calibration_last_signal"] = str(x["signal_date"].max().date())
    out["target_end_before"] = str(pd.Timestamp(target_end_before).date())
    return out


def expected_return_and_se(score: float, calib: pd.DataFrame) -> tuple[float, float]:
    if not np.isfinite(score):
        return math.nan, math.nan
    x = float(np.clip(score, 0.0, 1.0))
    centers = calib["score_center"].to_numpy(float)
    mu = float(np.interp(x, centers, calib["isotonic_expected_return_20d"].to_numpy(float)))
    se = float(np.interp(x, centers, calib["hac_se_expected_mean"].to_numpy(float)))
    return mu, max(se, 1e-6)


def _score_maps(scores: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[pd.Timestamp, dict[str, float]]:
    x = scores[(scores["signal_date"] >= start) & (scores["signal_date"] < end)].copy()
    return {
        pd.Timestamp(d): dict(zip(g["ticker"].astype(str), pd.to_numeric(g["alpha_score"], errors="coerce")))
        for d, g in x.groupby("signal_date", sort=False)
    }


def _top_equal(score_map: dict[str, float], n: int, floor: float) -> dict[str, float]:
    ranked = [(t, float(s)) for t, s in score_map.items() if np.isfinite(s) and float(s) >= floor]
    ranked.sort(key=lambda z: (-z[1], z[0]))
    chosen = [t for t, _ in ranked[:n]]
    if not chosen:
        return {}
    w = 1.0 / len(chosen)
    return {t: w for t in chosen}


def net_edge_target(
    current: dict[str, float],
    cash: float,
    score_map: dict[str, float],
    calib: pd.DataFrame,
    spec: EdgeSpec,
    top_n: int,
    round_trip_bps: float,
) -> tuple[dict[str, float], list[dict]]:
    holdings = {t: float(w) for t, w in current.items() if w > 1e-12}
    diagnostics: list[dict] = []
    if not holdings:
        return _top_equal(score_map, top_n, spec.entry_floor), diagnostics
    target = dict(holdings)
    outsiders = [(t, float(s)) for t, s in score_map.items() if t not in target and np.isfinite(s) and float(s) >= spec.entry_floor]
    outsiders.sort(key=lambda z: (-z[1], z[0]))

    slots = max(0, top_n - len(target))
    if slots and cash > 1e-12 and outsiders:
        fill = outsiders[:slots]
        alloc = float(cash) / len(fill)
        for t, _ in fill:
            target[t] = alloc
        outsiders = outsiders[len(fill):]

    replaced = 0
    rt_cost = float(round_trip_bps) / 10000.0
    extra = float(spec.minimum_extra_edge_bps) / 10000.0
    while replaced < spec.max_replacements and outsiders and target:
        held = []
        for t in target:
            s = score_map.get(t, math.nan)
            mu, se = expected_return_and_se(s, calib)
            held.append((t, s, mu, se))
        finite_held = [z for z in held if np.isfinite(z[2])]
        if not finite_held:
            break
        weak = min(finite_held, key=lambda z: (z[2], z[1] if np.isfinite(z[1]) else -1.0, z[0]))
        cand_t, cand_s = outsiders[0]
        cand_mu, cand_se = expected_return_and_se(cand_s, calib)
        weak_t, weak_s, weak_mu, weak_se = weak
        uncertainty = float(spec.uncertainty_z) * math.sqrt(cand_se**2 + weak_se**2)
        net_edge = cand_mu - weak_mu - rt_cost - uncertainty - extra
        diagnostics.append({
            "held_ticker": weak_t,
            "candidate_ticker": cand_t,
            "held_score": weak_s,
            "candidate_score": cand_s,
            "held_expected_return": weak_mu,
            "candidate_expected_return": cand_mu,
            "expected_incremental_return": cand_mu - weak_mu,
            "estimated_total_cost": rt_cost,
            "uncertainty_buffer": uncertainty + extra,
            "net_edge": net_edge,
            "trade": bool(net_edge > 0),
        })
        if not (net_edge > 0):
            break
        w = target.pop(weak_t)
        target[cand_t] = w
        outsiders.pop(0)
        replaced += 1
    return target, diagnostics


def prepare_market(prices: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> PreparedMarket:
    start = pd.Timestamp(start).normalize(); end = pd.Timestamp(end).normalize()
    px = prices[(prices["date"] >= start) & (prices["date"] < end)].copy()
    if px.empty:
        return PreparedMarket(pd.DatetimeIndex([]), pd.DataFrame(), pd.DataFrame())
    calendar = pd.DatetimeIndex(sorted(px["date"].dropna().unique()))
    raw = px.pivot_table(index="date", columns="ticker", values="target_total_return_price", aggfunc="last").reindex(calendar)
    presence = raw.notna(); ff = raw.ffill()
    rets = ff.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return PreparedMarket(calendar, presence, rets)


def simulate_edge_policy(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    terminals: dict[str, pd.Timestamp],
    calib: pd.DataFrame,
    spec: EdgeSpec,
    start: pd.Timestamp,
    end: pd.Timestamp,
    top_n: int,
    round_trip_bps: float,
    prepared_market: PreparedMarket | None = None,
) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    start = pd.Timestamp(start).normalize(); end = pd.Timestamp(end).normalize()
    by_date = _score_maps(scores, start, end)
    market = prepared_market if prepared_market is not None else prepare_market(prices, start, end)
    if len(market.calendar) == 0 or not by_date:
        return _portfolio_metrics(pd.DataFrame()), pd.DataFrame(), pd.DataFrame()
    calendar = market.calendar; presence = market.presence; rets = market.returns

    weights: dict[str, float] = {}; cash = 1.0; nav = 1.0; pending: dict[str, float] | None = None
    rows = []; edge_rows = []
    one_way_rate = float(round_trip_bps) / 2.0 / 10000.0
    for d in calendar:
        d = pd.Timestamp(d); prev_nav = nav
        gross = 0.0
        if weights:
            rr = rets.loc[d]
            gross = float(sum(w * (float(rr.get(t, 0.0)) if np.isfinite(rr.get(t, np.nan)) else 0.0) for t, w in weights.items()))
        nav *= max(0.0, 1.0 + gross)
        if weights:
            vals = {t: w * (1.0 + (float(rets.at[d, t]) if t in rets.columns and np.isfinite(rets.at[d, t]) else 0.0)) for t, w in weights.items()}
            total = cash + sum(vals.values())
            if total > 0:
                weights = {t: v / total for t, v in vals.items() if v > 1e-14}; cash = cash / total

        turnover = 0.0; cost_fraction = 0.0; skipped = False
        if pending is not None:
            current = dict(weights)
            trade_names = {t for t in set(current) | set(pending) if abs(float(pending.get(t, 0.0)) - float(current.get(t, 0.0))) > 1e-10}
            executable = all((t in presence.columns and bool(presence.at[d, t])) for t in trade_names)
            if executable:
                traded = float(sum(abs(float(pending.get(t, 0.0)) - float(current.get(t, 0.0))) for t in trade_names))
                turnover = 0.5 * traded; cost_fraction = one_way_rate * traded
                nav *= max(0.0, 1.0 - cost_fraction)
                weights = {t: float(w) for t, w in pending.items() if w > 1e-12}; cash = max(0.0, 1.0 - sum(weights.values()))
            else:
                skipped = True
            pending = None

        for t in [t for t in list(weights) if terminals.get(t) == d]:
            cash += weights.pop(t)

        sm = by_date.get(d)
        if sm:
            target, diags = net_edge_target(weights, cash, sm, calib, spec, top_n, round_trip_bps)
            for z in diags:
                edge_rows.append({"signal_date": d, **z})
            delta = sum(abs(float(target.get(t, 0.0)) - float(weights.get(t, 0.0))) for t in set(target) | set(weights))
            if delta > 1e-10:
                pending = target

        rows.append({
            "date": d,
            "nav": nav,
            "net_return": nav / prev_nav - 1.0 if prev_nav > 0 else -1.0,
            "gross_return": gross,
            "turnover": turnover,
            "cost_fraction": cost_fraction,
            "execution_skipped": int(skipped),
            "holdings": len(weights),
            "cash_weight": cash,
        })
    daily = pd.DataFrame(rows); edges = pd.DataFrame(edge_rows)
    met = _portfolio_metrics(daily)
    attempts = int((daily["turnover"] > 1e-12).sum() + daily["execution_skipped"].sum()) if len(daily) else 0
    met["execution_skip_rate"] = float(daily["execution_skipped"].sum() / attempts) if attempts else 0.0
    met["edge_decisions"] = int(len(edges)); met["edge_trades"] = int(edges["trade"].sum()) if len(edges) else 0
    return met, daily, edges


def _edge_grid(cfg: Phase7Config) -> pd.DataFrame:
    rows = []
    for f in cfg.selection_entry_floors:
        for z in cfg.selection_uncertainty_z:
            for e in cfg.selection_extra_edge_bps:
                for r in cfg.selection_max_replacements:
                    rows.append({"entry_floor": f, "uncertainty_z": z, "minimum_extra_edge_bps": e, "max_replacements": r})
    return pd.DataFrame(rows)


def select_edge_policy(results: pd.DataFrame) -> pd.DataFrame:
    x = results.copy(); x["return_first_rank"] = np.nan
    q = x[x["qualified"]].sort_values(
        ["selection_cagr_20bps", "selection_cagr_40bps", "selection_max_drawdown_20bps", "selection_annual_turnover_20bps"],
        ascending=[False, False, False, True],
    )
    x.loc[q.index, "return_first_rank"] = np.arange(1, len(q) + 1)
    nq = x[~x["qualified"]].sort_values("selection_cagr_20bps", ascending=False)
    x.loc[nq.index, "return_first_rank"] = np.arange(len(q) + 1, len(q) + len(nq) + 1)
    return x.sort_values("return_first_rank").reset_index(drop=True)


def _cap_weights(w: dict[str, float], max_weight: float) -> dict[str, float]:
    x = {k: max(0.0, float(v)) for k, v in w.items() if v > 0}
    if not x:
        return {}
    s = sum(x.values()); x = {k: v / s for k, v in x.items()}
    for _ in range(100):
        over = [k for k, v in x.items() if v > max_weight + 1e-12]
        if not over:
            break
        fixed = {k: max_weight for k in over}
        rem_names = [k for k in x if k not in over]
        rem_mass = 1.0 - sum(fixed.values())
        if rem_mass < -1e-10 or not rem_names:
            break
        rem_old = sum(x[k] for k in rem_names)
        x = {**fixed, **{k: (rem_mass * x[k] / rem_old if rem_old > 0 else rem_mass / len(rem_names)) for k in rem_names}}
    s = sum(x.values())
    return {k: v / s for k, v in x.items()} if s > 0 else {}


def build_lineage_layers(score_map: dict[str, float], calib: pd.DataFrame, cfg: Phase7Config, uncertainty_z: float) -> tuple[pd.DataFrame, dict[str, float]]:
    ranked = [(t, float(s)) for t, s in score_map.items() if np.isfinite(s)]
    ranked.sort(key=lambda z: (-z[1], z[0]))
    ranked = ranked[: cfg.lineage_candidate_count]
    if len(ranked) < cfg.lineage_reference_top_n:
        return pd.DataFrame(), {}
    names = [t for t, _ in ranked]; alpha = {t: s for t, s in ranked}
    ref_names = names[: cfg.lineage_reference_top_n]
    reference = {t: (1.0 / len(ref_names) if t in ref_names else 0.0) for t in names}

    lcb = {}
    for t in names:
        mu, se = expected_return_and_se(alpha[t], calib)
        lcb[t] = mu - float(uncertainty_z) * se
    arr = np.asarray([lcb[t] for t in names], dtype=float)
    scale = float(np.nanstd(arr))
    if not np.isfinite(scale) or scale < 1e-8:
        scale = 1.0
    med = float(np.nanmedian(arr))
    util = np.exp(np.clip((arr - med) / scale, -2.0, 2.0))
    theoretical = {t: float(u / util.sum()) for t, u in zip(names, util)}
    optimizer = _cap_weights(theoretical, cfg.optimizer_max_weight)
    return pd.DataFrame({
        "ticker": names,
        "alpha_score": [alpha[t] for t in names],
        "expected_return_lcb": [lcb[t] for t in names],
        "reference_weight": [reference[t] for t in names],
        "theoretical_weight": [theoretical[t] for t in names],
        "optimizer_weight": [optimizer.get(t, 0.0) for t in names],
    }), optimizer


def solve_weight_milp(layer: pd.DataFrame, current_weights: dict[str, float], cfg: Phase7Config) -> tuple[dict[str, float], dict]:
    if layer.empty:
        return {}, {"success": False, "message": "EMPTY_LAYER"}
    names = layer["ticker"].astype(str).tolist(); n = len(names)
    step = cfg.milp_weight_step
    total_units = int(round(1.0 / step)); min_u = int(round(cfg.milp_min_weight / step)); max_u = int(round(cfg.milp_max_weight / step))
    opt_units = layer["optimizer_weight"].to_numpy(float) / step
    cur_units = np.asarray([float(current_weights.get(t, 0.0)) / step for t in names], dtype=float)
    # Variables: integer weight units w[n], binary z[n], continuous abs tracking d[n], continuous abs turnover q[n]
    N = 4 * n
    c = np.zeros(N, dtype=float)
    c[2*n:3*n] = 1.0
    c[3*n:4*n] = 0.05
    integrality = np.zeros(N, dtype=int); integrality[:n] = 1; integrality[n:2*n] = 1
    lb = np.zeros(N); ub = np.full(N, np.inf)
    ub[:n] = max_u; ub[n:2*n] = 1.0
    rows = []; lo = []; hi = []
    # Sum weights = total units
    a = np.zeros(N); a[:n] = 1; rows.append(a); lo.append(total_units); hi.append(total_units)
    # Exact holdings count, matching research top-N implementability.
    a = np.zeros(N); a[n:2*n] = 1; rows.append(a); lo.append(cfg.milp_holdings); hi.append(cfg.milp_holdings)
    for i in range(n):
        a = np.zeros(N); a[i] = 1; a[n+i] = -max_u; rows.append(a); lo.append(-np.inf); hi.append(0)
        a = np.zeros(N); a[i] = -1; a[n+i] = min_u; rows.append(a); lo.append(-np.inf); hi.append(0)
        # d >= |w-opt|
        a = np.zeros(N); a[i] = 1; a[2*n+i] = -1; rows.append(a); lo.append(-np.inf); hi.append(opt_units[i])
        a = np.zeros(N); a[i] = -1; a[2*n+i] = -1; rows.append(a); lo.append(-np.inf); hi.append(-opt_units[i])
        # q >= |w-current|
        a = np.zeros(N); a[i] = 1; a[3*n+i] = -1; rows.append(a); lo.append(-np.inf); hi.append(cur_units[i])
        a = np.zeros(N); a[i] = -1; a[3*n+i] = -1; rows.append(a); lo.append(-np.inf); hi.append(-cur_units[i])
    cons = LinearConstraint(np.vstack(rows), np.asarray(lo), np.asarray(hi))
    res = milp(c=c, integrality=integrality, bounds=Bounds(lb, ub), constraints=cons, options={"time_limit": 5.0})
    if not bool(res.success):
        return {}, {"success": False, "message": str(res.message)}
    wu = np.rint(res.x[:n]).astype(int)
    weights = {t: float(u * step) for t, u in zip(names, wu) if u > 0}
    # Normal numerical guard.
    s = sum(weights.values())
    if s > 0 and abs(s - 1.0) > 1e-8:
        weights = {k: v / s for k, v in weights.items()}
    return weights, {"success": True, "message": str(res.message), "objective": float(res.fun)}


def _rank_values(x: pd.Series, ascending: bool = False) -> pd.Series:
    return x.rank(method="average", ascending=ascending)


def lineage_metrics(layer: pd.DataFrame, milp_weights: dict[str, float]) -> dict:
    x = layer.copy(); x["milp_weight"] = x["ticker"].map(milp_weights).fillna(0.0)
    alpha = pd.to_numeric(x["alpha_score"], errors="coerce").to_numpy(float)
    final = pd.to_numeric(x["milp_weight"], errors="coerce").to_numpy(float)
    sp = spearmanr(alpha, final, nan_policy="omit").statistic if len(x) >= 3 else math.nan
    kd = kendalltau(alpha, final, nan_policy="omit").statistic if len(x) >= 3 else math.nan
    x = x.sort_values(["alpha_score", "ticker"], ascending=[False, True]).reset_index(drop=True)
    top5 = set(x.head(5)["ticker"]); top10 = set(x.head(10)["ticker"]); held = set(x.loc[x["milp_weight"] > 1e-12, "ticker"])
    top5_capture = len(top5 & held) / 5.0; top10_capture = len(top10 & held) / 10.0
    zero_ref_theory = float(x.loc[(x["reference_weight"] <= 1e-12) & (x["theoretical_weight"] > 0), "theoretical_weight"].sum())
    inversions = 0
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            if x.loc[j, "milp_weight"] > x.loc[i, "milp_weight"] + 1e-9:
                inversions += 1
    excluded = x.head(10).loc[x.head(10)["milp_weight"] <= 1e-12, "ticker"].tolist()
    ar = _rank_values(x["alpha_score"], ascending=False); wr = _rank_values(x["milp_weight"], ascending=False)
    rank_disp = float(np.mean(np.abs(ar - wr)))
    ref_pos = x["reference_weight"] > 1e-12
    amp = float((x.loc[ref_pos, "milp_weight"] / x.loc[ref_pos, "reference_weight"]).max()) if ref_pos.any() else math.nan
    l1_rt = float(np.abs(x["reference_weight"] - x["theoretical_weight"]).sum())
    l1_to = float(np.abs(x["theoretical_weight"] - x["optimizer_weight"]).sum())
    l1_om = float(np.abs(x["optimizer_weight"] - x["milp_weight"]).sum())
    l1_rm = float(np.abs(x["reference_weight"] - x["milp_weight"]).sum())
    ref_alpha = float((x["reference_weight"] * x["alpha_score"]).sum())
    milp_alpha = float((x["milp_weight"] * x["alpha_score"]).sum())
    capture = milp_alpha / ref_alpha if ref_alpha > 0 else math.nan
    x["optimizer_milp_abs_diff"] = np.abs(x["optimizer_weight"] - x["milp_weight"])
    loc = ";".join((x.nlargest(3, "optimizer_milp_abs_diff")["ticker"] + ":" + x.nlargest(3, "optimizer_milp_abs_diff")["optimizer_milp_abs_diff"].map(lambda v: f"{v:.4f}")).tolist())
    bindings = []
    if len(excluded): bindings.append("CARDINALITY_EXCLUSION")
    if (x["optimizer_weight"] >= x["optimizer_weight"].max() - 1e-12).sum() > 1: bindings.append("MAX_WEIGHT_CAP_OR_TIE")
    if l1_om > 0.10: bindings.append("DISCRETIZATION_OR_CARDINALITY")
    alpha_lost = bool(capture < 0.95 or top10_capture < 0.90 or (np.isfinite(sp) and sp < 0.75))
    reasons = (["ALPHA_LOSS"] + bindings) if alpha_lost else (["ALPHA_PRESERVED"] + bindings)
    return {
        "spearman_alpha_milp": float(sp) if np.isfinite(sp) else math.nan,
        "kendall_alpha_milp": float(kd) if np.isfinite(kd) else math.nan,
        "top5_capture": top5_capture,
        "top10_capture": top10_capture,
        "top5_overlap": top5_capture,
        "top10_overlap": top10_capture,
        "zero_reference_to_positive_theoretical_mass": zero_ref_theory,
        "low_alpha_high_weight_inversions": int(inversions),
        "excluded_top_alpha_names": ";".join(excluded),
        "mean_rank_displacement": rank_disp,
        "amplification_vs_reference": amp,
        "l1_reference_theoretical": l1_rt,
        "l1_theoretical_optimizer": l1_to,
        "l1_optimizer_milp": l1_om,
        "l1_reference_milp": l1_rm,
        "alpha_capture": capture,
        "optimizer_vs_milp_localization": loc,
        "alpha_loss_mechanism": ";".join(reasons),
    }


def monthly_lineage_audit(scores: pd.DataFrame, calib: pd.DataFrame, cfg: Phase7Config, uncertainty_z: float, start: pd.Timestamp, end: pd.Timestamp, partition_name: str) -> pd.DataFrame:
    x = scores[(scores["signal_date"] >= start) & (scores["signal_date"] < end)].copy()
    dates = sorted(x["signal_date"].dropna().unique())
    chosen = []
    seen = set()
    for d in dates:
        p = pd.Timestamp(d).to_period("M")
        if p not in seen:
            seen.add(p); chosen.append(pd.Timestamp(d))
    current: dict[str, float] = {}; rows = []
    for d in chosen:
        g = x[x["signal_date"] == d]
        sm = dict(zip(g["ticker"].astype(str), pd.to_numeric(g["alpha_score"], errors="coerce")))
        layer, _ = build_lineage_layers(sm, calib, cfg, uncertainty_z)
        if layer.empty:
            continue
        final, info = solve_weight_milp(layer, current, cfg)
        metrics = lineage_metrics(layer, final) if info.get("success") else {}
        rows.append({"partition": partition_name, "signal_date": d, "milp_success": bool(info.get("success")), "milp_message": info.get("message", ""), **metrics})
        if final:
            current = final
    return pd.DataFrame(rows)


def _aggregate_lineage(x: pd.DataFrame, partition: str) -> dict:
    if x.empty:
        return {"partition": partition, "snapshots": 0}
    return {
        "partition": partition,
        "snapshots": int(len(x)),
        "milp_success_rate": float(x["milp_success"].mean()),
        "median_spearman_alpha_milp": float(pd.to_numeric(x["spearman_alpha_milp"], errors="coerce").median()),
        "median_kendall_alpha_milp": float(pd.to_numeric(x["kendall_alpha_milp"], errors="coerce").median()),
        "median_top5_capture": float(pd.to_numeric(x["top5_capture"], errors="coerce").median()),
        "median_top10_capture": float(pd.to_numeric(x["top10_capture"], errors="coerce").median()),
        "median_alpha_capture": float(pd.to_numeric(x["alpha_capture"], errors="coerce").median()),
        "median_l1_optimizer_milp": float(pd.to_numeric(x["l1_optimizer_milp"], errors="coerce").median()),
        "median_rank_displacement": float(pd.to_numeric(x["mean_rank_displacement"], errors="coerce").median()),
        "median_zero_reference_to_positive_theoretical_mass": float(pd.to_numeric(x["zero_reference_to_positive_theoretical_mass"], errors="coerce").median()),
        "snapshots_with_excluded_top_alpha": int((x["excluded_top_alpha_names"].fillna("").astype(str).str.len() > 0).sum()),
    }


def _clean_json(v):
    if isinstance(v, dict): return {str(k): _clean_json(x) for k, x in v.items()}
    if isinstance(v, list): return [_clean_json(x) for x in v]
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating,)): return None if not np.isfinite(v) else float(v)
    if isinstance(v, float): return None if not math.isfinite(v) else v
    if isinstance(v, pd.Timestamp): return str(v)
    return v


def build_phase7(root: Path) -> dict:
    cfg = load_config(root); outputs = root / "outputs"; outputs.mkdir(parents=True, exist_ok=True)
    with (root / cfg.phase6_summary_path).open("r", encoding="utf-8") as f: p6 = json.load(f)
    with (root / cfg.phase6_champion_spec_path).open("r", encoding="utf-8") as f: p6spec = json.load(f)
    validate_phase6(p6, p6spec, cfg)
    scores = load_h20_scores(root, cfg); targets = load_20d_targets(root, cfg)

    # Strict temporal contract: 2019-2020 calibrates expected-return curve; 2021-2022 selects net-edge; 2023-2024 confirms only.
    calib_early = fit_edge_calibration(scores, targets, ["WF_2019_2020"], cfg.selection_start, cfg.calibration_bins, cfg.hac_lag)
    calib_early.to_csv(outputs / "phase7_edge_calibration_selection.csv", index=False)

    p6cfg_proxy = type("Proxy", (), {"return_price_layer_path": cfg.return_price_layer_path, "terminal_overlay_path": cfg.terminal_overlay_path, "final_oos_start": cfg.final_oos_start})()
    prices, terminals = load_price_surface(root, p6cfg_proxy)
    selection_scores = scores[scores["partition"].eq("WF_2021_2022")].copy()
    selection_market = prepare_market(prices, cfg.selection_start, cfg.validation_start)

    grid = _edge_grid(cfg); rows = []
    for r in grid.to_dict("records"):
        spec = EdgeSpec(float(r["entry_floor"]), float(r["uncertainty_z"]), float(r["minimum_extra_edge_bps"]), int(r["max_replacements"]))
        mb, _, _ = simulate_edge_policy(selection_scores, prices, terminals, calib_early, spec, cfg.selection_start, cfg.validation_start, cfg.top_n, cfg.base_round_trip_bps, prepared_market=selection_market)
        ms, _, _ = simulate_edge_policy(selection_scores, prices, terminals, calib_early, spec, cfg.selection_start, cfg.validation_start, cfg.top_n, cfg.stress_round_trip_bps, prepared_market=selection_market)
        qualified = bool(
            float(mb.get("cagr", -1)) > 0 and float(ms.get("cagr", -1)) > 0 and
            float(mb.get("max_drawdown", -1)) >= -cfg.max_allowed_drawdown and
            float(mb.get("execution_skip_rate", 1)) <= cfg.max_execution_skip_rate
        )
        rows.append({**r,
            "selection_total_return_20bps": mb.get("total_return"), "selection_cagr_20bps": mb.get("cagr"),
            "selection_max_drawdown_20bps": mb.get("max_drawdown"), "selection_annual_turnover_20bps": mb.get("annual_turnover"),
            "selection_trade_days_20bps": mb.get("trade_days"), "selection_edge_decisions_20bps": mb.get("edge_decisions"), "selection_edge_trades_20bps": mb.get("edge_trades"),
            "selection_total_return_40bps": ms.get("total_return"), "selection_cagr_40bps": ms.get("cagr"),
            "selection_max_drawdown_40bps": ms.get("max_drawdown"), "selection_annual_turnover_40bps": ms.get("annual_turnover"),
            "qualified": qualified,
        })
    leaderboard = select_edge_policy(pd.DataFrame(rows)); leaderboard.to_csv(outputs / "phase7_edge_policy_leaderboard.csv", index=False)
    q = leaderboard[leaderboard["qualified"]]
    champion = q.iloc[0].to_dict() if len(q) else None

    # Weekly research benchmark over the same selection slice; comparison only, never used to select edge hyperparameters.
    weekly_sel, _ = simulate_policy(
        ensemble_scores=selection_scores.rename(columns={"alpha_score": "ensemble_score"})[["signal_date", "ticker", "ensemble_score"]],
        prices=prices, terminals=terminals, start=cfg.selection_start, end=cfg.validation_start, top_n=cfg.top_n,
        policy_name="WEEKLY", round_trip_bps=cfg.base_round_trip_bps,
    )

    validation_rows = []; validation_confirmed = False; selected_spec = None
    calib_final = fit_edge_calibration(scores, targets, ["WF_2019_2020", "WF_2021_2022"], cfg.validation_start, cfg.calibration_bins, cfg.hac_lag)
    calib_final.to_csv(outputs / "phase7_edge_calibration_validation.csv", index=False)
    val_scores = scores[scores["partition"].eq("VALIDATION_2023_2024")].copy()
    validation_market = prepare_market(prices, cfg.validation_start, cfg.final_oos_start)
    if champion is not None:
        selected_spec = EdgeSpec(float(champion["entry_floor"]), float(champion["uncertainty_z"]), float(champion["minimum_extra_edge_bps"]), int(champion["max_replacements"]))
        vb, navb, edgesb = simulate_edge_policy(val_scores, prices, terminals, calib_final, selected_spec, cfg.validation_start, cfg.final_oos_start, cfg.top_n, cfg.base_round_trip_bps, prepared_market=validation_market)
        vs, _, _ = simulate_edge_policy(val_scores, prices, terminals, calib_final, selected_spec, cfg.validation_start, cfg.final_oos_start, cfg.top_n, cfg.stress_round_trip_bps, prepared_market=validation_market)
        weekly_val, _ = simulate_policy(
            ensemble_scores=val_scores.rename(columns={"alpha_score": "ensemble_score"})[["signal_date", "ticker", "ensemble_score"]],
            prices=prices, terminals=terminals, start=cfg.validation_start, end=cfg.final_oos_start, top_n=cfg.top_n,
            policy_name="WEEKLY", round_trip_bps=cfg.base_round_trip_bps,
        )
        validation_rows = [
            {"cost_bps": cfg.base_round_trip_bps, **vb, "weekly_reference_cagr": weekly_val.get("cagr"), "cagr_delta_vs_weekly": (vb.get("cagr", math.nan) - weekly_val.get("cagr", math.nan))},
            {"cost_bps": cfg.stress_round_trip_bps, **vs, "weekly_reference_cagr": weekly_val.get("cagr"), "cagr_delta_vs_weekly": (vs.get("cagr", math.nan) - weekly_val.get("cagr", math.nan))},
        ]
        pd.DataFrame(validation_rows).to_csv(outputs / "phase7_validation_confirmation.csv", index=False)
        if len(navb): navb.to_csv(outputs / "phase7_validation_nav.csv", index=False)
        if len(edgesb): edgesb.to_csv(outputs / "phase7_validation_edge_decisions.csv", index=False)
        validation_confirmed = bool(
            float(vb.get("cagr", -1)) > 0 and float(vs.get("cagr", -1)) > 0 and
            float(vb.get("max_drawdown", -1)) >= -cfg.max_allowed_drawdown and
            float(vb.get("execution_skip_rate", 1)) <= cfg.max_execution_skip_rate
        )

    lineage_snapshots = pd.DataFrame(); lineage_summary = pd.DataFrame()
    lineage_ok = False; h_conclusion = "UNTESTED"
    if selected_spec is not None:
        lin_sel = monthly_lineage_audit(selection_scores, calib_early, cfg, selected_spec.uncertainty_z, cfg.selection_start, cfg.validation_start, "SELECTION_2021_2022")
        lin_val = monthly_lineage_audit(val_scores, calib_final, cfg, selected_spec.uncertainty_z, cfg.validation_start, cfg.final_oos_start, "VALIDATION_2023_2024")
        lineage_snapshots = pd.concat([lin_sel, lin_val], ignore_index=True)
        lineage_snapshots.to_csv(outputs / "phase7_lineage_snapshot_audit.csv", index=False)
        aggs = [_aggregate_lineage(lin_sel, "SELECTION_2021_2022"), _aggregate_lineage(lin_val, "VALIDATION_2023_2024")]
        lineage_summary = pd.DataFrame(aggs); lineage_summary.to_csv(outputs / "phase7_lineage_summary.csv", index=False)
        v = aggs[1]
        lineage_ok = bool(
            v.get("milp_success_rate", 0) >= 0.999 and
            v.get("median_spearman_alpha_milp", -1) >= cfg.lineage_min_spearman and
            v.get("median_kendall_alpha_milp", -1) >= cfg.lineage_min_kendall and
            v.get("median_top10_capture", 0) >= cfg.lineage_min_top10_capture and
            v.get("median_alpha_capture", 0) >= cfg.lineage_min_alpha_capture and
            v.get("median_l1_optimizer_milp", 1e9) <= cfg.lineage_max_optimizer_milp_l1
        )
        h_conclusion = "H0_OPTIMIZER_PRESERVES_ALPHA" if lineage_ok else "H1_OPTIMIZER_EXCESSIVELY_TRANSFORMS_ALPHA"

    gate = []
    def add(test, ok, value, rule, blocking=True):
        gate.append({"test": test, "status": "PASS" if ok else "FAIL", "blocking": bool(blocking), "value": value, "rule": rule})
    add("PHASE6_INPUT_PASS", p6.get("status") == "PASS", p6.get("status"), "Phase 6 must PASS")
    add("PHASE6_EDGE_READINESS", p6.get("policy_readiness") == "READY_FOR_EXPECTED_EDGE_CALIBRATION", p6.get("policy_readiness"), "Phase 6 must be ready for expected-edge calibration")
    add("FINAL_OOS_SCORE_FIREWALL", bool(scores["signal_date"].max() < cfg.final_oos_start), str(scores["signal_date"].max().date()), "no Phase 7 score may reach final OOS")
    add("TEMPORAL_CALIBRATION_SEPARATION", True, "2019-2020 -> calibrate; 2021-2022 -> select; 2023-2024 -> confirm", "expected-return calibration and edge-policy selection use disjoint chronological periods")
    add("QUALIFIED_EDGE_POLICY_EXISTS", champion is not None, int(len(q)), ">=1 qualified net-edge policy")
    add("VALIDATION_EDGE_CONFIRMATION", validation_confirmed, validation_confirmed, "selected edge policy must remain positive under base and stress costs in 2023-2024", blocking=False)
    add("ALPHA_LINEAGE_AUDIT", lineage_ok, h_conclusion, "same-snapshot alpha -> reference -> theoretical -> optimizer -> MILP must preserve alpha", blocking=True)
    status = "PASS" if all(r["status"] == "PASS" for r in gate if r["blocking"]) else "FAIL"
    readiness = "READY_FOR_PRE_FREEZE_REPLAY" if status == "PASS" and validation_confirmed and lineage_ok else "REVIEW_BEFORE_FREEZE"

    if selected_spec is not None:
        selected_payload = {
            "build": PHASE7_BUILD,
            "policy_type": "EVENT_DRIVEN_EXPECTED_NET_EDGE",
            "alpha_surface": "H20 / Phase 5 DEV_IC_COMPOSITE",
            "top_n": cfg.top_n,
            "entry_floor": selected_spec.entry_floor,
            "uncertainty_z": selected_spec.uncertainty_z,
            "minimum_extra_edge_bps": selected_spec.minimum_extra_edge_bps,
            "max_replacements_per_session": selected_spec.max_replacements,
            "decision_rule": "trade only when expected_incremental_return - estimated_total_cost - uncertainty_buffer > 0",
            "base_round_trip_cost_bps": cfg.base_round_trip_bps,
            "stress_round_trip_cost_bps": cfg.stress_round_trip_bps,
            "selection_period": "2021-01-04 to 2023-01-03 using calibration fitted only on 2019-2020",
            "validation_period": "2023-01-03 to 2025-01-01 confirmation only",
            "final_oos_start": str(cfg.final_oos_start.date()),
            "final_oos_used": False,
            "lineage_hypothesis_conclusion": h_conclusion,
            "warning": "Pre-freeze candidate only. Do not refit/tune on 2025+.",
        }
        with (outputs / "phase7_pre_freeze_candidate.json").open("w", encoding="utf-8") as f: json.dump(_clean_json(selected_payload), f, indent=2)

    pd.DataFrame(gate).to_csv(outputs / "phase7_gate.csv", index=False)
    summary = {
        "status": status, "phase": 7, "build": PHASE7_BUILD, "name": cfg.name, "objective": cfg.objective,
        "phase6_input": {"status": p6.get("status"), "policy_readiness": p6.get("policy_readiness")},
        "temporal_contract": {"edge_calibration": "WF_2019_2020_ONLY", "edge_policy_selection": "WF_2021_2022_ONLY", "validation": "2023_2024_CONFIRMATION_ONLY", "final_oos_start": str(cfg.final_oos_start.date()), "final_oos_used": False},
        "edge_policy_candidates": int(len(leaderboard)), "qualified_edge_policies": int(len(q)), "selected_edge_policy": champion,
        "weekly_reference_selection_cagr_20bps": weekly_sel.get("cagr"),
        "validation_confirmed": validation_confirmed,
        "lineage_hypothesis_conclusion": h_conclusion,
        "lineage_validation_summary": _aggregate_lineage(lineage_snapshots[lineage_snapshots["partition"].eq("VALIDATION_2023_2024")] if len(lineage_snapshots) else pd.DataFrame(), "VALIDATION_2023_2024"),
        "readiness": readiness,
        "gate": gate,
        "next_gate": "If READY_FOR_PRE_FREEZE_REPLAY: Phase 8 refits only fixed components on all pre-OOS data, fingerprints the model/policy, runs deterministic pre-freeze replay, then and only then opens untouched 2025+ OOS once.",
    }
    with (outputs / "phase7_summary.json").open("w", encoding="utf-8") as f: json.dump(_clean_json(summary), f, indent=2)
    return summary
