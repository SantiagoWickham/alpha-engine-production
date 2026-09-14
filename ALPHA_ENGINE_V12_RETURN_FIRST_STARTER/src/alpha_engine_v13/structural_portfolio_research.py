from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

BUILD = "V13_P3S_FAST_STRUCTURAL_REPAIR_2026-09-12"
HORIZONS = (5, 10, 20, 60, 120, 252)


@dataclass(frozen=True)
class Cfg:
    p: dict


def _date(s):
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")


def _ticker(s):
    return s.astype(str).str.upper().str.strip().str.replace(".", "-", regex=False)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_cfg(workspace: Path) -> Cfg:
    with (workspace / "config" / "v13_phase3_structural.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase3_structural"])


def source_root(workspace: Path, cfg: Cfg) -> Path:
    p0 = _load_json(workspace / cfg.p["phase0_summary"])
    if p0.get("status") != "PASS":
        raise RuntimeError("Phase 0 must PASS")
    return Path(p0["source_manifest"]["source_v12_root"])


def load_cached_advisor(workspace: Path, cfg: Cfg) -> pd.DataFrame:
    path = workspace / cfg.p["cached_advisor_surface"]
    if not path.exists():
        raise FileNotFoundError(f"Missing cached advisor surface: {path}")
    x = pd.read_parquet(path)
    x["signal_date"] = _date(x["signal_date"])
    x["ticker"] = _ticker(x["ticker"])
    hold = pd.Timestamp(cfg.p["holdout_start"])
    if (x["signal_date"] >= hold).any():
        raise RuntimeError("HOLDOUT BREACH in cached advisor")
    need_roles = {"POLICY_SELECTION_2021_2022", "VALIDATION_2023_2024"}
    missing = need_roles - set(x["role"].astype(str).unique())
    if missing:
        raise RuntimeError(f"Cached advisor missing roles: {sorted(missing)}")
    required = []
    for h in HORIZONS:
        required += [f"mu_day_{h}d", f"se_day_{h}d", f"alpha_day_{h}d", f"alpha_se_day_{h}d"]
    miss_cols = [c for c in required if c not in x.columns]
    if miss_cols:
        raise RuntimeError(f"Cached advisor missing horizon columns: {miss_cols}")
    return x.sort_values(["signal_date", "ticker"]).reset_index(drop=True)


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


