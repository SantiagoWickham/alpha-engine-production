from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine_v12.edge_lineage import (
    EdgeSpec,
    expected_return_and_se,
    load_config as load_phase7_config,
    net_edge_target,
    prepare_market,
    solve_weight_milp,
)
from alpha_engine_v12.portfolio_policy import _portfolio_metrics, load_price_surface
from alpha_engine_v12.pre_freeze import canonicalize, sha256_payload

PHASE8B_BUILD = "V1_EXECUTION_PARITY_2026-09-12"


@dataclass(frozen=True)
class Phase8BConfig:
    name: str
    objective: str
    phase8_summary_path: str
    phase8_final_model_spec_path: str
    phase8_freeze_manifest_path: str
    phase8_pre_oos_scores_path: str
    return_price_layer_path: str
    terminal_overlay_path: str
    validation_start: pd.Timestamp
    final_oos_start: pd.Timestamp
    maximum_execution_skip_rate: float
    require_milp_success_rate: float
    require_positive_base_cagr: bool
    require_positive_stress_cagr: bool
    require_replay_determinism: bool
    float_decimals: int


def load_config(root: Path) -> Phase8BConfig:
    with (root / "config" / "phase8b.toml").open("rb") as f:
        raw = tomllib.load(f)["phase8b"]
    p = raw["partitions"]
    i = raw["integrity"]
    cfg = Phase8BConfig(
        name=str(raw["name"]),
        objective=str(raw["objective"]),
        phase8_summary_path=str(raw["phase8_summary_path"]),
        phase8_final_model_spec_path=str(raw["phase8_final_model_spec_path"]),
        phase8_freeze_manifest_path=str(raw["phase8_freeze_manifest_path"]),
        phase8_pre_oos_scores_path=str(raw["phase8_pre_oos_scores_path"]),
        return_price_layer_path=str(raw["return_price_layer_path"]),
        terminal_overlay_path=str(raw["terminal_overlay_path"]),
        validation_start=pd.Timestamp(p["validation_start"]).normalize(),
        final_oos_start=pd.Timestamp(p["final_oos_start"]).normalize(),
        maximum_execution_skip_rate=float(i["maximum_execution_skip_rate"]),
        require_milp_success_rate=float(i["require_milp_success_rate"]),
        require_positive_base_cagr=bool(i["require_positive_base_cagr"]),
        require_positive_stress_cagr=bool(i["require_positive_stress_cagr"]),
        require_replay_determinism=bool(i["require_replay_determinism"]),
        float_decimals=int(i["float_decimals"]),
    )
    if not cfg.validation_start < cfg.final_oos_start:
        raise ValueError("Invalid Phase 8B temporal boundary")
    return cfg


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.normalize()


