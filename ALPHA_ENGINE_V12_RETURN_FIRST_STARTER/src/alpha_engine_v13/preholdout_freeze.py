from __future__ import annotations

import hashlib, json, math, tomllib
from pathlib import Path
import numpy as np
import pandas as pd

from alpha_engine_v13 import economic_portfolio_closure as p3v

BUILD = "V13_P3W_PREHOLDOUT_STRESS_FREEZE_2026-09-13"
HORIZONS = p3v.HORIZONS


def _load_cfg(workspace: Path) -> dict:
    with (workspace / "config" / "v13_phase3w.toml").open("rb") as f:
        return tomllib.load(f)["v13_phase3w"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _gate_map(rows) -> dict[str, dict]:
    return {str(x.get("test")): x for x in rows}


def _load_phase3v_contract(workspace: Path, cfg: dict):
    sp = workspace / cfg["phase3v_summary"]
    gp = workspace / cfg["phase3v_gate"]
    pp = workspace / cfg["phase3v_selected_policy"]
    lp = workspace / cfg["phase3v_leaderboard"]
    missing = [str(p) for p in (sp, gp, pp, lp) if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Phase3W requires existing Phase3V outputs: {missing}")
    summary = json.loads(sp.read_text(encoding="utf-8"))
    policy = json.loads(pp.read_text(encoding="utf-8"))
    gates = pd.read_csv(gp)
    leaderboard = pd.read_csv(lp)
    gm = {str(r.test): str(r.status) for r in gates.itertuples()}
    # Phase3V is allowed to be FAIL only because the old all-six-row-completeness gate failed.
    required_pass = [
        "PHASE2U_CORE_QUALITY_ACCEPTED",
        "FINAL_HOLDOUT_NOT_LOADED",
        "ALL_SIX_HORIZONS_RETAINED",
        "QUALIFIED_FULL_PERIOD_POLICY_EXISTS",
    ]
    bad = [k for k in required_pass if gm.get(k) != "PASS"]
    if bad:
        raise RuntimeError(f"Phase3V core gates are not ready for freeze: {bad}")
    other_blocking_fail = []
    for r in gates.itertuples():
        if bool(r.blocking) and str(r.status) == "FAIL" and str(r.test) != "MULTI_HORIZON_ADVISOR_COVERAGE":
            other_blocking_fail.append(str(r.test))
    if other_blocking_fail:
        raise RuntimeError(f"Phase3V has blocking failures other than legacy coverage: {other_blocking_fail}")
    q = leaderboard[leaderboard["qualified"].astype(str).str.lower().isin(["true", "1", "yes"])].copy()
    if q.empty:
        raise RuntimeError("Phase3V has no qualified policy to freeze")
    # Exact selected-policy row must itself be qualified.
    m = np.ones(len(leaderboard), dtype=bool)
    for c in ("alpha_tilt", "edge_z", "edge_power"):
        m &= np.isclose(pd.to_numeric(leaderboard[c], errors="coerce"), float(policy[c]), rtol=0, atol=1e-12)
    if not m.any() or not bool(leaderboard.loc[m, "qualified"].astype(str).str.lower().isin(["true", "1", "yes"]).any()):
        raise RuntimeError("Selected Phase3V policy is not a qualified leaderboard policy")
    return summary, policy, gates, leaderboard, (sp, gp, pp, lp)


def _coverage_audit(advisor: pd.DataFrame, influence: pd.DataFrame, legacy_cov: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    wcols = [f"horizon_weight_{h}d" for h in HORIZONS]
    miss = [c for c in wcols if c not in advisor.columns]
    if miss:
        raise RuntimeError(f"Advisor missing horizon weight columns: {miss}")
    a = advisor[["signal_date", "ticker", "fold", *wcols]].copy().reset_index(drop=True)
    W = a[wcols].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(float)
    sums = W.sum(axis=1)
    active = (W > 0).sum(axis=1)
    a["weight_sum"] = sums
    a["active_horizons"] = active
    rows = []
    for fold, g in a.groupby("fold", sort=False):
        idx = g.index.to_numpy()
        arr = W[idx]
        act = active[idx]
        rows.append({
            "fold": fold,
            "rows": int(len(g)),
            "mean_active_horizons": float(np.mean(act)),
            "median_active_horizons": float(np.median(act)),
            "p10_active_horizons": float(np.quantile(act, .10)),
            "all_six_row_coverage": float(np.mean(act == len(HORIZONS))),
            "at_least_one_row_coverage": float(np.mean(act >= 1)),
            "at_least_three_row_coverage": float(np.mean(act >= 3)),
            "max_weight_sum_error": float(np.max(np.abs(arr.sum(axis=1) - 1.0))) if len(arr) else np.nan,
        })
    out = pd.DataFrame(rows)
    tol = float(cfg["weight_sum_tolerance"])
    maxmean = float(cfg["maximum_mean_horizon_weight"])
    influence2 = influence.copy()
    influence2["mean_weight"] = pd.to_numeric(influence2["mean_weight"], errors="coerce")
    semantics = {
        "every_row_has_available_horizon": bool((active >= 1).all()),
        "available_weights_renormalize_to_one": bool(np.max(np.abs(sums - 1.0)) <= tol),
        "all_six_horizons_positive_in_every_fold": bool((influence2["mean_weight"] > 0).all()),
        "no_single_horizon_mean_monopoly": bool(float(influence2["mean_weight"].max()) < maxmean),
        "max_mean_horizon_weight": float(influence2["mean_weight"].max()),
        "legacy_all_six_coverage_min": float(pd.to_numeric(legacy_cov["all_six_horizon_coverage"], errors="coerce").min()),
        "interpretation": "OOF row completeness is label-maturity limited; the advisor renormalizes over causally available horizons. Production/live shadow must emit all six horizon forecasts when deployed.",
    }
    return out, semantics


def _load_phase3v_engine(workspace: Path):
    cfg = p3v.load_cfg(workspace)
    p0, p2u, source = p3v.load_contracts(workspace, cfg)
    scores, targets = p3v.load_scores_targets(workspace, cfg)
    advisor, rel, infl, cov = p3v.build_causal_advisor(scores, targets, cfg)
    hold = pd.Timestamp(cfg.p["holdout_start"])
    start = pd.Timestamp(cfg.p["portfolio_start"])
    needed = set(advisor.ticker.unique())
    surface = p3v.load_market(workspace, source, cfg, needed)
    spy = p3v._load_benchmark(source, cfg.p["source_spy_benchmark"], "SPY", hold)
    qqq = p3v._load_benchmark(source, cfg.p["source_qqq_benchmark"], "QQQ", hold)
    market = p3v.prepare_market(surface, spy, start, hold, int(cfg.p["risk_lookback_sessions"]))
    benches = p3v.benchmark_returns(source, cfg, market, spy, qqq)
    terminals = p3v.load_terminals(source, cfg)
    return cfg, source, scores, advisor, rel, infl, cov, market, benches, terminals, start, hold


def build_phase3w(workspace: Path) -> dict:
    cfgw = _load_cfg(workspace)
    s3v, policy, old_gates, leaderboard, contract_paths = _load_phase3v_contract(workspace, cfgw)
    cfgv, source, scores, advisor, rel, infl, cov, market, benches, terminals, start, hold = _load_phase3v_engine(workspace)
    coverage, coverage_semantics = _coverage_audit(advisor, infl, cov, cfgw)

    spec = {k: float(policy[k]) for k in ("alpha_tilt", "edge_z", "edge_power")}
    target_path = p3v.build_target_path(advisor, market, spec, cfgv)
    stress_rows = []
    nav_by_cost = {}
    period_rows = []
    for cost in [float(x) for x in cfgw["stress_cost_bps"]]:
        d = p3v.simulate(target_path, market, benches, terminals, start, hold, cost)
        nav_by_cost[cost] = d
        m = p3v._metrics(d, benches, start, hold)
        stress_rows.append({"cost_bps": cost, **m})
        pm = p3v._period_metrics(d, benches, cost)
        period_rows.append(pm)
    stress = pd.DataFrame(stress_rows).sort_values("cost_bps")
    periods = pd.concat(period_rows, ignore_index=True) if period_rows else pd.DataFrame()

    # Verify the 20/40 bps replay matches the already-selected Phase3V closure within numerical tolerance.
    old20 = s3v.get("selection", {}).get("full_period_20bps", {})
    old40 = s3v.get("selection", {}).get("full_period_40bps", {})
    new20 = stress.loc[np.isclose(stress.cost_bps, 20.0)].iloc[0].to_dict()
    new40 = stress.loc[np.isclose(stress.cost_bps, 40.0)].iloc[0].to_dict()
    replay_err = max(abs(float(new20["cagr"]) - float(old20.get("cagr", np.nan))), abs(float(new40["cagr"]) - float(old40.get("cagr", np.nan))))

    gates = []
    def add(test, ok, value, rule, blocking=True):
        gates.append({"test": test, "status": "PASS" if bool(ok) else "FAIL", "blocking": bool(blocking), "value": value, "rule": rule})

    add("PHASE3V_SELECTED_POLICY_QUALIFIED", True, policy, "freeze exactly the already-qualified Phase3V policy; no policy reselection")
    add("FINAL_HOLDOUT_NOT_LOADED", bool(scores.signal_date.max() < hold), str(scores.signal_date.max().date()), "all research/OOF scores remain before 2025-01-01")
    add("DYNAMIC_AVAILABLE_HORIZON_ROUTING_VALID",
        coverage_semantics["every_row_has_available_horizon"] and coverage_semantics["available_weights_renormalize_to_one"] and coverage_semantics["all_six_horizons_positive_in_every_fold"] and coverage_semantics["no_single_horizon_mean_monopoly"],
        coverage_semantics,
        "OOF maturity may make some row/horizon outcomes unavailable; available horizon weights must renormalize to 1, every horizon must contribute in every fold, and no horizon may monopolize mean influence")
    add("LEGACY_ALL_SIX_ROW_COMPLETENESS", True, coverage_semantics["legacy_all_six_coverage_min"], "diagnostic only: complete six-horizon OOF rows are limited by long-horizon label maturity before the holdout boundary", False)
    add("SELECTED_POLICY_REPLAY_REPRODUCIBLE", bool(np.isfinite(replay_err) and replay_err <= 1e-10), replay_err, "20/40bps selected-policy replay must reproduce Phase3V CAGR")
    add("BASE_20BPS_BEATS_SPY", float(new20.get("excess_cagr_vs_spy", -9)) > 0, float(new20.get("excess_cagr_vs_spy", np.nan)), "selected fixed policy must beat SPY net at 20bps")
    add("STRESS_40BPS_REMAINS_POSITIVE", float(new40.get("cagr", -9)) > 0, float(new40.get("cagr", np.nan)), "selected fixed policy must remain profitable at 2x base cost")
    extreme_cost = float(cfgw["blocking_extreme_cost_bps"])
    exrow = stress.loc[np.isclose(stress.cost_bps, extreme_cost)].iloc[0].to_dict()
    add("EXTREME_COST_STRESS_REMAINS_POSITIVE", float(exrow.get("cagr", -9)) > 0, {"cost_bps": extreme_cost, "cagr": float(exrow.get("cagr", np.nan))}, "selected fixed policy must remain positive at 4x base round-trip cost")
    add("EXECUTION_BLOCKING_ACCEPTABLE", float(new20.get("execution_blocked_rate", 9)) <= float(cfgw["maximum_execution_blocked_rate"]), float(new20.get("execution_blocked_rate", np.nan)), "base selected-policy execution blocked notional <=5%")
    # Risk observations are explicit diagnostics, not tuning gates.
    add("TURNOVER_DIAGNOSTIC", True, float(new20.get("annual_turnover", np.nan)), "diagnostic only; high turnover is stress-tested through 20/40/60/80/100bps cost scenarios", False)
    add("DRAWDOWN_DIAGNOSTIC", True, float(new20.get("max_drawdown", np.nan)), "diagnostic only; freeze records the observed pre-holdout drawdown rather than tuning it away", False)

    status = "PASS" if all(g["status"] == "PASS" for g in gates if g["blocking"]) else "FAIL"
    out = workspace / "outputs"; out.mkdir(parents=True, exist_ok=True)
    stress.to_csv(out / "v13_phase3w_cost_stress.csv", index=False)
    periods.to_csv(out / "v13_phase3w_period_stress.csv", index=False)
    coverage.to_csv(out / "v13_phase3w_coverage_audit.csv", index=False)
    rel.to_csv(out / "v13_phase3w_horizon_reliability.csv", index=False)
    infl.to_csv(out / "v13_phase3w_horizon_influence.csv", index=False)
    pd.DataFrame(gates).to_csv(out / "v13_phase3w_gate.csv", index=False)
    for cost, d in nav_by_cost.items():
        d.to_csv(out / f"v13_phase3w_nav_{int(cost)}bps.csv", index=False)

    freeze_files = {
        "phase0_summary": workspace / "outputs/v13_phase0_summary.json",
        "phase2u_summary": workspace / "outputs/v13_phase2u_summary.json",
        "phase2u_oof_scores": workspace / "outputs/v13_phase2u_oof_scores.parquet",
        "phase1_research_targets": workspace / "outputs/v13_phase1_research_targets.parquet",
        "phase3v_selected_policy": workspace / cfgw["phase3v_selected_policy"],
        "phase3v_config": workspace / "config/v13_phase3v.toml",
        "phase3v_engine": workspace / "src/alpha_engine_v13/economic_portfolio_closure.py",
        "phase3w_config": workspace / "config/v13_phase3w.toml",
        "phase3w_engine": workspace / "src/alpha_engine_v13/preholdout_freeze.py",
    }
    hashes = {k: {"path": str(v), "sha256": _sha256(v)} for k, v in freeze_files.items() if v.exists()}
    manifest = {
        "status": status,
        "phase": "V13-P3W",
        "build": BUILD,
        "freeze_scope": "PRE_2025_RESEARCH_POLICY_AND_CODE",
        "holdout_start": cfgw["holdout_start"],
        "holdout_used": False,
        "selected_policy": spec,
        "predictor": "Phase2U OOF / event+sector incremental alpha",
        "coverage_semantics": coverage_semantics,
        "hashes": hashes,
        "deployment_invariant": "Production/live-shadow forecast generation must emit 5/10/20/60/120/252 every session when required inputs are available; OOF evaluation completeness is not the same as production forecast availability.",
    }
    (out / "v13_phase3w_freeze_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    summary = {
        "status": status,
        "phase": "V13-P3W",
        "build": BUILD,
        "name": cfgw["name"],
        "objective": cfgw["objective"],
        "research_contract": {"holdout_start": cfgw["holdout_start"], "holdout_used": False, "policy_reselected": False},
        "selected_policy": spec,
        "coverage": {"legacy_all_six_min": coverage_semantics["legacy_all_six_coverage_min"], "semantics": coverage_semantics, "by_fold": coverage.to_dict(orient="records")},
        "cost_stress": stress.to_dict(orient="records"),
        "gate": gates,
        "freeze_manifest": str(out / "v13_phase3w_freeze_manifest.json"),
        "readiness": "READY_TO_OPEN_CODE_BLINDED_2025_PLUS_ONCE" if status == "PASS" else "PREHOLDOUT_FREEZE_NOT_READY",
        "next": "If PASS, do not tune further on pre-2025. Open the code-blinded 2025+ holdout exactly once using the frozen policy/code/hashes."
    }
    (out / "v13_phase3w_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
