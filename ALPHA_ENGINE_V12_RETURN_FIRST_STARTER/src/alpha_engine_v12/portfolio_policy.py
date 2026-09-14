from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from alpha_engine_v12.model_tournament import (
    load_config as load_phase5_config,
    load_targets as load_phase5_targets,
    cross_sectional_rank_features,
    _prepare_horizon_frame,
    _mask_train_test,
    _mask_development_validation,
    fit_predict_architectures,
    _score_rank_by_date,
)

PHASE6_BUILD = "V1_FIX1_PANDAS_LOC_2026-09-12"
HORIZONS = (20, 60, 120, 252)


@dataclass(frozen=True)
class EnsembleSpec:
    name: str
    weights: dict[int, float]


@dataclass(frozen=True)
class EventPreset:
    name: str
    hold_floor: float
    minimum_score_edge: float


@dataclass(frozen=True)
class Phase6Config:
    name: str
    objective: str
    phase5_summary_path: str
    phase5_model_spec_path: str
    phase5_feature_pool_path: str
    phase5_oof_scores_path: str
    phase5_validation_scores_path: str
    feature_library_path: str
    targets_path: str
    return_price_layer_path: str
    terminal_overlay_path: str
    output_policy_scores_path: str
    final_oos_start: pd.Timestamp
    validation_start: pd.Timestamp
    base_round_trip_bps: float
    stress_round_trip_bps: float
    top_n: tuple[int, ...]
    scheduled_cadences: tuple[str, ...]
    max_execution_skip_rate: float
    max_allowed_drawdown: float
    minimum_entry_score: float
    max_replacements_per_event: int
    event_presets: tuple[EventPreset, ...]
    ensembles: tuple[EnsembleSpec, ...]
    selection: dict[str, object]


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")