def _norm_ticker(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.upper()


def validate_phase8(summary: dict, spec: dict, manifest: dict, cfg: Phase8BConfig) -> None:
    if summary.get("status") != "PASS" or summary.get("readiness") != "READY_TO_OPEN_FINAL_OOS_ONCE":
        raise RuntimeError("Phase 8 must PASS and be READY_TO_OPEN_FINAL_OOS_ONCE")
    if manifest.get("freeze_status") != "LOCKED_PRE_OOS":
        raise RuntimeError("Phase 8 freeze is not LOCKED_PRE_OOS")
    if bool(manifest.get("final_oos_used")) or bool(summary.get("final_oos_firewall", {}).get("used")):
        raise RuntimeError("Final OOS was already marked used before Phase 8B")
    if pd.Timestamp(manifest.get("final_oos_start")).normalize() != cfg.final_oos_start:
        raise RuntimeError("Phase 8 / Phase 8B final OOS boundary mismatch")
    expected_model = str(manifest.get("model_fingerprint_sha256") or "")
    actual_model = sha256_payload({k: v for k, v in spec.items() if k != "model_fingerprint_sha256"}, cfg.float_decimals)
    if expected_model != actual_model or str(spec.get("model_fingerprint_sha256")) != expected_model:
        raise RuntimeError("Phase 8 model fingerprint mismatch")


def _edge_spec(spec: dict) -> EdgeSpec:
    p = spec["policy"]
    return EdgeSpec(
        entry_floor=float(p["entry_floor"]),
        uncertainty_z=float(p["uncertainty_z"]),
        minimum_extra_edge_bps=float(p["minimum_extra_edge_bps"]),
        max_replacements=int(p["max_replacements_per_session"]),
    )


def load_frozen_scores(root: Path, cfg: Phase8BConfig) -> pd.DataFrame:
    x = pd.read_parquet(root / cfg.phase8_pre_oos_scores_path, columns=["signal_date", "ticker", "alpha_score"])
    x["signal_date"] = _as_date(x["signal_date"])
    x["ticker"] = _norm_ticker(x["ticker"])
    x["alpha_score"] = pd.to_numeric(x["alpha_score"], errors="coerce")
    x = x[(x["signal_date"] >= cfg.validation_start) & (x["signal_date"] < cfg.final_oos_start)].copy()
    x = x[np.isfinite(x["alpha_score"])].sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    if x.empty:
        raise RuntimeError("No Phase 8 validation scores for execution parity")
    if x["signal_date"].max() >= cfg.final_oos_start:
        raise RuntimeError("Phase 8B score load crossed final OOS")
    return x


def calibration_from_spec(spec: dict) -> pd.DataFrame:
    rows = []
    for r in spec.get("edge_calibration", []):
        rows.append({
            "score_center": float(r["score_center"]),
            "isotonic_expected_return_20d": float(r["expected_return_20d"]),
            "hac_se_expected_mean": float(r["hac_se"]),
        })
    out = pd.DataFrame(rows).sort_values("score_center").reset_index(drop=True)
    if len(out) < 2:
        raise RuntimeError("Frozen edge calibration is incomplete")
    return out


def _score_maps(scores: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[pd.Timestamp, dict[str, float]]:
    x = scores[(scores["signal_date"] >= start) & (scores["signal_date"] < end)]
    return {
        pd.Timestamp(d): dict(zip(g["ticker"].astype(str), pd.to_numeric(g["alpha_score"], errors="coerce")))
        for d, g in x.groupby("signal_date", sort=False)
    }


def _weighted_membership_target(
    members: list[str],
    score_map: dict[str, float],
    calib: pd.DataFrame,
    uncertainty_z: float,
    current_weights: dict[str, float],
    p7cfg,
) -> tuple[dict[str, float], dict]:
    names = sorted({str(t) for t in members})
    if len(names) != int(p7cfg.milp_holdings):
        return {}, {"success": False, "message": f"MEMBERSHIP_COUNT_{len(names)}_EXPECTED_{p7cfg.milp_holdings}"}
    lcb = []
    alpha = []
    for t in names:
        s = float(score_map.get(t, np.nan))
        mu, se = expected_return_and_se(s, calib)
        if not (np.isfinite(s) and np.isfinite(mu) and np.isfinite(se)):
            return {}, {"success": False, "message": f"NONFINITE_WEIGHT_INPUT_{t}"}
        alpha.append(s)
        lcb.append(mu - float(uncertainty_z) * se)
    arr = np.asarray(lcb, dtype=float)
    scale = float(np.nanstd(arr))
    if not np.isfinite(scale) or scale < 1e-8:
        scale = 1.0
    med = float(np.nanmedian(arr))
    util = np.exp(np.clip((arr - med) / scale, -2.0, 2.0))
    theoretical = util / util.sum()

    # Continuous max-weight cap, restricted to the already approved membership.
    w = theoretical.copy()
    cap = float(p7cfg.optimizer_max_weight)
    for _ in range(100):
        over = w > cap + 1e-12
        if not over.any():
            break
        fixed_mass = float(over.sum()) * cap
        rem = ~over
        if not rem.any() or fixed_mass >= 1.0:
            break
        old = float(w[rem].sum())
        w[over] = cap
        w[rem] = (1.0 - fixed_mass) * w[rem] / old if old > 0 else (1.0 - fixed_mass) / rem.sum()
    w = w / w.sum()

    layer = pd.DataFrame({
        "ticker": names,
        "alpha_score": alpha,
        "expected_return_lcb": lcb,
        "reference_weight": [1.0 / len(names)] * len(names),
        "theoretical_weight": theoretical,
        "optimizer_weight": w,
    })
    milp, meta = solve_weight_milp(layer, current_weights, p7cfg)
    if not meta.get("success"):
        return {}, meta
    if set(milp) != set(names):
        return {}, {"success": False, "message": "MILP_CHANGED_APPROVED_MEMBERSHIP"}
    return milp, meta


def simulate_execution_parity(
    scores: pd.DataFrame,
    prices: pd.DataFrame,
    terminals: dict[str, pd.Timestamp],
    calib: pd.DataFrame,
    edge: EdgeSpec,
    start: pd.Timestamp,
    end: pd.Timestamp,
    top_n: int,
    round_trip_bps: float,
    p7cfg,
) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    start = pd.Timestamp(start).normalize(); end = pd.Timestamp(end).normalize()
    by_date = _score_maps(scores, start, end)
    market = prepare_market(prices, start, end)
    if len(market.calendar) == 0 or not by_date:
        return _portfolio_metrics(pd.DataFrame()), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    calendar = market.calendar; presence = market.presence; rets = market.returns
    weights: dict[str, float] = {}; cash = 1.0; nav = 1.0
    pending: dict[str, float] | None = None
    rows = []; edges = []; milp_rows = []
    one_way = float(round_trip_bps) / 2.0 / 10000.0

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
                weights = {t: v / total for t, v in vals.items() if v > 1e-14}
                cash = cash / total

        turnover = 0.0; cost_fraction = 0.0; skipped = False
        if pending is not None:
            current = dict(weights)
            trade_names = {t for t in set(current) | set(pending) if abs(float(pending.get(t, 0.0)) - float(current.get(t, 0.0))) > 1e-10}
            executable = all((t in presence.columns and bool(presence.at[d, t])) for t in trade_names)
            if executable:
                traded = float(sum(abs(float(pending.get(t, 0.0)) - float(current.get(t, 0.0))) for t in trade_names))
                turnover = 0.5 * traded
                cost_fraction = one_way * traded
                nav *= max(0.0, 1.0 - cost_fraction)
                weights = {t: float(w) for t, w in pending.items() if w > 1e-12}
                cash = max(0.0, 1.0 - sum(weights.values()))
            else:
                skipped = True
            pending = None

        for t in [t for t in list(weights) if terminals.get(t) == d]:
            cash += weights.pop(t)

        sm = by_date.get(d)
        if sm:
            membership_target, diag = net_edge_target(weights, cash, sm, calib, edge, top_n, round_trip_bps)
            for z in diag:
                edges.append({"signal_date": d, **z})
            old_members = set(weights)
            new_members = {t for t, w in membership_target.items() if w > 1e-12}
            membership_changed = new_members != old_members
            if membership_changed:
                target, meta = _weighted_membership_target(
                    sorted(new_members), sm, calib, edge.uncertainty_z, weights, p7cfg
                )
                milp_rows.append({
                    "signal_date": d,
                    "success": bool(meta.get("success")),
                    "message": str(meta.get("message", "")),
                    "members_before": len(old_members),
                    "members_after": len(new_members),
                    "membership_changes": len(old_members.symmetric_difference(new_members)),
                })
                if meta.get("success"):
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

    daily = pd.DataFrame(rows); edge_df = pd.DataFrame(edges); milp_df = pd.DataFrame(milp_rows)
    met = _portfolio_metrics(daily)
    attempts = int((daily["turnover"] > 1e-12).sum() + daily["execution_skipped"].sum()) if len(daily) else 0
    met["execution_skip_rate"] = float(daily["execution_skipped"].sum() / attempts) if attempts else 0.0
    met["edge_decisions"] = int(len(edge_df)); met["edge_trades"] = int(edge_df["trade"].sum()) if len(edge_df) else 0
    met["milp_calls"] = int(len(milp_df)); met["milp_success_rate"] = float(milp_df["success"].mean()) if len(milp_df) else 0.0
    return met, daily, edge_df, milp_df


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


def build_phase8b(root: Path) -> dict:
    cfg = load_config(root); out = root / "outputs"; out.mkdir(parents=True, exist_ok=True)
    with (root / cfg.phase8_summary_path).open("r", encoding="utf-8") as f: p8 = json.load(f)
    with (root / cfg.phase8_final_model_spec_path).open("r", encoding="utf-8") as f: spec = json.load(f)
    with (root / cfg.phase8_freeze_manifest_path).open("r", encoding="utf-8") as f: manifest = json.load(f)
    validate_phase8(p8, spec, manifest, cfg)

    scores = load_frozen_scores(root, cfg)
    calibration = calibration_from_spec(spec)
    p7cfg = load_phase7_config(root)
    policy = spec["policy"]
    edge = _edge_spec(spec)
    top_n = int(policy["top_n"])
    if int(p7cfg.milp_holdings) != top_n:
        raise RuntimeError("Frozen top_n and MILP holdings must match for execution parity")

    proxy = type("Proxy", (), {
        "return_price_layer_path": cfg.return_price_layer_path,
        "terminal_overlay_path": cfg.terminal_overlay_path,
        "final_oos_start": cfg.final_oos_start,
    })()
    prices, terminals = load_price_surface(root, proxy)

    base, nav1, edges1, milp1 = simulate_execution_parity(
        scores, prices, terminals, calibration, edge, cfg.validation_start, cfg.final_oos_start,
        top_n, float(policy["base_round_trip_cost_bps"]), p7cfg,
    )
    base2, nav2, edges2, milp2 = simulate_execution_parity(
        scores, prices, terminals, calibration, edge, cfg.validation_start, cfg.final_oos_start,
        top_n, float(policy["base_round_trip_cost_bps"]), p7cfg,
    )
    stress, _, _, _ = simulate_execution_parity(
        scores, prices, terminals, calibration, edge, cfg.validation_start, cfg.final_oos_start,
        top_n, float(policy["stress_round_trip_cost_bps"]), p7cfg,
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

    parity_payload = {
        "build": PHASE8B_BUILD,
        "phase8_freeze_fingerprint_sha256": manifest["freeze_fingerprint_sha256"],
        "phase8_model_fingerprint_sha256": manifest["model_fingerprint_sha256"],
        "frozen_model_spec": {k: v for k, v in spec.items() if k != "model_fingerprint_sha256"},
        "execution_weighting": {
            "membership_rule": "FROZEN_EVENT_DRIVEN_NET_EDGE",
            "weighting_rule": "ON_MEMBERSHIP_CHANGE_ONLY: EXPECTED_RETURN_LCB -> CONTINUOUS_CAP -> MILP",
            "membership_may_be_changed_by_milp": False,
            "milp_holdings": int(p7cfg.milp_holdings),
            "milp_min_weight": float(p7cfg.milp_min_weight),
            "milp_max_weight": float(p7cfg.milp_max_weight),
            "milp_weight_step": float(p7cfg.milp_weight_step),
        },
        "final_oos_start": str(cfg.final_oos_start.date()),
        "final_oos_used": False,
    }
    execution_fingerprint = sha256_payload(parity_payload, cfg.float_decimals)
    final_freeze_fingerprint = hashlib.sha256((manifest["freeze_fingerprint_sha256"] + ":" + execution_fingerprint).encode()).hexdigest()

    gate_rows = []
    def add(test, ok, value, rule, blocking=True):
        gate_rows.append({"test": test, "status": "PASS" if ok else "FAIL", "blocking": bool(blocking), "value": value, "rule": rule})
    add("PHASE8_LOCKED", p8.get("status") == "PASS" and manifest.get("freeze_status") == "LOCKED_PRE_OOS", manifest.get("freeze_status"), "Phase 8 must be locked")
    add("FINAL_OOS_STILL_CLOSED", scores["signal_date"].max() < cfg.final_oos_start, str(scores["signal_date"].max().date()), "Phase 8B may not load 2025+ scores")
    add("MILP_EXECUTION_PARITY", float(base.get("milp_success_rate", 0)) >= cfg.require_milp_success_rate, base.get("milp_success_rate"), f"MILP success rate >= {cfg.require_milp_success_rate:.3f}")
    add("EXECUTION_SKIP_RATE", float(base.get("execution_skip_rate", 1)) <= cfg.maximum_execution_skip_rate, base.get("execution_skip_rate"), f"execution skip rate <= {cfg.maximum_execution_skip_rate:.3f}")
    add("BASE_VALIDATION_POSITIVE", (not cfg.require_positive_base_cagr) or float(base.get("cagr", -1)) > 0, base.get("cagr"), "fixed execution-parity implementation must remain positive at base cost")
    add("STRESS_VALIDATION_POSITIVE", (not cfg.require_positive_stress_cagr) or float(stress.get("cagr", -1)) > 0, stress.get("cagr"), "fixed execution-parity implementation must remain positive at stress cost")
    add("DETERMINISTIC_EXECUTION_REPLAY", (not cfg.require_replay_determinism) or deterministic, hashes1, "identical runs must produce identical NAV/edge/MILP hashes")
    gate = pd.DataFrame(gate_rows)
    status = "PASS" if not (gate["blocking"].astype(bool) & gate["status"].eq("FAIL")).any() else "FAIL"
    readiness = "READY_TO_OPEN_FINAL_OOS_ONCE" if status == "PASS" else "NOT_READY_FOR_FINAL_OOS"

    nav1.to_csv(out / "phase8b_execution_parity_nav.csv", index=False)
    edges1.to_csv(out / "phase8b_execution_parity_edge_decisions.csv", index=False)
    milp1.to_csv(out / "phase8b_execution_parity_milp_audit.csv", index=False)
    gate.to_csv(out / "phase8b_gate.csv", index=False)
    pd.DataFrame([
        {"cost_bps": float(policy["base_round_trip_cost_bps"]), **base},
        {"cost_bps": float(policy["stress_round_trip_cost_bps"]), **stress},
    ]).to_csv(out / "phase8b_validation_confirmation.csv", index=False)

    parity_payload["execution_fingerprint_sha256"] = execution_fingerprint
    parity_payload["final_freeze_fingerprint_sha256"] = final_freeze_fingerprint
    (out / "phase8b_execution_model_spec.json").write_text(json.dumps(canonicalize(parity_payload, cfg.float_decimals), indent=2), encoding="utf-8")
    freeze = {
        "build": PHASE8B_BUILD,
        "freeze_status": "LOCKED_PRE_OOS_EXECUTION_PARITY" if status == "PASS" else "NOT_LOCKED",
        "phase8_freeze_fingerprint_sha256": manifest["freeze_fingerprint_sha256"],
        "execution_fingerprint_sha256": execution_fingerprint,
        "final_freeze_fingerprint_sha256": final_freeze_fingerprint,
        "final_oos_start": str(cfg.final_oos_start.date()),
        "final_oos_used": False,
        "deterministic": deterministic,
        "warning": "This supersedes Phase 8 for final OOS execution identity. Do not change model, policy, membership logic, optimizer or MILP before Phase 9.",
    }
    (out / "phase8b_freeze_manifest.json").write_text(json.dumps(canonicalize(freeze, cfg.float_decimals), indent=2), encoding="utf-8")

    summary = {
        "status": status,
        "phase": "8B",
        "build": PHASE8B_BUILD,
        "name": cfg.name,
        "objective": cfg.objective,
        "correction_reason": "Phase 8 lineage audited MILP weights but its NAV replay did not apply MILP weights. Phase 8B enforces research/live execution parity before final OOS is opened.",
        "parameters_reselected": False,
        "phase8_freeze_status": manifest.get("freeze_status"),
        "validation_base": base,
        "validation_stress": stress,
        "execution_parity": {
            "milp_success_rate": base.get("milp_success_rate"),
            "deterministic": deterministic,
            "hashes": hashes1,
        },
        "freeze": freeze,
        "final_oos_firewall": {"final_oos_start": str(cfg.final_oos_start.date()), "used": False},
        "readiness": readiness,
        "next_gate": "If READY_TO_OPEN_FINAL_OOS_ONCE: Phase 9 must use phase8b final freeze identity and open 2025+ once with no tuning.",
    }
    (out / "phase8b_summary.json").write_text(json.dumps(canonicalize(summary, cfg.float_decimals), indent=2), encoding="utf-8")
    return summary