def pre2021_horizon_skill(leader: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for h in HORIZONS:
        ev = leader[
            (leader["horizon_sessions"].astype(int) == h)
            & leader["period"].isin(["EVIDENCE_2017_2018", "OUTER_2019_2020"])
        ].copy()
        arch = _rank_architecture(ev)
        use = ev[ev["architecture"].eq(arch)]
        econ = float(use["economic_score"].mean())
        worst = float(use["worst_cut_robust_excess"].min())
        skill = 0.5 * econ + 0.5 * worst
        rows.append(
            {
                "horizon_sessions": h,
                "architecture": arch,
                "pre2021_economic_score": econ,
                "pre2021_worst_cut_robust_excess": worst,
                "pre2021_skill": skill,
            }
        )
    out = pd.DataFrame(rows)
    sd = float(out["pre2021_skill"].std(ddof=0))
    if not np.isfinite(sd) or sd <= 1e-12:
        out["skill_z"] = 0.0
    else:
        out["skill_z"] = (out["pre2021_skill"] - out["pre2021_skill"].mean()) / sd
    return out


def skill_prior(skill: pd.DataFrame, beta: float, floor: float) -> dict[int, float]:
    if floor < 0 or floor * len(HORIZONS) >= 1:
        raise ValueError("Invalid horizon floor")
    z = skill.set_index("horizon_sessions")["skill_z"].reindex(HORIZONS).fillna(0.0).to_numpy(float)
    logits = beta * z
    logits -= np.nanmax(logits)
    raw = np.exp(logits)
    raw /= raw.sum()
    w = (1.0 - floor * len(HORIZONS)) * raw + floor
    return {h: float(v) for h, v in zip(HORIZONS, w)}


def _softmax_rows(logits: np.ndarray) -> np.ndarray:
    z = logits - np.nanmax(logits, axis=1, keepdims=True)
    e = np.exp(np.clip(z, -40, 40))
    den = e.sum(axis=1, keepdims=True)
    return e / np.where(den > 0, den, 1.0)


def dynamic_reaggregate(
    base: pd.DataFrame,
    prior: dict[int, float],
    signal_gamma: float,
    horizon_floor: float,
) -> pd.DataFrame:
    """Fuse all six horizons for each asset/day without choosing a single horizon.

    A pre-2021 OOF skill prior supplies global reliability. Current per-asset term-structure
    evidence then tilts those weights using both absolute-return and benchmark-alpha z-scores.
    Every horizon retains strictly positive mass through horizon_floor.
    """
    out = base.copy()
    mus = np.column_stack([pd.to_numeric(out[f"mu_day_{h}d"], errors="coerce").to_numpy(float) for h in HORIZONS])
    ses = np.column_stack([pd.to_numeric(out[f"se_day_{h}d"], errors="coerce").to_numpy(float) for h in HORIZONS])
    al = np.column_stack([pd.to_numeric(out[f"alpha_day_{h}d"], errors="coerce").to_numpy(float) for h in HORIZONS])
    ase = np.column_stack([pd.to_numeric(out[f"alpha_se_day_{h}d"], errors="coerce").to_numpy(float) for h in HORIZONS])

    rz = np.divide(mus, ses, out=np.zeros_like(mus), where=np.isfinite(ses) & (ses > 1e-12))
    az = np.divide(al, ase, out=np.zeros_like(al), where=np.isfinite(ase) & (ase > 1e-12))
    rz = np.clip(np.nan_to_num(rz, nan=0.0, posinf=3.0, neginf=-3.0), -3.0, 3.0)
    az = np.clip(np.nan_to_num(az, nan=0.0, posinf=3.0, neginf=-3.0), -3.0, 3.0)

    p = np.asarray([prior[h] for h in HORIZONS], dtype=float)
    p = p / p.sum()
    # Alpha is slightly more informative for benchmark-relative selection; absolute return still matters.
    current_signal = 0.40 * rz + 0.60 * az
    logits = np.log(np.maximum(p, 1e-12))[None, :] + float(signal_gamma) * current_signal
    w = _softmax_rows(logits)
    # The pre-2021 prior already contains the requested floor. Preserve it exactly
    # when gamma=0; with live term-structure tilts, re-impose the same positive floor.
    if horizon_floor > 0 and abs(float(signal_gamma)) > 1e-15:
        w = (1.0 - horizon_floor * len(HORIZONS)) * w + horizon_floor
        w = w / w.sum(axis=1, keepdims=True)

    mu = np.sum(w * mus, axis=1)
    a = np.sum(w * al, axis=1)
    stat = np.sqrt(np.sum((w ** 2) * (ses ** 2), axis=1))
    astat = np.sqrt(np.sum((w ** 2) * (ase ** 2), axis=1))
    disagreement = np.sqrt(np.sum(w * (mus - mu[:, None]) ** 2, axis=1))
    adisagreement = np.sqrt(np.sum(w * (al - a[:, None]) ** 2, axis=1))
    u = np.maximum(stat + disagreement, 1e-8)
    au = np.maximum(astat + adisagreement, 1e-8)

    out["expected_return_per_session"] = mu
    out["uncertainty_per_session"] = u
    out["expected_robust_alpha_per_session"] = a
    out["alpha_uncertainty_per_session"] = au
    out["advisor_conviction_z"] = mu / u
    out["advisor_alpha_z"] = a / au
    out["effective_horizon_sessions"] = np.sum(w * np.asarray(HORIZONS, float)[None, :], axis=1)
    out["horizon_agreement"] = np.sum(w * (mus > 0), axis=1)
    out["alpha_horizon_agreement"] = np.sum(w * (al > 0), axis=1)
    out["term_dispersion"] = disagreement

    for j, h in enumerate(HORIZONS):
        out[f"dynamic_horizon_weight_{h}d"] = w[:, j]

    for name, idx in [("tactical", [0, 1, 2]), ("strategic", [3, 4, 5])]:
        ww = w[:, idx]
        ww = ww / ww.sum(axis=1, keepdims=True)
        out[f"{name}_expected_return_per_session"] = np.sum(ww * mus[:, idx], axis=1)
        out[f"{name}_expected_robust_alpha_per_session"] = np.sum(ww * al[:, idx], axis=1)
        out[f"{name}_positive_share"] = np.sum(ww * (mus[:, idx] > 0), axis=1)
    return out


def _read_provider_cache(cache_dir: Path, tickers: set[str], hold: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for t in sorted(tickers):
        p = cache_dir / f"{t.replace('/', '_').replace(chr(92), '_')}.parquet"
        if not p.exists():
            continue
        try:
            cols = ["date", "ticker", "close", "adj_close"]
            x = pd.read_parquet(p, columns=cols)
        except Exception:
            continue
        x["date"] = _date(x["date"])
        x["ticker"] = _ticker(x["ticker"])
        x["close"] = pd.to_numeric(x["close"], errors="coerce")
        x["adj_close"] = pd.to_numeric(x["adj_close"], errors="coerce")
        x = x[(x["date"] < hold) & x["ticker"].isin(tickers)]
        if len(x):
            rows.append(x)
    if not rows:
        return pd.DataFrame(columns=["date", "ticker", "provider_close", "provider_adj_close"])
    y = pd.concat(rows, ignore_index=True).drop_duplicates(["date", "ticker"], keep="last")
    return y.rename(columns={"close": "provider_close", "adj_close": "provider_adj_close"})


def build_execution_surface(source: Path, workspace: Path, cfg: Cfg, advisor: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create one cached pre-2025 market surface.

    Execution availability uses only observable raw closes. Mark-to-market uses total-return /
    adjusted histories when available. No target adjusted price is ever used as execution price.
    """
    cache_path = workspace / cfg.p["execution_surface_cache"]
    audit_path = workspace / "outputs" / "v13_phase3s_execution_source_audit.csv"
    hold = pd.Timestamp(cfg.p["holdout_start"])
    needed_tickers = set(advisor["ticker"].astype(str).unique())

    if cache_path.exists():
        x = pd.read_parquet(cache_path)
        x["date"] = _date(x["date"])
        x["ticker"] = _ticker(x["ticker"])
        if (x["date"] >= hold).any():
            raise RuntimeError("HOLDOUT BREACH in cached execution surface")
        audit = pd.read_csv(audit_path) if audit_path.exists() else pd.DataFrame()
        return x, audit

    cpath = source / cfg.p["source_canonical_pit_panel"]
    ppath = source / cfg.p["source_return_price_layer"]
    c = pd.read_parquet(cpath, columns=["date", "ticker", "close", "adj_close", "research_eligible"])
    c["date"] = _date(c["date"]); c["ticker"] = _ticker(c["ticker"])
    c = c[(c["date"] < hold) & c["ticker"].isin(needed_tickers)].copy()
    for col in ["close", "adj_close"]:
        c[col] = pd.to_numeric(c[col], errors="coerce")
    c["research_eligible"] = c["research_eligible"].fillna(False).astype(bool)
    c = c.rename(columns={"close": "canonical_close", "adj_close": "canonical_adj", "research_eligible": "canonical_eligible"})
    c = c.drop_duplicates(["date", "ticker"], keep="last")

    p = pd.read_parquet(ppath, columns=["date", "ticker", "close", "target_total_return_price", "research_eligible"])
    p["date"] = _date(p["date"]); p["ticker"] = _ticker(p["ticker"])
    p = p[(p["date"] < hold) & p["ticker"].isin(needed_tickers)].copy()
    p["close"] = pd.to_numeric(p["close"], errors="coerce")
    p["target_total_return_price"] = pd.to_numeric(p["target_total_return_price"], errors="coerce")
    p["research_eligible"] = p["research_eligible"].fillna(False).astype(bool)
    p = p.rename(columns={"close": "phase2c_close", "target_total_return_price": "phase2c_total_return", "research_eligible": "phase2c_eligible"})
    p = p.drop_duplicates(["date", "ticker"], keep="last")

    provider = _read_provider_cache(source / cfg.p["adjusted_cache_dir"], needed_tickers, hold)

    x = c.merge(p, on=["date", "ticker"], how="outer").merge(provider, on=["date", "ticker"], how="outer")
    for col in ["canonical_close", "canonical_adj", "phase2c_close", "phase2c_total_return", "provider_close", "provider_adj_close"]:
        if col not in x:
            x[col] = np.nan
        x[col] = pd.to_numeric(x[col], errors="coerce")

    x["execution_close"] = x["canonical_close"].where(x["canonical_close"] > 0)
    x["execution_source"] = np.where(x["execution_close"].notna(), "CANONICAL_CLOSE", "")
    m = x["execution_close"].isna() & (x["phase2c_close"] > 0)
    x.loc[m, "execution_close"] = x.loc[m, "phase2c_close"]
    x.loc[m, "execution_source"] = "PHASE2C_CLOSE"
    m = x["execution_close"].isna() & (x["provider_close"] > 0)
    x.loc[m, "execution_close"] = x.loc[m, "provider_close"]
    x.loc[m, "execution_source"] = "PROVIDER_RAW_CLOSE"

    # Marking / return layer. Adjusted or total-return data are allowed here, never for execution.
    x["mark_price"] = x["phase2c_total_return"].where(x["phase2c_total_return"] > 0)
    x["mark_source"] = np.where(x["mark_price"].notna(), "PHASE2C_TOTAL_RETURN", "")
    for col, name in [
        ("canonical_adj", "CANONICAL_ADJ"),
        ("provider_adj_close", "PROVIDER_ADJ"),
        ("canonical_close", "CANONICAL_CLOSE"),
        ("phase2c_close", "PHASE2C_CLOSE"),
        ("provider_close", "PROVIDER_RAW_CLOSE"),
    ]:
        m = x["mark_price"].isna() & (x[col] > 0)
        x.loc[m, "mark_price"] = x.loc[m, col]
        x.loc[m, "mark_source"] = name

    ce = x.get("canonical_eligible", pd.Series(False, index=x.index)).fillna(False).astype(bool)
    pe = x.get("phase2c_eligible", pd.Series(False, index=x.index)).fillna(False).astype(bool)
    x["research_eligible"] = ce | pe
    x = x[["date", "ticker", "execution_close", "mark_price", "research_eligible", "execution_source", "mark_source"]].drop_duplicates(["date", "ticker"], keep="last")
    x = x.sort_values(["date", "ticker"]).reset_index(drop=True)
    if (x["date"] >= hold).any():
        raise RuntimeError("HOLDOUT BREACH while constructing execution surface")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    x.to_parquet(cache_path, index=False)
    audit = pd.DataFrame([
        {"metric": "rows", "value": int(len(x))},
        {"metric": "tickers", "value": int(x["ticker"].nunique())},
        {"metric": "execution_close_coverage", "value": float(x["execution_close"].notna().mean())},
        {"metric": "mark_price_coverage", "value": float(x["mark_price"].notna().mean())},
    ])
    for name, n in x["execution_source"].value_counts(dropna=False).items():
        audit.loc[len(audit)] = {"metric": f"execution_source::{name or 'MISSING'}", "value": int(n)}
    for name, n in x["mark_source"].value_counts(dropna=False).items():
        audit.loc[len(audit)] = {"metric": f"mark_source::{name or 'MISSING'}", "value": int(n)}
    audit.to_csv(audit_path, index=False)
    return x, audit


def _load_benchmark_price(source: Path, rel: str, symbol: str, hold: pd.Timestamp) -> pd.Series:
    x = pd.read_parquet(source / rel)
    x["date"] = _date(x["date"])
    x[symbol] = pd.to_numeric(x[symbol], errors="coerce")
    x = x[(x["date"] < hold) & x[symbol].notna() & (x[symbol] > 0)]
    return x.drop_duplicates("date", keep="last").set_index("date")[symbol].sort_index()


def prepare_market(surface: pd.DataFrame, spy_price: pd.Series, start: pd.Timestamp, end: pd.Timestamp, lookback: int):
    cal_all = pd.DatetimeIndex(spy_price.index[(spy_price.index < end)].unique()).sort_values()
    prior = cal_all[cal_all < start]
    lb = prior[max(0, len(prior) - lookback - 5)] if len(prior) else start
    cal = cal_all[(cal_all >= lb) & (cal_all < end)]
    x = surface[(surface["date"] >= lb) & (surface["date"] < end)].copy()
    mp = x.pivot_table(index="date", columns="ticker", values="mark_price", aggfunc="last").reindex(cal)
    ex = x.pivot_table(index="date", columns="ticker", values="execution_close", aggfunc="last").reindex(cal)
    elig = x.pivot_table(index="date", columns="ticker", values="research_eligible", aggfunc="last").reindex(cal)
    elig = elig.fillna(False).astype(bool)
    mpff = mp.ffill(limit=5)
    ret = mpff.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    # Keep missing marks as NaN for risk/benchmark cross-sections. The simulator itself
    # treats an unavailable daily mark as 0 for an existing holding until marking resumes.
    ret = ret.where(mp.notna())
    return {"calendar": cal, "returns": ret, "execution_presence": ex.notna(), "research_eligible": elig, "mark_price": mp, "execution_close": ex}


def execution_next_session_audit(advisor: pd.DataFrame, market: dict, selection_start: pd.Timestamp, hold: pd.Timestamp) -> pd.DataFrame:
    cal = pd.DatetimeIndex(market["calendar"])
    pos = {pd.Timestamp(d): i for i, d in enumerate(cal)}
    pres = market["execution_presence"]
    rows = []
    for role, g in advisor.groupby("role"):
        total = 0; ok = 0
        for d, gg in g.groupby("signal_date"):
            d = pd.Timestamp(d)
            i = pos.get(d)
            if i is None or i + 1 >= len(cal):
                continue
            nd = cal[i + 1]
            p = pres.loc[nd] if nd in pres.index else pd.Series(dtype=bool)
            vals = [bool(p.get(t, False)) for t in gg["ticker"].astype(str)]
            total += len(vals); ok += int(sum(vals))
        rows.append({"role": role, "advisor_keys": total, "next_session_execution_available": ok, "next_session_execution_coverage": ok / total if total else np.nan})
    return pd.DataFrame(rows)


def benchmark_series(source: Path, cfg: Cfg, market: dict, spy_price: pd.Series, qqq_price: pd.Series):
    out = {
        "SPY": spy_price.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan),
        "QQQ": qqq_price.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan),
    }
    r = market["returns"]
    prev_elig = market["research_eligible"].shift(1).fillna(False).astype(bool)
    out["UNIVERSE_EQUAL_WEIGHT"] = r.where(prev_elig).mean(axis=1, skipna=True)
    return out


def benchmark_metrics(s: pd.Series, start: pd.Timestamp, end: pd.Timestamp):
    x = s[(s.index >= start) & (s.index < end)].dropna()
    if x.empty:
        return {"cagr": math.nan, "total_return": math.nan}
    nav = (1.0 + x).cumprod()
    return {"cagr": float(nav.iloc[-1] ** (252.0 / len(nav)) - 1.0), "total_return": float(nav.iloc[-1] - 1.0)}


def prepare_risk(market: dict, spy_ret: pd.Series, lookback: int, min_obs: int):
    r = market["returns"]
    m = spy_ret.reindex(r.index)
    mv = m.rolling(lookback, min_periods=min_obs).var().clip(lower=1e-8)
    beta = pd.DataFrame(index=r.index, columns=r.columns, dtype="float32")
    idio = pd.DataFrame(index=r.index, columns=r.columns, dtype="float32")
    for t in r.columns:
        rr = r[t]
        cov = rr.rolling(lookback, min_periods=min_obs).cov(m)
        vr = rr.rolling(lookback, min_periods=min_obs).var()
        b = (cov / mv).replace([np.inf, -np.inf], np.nan)
        iv = (vr - b * b * mv).clip(lower=1e-6)
        beta[t] = b.astype("float32")
        idio[t] = iv.astype("float32")
    return {"beta": beta, "idio": idio, "market_var": mv}


def risk_stats(risk: dict, d: pd.Timestamp, names: list[str]):
    if d in risk["beta"].index:
        b = risk["beta"].loc[d].reindex(names).to_numpy(float)
        iv = risk["idio"].loc[d].reindex(names).to_numpy(float)
    else:
        b = np.full(len(names), np.nan); iv = np.full(len(names), np.nan)
    vm = float(risk["market_var"].get(d, np.nan))
    b = np.where(np.isfinite(b), b, 1.0)
    iv = np.where(np.isfinite(iv), np.maximum(iv, 1e-6), 0.0004)
    vm = vm if np.isfinite(vm) and vm > 0 else 0.0001
    return b, iv, vm


def kelly(signal: dict[str, float], beta: np.ndarray, idio: np.ndarray, vm: float):
    names = list(signal)
    mu = np.asarray([max(0.0, float(signal[t])) for t in names], float)
    if not names or not np.any(mu > 0):
        return {}
    di = 1.0 / np.maximum(np.asarray(idio, float), 1e-8)
    b = np.asarray(beta, float)
    vm = max(float(vm), 1e-8)
    dm = di * mu; db = di * b
    den = 1.0 / vm + float(np.dot(b, db))
    raw = dm - db * (float(np.dot(b, dm)) / den)
    raw = np.maximum(raw, 0.0)
    if raw.sum() <= 0:
        raw = np.maximum(dm, 0.0)
    if raw.sum() <= 0:
        return {}
    if raw.sum() > 1.0:
        raw = raw / raw.sum()
    return {t: float(w) for t, w in zip(names, raw) if w > 1e-10}


def build_target_path(advisor: pd.DataFrame, risk: dict, return_z_gate: float, alpha_z_gate: float, alpha_tilt: float):
    out = {}
    for d, g in advisor.groupby("signal_date", sort=False):
        q = g.set_index("ticker")
        mu = pd.to_numeric(q["expected_return_per_session"], errors="coerce")
        se = pd.to_numeric(q["uncertainty_per_session"], errors="coerce")
        a = pd.to_numeric(q["expected_robust_alpha_per_session"], errors="coerce")
        ase = pd.to_numeric(q["alpha_uncertainty_per_session"], errors="coerce")
        rz = mu / se.replace(0, np.nan)
        az = a / ase.replace(0, np.nan)
        mask = np.isfinite(mu) & np.isfinite(rz) & (mu > 0) & (rz >= float(return_z_gate))
        if alpha_z_gate > -90:
            mask &= np.isfinite(az) & (az >= float(alpha_z_gate))
        names = q.index[mask]
        signal = {}
        for t in names:
            aval = float(a.loc[t]) if np.isfinite(a.loc[t]) else 0.0
            s = float(mu.loc[t] + float(alpha_tilt) * aval)
            if np.isfinite(s) and s > 0:
                signal[str(t)] = s
        if signal:
            names2 = list(signal)
            b, iv, vm = risk_stats(risk, pd.Timestamp(d), names2)
            out[pd.Timestamp(d)] = kelly(signal, b, iv, vm)
        else:
            out[pd.Timestamp(d)] = {}
    return out


def partial_target(cur: dict[str, float], des: dict[str, float], pres: pd.Series):
    cur = {str(t): max(0.0, float(w)) for t, w in cur.items() if float(w) > 1e-14}
    des = {str(t): max(0.0, float(w)) for t, w in des.items() if float(w) > 1e-14}
    uni = set(cur) | set(des)
    requested = float(sum(abs(des.get(t, 0.0) - cur.get(t, 0.0)) for t in uni))
    if requested <= 1e-14:
        return dict(cur), {"requested": 0.0, "executed": 0.0, "blocked_requested": 0.0, "target_deviation": 0.0, "blocked_names": 0, "full_skip": False, "partial": False}
    trade = {t for t in uni if abs(des.get(t, 0.0) - cur.get(t, 0.0)) > 1e-12}
    unavailable = {t for t in trade if not bool(pres.get(t, False))}
    blocked = float(sum(abs(des.get(t, 0.0) - cur.get(t, 0.0)) for t in unavailable))
    locked = {t: cur[t] for t in unavailable if cur.get(t, 0.0) > 1e-14}
    free = max(0.0, 1.0 - sum(locked.values()))
    dex = {t: w for t, w in des.items() if t not in unavailable}
    ds = float(sum(dex.values()))
    scale = min(1.0, free / ds) if ds > 1e-14 else 0.0
    actual = dict(locked)
    actual.update({t: w * scale for t, w in dex.items() if w * scale > 1e-14})
    sm = float(sum(actual.values()))
    if sm > 1.0 + 1e-10:
        actual = {t: w / sm for t, w in actual.items()}
    executed = float(sum(abs(actual.get(t, 0.0) - cur.get(t, 0.0)) for t in set(cur) | set(actual)))
    deviation = float(sum(abs(des.get(t, 0.0) - actual.get(t, 0.0)) for t in uni))
    return actual, {
        "requested": requested,
        "executed": executed,
        "blocked_requested": blocked,
        "target_deviation": deviation,
        "blocked_names": len(unavailable),
        "full_skip": executed <= 1e-12 and requested > 1e-12,
        "partial": blocked > 1e-12,
    }


def load_terminals(source: Path, cfg: Cfg):
    path = source / cfg.p["source_terminal_overlay"]
    if not path.exists():
        return {}
    x = pd.read_csv(path)
    if x.empty or "ticker" not in x or "terminal_price_date" not in x:
        return {}
    x["ticker"] = _ticker(x["ticker"]); x["terminal_price_date"] = _date(x["terminal_price_date"])
    if "overlay_validated" in x:
        v = x["overlay_validated"]
        if v.dtype != bool:
            v = v.astype(str).str.lower().isin(["true", "1", "yes"])
        x = x[v]
    return {str(r.ticker): pd.Timestamp(r.terminal_price_date) for r in x.dropna(subset=["terminal_price_date"]).itertuples()}


def simulate(
    advisor: pd.DataFrame,
    market: dict,
    benches: dict,
    terminals: dict,
    start: pd.Timestamp,
    end: pd.Timestamp,
    round_trip_bps: float,
    target_path: dict,
    initial_weights: dict[str, float] | None = None,
    initial_cash: float = 1.0,
):
    cal = market["calendar"][(market["calendar"] >= start) & (market["calendar"] < end)]
    ret = market["returns"]; pres = market["execution_presence"]
    by = {pd.Timestamp(d): g.set_index("ticker") for d, g in advisor[(advisor["signal_date"] >= start) & (advisor["signal_date"] < end)].groupby("signal_date", sort=False)}
    w = dict(initial_weights or {}); cash = float(initial_cash); nav = 1.0; pending = None
    one = float(round_trip_bps) / 2.0 / 10000.0
    rows = []
    for d in cal:
        d = pd.Timestamp(d); prev_nav = nav
        # Mark current holdings through today's close/mark.
        if w:
            rr = ret.loc[d]
            gross = sum(v * (float(rr.get(t, 0.0)) if np.isfinite(rr.get(t, np.nan)) else 0.0) for t, v in w.items())
        else:
            gross = 0.0
        nav *= max(0.0, 1.0 + gross)
        if w:
            vals = {t: v * (1.0 + (float(ret.at[d, t]) if t in ret.columns and np.isfinite(ret.at[d, t]) else 0.0)) for t, v in w.items()}
            total = cash + sum(vals.values())
            if total > 0:
                w = {t: v / total for t, v in vals.items() if v > 1e-14}; cash = cash / total

        meta = {"requested": 0.0, "executed": 0.0, "blocked_requested": 0.0, "target_deviation": 0.0, "blocked_names": 0, "full_skip": False, "partial": False}
        turnover = 0.0; cost = 0.0
        if pending is not None:
            presence = pres.loc[d] if d in pres.index else pd.Series(dtype=bool)
            actual, meta = partial_target(w, pending, presence)
            if meta["executed"] > 1e-12:
                turnover = 0.5 * meta["executed"]
                cost = one * meta["executed"]
                nav *= max(0.0, 1.0 - cost)
                w = {t: float(v) for t, v in actual.items() if v > 1e-10}
                cash = max(0.0, 1.0 - sum(w.values()))
            pending = None

        # Validated terminal date: last marked value is converted to cash.
        for t in [t for t in list(w) if terminals.get(t) == d]:
            cash += w.pop(t)

        g = by.get(d); decision = False; benefit = 0.0
        if g is not None and len(g):
            target = target_path.get(d, {})
            uni = set(w) | set(target)
            delta = {t: target.get(t, 0.0) - w.get(t, 0.0) for t in uni}
            # The target path already embeds alpha tilt. Rebalance benefit uses current expected absolute return.
            mu = {t: (float(g["expected_return_per_session"].get(t, 0.0)) if t in g.index and np.isfinite(g["expected_return_per_session"].get(t, np.nan)) else 0.0) for t in uni}
            eff = {t: (float(g["effective_horizon_sessions"].get(t, 1.0)) if t in g.index and np.isfinite(g["effective_horizon_sessions"].get(t, np.nan)) else 1.0) for t in uni}
            benefit = float(sum(delta[t] * mu[t] * eff[t] for t in uni))
            est = one * float(sum(abs(v) for v in delta.values()))
            forced_exit = any(t not in g.index for t in w)
            if sum(abs(v) for v in delta.values()) > 1e-10 and (forced_exit or benefit > est):
                pending = target; decision = True

        rows.append({
            "date": d, "nav": nav, "net_return": nav / prev_nav - 1.0 if prev_nav > 0 else -1.0,
            "turnover": turnover, "cost_fraction": cost, "holdings": len(w), "cash_weight": cash,
            "max_name_weight": max(w.values()) if w else 0.0, "rebalance_scheduled": int(decision),
            "requested_trade_notional": meta["requested"], "executed_trade_notional": meta["executed"],
            "blocked_requested_notional": meta["blocked_requested"], "target_deviation_notional": meta["target_deviation"],
            "blocked_trade_names": meta["blocked_names"], "partial_execution": int(meta["partial"]), "full_skip": int(meta["full_skip"]),
            "expected_incremental_return": benefit,
        })

    daily = pd.DataFrame(rows)
    n = len(daily); nv = float(daily["nav"].iloc[-1]) if n else np.nan; yrs = n / 252.0 if n else np.nan
    m = {
        "days": n,
        "total_return": nv - 1.0 if n else np.nan,
        "cagr": nv ** (252.0 / n) - 1.0 if n and nv > 0 else np.nan,
        "max_drawdown": float((daily["nav"] / daily["nav"].cummax() - 1.0).min()) if n else np.nan,
        "annual_turnover": float(daily["turnover"].sum() / yrs) if n else np.nan,
        "trade_days": int((daily["turnover"] > 1e-12).sum()) if n else 0,
        "median_holdings": float(daily["holdings"].median()) if n else 0.0,
        "max_holdings": int(daily["holdings"].max()) if n else 0,
        "mean_cash_weight": float(daily["cash_weight"].mean()) if n else 1.0,
        "median_max_name_weight": float(daily["max_name_weight"].median()) if n else 0.0,
        "p95_max_name_weight": float(daily["max_name_weight"].quantile(0.95)) if n else 0.0,
        "scheduled_rebalances": int(daily["rebalance_scheduled"].sum()) if n else 0,
        "partial_execution_days": int(daily["partial_execution"].sum()) if n else 0,
        "full_execution_skip_days": int(daily["full_skip"].sum()) if n else 0,
        "blocked_trade_names": int(daily["blocked_trade_names"].sum()) if n else 0,
    }
    req = float(daily["requested_trade_notional"].sum()) if n else 0.0
    exe = float(daily["executed_trade_notional"].sum()) if n else 0.0
    blk = float(daily["blocked_requested_notional"].sum()) if n else 0.0
    dev = float(daily["target_deviation_notional"].sum()) if n else 0.0
    m.update({
        "requested_trade_notional": req, "executed_trade_notional": exe,
        "blocked_requested_notional": blk, "target_deviation_notional": dev,
        "execution_blocked_requested_rate": blk / req if req > 1e-14 else 0.0,
        "target_deviation_rate": dev / req if req > 1e-14 else 0.0,
    })
    for k, s in benches.items():
        bm = benchmark_metrics(s, start, end)
        key = k.lower()
        m[f"{key}_cagr"] = bm["cagr"]
        m[f"excess_cagr_vs_{key}"] = m["cagr"] - bm["cagr"] if np.isfinite(m["cagr"]) and np.isfinite(bm["cagr"]) else np.nan
    ex = [m.get("excess_cagr_vs_spy"), m.get("excess_cagr_vs_qqq"), m.get("excess_cagr_vs_universe_equal_weight")]
    m["robust_excess_cagr"] = float(np.nanmin(ex))
    return m, daily, w, cash


def horizon_influence(advisor: pd.DataFrame, role: str):
    x = advisor[advisor["role"].eq(role)] if "role" in advisor.columns else advisor
    rows = []
    for h in HORIZONS:
        c = f"dynamic_horizon_weight_{h}d"
        rows.append({
            "role": role,
            "horizon_sessions": h,
            "mean_weight": float(pd.to_numeric(x[c], errors="coerce").mean()),
            "median_weight": float(pd.to_numeric(x[c], errors="coerce").median()),
            "p10_weight": float(pd.to_numeric(x[c], errors="coerce").quantile(0.10)),
            "p90_weight": float(pd.to_numeric(x[c], errors="coerce").quantile(0.90)),
        })
    return rows


def outer_2021_2022_horizon_evidence(leader: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for h in HORIZONS:
        pre=leader[(leader["horizon_sessions"].astype(int)==h) & leader["period"].isin(["EVIDENCE_2017_2018","OUTER_2019_2020"])].copy()
        arch=_rank_architecture(pre)
        o=leader[(leader["horizon_sessions"].astype(int)==h) & leader["period"].eq("OUTER_2021_2022") & leader["architecture"].eq(arch)]
        if len(o):
            r=o.iloc[0]
            rows.append({"horizon_sessions":h,"architecture_used":arch,"economic_score":float(r["economic_score"]),"worst_cut_robust_excess":float(r["worst_cut_robust_excess"]),"mean_rank_ic":float(r["mean_rank_ic"]),"positive_cut_share":float(r.get("positive_cut_share",np.nan))})
    return pd.DataFrame(rows)


def candidate_specs(cfg: Cfg):
    rows = []
    for gamma in cfg.p["signal_gamma_grid"]:
        for rz in cfg.p["return_z_gate_grid"]:
            for az in cfg.p["alpha_z_gate_grid"]:
                for tilt in cfg.p["alpha_tilt_grid"]:
                    rows.append({
                        "signal_gamma": float(gamma),
                        "return_z_gate": float(rz),
                        "alpha_z_gate": float(az),
                        "alpha_tilt": float(tilt),
                    })
    return rows


def build_structural(workspace: Path):
    cfg = load_cfg(workspace)
    source = source_root(workspace, cfg)
    p2 = _load_json(workspace / cfg.p["phase2_summary"])
    if p2.get("status") != "PASS":
        raise RuntimeError("Phase 2 must PASS")

    cached = load_cached_advisor(workspace, cfg)
    leader = pd.read_csv(workspace / cfg.p["phase2_leaderboard"])
    skill = pre2021_horizon_skill(leader)
    oof_2021_2022 = outer_2021_2022_horizon_evidence(leader)
    prior = skill_prior(skill, float(cfg.p["pre2021_skill_beta"]), float(cfg.p["horizon_weight_floor"]))

    surface, source_audit = build_execution_surface(source, workspace, cfg, cached)
    hold = pd.Timestamp(cfg.p["holdout_start"])
    start = pd.Timestamp(cfg.p["selection_start"])
    val = pd.Timestamp(cfg.p["validation_start"])
    spy_price = _load_benchmark_price(source, cfg.p["source_spy_benchmark"], "SPY", hold)
    qqq_price = _load_benchmark_price(source, cfg.p["source_qqq_benchmark"], "QQQ", hold)
    market = prepare_market(surface, spy_price, start, hold, int(cfg.p["risk_lookback_sessions"]))
    benches = benchmark_series(source, cfg, market, spy_price, qqq_price)
    risk = prepare_risk(market, benches["SPY"], int(cfg.p["risk_lookback_sessions"]), int(cfg.p["minimum_risk_observations"]))
    terminals = load_terminals(source, cfg)

    exec_audit = execution_next_session_audit(cached, market, start, hold)
    out = workspace / "outputs"; out.mkdir(parents=True, exist_ok=True)
    exec_audit.to_csv(out / "v13_phase3s_next_session_execution_audit.csv", index=False)

    sel0 = cached[cached["role"].eq("POLICY_SELECTION_2021_2022")].copy()
    val0 = cached[cached["role"].eq("VALIDATION_2023_2024")].copy()
    gammas = sorted(set(float(x) for x in cfg.p["signal_gamma_grid"]))
    sel_modes = {g: dynamic_reaggregate(sel0, prior, g, float(cfg.p["horizon_weight_floor"])) for g in gammas}
    val_modes = {g: dynamic_reaggregate(val0, prior, g, float(cfg.p["horizon_weight_floor"])) for g in gammas}

    specs = candidate_specs(cfg)
    target_cache = {}
    rows = []
    base_cost = float(cfg.p["base_round_trip_cost_bps"])
    stress_cost = float(cfg.p["stress_round_trip_cost_bps"])
    max_block = float(cfg.p["maximum_execution_blocked_rate"])

    for i, spec in enumerate(specs, 1):
        g = spec["signal_gamma"]
        a = sel_modes[g]
        key = (g, spec["return_z_gate"], spec["alpha_z_gate"], spec["alpha_tilt"])
        if key not in target_cache:
            target_cache[key] = build_target_path(a, risk, spec["return_z_gate"], spec["alpha_z_gate"], spec["alpha_tilt"])
        tp = target_cache[key]
        b, _, _, _ = simulate(a, market, benches, terminals, start, val, base_cost, tp)
        st, _, _, _ = simulate(a, market, benches, terminals, start, val, stress_cost, tp)
        qualified = (
            b["robust_excess_cagr"] > 0
            and st["robust_excess_cagr"] > 0
            and b["execution_blocked_requested_rate"] <= max_block
        )
        rows.append({
            **spec,
            "cagr_20bps": b["cagr"],
            "robust_excess_cagr_20bps": b["robust_excess_cagr"],
            "excess_vs_spy_20bps": b["excess_cagr_vs_spy"],
            "excess_vs_qqq_20bps": b["excess_cagr_vs_qqq"],
            "excess_vs_uew_20bps": b["excess_cagr_vs_universe_equal_weight"],
            "cagr_40bps": st["cagr"],
            "robust_excess_cagr_40bps": st["robust_excess_cagr"],
            "max_drawdown_20bps": b["max_drawdown"],
            "annual_turnover_20bps": b["annual_turnover"],
            "median_holdings_20bps": b["median_holdings"],
            "max_holdings_20bps": b["max_holdings"],
            "median_max_name_weight_20bps": b["median_max_name_weight"],
            "p95_max_name_weight_20bps": b["p95_max_name_weight"],
            "mean_cash_weight_20bps": b["mean_cash_weight"],
            "execution_blocked_rate_20bps": b["execution_blocked_requested_rate"],
            "target_deviation_rate_20bps": b["target_deviation_rate"],
            "qualified": bool(qualified),
        })
        if i % 12 == 0 or i == len(specs):
            print(f"STRUCTURAL replay policies: {i}/{len(specs)}")

    lb = pd.DataFrame(rows).sort_values(
        ["qualified", "robust_excess_cagr_20bps", "robust_excess_cagr_40bps", "cagr_20bps", "max_drawdown_20bps", "annual_turnover_20bps"],
        ascending=[False, False, False, False, False, True],
    ).reset_index(drop=True)
    lb["return_first_rank"] = np.arange(1, len(lb) + 1)
    champ = lb.iloc[0].to_dict()
    spec = {k: float(champ[k]) for k in ["signal_gamma", "return_z_gate", "alpha_z_gate", "alpha_tilt"]}

    a_sel = sel_modes[spec["signal_gamma"]]
    a_val = val_modes[spec["signal_gamma"]]
    tp_sel = target_cache[(spec["signal_gamma"], spec["return_z_gate"], spec["alpha_z_gate"], spec["alpha_tilt"])]
    tp_val = build_target_path(a_val, risk, spec["return_z_gate"], spec["alpha_z_gate"], spec["alpha_tilt"])

    sb, snav, cw, cc = simulate(a_sel, market, benches, terminals, start, val, base_cost, tp_sel)
    vb, vnav, _, _ = simulate(a_val, market, benches, terminals, val, hold, base_cost, tp_val, cw, cc)
    ss, _, cws, ccs = simulate(a_sel, market, benches, terminals, start, val, stress_cost, tp_sel)
    vs, _, _, _ = simulate(a_val, market, benches, terminals, val, hold, stress_cost, tp_val, cws, ccs)

    qual = int(lb["qualified"].sum())
    confirmed = bool(vb["robust_excess_cagr"] > 0 and vs["robust_excess_cagr"] > 0)
    selected_influence = pd.DataFrame(horizon_influence(a_sel, "POLICY_SELECTION_2021_2022") + horizon_influence(a_val, "VALIDATION_2023_2024"))

    # Diagnosis is explicit so one run tells us where to go next.
    reasons = []
    next_cov = float(exec_audit["next_session_execution_coverage"].min()) if len(exec_audit) else 0.0
    if next_cov < float(cfg.p["minimum_next_session_execution_coverage"]):
        reasons.append("EXECUTION_SOURCE_COVERAGE_INSUFFICIENT")
    if champ["execution_blocked_rate_20bps"] > max_block:
        reasons.append("EXECUTION_MAPPING_STILL_BLOCKING")
    if champ["median_holdings_20bps"] > float(cfg.p["overdiversification_diagnostic_holdings"]):
        reasons.append("OVERDIVERSIFIED_SELECTION")
    if len(oof_2021_2022) and (oof_2021_2022["economic_score"] <= 0).all():
        reasons.append("ALL_HORIZON_OOF_ALPHA_NEGATIVE_2021_2022")
    if champ["robust_excess_cagr_20bps"] <= 0:
        reasons.append("INSUFFICIENT_SELECTION_ALPHA")
    if vb["robust_excess_cagr"] <= 0:
        reasons.append("VALIDATION_ALPHA_NOT_CONFIRMED")

    gates = [
        {"test": "CACHED_ADVISOR_REUSED", "status": "PASS", "blocking": True, "value": str(workspace / cfg.p["cached_advisor_surface"]), "rule": "no model retraining"},
        {"test": "FINAL_HOLDOUT_NOT_LOADED", "status": "PASS" if cached["signal_date"].max() < hold else "FAIL", "blocking": True, "value": str(cached["signal_date"].max().date()), "rule": "< 2025-01-01"},
        {"test": "RAW_CLOSE_EXECUTION_SURFACE", "status": "PASS", "blocking": True, "value": str(workspace / cfg.p["execution_surface_cache"]), "rule": "execution uses canonical/phase2c/provider raw close only"},
        {"test": "NEXT_SESSION_EXECUTION_COVERAGE", "status": "PASS" if next_cov >= float(cfg.p["minimum_next_session_execution_coverage"]) else "FAIL", "blocking": True, "value": next_cov, "rule": f">= {cfg.p['minimum_next_session_execution_coverage']}"},
        {"test": "ALL_SIX_HORIZONS_NONZERO", "status": "PASS" if selected_influence["p10_weight"].min() > 0 else "FAIL", "blocking": True, "value": float(selected_influence["p10_weight"].min()), "rule": "all six have strictly positive dynamic weights"},
        {"test": "QUALIFIED_POLICY_EXISTS", "status": "PASS" if qual > 0 else "FAIL", "blocking": True, "value": qual, "rule": "positive robust excess base/stress and executable"},
        {"test": "VALIDATION_CONFIRMATION", "status": "PASS" if confirmed else "FAIL", "blocking": False, "value": confirmed, "rule": "2023-2024 diagnostic only"},
    ]
    status = "PASS" if all(g["status"] == "PASS" for g in gates if g["blocking"]) else "FAIL"

    lb.to_csv(out / "v13_phase3s_structural_leaderboard.csv", index=False)
    skill.to_csv(out / "v13_phase3s_pre2021_horizon_skill.csv", index=False)
    oof_2021_2022.to_csv(out / "v13_phase3s_oof_2021_2022_horizon_evidence.csv", index=False)
    selected_influence.to_csv(out / "v13_phase3s_selected_horizon_influence.csv", index=False)
    pd.DataFrame(gates).to_csv(out / "v13_phase3s_gate.csv", index=False)
    pd.DataFrame([{"period": "SELECTION_2021_2022", "cost_bps": base_cost, **sb}, {"period": "SELECTION_2021_2022", "cost_bps": stress_cost, **ss}, {"period": "VALIDATION_2023_2024", "cost_bps": base_cost, **vb}, {"period": "VALIDATION_2023_2024", "cost_bps": stress_cost, **vs}]).to_csv(out / "v13_phase3s_period_metrics.csv", index=False)
    snav.to_csv(out / "v13_phase3s_selection_nav.csv", index=False)
    vnav.to_csv(out / "v13_phase3s_validation_nav.csv", index=False)

    summary = {
        "status": status,
        "phase": "V13-P3S",
        "build": BUILD,
        "mode": "FAST_CACHED_STRUCTURAL_REPAIR",
        "cache": {"advisor_rows": int(len(cached)), "models_retrained": False, "dense_scores_rebuilt": False},
        "execution": {
            "surface_cache": str(workspace / cfg.p["execution_surface_cache"]),
            "next_session_audit": exec_audit.to_dict(orient="records"),
            "source_audit": source_audit.to_dict(orient="records") if len(source_audit) else [],
        },
        "horizon_prior": prior,
        "oof_2021_2022_horizon_evidence": oof_2021_2022.to_dict(orient="records"),
        "selection": {
            "candidate_policies": int(len(lb)),
            "qualified_policies": qual,
            "selected_policy": spec,
            "metrics": {k: champ.get(k) for k in [
                "cagr_20bps", "robust_excess_cagr_20bps", "cagr_40bps", "robust_excess_cagr_40bps",
                "median_holdings_20bps", "max_holdings_20bps", "median_max_name_weight_20bps", "p95_max_name_weight_20bps",
                "annual_turnover_20bps", "execution_blocked_rate_20bps", "target_deviation_rate_20bps",
            ]},
        },
        "selected_horizon_influence": selected_influence.to_dict(orient="records"),
        "validation": {"base": vb, "stress": vs, "confirmed": confirmed, "used_for_selection": False},
        "holdout": {"start": cfg.p["holdout_start"], "used": False},
        "diagnosis": reasons,
        "gate": gates,
        "next": "If PASS, freeze/stress Phase 3S before code-blinded 2025+ confirmation. If FAIL, this single run separates execution coverage, concentration/cardinality, horizon fusion, and alpha insufficiency without retraining models.",
    }
    (out / "v13_phase3s_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