def _norm_ticker(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.replace(".", "-", regex=False).str.strip()


def load_config(root: Path) -> Phase6Config:
    with (root / "config" / "phase6.toml").open("rb") as f:
        raw = tomllib.load(f)["phase6"]
    parts = raw["partitions"]
    ensembles = []
    for x in raw.get("ensembles", []):
        w = {20: float(x.get("h20", 0.0)), 60: float(x.get("h60", 0.0)), 120: float(x.get("h120", 0.0)), 252: float(x.get("h252", 0.0))}
        if sum(v > 0 for v in w.values()) < 1 or not np.isclose(sum(w.values()), 1.0):
            raise ValueError(f"Invalid ensemble weights for {x.get('name')}: {w}")
        ensembles.append(EnsembleSpec(str(x["name"]), w))
    presets = tuple(EventPreset(str(x["name"]), float(x["hold_floor"]), float(x["minimum_score_edge"])) for x in raw.get("event_presets", []))
    return Phase6Config(
        name=str(raw["name"]), objective=str(raw["objective"]),
        phase5_summary_path=str(raw["phase5_summary_path"]), phase5_model_spec_path=str(raw["phase5_model_spec_path"]),
        phase5_feature_pool_path=str(raw["phase5_feature_pool_path"]), phase5_oof_scores_path=str(raw["phase5_oof_scores_path"]),
        phase5_validation_scores_path=str(raw["phase5_validation_scores_path"]), feature_library_path=str(raw["feature_library_path"]),
        targets_path=str(raw["targets_path"]), return_price_layer_path=str(raw["return_price_layer_path"]),
        terminal_overlay_path=str(raw["terminal_overlay_path"]), output_policy_scores_path=str(raw["output_policy_scores_path"]),
        final_oos_start=pd.Timestamp(parts["final_oos_start"]).normalize(), validation_start=pd.Timestamp(parts["validation_start"]).normalize(),
        base_round_trip_bps=float(raw["costs"]["base_round_trip_bps"]), stress_round_trip_bps=float(raw["costs"]["stress_round_trip_bps"]),
        top_n=tuple(int(x) for x in raw["policy"]["top_n"]), scheduled_cadences=tuple(str(x) for x in raw["policy"]["scheduled_cadences"]),
        max_execution_skip_rate=float(raw["policy"]["max_execution_skip_rate"]), max_allowed_drawdown=float(raw["policy"]["max_allowed_drawdown"]),
        minimum_entry_score=float(raw["policy"]["minimum_entry_score"]), max_replacements_per_event=int(raw["policy"]["max_replacements_per_event"]),
        event_presets=presets, ensembles=tuple(ensembles), selection=dict(raw["selection"]),
    )


def validate_phase5(summary: dict, cfg: Phase6Config) -> None:
    if summary.get("status") != "PASS":
        raise RuntimeError("Phase 5 must PASS before Phase 6")
    if summary.get("model_readiness") != "READY_FOR_PORTFOLIO_POLICY_RESEARCH":
        raise RuntimeError("Phase 5 is not READY_FOR_PORTFOLIO_POLICY_RESEARCH")
    fw = summary.get("final_oos_firewall") or {}
    if fw.get("used_for_model_selection") is not False:
        raise RuntimeError("Phase 5 final OOS firewall is not intact")
    if pd.Timestamp(fw.get("final_oos_start")).normalize() != cfg.final_oos_start:
        raise RuntimeError("Phase 5 / Phase 6 final OOS boundary mismatch")


def champion_map(summary: dict) -> dict[int, str]:
    out: dict[int, str] = {}
    for x in summary.get("champions", []):
        if bool(x.get("qualified")):
            out[int(x["horizon_sessions"])] = str(x["architecture"])
    missing = [h for h in HORIZONS if h not in out]
    if missing:
        raise RuntimeError(f"Missing qualified Phase 5 champions for horizons {missing}")
    return out


def load_phase5_pool(root: Path, cfg: Phase6Config) -> pd.DataFrame:
    p = pd.read_csv(root / cfg.phase5_feature_pool_path)
    req = {"feature", "horizon_sessions", "kept_after_correlation_prune", "development_direction", "development_mean_spearman_ic"}
    missing = req - set(p.columns)
    if missing:
        raise ValueError(f"Phase 5 feature pool missing {sorted(missing)}")
    p["horizon_sessions"] = pd.to_numeric(p["horizon_sessions"], errors="raise").astype(int)
    if p["kept_after_correlation_prune"].dtype != bool:
        p["kept_after_correlation_prune"] = p["kept_after_correlation_prune"].astype(str).str.lower().isin(["true", "1", "yes"])
    return p


def load_pre_oos_ranked_features(root: Path, cfg: Phase6Config, pool: pd.DataFrame) -> pd.DataFrame:
    cols = sorted(pool.loc[pool["kept_after_correlation_prune"], "feature"].astype(str).unique().tolist())
    f = pd.read_parquet(root / cfg.feature_library_path, columns=["date", "ticker", "feature_allowed", *cols])
    f["date"] = _as_date(f["date"]); f["ticker"] = _norm_ticker(f["ticker"])
    f = f[f["date"] < cfg.final_oos_start].copy()
    if not f["feature_allowed"].fillna(False).astype(bool).all():
        raise RuntimeError("Feature-forbidden rows entered Phase 6")
    return cross_sectional_rank_features(f[["date", "ticker", *cols]], cols)


def _select_score_frame(ranked: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, features: list[str]) -> pd.DataFrame:
    """Select one causal score surface window without pandas tuple-indexing ambiguity."""
    mask = (ranked["date"] >= start) & (ranked["date"] < end)
    cols = ["date", "ticker", *features]
    return ranked.loc[mask, cols].rename(columns={"date": "signal_date"}).copy()


def regenerate_policy_scores(root: Path, cfg: Phase6Config, phase5_summary: dict, pool: pd.DataFrame) -> pd.DataFrame:
    p5cfg = load_phase5_config(root)
    champions = champion_map(phase5_summary)
    ranked = load_pre_oos_ranked_features(root, cfg, pool)
    targets = load_phase5_targets(root, p5cfg)
    frames: list[pd.DataFrame] = []
    for h in HORIZONS:
        hp = pool[(pool["horizon_sessions"] == h)].copy()
        features = hp.loc[hp["kept_after_correlation_prune"], "feature"].astype(str).tolist()
        if not features:
            raise RuntimeError(f"No Phase 5 features retained for horizon {h}")
        train_frame = _prepare_horizon_frame(ranked[["date", "ticker", *features]], targets, features, h)
        arch = champions[h]
        for fold in p5cfg.cv_folds:
            tr_mask, _ = _mask_train_test(train_frame, p5cfg, h, fold)
            train = train_frame.loc[tr_mask].copy()
            score_frame = _select_score_frame(ranked, fold.test_start, fold.test_end, features)
            if train.empty or score_frame.empty:
                continue
            preds = fit_predict_architectures(train, score_frame, features, hp, h, p5cfg)
            score = preds[arch]
            sf = score_frame[["signal_date", "ticker"]].copy()
            sf["horizon_sessions"] = h; sf["architecture"] = arch; sf["partition"] = fold.name
            sf["score"] = score; sf["score_rank_pct"] = _score_rank_by_date(sf[["signal_date"]], score)
            frames.append(sf)
        tr_mask, _ = _mask_development_validation(train_frame, p5cfg, h)
        train = train_frame.loc[tr_mask].copy()
        score_frame = _select_score_frame(ranked, p5cfg.partitions["validation_start"], p5cfg.partitions["final_oos_start"], features)
        if not train.empty and not score_frame.empty:
            preds = fit_predict_architectures(train, score_frame, features, hp, h, p5cfg)
            score = preds[arch]
            sf = score_frame[["signal_date", "ticker"]].copy()
            sf["horizon_sessions"] = h; sf["architecture"] = arch; sf["partition"] = "VALIDATION_2023_2024"
            sf["score"] = score; sf["score_rank_pct"] = _score_rank_by_date(sf[["signal_date"]], score)
            frames.append(sf)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if out.empty:
        raise RuntimeError("Phase 6 could not regenerate champion score surfaces")
    if out["signal_date"].max() >= cfg.final_oos_start:
        raise RuntimeError("Final OOS score entered Phase 6")
    return out.sort_values(["partition", "signal_date", "horizon_sessions", "ticker"]).reset_index(drop=True)


def score_fidelity(regenerated: pd.DataFrame, stored: pd.DataFrame, source: str, champions: dict[int, str]) -> pd.DataFrame:
    if stored.empty:
        return pd.DataFrame(columns=["source", "horizon_sessions", "architecture", "overlap_rows", "score_correlation", "mean_abs_diff"])
    s = stored.copy()
    if "date" in s.columns and "signal_date" not in s.columns:
        s = s.rename(columns={"date": "signal_date"})
    s["signal_date"] = _as_date(s["signal_date"]); s["ticker"] = _norm_ticker(s["ticker"])
    rows = []
    for h, arch in champions.items():
        a = regenerated[(regenerated["horizon_sessions"] == h) & (regenerated["architecture"] == arch)][["signal_date", "ticker", "score"]].rename(columns={"score": "regen_score"})
        b = s[(pd.to_numeric(s["horizon_sessions"], errors="coerce") == h) & (s["architecture"].astype(str) == arch)][["signal_date", "ticker", "score"]].rename(columns={"score": "stored_score"})
        m = a.merge(b, on=["signal_date", "ticker"], how="inner")
        x = pd.to_numeric(m["regen_score"], errors="coerce"); y = pd.to_numeric(m["stored_score"], errors="coerce")
        ok = np.isfinite(x) & np.isfinite(y)
        corr = float(x[ok].corr(y[ok])) if int(ok.sum()) >= 3 else math.nan
        mad = float(np.mean(np.abs(x[ok] - y[ok]))) if int(ok.sum()) else math.nan
        rows.append({"source": source, "horizon_sessions": h, "architecture": arch, "overlap_rows": int(ok.sum()), "score_correlation": corr, "mean_abs_diff": mad})
    return pd.DataFrame(rows)


def build_ensemble_surface(scores: pd.DataFrame, ensemble: EnsembleSpec, partition: str) -> pd.DataFrame:
    x = scores[scores["partition"].eq(partition)][["signal_date", "ticker", "horizon_sessions", "score_rank_pct"]].copy()
    wide = x.pivot_table(index=["signal_date", "ticker"], columns="horizon_sessions", values="score_rank_pct", aggfunc="first")
    needed = [h for h, w in ensemble.weights.items() if w > 0]
    for h in needed:
        if h not in wide.columns:
            wide[h] = np.nan
    ok = wide[needed].notna().all(axis=1)
    raw = sum(float(ensemble.weights[h]) * pd.to_numeric(wide[h], errors="coerce") for h in needed)
    out = wide.reset_index()[["signal_date", "ticker"]]
    out["ensemble_score_raw"] = np.where(ok.to_numpy(), raw.to_numpy(), np.nan)
    out["ensemble_score"] = out["ensemble_score_raw"].groupby(out["signal_date"], sort=False).rank(method="average", pct=True)
    out["ensemble"] = ensemble.name
    return out[np.isfinite(out["ensemble_score"])].sort_values(["signal_date", "ensemble_score", "ticker"], ascending=[True, False, True]).reset_index(drop=True)


def load_price_surface(root: Path, cfg: Phase6Config) -> tuple[pd.DataFrame, dict[str, pd.Timestamp]]:
    p = pd.read_parquet(root / cfg.return_price_layer_path, columns=["date", "ticker", "research_eligible", "target_total_return_price"])
    p["date"] = _as_date(p["date"]); p["ticker"] = _norm_ticker(p["ticker"])
    p["target_total_return_price"] = pd.to_numeric(p["target_total_return_price"], errors="coerce")
    p = p[(p["date"] < cfg.final_oos_start) & p["research_eligible"].fillna(False).astype(bool) & (p["target_total_return_price"] > 0)].copy()
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
    return p, terminals


def _top_target(score_map: dict[str, float], top_n: int) -> dict[str, float]:
    ranked = [(t, float(s)) for t, s in score_map.items() if np.isfinite(s)]
    ranked.sort(key=lambda z: (-z[1], z[0]))
    chosen = [t for t, _ in ranked[:top_n]]
    if not chosen:
        return {}
    w = 1.0 / len(chosen)
    return {t: w for t in chosen}


def event_target(
    current: dict[str, float], cash: float, score_map: dict[str, float], top_n: int,
    entry_floor: float, hold_floor: float, edge: float, max_replacements: int,
) -> dict[str, float]:
    holdings = {t: float(w) for t, w in current.items() if w > 1e-12}
    if not holdings:
        return _top_target({t: s for t, s in score_map.items() if np.isfinite(s) and s >= entry_floor}, top_n)
    target = dict(holdings)
    cash_left = max(0.0, float(cash))
    outsiders = [(t, float(s)) for t, s in score_map.items() if t not in target and np.isfinite(s) and s >= entry_floor]
    outsiders.sort(key=lambda z: (-z[1], z[0]))

    # Fill genuinely empty slots from cash without disturbing existing holdings.
    slots = max(0, top_n - len(target))
    if slots and cash_left > 1e-12 and outsiders:
        fill = outsiders[:slots]
        alloc = cash_left / len(fill)
        for t, _ in fill:
            target[t] = alloc
        cash_left = 0.0
        outsiders = outsiders[len(fill):]

    replacements = 0
    while replacements < max_replacements and outsiders and target:
        held_scored = [(t, score_map.get(t, np.nan)) for t in target]
        held_finite = [(t, float(s)) for t, s in held_scored if np.isfinite(s)]
        if not held_finite:
            break
        weak_t, weak_s = min(held_finite, key=lambda z: (z[1], z[0]))
        cand_t, cand_s = outsiders[0]
        gap = cand_s - weak_s
        material = gap >= edge and (weak_s < hold_floor or gap >= 2.0 * edge)
        if not material:
            break
        w = target.pop(weak_t)
        target[cand_t] = w
        outsiders.pop(0)
        replacements += 1
    return target


def should_schedule(date: pd.Timestamp, cadence: str, last_key: object | None) -> tuple[bool, object]:
    d = pd.Timestamp(date)
    if cadence == "DAILY":
        return True, d
    if cadence == "WEEKLY":
        key = (int(d.isocalendar().year), int(d.isocalendar().week))
    elif cadence == "MONTHLY":
        key = (d.year, d.month)
    else:
        raise ValueError(f"Unknown cadence {cadence}")
    return key != last_key, key


def _portfolio_metrics(daily: pd.DataFrame) -> dict[str, float]:
    if daily.empty:
        return {"days": 0, "total_return": math.nan, "cagr": math.nan, "max_drawdown": math.nan, "annual_turnover": math.nan}
    nav = pd.to_numeric(daily["nav"], errors="coerce")
    n = int(len(daily))
    total = float(nav.iloc[-1] - 1.0)
    cagr = float(nav.iloc[-1] ** (252.0 / max(n, 1)) - 1.0) if nav.iloc[-1] > 0 else -1.0
    dd = nav / nav.cummax() - 1.0
    yrs = n / 252.0
    ann_turn = float(pd.to_numeric(daily["turnover"], errors="coerce").fillna(0).sum() / yrs) if yrs > 0 else math.nan
    rets = pd.to_numeric(daily["net_return"], errors="coerce").fillna(0)
    monthly = rets.groupby(pd.to_datetime(daily["date"]).dt.to_period("M")).apply(lambda x: float(np.prod(1.0 + x) - 1.0))
    return {
        "days": n, "total_return": total, "cagr": cagr, "max_drawdown": float(dd.min()),
        "annual_turnover": ann_turn, "trade_days": int((daily["turnover"] > 1e-12).sum()),
        "execution_skips": int(daily["execution_skipped"].sum()),
        "positive_month_share": float((monthly > 0).mean()) if len(monthly) else math.nan,
        "total_cost_fraction_sum": float(pd.to_numeric(daily["cost_fraction"], errors="coerce").fillna(0).sum()),
    }


def simulate_policy(
    ensemble_scores: pd.DataFrame, prices: pd.DataFrame, terminals: dict[str, pd.Timestamp],
    start: pd.Timestamp, end: pd.Timestamp, top_n: int, policy_name: str, round_trip_bps: float,
    entry_floor: float = 0.80, event_hold_floor: float | None = None, event_edge: float | None = None,
    max_replacements: int = 2,
) -> tuple[dict[str, float], pd.DataFrame]:
    start = pd.Timestamp(start).normalize(); end = pd.Timestamp(end).normalize()
    score = ensemble_scores[(ensemble_scores["signal_date"] >= start) & (ensemble_scores["signal_date"] < end)].copy()
    px = prices[(prices["date"] >= start) & (prices["date"] < end)].copy()
    if px.empty or score.empty:
        return _portfolio_metrics(pd.DataFrame()), pd.DataFrame()
    calendar = pd.DatetimeIndex(sorted(px["date"].dropna().unique()))
    raw = px.pivot_table(index="date", columns="ticker", values="target_total_return_price", aggfunc="last").reindex(calendar)
    presence = raw.notna()
    ff = raw.ffill()
    rets = ff.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    by_date = {pd.Timestamp(d): dict(zip(g["ticker"].astype(str), pd.to_numeric(g["ensemble_score"], errors="coerce"))) for d, g in score.groupby("signal_date", sort=False)}

    weights: dict[str, float] = {}
    cash = 1.0
    nav = 1.0
    pending: dict[str, float] | None = None
    last_sched = None
    rows = []
    one_way_rate = float(round_trip_bps) / 2.0 / 10000.0

    for d in calendar:
        d = pd.Timestamp(d)
        prev_nav = nav
        # Realized close-to-close total return belongs to positions held before today's close execution.
        gross = 0.0
        if weights:
            rr = rets.loc[d]
            gross = float(sum(w * (float(rr.get(t, 0.0)) if np.isfinite(rr.get(t, np.nan)) else 0.0) for t, w in weights.items()))
        nav *= max(0.0, 1.0 + gross)
        # Drift weights after returns.
        if weights:
            vals = {t: w * (1.0 + (float(rets.at[d, t]) if t in rets.columns and np.isfinite(rets.at[d, t]) else 0.0)) for t, w in weights.items()}
            cash_val = cash
            total = cash_val + sum(vals.values())
            if total > 0:
                weights = {t: v / total for t, v in vals.items() if v > 1e-14}
                cash = cash_val / total

        turnover = 0.0; cost_fraction = 0.0; skipped = False
        if pending is not None:
            current = dict(weights)
            trade_names = {t for t in set(current) | set(pending) if abs(float(pending.get(t, 0.0)) - float(current.get(t, 0.0))) > 1e-10}
            executable = all((t in presence.columns and bool(presence.at[d, t])) for t in trade_names)
            if executable:
                traded = float(sum(abs(float(pending.get(t, 0.0)) - float(current.get(t, 0.0))) for t in trade_names))
                turnover = 0.5 * traded
                cost_fraction = one_way_rate * traded
                nav *= max(0.0, 1.0 - cost_fraction)
                weights = {t: float(w) for t, w in pending.items() if w > 1e-12}
                cash = max(0.0, 1.0 - sum(weights.values()))
            else:
                skipped = True
            pending = None

        # After the validated terminal close, proceeds are cash. Overlay is used only for settlement, never candidate ranking.
        terminal_now = [t for t in list(weights) if terminals.get(t) == d]
        for t in terminal_now:
            cash += weights.pop(t)

        score_map = by_date.get(d)
        if score_map:
            if policy_name in {"MONTHLY", "WEEKLY", "DAILY"}:
                yes, last_sched = should_schedule(d, policy_name, last_sched)
                if yes:
                    pending = _top_target(score_map, top_n)
            elif policy_name.startswith("EVENT_"):
                if event_hold_floor is None or event_edge is None:
                    raise ValueError("Event policy requires hold floor and edge")
                target = event_target(weights, cash, score_map, top_n, entry_floor, event_hold_floor, event_edge, max_replacements)
                delta = sum(abs(float(target.get(t, 0.0)) - float(weights.get(t, 0.0))) for t in set(target) | set(weights))
                if delta > 1e-10:
                    pending = target
            else:
                raise ValueError(policy_name)

        net_ret = nav / prev_nav - 1.0 if prev_nav > 0 else -1.0
        rows.append({"date": d, "nav": nav, "net_return": net_ret, "gross_return": gross, "turnover": turnover, "cost_fraction": cost_fraction, "execution_skipped": int(skipped), "holdings": len(weights), "cash_weight": cash})
    daily = pd.DataFrame(rows)
    met = _portfolio_metrics(daily)
    exec_attempts = int((daily["turnover"] > 1e-12).sum() + daily["execution_skipped"].sum()) if len(daily) else 0
    met["execution_skip_rate"] = float(daily["execution_skipped"].sum() / exec_attempts) if exec_attempts else 0.0
    return met, daily


def benchmark_metrics(prices: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, ticker: str = "SPY") -> dict[str, float]:
    x = prices[(prices["ticker"] == ticker) & (prices["date"] >= start) & (prices["date"] < end)].sort_values("date")
    if len(x) < 2:
        return {"benchmark_total_return": math.nan, "benchmark_cagr": math.nan, "benchmark_max_drawdown": math.nan}
    p = pd.to_numeric(x["target_total_return_price"], errors="coerce").dropna()
    if len(p) < 2:
        return {"benchmark_total_return": math.nan, "benchmark_cagr": math.nan, "benchmark_max_drawdown": math.nan}
    nav = p / p.iloc[0]
    total = float(nav.iloc[-1] - 1)
    cagr = float(nav.iloc[-1] ** (252.0 / max(len(nav) - 1, 1)) - 1.0)
    dd = nav / nav.cummax() - 1
    return {"benchmark_total_return": total, "benchmark_cagr": cagr, "benchmark_max_drawdown": float(dd.min())}


def _candidate_specs(cfg: Phase6Config) -> list[dict]:
    rows = []
    for ens in cfg.ensembles:
        for n in cfg.top_n:
            for c in cfg.scheduled_cadences:
                rows.append({"ensemble": ens.name, "top_n": n, "policy": c, "hold_floor": math.nan, "score_edge": math.nan})
            for e in cfg.event_presets:
                rows.append({"ensemble": ens.name, "top_n": n, "policy": e.name, "hold_floor": e.hold_floor, "score_edge": e.minimum_score_edge})
    return rows


def _aggregate_candidate(base_results: list[dict], stress_results: list[dict], cfg: Phase6Config) -> dict:
    b = pd.DataFrame(base_results); s = pd.DataFrame(stress_results)
    if b.empty or s.empty:
        return {}
    total = float(np.prod(1.0 + b["total_return"].to_numpy(float)) - 1.0)
    days = int(b["days"].sum())
    cagr = float((1.0 + total) ** (252.0 / max(days, 1)) - 1.0) if total > -1 else -1.0
    stotal = float(np.prod(1.0 + s["total_return"].to_numpy(float)) - 1.0)
    scagr = float((1.0 + stotal) ** (252.0 / max(int(s["days"].sum()), 1)) - 1.0) if stotal > -1 else -1.0
    return {
        "oof_total_return_20bps": total, "oof_cagr_20bps": cagr,
        "worst_fold_cagr_20bps": float(b["cagr"].min()), "worst_fold_max_drawdown_20bps": float(b["max_drawdown"].min()),
        "mean_annual_turnover_20bps": float(b["annual_turnover"].mean()), "total_trade_days_20bps": int(b["trade_days"].sum()),
        "max_execution_skip_rate": float(b["execution_skip_rate"].max()),
        "oof_total_return_40bps": stotal, "oof_cagr_40bps": scagr, "worst_fold_cagr_40bps": float(s["cagr"].min()),
    }


def select_policy(leaderboard: pd.DataFrame) -> pd.DataFrame:
    x = leaderboard.copy()
    x["return_first_rank"] = np.nan
    q = x[x["qualified"]].sort_values(
        ["oof_cagr_20bps", "worst_fold_cagr_20bps", "oof_cagr_40bps", "worst_fold_max_drawdown_20bps", "mean_annual_turnover_20bps"],
        ascending=[False, False, False, False, True],
    )
    x.loc[q.index, "return_first_rank"] = np.arange(1, len(q) + 1)
    nq = x[~x["qualified"]].sort_values("oof_cagr_20bps", ascending=False)
    x.loc[nq.index, "return_first_rank"] = np.arange(len(q) + 1, len(q) + len(nq) + 1)
    return x.sort_values(["return_first_rank", "ensemble", "top_n", "policy"]).reset_index(drop=True)


def build_phase6(root: Path) -> dict:
    cfg = load_config(root)
    outputs = root / "outputs"; outputs.mkdir(parents=True, exist_ok=True)
    with (root / cfg.phase5_summary_path).open("r", encoding="utf-8") as f:
        p5summary = json.load(f)
    validate_phase5(p5summary, cfg)
    champions = champion_map(p5summary)
    pool = load_phase5_pool(root, cfg)
    scores = regenerate_policy_scores(root, cfg, p5summary, pool)
    scores.to_parquet(root / cfg.output_policy_scores_path, index=False)

    fidelity_frames = []
    stored_oof = pd.read_parquet(root / cfg.phase5_oof_scores_path)
    stored_val = pd.read_parquet(root / cfg.phase5_validation_scores_path)
    fidelity_frames.append(score_fidelity(scores[scores["partition"].str.startswith("WF_")], stored_oof, "PHASE5_OOF", champions))
    fidelity_frames.append(score_fidelity(scores[scores["partition"].eq("VALIDATION_2023_2024")], stored_val, "PHASE5_VALIDATION", champions))
    fidelity = pd.concat(fidelity_frames, ignore_index=True)

    prices, terminals = load_price_surface(root, cfg)
    p5cfg = load_phase5_config(root)
    fold_map = {f.name: f for f in p5cfg.cv_folds}
    ensemble_cache: dict[tuple[str, str], pd.DataFrame] = {}
    for ens in cfg.ensembles:
        for part in [*(f.name for f in p5cfg.cv_folds), "VALIDATION_2023_2024"]:
            ensemble_cache[(ens.name, part)] = build_ensemble_surface(scores, ens, part)

    grid = pd.DataFrame(_candidate_specs(cfg))
    fold_rows = []; leaderboard_rows = []
    for spec in grid.to_dict("records"):
        base_res = []; stress_res = []
        for fold in p5cfg.cv_folds:
            surf = ensemble_cache[(spec["ensemble"], fold.name)]
            common = dict(ensemble_scores=surf, prices=prices, terminals=terminals, start=fold.test_start, end=fold.test_end,
                          top_n=int(spec["top_n"]), policy_name=str(spec["policy"]), entry_floor=cfg.minimum_entry_score,
                          event_hold_floor=None if pd.isna(spec["hold_floor"]) else float(spec["hold_floor"]),
                          event_edge=None if pd.isna(spec["score_edge"]) else float(spec["score_edge"]), max_replacements=cfg.max_replacements_per_event)
            mb, _ = simulate_policy(round_trip_bps=cfg.base_round_trip_bps, **common)
            ms, _ = simulate_policy(round_trip_bps=cfg.stress_round_trip_bps, **common)
            bm = benchmark_metrics(prices, fold.test_start, fold.test_end)
            base_res.append(mb); stress_res.append(ms)
            fold_rows.append({**spec, "fold": fold.name, "cost_bps": cfg.base_round_trip_bps, **mb, **bm})
            fold_rows.append({**spec, "fold": fold.name, "cost_bps": cfg.stress_round_trip_bps, **ms, **bm})
        agg = _aggregate_candidate(base_res, stress_res, cfg)
        positive_each = all(float(x.get("cagr", math.nan)) > 0 for x in base_res) if bool(cfg.selection["require_positive_each_oof_fold"]) else True
        stress_positive = float(agg.get("oof_cagr_40bps", -1)) > 0 if bool(cfg.selection["require_positive_stress_oof"]) else True
        dd_ok = float(agg.get("worst_fold_max_drawdown_20bps", -1)) >= -cfg.max_allowed_drawdown
        skip_ok = float(agg.get("max_execution_skip_rate", 1)) <= cfg.max_execution_skip_rate
        qualified = bool(positive_each and stress_positive and dd_ok and skip_ok)
        leaderboard_rows.append({**spec, **agg, "positive_each_oof_fold": positive_each, "stress_oof_positive": stress_positive, "drawdown_ok": dd_ok, "execution_ok": skip_ok, "qualified": qualified})

    fold_df = pd.DataFrame(fold_rows)
    leaderboard = select_policy(pd.DataFrame(leaderboard_rows))
    qualified = leaderboard[leaderboard["qualified"]].copy()
    champion = qualified.iloc[0].to_dict() if len(qualified) else None
    readiness = "NEEDS_POLICY_RESEARCH"
    validation_rows = []
    champion_nav = pd.DataFrame()
    validation_confirmed = False
    if champion is not None:
        surf = ensemble_cache[(str(champion["ensemble"]), "VALIDATION_2023_2024")]
        common = dict(ensemble_scores=surf, prices=prices, terminals=terminals, start=p5cfg.partitions["validation_start"], end=p5cfg.partitions["final_oos_start"],
                      top_n=int(champion["top_n"]), policy_name=str(champion["policy"]), entry_floor=cfg.minimum_entry_score,
                      event_hold_floor=None if pd.isna(champion["hold_floor"]) else float(champion["hold_floor"]),
                      event_edge=None if pd.isna(champion["score_edge"]) else float(champion["score_edge"]), max_replacements=cfg.max_replacements_per_event)
        vb, navb = simulate_policy(round_trip_bps=cfg.base_round_trip_bps, **common)
        vs, _ = simulate_policy(round_trip_bps=cfg.stress_round_trip_bps, **common)
        bm = benchmark_metrics(prices, p5cfg.partitions["validation_start"], p5cfg.partitions["final_oos_start"])
        validation_rows.append({"cost_bps": cfg.base_round_trip_bps, **vb, **bm})
        validation_rows.append({"cost_bps": cfg.stress_round_trip_bps, **vs, **bm})
        champion_nav = navb
        base_ok = float(vb.get("cagr", -1)) > 0 if bool(cfg.selection["validation_requires_positive_base_cagr"]) else True
        stress_ok = float(vs.get("cagr", -1)) > 0 if bool(cfg.selection["validation_requires_positive_stress_cagr"]) else True
        validation_confirmed = bool(base_ok and stress_ok and float(vb.get("max_drawdown", -1)) >= -cfg.max_allowed_drawdown)
        readiness = "READY_FOR_EXPECTED_EDGE_CALIBRATION" if validation_confirmed else "REVIEW_POLICY_ROBUSTNESS"

    fidelity_corr = pd.to_numeric(fidelity["score_correlation"], errors="coerce")
    fidelity_ok = bool((fidelity["overlap_rows"] > 0).all() and (fidelity_corr >= float(cfg.selection["score_fidelity_min_correlation"])).all())
    gate_rows = []
    def add(test: str, ok: bool, value: object, rule: str, blocking: bool = True) -> None:
        gate_rows.append({"test": test, "status": "PASS" if ok else "FAIL", "blocking": blocking, "value": value, "rule": rule})
    add("PHASE5_INPUT_PASS", p5summary.get("status") == "PASS", p5summary.get("status"), "Phase 5 must PASS")
    add("PHASE5_MODEL_READINESS", p5summary.get("model_readiness") == "READY_FOR_PORTFOLIO_POLICY_RESEARCH", p5summary.get("model_readiness"), "Phase 5 must be ready for policy research")
    add("FINAL_OOS_SCORE_FIREWALL", bool(scores["signal_date"].max() < cfg.final_oos_start), str(scores["signal_date"].max().date()), "all Phase 6 score surfaces must be strictly before 2025-01-01")
    add("CHAMPION_SCORE_REGENERATION_FIDELITY", fidelity_ok, float(fidelity_corr.min()) if len(fidelity_corr) else math.nan, f"all overlapping regenerated/stored champion scores correlation >= {cfg.selection['score_fidelity_min_correlation']}")
    add("POLICY_GRID_NONEMPTY", len(leaderboard) > 0, int(len(leaderboard)), "> 0 policy candidates")
    add("QUALIFIED_POLICY_EXISTS", len(qualified) >= int(cfg.selection["minimum_qualified_policies"]), int(len(qualified)), f">= {cfg.selection['minimum_qualified_policies']} robust OOF policies")
    add("VALIDATION_NOT_USED_FOR_POLICY_SELECTION", True, False, "policy rank is determined exclusively from OOF 2019-2022; validation is confirmation only")
    add("POLICY_READINESS", readiness == "READY_FOR_EXPECTED_EDGE_CALIBRATION", readiness, "OOF champion must confirm positive net CAGR under base and stress costs in 2023-2024", blocking=False)
    status = "PASS" if all((r["status"] == "PASS") for r in gate_rows if r["blocking"]) else "FAIL"

    # Diagnostics by policy family: best OOF candidate per family, no validation selection.
    class_rows = []
    for cls, g in leaderboard.assign(policy_class=np.where(leaderboard["policy"].str.startswith("EVENT_"), "EVENT_DRIVEN", leaderboard["policy"])).groupby("policy_class"):
        best = g.sort_values("return_first_rank").iloc[0]
        class_rows.append({"policy_class": cls, "best_return_first_rank": int(best["return_first_rank"]), "ensemble": best["ensemble"], "top_n": int(best["top_n"]), "policy": best["policy"], "qualified": bool(best["qualified"]), "oof_cagr_20bps": float(best["oof_cagr_20bps"]), "oof_cagr_40bps": float(best["oof_cagr_40bps"]), "worst_fold_cagr_20bps": float(best["worst_fold_cagr_20bps"]), "mean_annual_turnover_20bps": float(best["mean_annual_turnover_20bps"])})

    grid.to_csv(outputs / "phase6_policy_grid.csv", index=False)
    fold_df.to_csv(outputs / "phase6_oof_results.csv", index=False)
    leaderboard.to_csv(outputs / "phase6_leaderboard.csv", index=False)
    pd.DataFrame(validation_rows).to_csv(outputs / "phase6_validation_confirmation.csv", index=False)
    fidelity.to_csv(outputs / "phase6_score_fidelity.csv", index=False)
    pd.DataFrame(class_rows).to_csv(outputs / "phase6_policy_class_summary.csv", index=False)
    pd.DataFrame(gate_rows).to_csv(outputs / "phase6_gate.csv", index=False)
    if len(champion_nav):
        champion_nav.to_csv(outputs / "phase6_champion_validation_nav.csv", index=False)

    champion_spec = {
        "build": PHASE6_BUILD,
        "selection_contract": "RETURN_FIRST; policy hyperparameters selected only on purged OOF 2019-2022; 2023-2024 confirmation only; final OOS 2025+ untouched",
        "research_champion": champion,
        "validation_confirmed": validation_confirmed,
        "readiness": readiness,
        "champion_models": champions,
        "base_round_trip_cost_bps": cfg.base_round_trip_bps,
        "stress_round_trip_cost_bps": cfg.stress_round_trip_bps,
        "warning": "This is a pre-OOS research policy, not the final frozen execution policy. Phase 7 must calibrate expected incremental return, uncertainty buffer and executable net-edge before freeze.",
    }
    with (outputs / "phase6_champion_spec.json").open("w", encoding="utf-8") as f:
        json.dump(champion_spec, f, indent=2, default=str)

    summary = {
        "status": status, "phase": 6, "build": PHASE6_BUILD, "name": cfg.name, "objective": cfg.objective,
        "phase5_input": {"status": p5summary.get("status"), "model_readiness": p5summary.get("model_readiness")},
        "champion_models": champions, "policy_candidates": int(len(leaderboard)), "qualified_policies": int(len(qualified)),
        "research_champion": champion, "validation_confirmed": validation_confirmed, "policy_readiness": readiness,
        "selection_contract": {"policy_selection_period": "OOF_2019_2022_ONLY", "validation_period": "2023_2024_CONFIRMATION_ONLY", "final_oos_start": str(cfg.final_oos_start.date()), "final_oos_used": False, "primary_sort": ["oof_cagr_20bps", "worst_fold_cagr_20bps", "oof_cagr_40bps", "max_drawdown", "turnover"]},
        "score_regeneration": {"max_score_date": str(scores["signal_date"].max().date()), "fidelity_min_correlation": float(fidelity_corr.min()) if len(fidelity_corr) else math.nan},
        "gate": gate_rows,
        "next_gate": "If policy_readiness is READY_FOR_EXPECTED_EDGE_CALIBRATION: Phase 7 calibrates expected incremental return + costs + uncertainty buffer, compares optimizer/reference/MILP alpha lineage, and only then prepares freeze. Final OOS remains untouched.",
    }
    with (outputs / "phase6_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    return summary
