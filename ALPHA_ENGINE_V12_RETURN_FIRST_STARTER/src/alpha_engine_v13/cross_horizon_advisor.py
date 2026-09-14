from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.isotonic import IsotonicRegression
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from alpha_engine_v13.multi_horizon_models import (
    Cfg as P2Cfg,
    _merge_horizon,
    _rank_architecture,
    _daily_target_rank,
    _feature_ic_weights,
    _matrix,
    _robust_excess_target,
    cross_sectional_rank_features,
    fit_architectures,
    load_cfg as load_p2_cfg,
    normalize_scores,
    usable_features,
)

BUILD = "V13_P3_FIX2_PARTIAL_EXECUTION_AND_AUDIT_2026-09-12"
HORIZONS = (5, 10, 20, 60, 120, 252)


@dataclass(frozen=True)
class Cfg:
    p: dict


def _date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")


def _ticker(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip()


def load_cfg(workspace: Path) -> Cfg:
    with (workspace / "config" / "v13_phase3.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase3"])


def _load_json(p: Path) -> dict:
    if not p.exists():
        raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding="utf-8"))


def load_contracts(workspace: Path, cfg: Cfg) -> tuple[dict, dict, dict, pd.DataFrame, Path]:
    p0 = _load_json(workspace / cfg.p["phase0_summary"])
    p2 = _load_json(workspace / cfg.p["phase2_summary"])
    champs = _load_json(workspace / cfg.p["phase2_champions"])
    leader = pd.read_csv(workspace / cfg.p["phase2_leaderboard"])
    if p0.get("status") != "PASS" or p2.get("status") != "PASS":
        raise RuntimeError("V13 Phase 0 and Phase 2 must PASS before Phase 3")
    if p2.get("readiness") != "READY_FOR_MULTI_HORIZON_CONVICTION_AND_DYNAMIC_PORTFOLIO_RESEARCH":
        raise RuntimeError("Phase 2 is not ready for advisor research")
    if bool(champs.get("holdout_used")) or bool(p2.get("research_contract", {}).get("holdout_used")):
        raise RuntimeError("2025+ holdout was marked used before Phase 3")
    hs = sorted(int(x) for x in champs.get("champions", {}).keys())
    if hs != list(HORIZONS):
        raise RuntimeError(f"Unexpected Phase 2 horizons: {hs}")
    source = Path(p0["source_manifest"]["source_v12_root"])
    return p0, p2, champs, leader, source


def load_phase1_frames(workspace: Path, cfg: Cfg) -> tuple[pd.DataFrame, pd.DataFrame]:
    feat = pd.read_parquet(workspace / cfg.p["feature_library"])
    targ = pd.read_parquet(workspace / cfg.p["research_targets"])
    feat["signal_date"] = _date(feat["signal_date"]); feat["ticker"] = _ticker(feat["ticker"])
    targ["signal_date"] = _date(targ["signal_date"]); targ["ticker"] = _ticker(targ["ticker"])
    hold = pd.Timestamp(cfg.p["holdout_start"])
    if (feat["signal_date"] >= hold).any() or (targ["signal_date"] >= hold).any():
        raise RuntimeError("HOLDOUT BREACH in Phase 1 frames")
    return feat.sort_values(["signal_date","ticker"]), targ.sort_values(["signal_date","ticker"])


def _train_before(merged: pd.DataFrame, h: int, start: pd.Timestamp, cutoff: pd.Timestamp) -> pd.DataFrame:
    endcol = f"target_end_date_{h}d"; rescol = f"target_resolved_{h}d"; ycol = f"fwd_return_{h}d"
    m = (
        (merged["signal_date"] >= start) & (merged["signal_date"] < cutoff)
        & merged[rescol].fillna(False).astype(bool)
        & merged[endcol].notna() & (merged[endcol] < cutoff)
        & pd.to_numeric(merged[ycol], errors="coerce").notna()
    )
    out = merged.loc[m].copy()
    if len(out) and not (out[endcol] < cutoff).all():
        raise RuntimeError("Dense-score training purge breach")
    return out


def _architecture_for_period(leader: pd.DataFrame, h: int, periods: list[str]) -> str:
    x = leader[(leader["horizon_sessions"].astype(int) == int(h)) & leader["period"].isin(periods)].copy()
    return _rank_architecture(x)


def fit_selected_architecture(train: pd.DataFrame, test: pd.DataFrame, feature_cols: list[str], h: int, arch: str, cfg: P2Cfg) -> np.ndarray:
    if train.empty or test.empty:
        return np.full(len(test), np.nan)
    ycol=f"fwd_return_{h}d"
    yr=_daily_target_rank(train,ycol); valid_y=np.isfinite(yr)
    xt_imp=_matrix(test,feature_cols,impute=True)
    if arch=="IC_COMPOSITE":
        w=_feature_ic_weights(train,feature_cols,h)
        return (xt_imp-0.5)@w
    x_train_imp=_matrix(train,feature_cols,impute=True)
    if arch=="RIDGE_RANK":
        model=Ridge(alpha=float(cfg.p["ridge_alpha"]),fit_intercept=True)
        model.fit(x_train_imp[valid_y],yr[valid_y]); return model.predict(xt_imp)
    params=dict(loss="squared_error",learning_rate=float(cfg.p["hgb_learning_rate"]),max_iter=int(cfg.p["hgb_max_iter"]),max_leaf_nodes=int(cfg.p["hgb_max_leaf_nodes"]),min_samples_leaf=int(cfg.p["hgb_min_samples_leaf"]),l2_regularization=float(cfg.p["hgb_l2"]),random_state=int(cfg.p["random_state"]))
    xtr=_matrix(train,feature_cols,impute=False); xte=_matrix(test,feature_cols,impute=False)
    if arch=="HGB_RANK":
        m=HistGradientBoostingRegressor(**params); m.fit(xtr[valid_y],yr[valid_y]); return m.predict(xte)
    if arch=="HGB_ROBUST_EXCESS":
        y=_robust_excess_target(train,h); ok=np.isfinite(y); m=HistGradientBoostingRegressor(**params); m.fit(xtr[ok],y[ok]); return m.predict(xte)
    if arch=="BLEND_RIDGE_HGB":
        r=Ridge(alpha=float(cfg.p["ridge_alpha"]),fit_intercept=True); r.fit(x_train_imp[valid_y],yr[valid_y]); rp=r.predict(xt_imp)
        m=HistGradientBoostingRegressor(**params); m.fit(xtr[valid_y],yr[valid_y]); hp=m.predict(xte); return 0.5*rp+0.5*hp
    raise ValueError(f"Unknown architecture {arch}")


def regenerate_dense_scores(
    features: pd.DataFrame,
    targets: pd.DataFrame,
    champs: dict,
    leader: pd.DataFrame,
    p2cfg: P2Cfg,
    cfg: Cfg,
) -> pd.DataFrame:
    feature_cols = usable_features(features, p2cfg)
    ranked = cross_sectional_rank_features(features, feature_cols)
    research_start = pd.Timestamp(cfg.p["research_start"])
    periods = [
        ("OOF_2019_2020_DENSE", pd.Timestamp(cfg.p["calibration_start"]), pd.Timestamp(cfg.p["selection_start"]), ["EVIDENCE_2017_2018"]),
        ("OOF_2021_2022_DENSE", pd.Timestamp(cfg.p["selection_start"]), pd.Timestamp(cfg.p["validation_start"]), ["EVIDENCE_2017_2018","OUTER_2019_2020"]),
        ("VALIDATION_2023_2024_DENSE", pd.Timestamp(cfg.p["validation_start"]), pd.Timestamp(cfg.p["holdout_start"]), None),
    ]
    all_rows = []
    for h in HORIZONS:
        merged = _merge_horizon(ranked, targets, h)
        for role, ps, pe, evidence_periods in periods:
            train = _train_before(merged, h, research_start, ps)
            test = ranked[(ranked["signal_date"] >= ps) & (ranked["signal_date"] < pe)].copy()
            if train.empty or test.empty:
                raise RuntimeError(f"Dense score period empty h={h} role={role}")
            if evidence_periods is None:
                arch = str(champs["champions"][str(h)]["champion_architecture"])
            else:
                arch = _architecture_for_period(leader, h, evidence_periods)
            raw = fit_selected_architecture(train, test, feature_cols, h, arch, p2cfg)
            score = normalize_scores(test, raw)
            sf = test[["signal_date","ticker"]].copy()
            sf["horizon_sessions"] = int(h)
            sf["score"] = score
            sf["architecture"] = arch
            sf["role"] = role
            all_rows.append(sf)
    out = pd.concat(all_rows, ignore_index=True)
    hold = pd.Timestamp(cfg.p["holdout_start"])
    if (out["signal_date"] >= hold).any():
        raise RuntimeError("HOLDOUT BREACH in dense score regeneration")
    return out.sort_values(["signal_date","ticker","horizon_sessions"]).reset_index(drop=True)


def _nw_mean_se(x: np.ndarray, lag: int) -> tuple[float,float]:
    x = np.asarray(x, float); x = x[np.isfinite(x)]; n = len(x)
    if n < 8:
        return math.nan, math.nan
    mu = float(x.mean()); u = x - mu
    gamma0 = float(np.dot(u,u) / n); v = gamma0
    L = min(int(lag), n - 1)
    for k in range(1, L + 1):
        gamma = float(np.dot(u[k:], u[:-k]) / n)
        v += 2.0 * (1.0 - k / (L + 1.0)) * gamma
    se = math.sqrt(max(v,0.0) / n)
    return mu, se


def fit_horizon_calibration(
    labeled_scores: pd.DataFrame,
    targets: pd.DataFrame,
    h: int,
    bins: int,
    minimum_dates: int,
    maturation_cutoff: pd.Timestamp,
) -> pd.DataFrame:
    """Calibrate score to BOTH absolute return and benchmark-relative alpha.

    Portfolio sizing must use an expected asset return that is commensurate with
    the covariance matrix. Benchmark excess is retained as an alpha diagnostic,
    but is NOT used as the Kelly mean vector. This avoids requiring every single
    holding to beat the strongest benchmark before it can enter the portfolio.
    """
    s = labeled_scores[labeled_scores["horizon_sessions"].astype(int).eq(int(h))][["signal_date","ticker","score"]].copy()
    cols = [
        "signal_date","ticker",f"target_end_date_{h}d",f"fwd_return_{h}d",
        f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d",f"target_resolved_{h}d"
    ]
    t = targets[cols].copy()
    x = s.merge(t, on=["signal_date","ticker"], how="inner", validate="one_to_one")
    x[f"target_end_date_{h}d"] = _date(x[f"target_end_date_{h}d"])
    x = x[
        x[f"target_resolved_{h}d"].fillna(False).astype(bool)
        & x[f"target_end_date_{h}d"].notna()
        & (x[f"target_end_date_{h}d"] < pd.Timestamp(maturation_cutoff))
    ].copy()
    x["future_return"] = pd.to_numeric(x[f"fwd_return_{h}d"], errors="coerce")
    ex = x[[f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]].apply(pd.to_numeric, errors="coerce")
    x["robust_excess"] = ex.min(axis=1, skipna=False)
    x = x[np.isfinite(x["score"]) & np.isfinite(x["future_return"]) & np.isfinite(x["robust_excess"])].copy()
    if x.empty:
        raise RuntimeError(f"No calibration rows for h={h}")
    x["bin"] = np.minimum((x["score"].clip(0, 1 - 1e-12) * bins).astype(int), bins-1)
    daily = x.groupby(["bin","signal_date"], observed=True).agg(
        future_return=("future_return","mean"), robust_excess=("robust_excess","mean")
    ).reset_index()
    rows=[]
    for b in range(bins):
        r = daily.loc[daily["bin"].eq(b), "future_return"].to_numpy(float)
        a = daily.loc[daily["bin"].eq(b), "robust_excess"].to_numpy(float)
        rmu,rse = _nw_mean_se(r, min(int(h),60))
        amu,ase = _nw_mean_se(a, min(int(h),60))
        rows.append({
            "horizon_sessions":h,"bin":b,"score_center":(b+0.5)/bins,
            "raw_mean_return":rmu,"hac_se_return":rse,
            "raw_mean_robust_excess":amu,"hac_se_robust_excess":ase,
            "dates":int(min(np.isfinite(r).sum(),np.isfinite(a).sum())),
        })
    tab = pd.DataFrame(rows)
    good = tab["raw_mean_return"].notna() & (tab["dates"] >= int(minimum_dates))
    if good.sum() < 4:
        raise RuntimeError(f"Insufficient calibration bins h={h}: {int(good.sum())}")
    # Higher model score must never imply a lower calibrated return in the
    # research mapping. Isotonic is fitted ONLY on matured pre-selection data.
    iso_r = IsotonicRegression(increasing=True, out_of_bounds="clip")
    iso_r.fit(tab.loc[good,"score_center"], tab.loc[good,"raw_mean_return"], sample_weight=tab.loc[good,"dates"])
    tab["expected_return"] = iso_r.predict(tab["score_center"])
    good_a = tab["raw_mean_robust_excess"].notna() & (tab["dates"] >= int(minimum_dates))
    if good_a.sum() >= 4:
        iso_a = IsotonicRegression(increasing=True, out_of_bounds="clip")
        iso_a.fit(tab.loc[good_a,"score_center"], tab.loc[good_a,"raw_mean_robust_excess"], sample_weight=tab.loc[good_a,"dates"])
        tab["expected_robust_excess"] = iso_a.predict(tab["score_center"])
    else:
        tab["expected_robust_excess"] = np.nan
    for c, goodmask in [("hac_se_return",good),("hac_se_robust_excess",good_a)]:
        tab[c] = tab[c].interpolate(limit_direction="both")
        if tab[c].isna().any():
            med = float(tab.loc[goodmask,c].median()) if goodmask.any() and tab.loc[goodmask,c].notna().any() else 0.01
            tab[c] = tab[c].fillna(med)
    return tab

def fit_all_calibrations(scores: pd.DataFrame, targets: pd.DataFrame, role: str, cfg: Cfg, maturation_cutoff: pd.Timestamp) -> pd.DataFrame:
    x = scores[scores["role"].eq(role)].copy()
    tabs = [fit_horizon_calibration(x, targets, h, int(cfg.p["calibration_bins"]), int(cfg.p["minimum_calibration_dates"]), pd.Timestamp(maturation_cutoff)) for h in HORIZONS]
    return pd.concat(tabs, ignore_index=True)


def _interp_calibration(score: np.ndarray, tab: pd.DataFrame, value_col: str, se_col: str) -> tuple[np.ndarray,np.ndarray]:
    centers = tab["score_center"].to_numpy(float)
    mu = tab[value_col].to_numpy(float)
    se = tab[se_col].to_numpy(float)
    s = np.asarray(score,float)
    return np.interp(s, centers, mu, left=mu[0], right=mu[-1]), np.interp(s, centers, se, left=se[0], right=se[-1])


def build_advisor_surface(dense_scores: pd.DataFrame, calibration: pd.DataFrame, role: str) -> pd.DataFrame:
    """Build a simultaneous six-horizon advisor.

    Absolute expected return drives economic eligibility/sizing. Robust benchmark
    excess remains a separate alpha view. Both are re-evaluated every session;
    no horizon is a holding-period clock.
    """
    x = dense_scores[dense_scores["role"].eq(role)].copy()
    wide = x.pivot_table(index=["signal_date","ticker"], columns="horizon_sessions", values="score", aggfunc="first")
    for h in HORIZONS:
        if h not in wide.columns:
            wide[h] = np.nan
    wide = wide[list(HORIZONS)].dropna().reset_index()
    if wide.empty:
        raise RuntimeError(f"No complete six-horizon dense rows for role={role}")
    out = wide[["signal_date","ticker"]].copy()
    mu_cols=[]; se_cols=[]; alpha_cols=[]; alpha_se_cols=[]
    for h in HORIZONS:
        tab = calibration[calibration["horizon_sessions"].astype(int).eq(h)].sort_values("score_center")
        mu,se = _interp_calibration(wide[h].to_numpy(float), tab, "expected_return", "hac_se_return")
        alpha,alpha_se = _interp_calibration(wide[h].to_numpy(float), tab, "expected_robust_excess", "hac_se_robust_excess")
        mu_d = mu / float(h); se_d = np.maximum(se / float(h), 1e-8)
        alpha_d = alpha / float(h); alpha_se_d = np.maximum(alpha_se / float(h), 1e-8)
        out[f"score_{h}d"] = wide[h].to_numpy(float)
        out[f"mu_day_{h}d"] = mu_d
        out[f"se_day_{h}d"] = se_d
        out[f"alpha_day_{h}d"] = alpha_d
        out[f"alpha_se_day_{h}d"] = alpha_se_d
        mu_cols.append(f"mu_day_{h}d"); se_cols.append(f"se_day_{h}d")
        alpha_cols.append(f"alpha_day_{h}d"); alpha_se_cols.append(f"alpha_se_day_{h}d")
    mus = out[mu_cols].to_numpy(float); ses = out[se_cols].to_numpy(float)
    precision = 1.0 / np.maximum(ses * ses, 1e-12)
    precision = precision / precision.sum(axis=1, keepdims=True)
    combined = (precision * mus).sum(axis=1)
    stat_se = np.sqrt((precision * precision * ses * ses).sum(axis=1))
    disagreement = np.sqrt((precision * (mus - combined[:,None])**2).sum(axis=1))
    out["expected_return_per_session"] = combined
    out["uncertainty_per_session"] = stat_se + disagreement
    # Backward-compatible alias used by the simulator; semantics are now ABSOLUTE return.
    out["expected_excess_per_session"] = combined
    alphas = out[alpha_cols].to_numpy(float); alpha_ses = out[alpha_se_cols].to_numpy(float)
    ap = 1.0 / np.maximum(alpha_ses * alpha_ses, 1e-12); ap = ap / ap.sum(axis=1,keepdims=True)
    out["expected_robust_alpha_per_session"] = (ap*alphas).sum(axis=1)
    out["alpha_uncertainty_per_session"] = np.sqrt((ap*ap*alpha_ses*alpha_ses).sum(axis=1)) + np.sqrt((ap*(alphas-(ap*alphas).sum(axis=1)[:,None])**2).sum(axis=1))
    for j,h in enumerate(HORIZONS):
        out[f"return_horizon_weight_{h}d"] = precision[:,j]
        out[f"alpha_horizon_weight_{h}d"] = ap[:,j]
    out["horizon_agreement"] = (precision * (mus > 0).astype(float)).sum(axis=1)
    out["alpha_horizon_agreement"] = (ap * (alphas > 0).astype(float)).sum(axis=1)
    out["term_dispersion"] = disagreement
    out["effective_horizon_sessions"] = (precision * np.asarray(HORIZONS, dtype=float)[None, :]).sum(axis=1)
    for name, idx in [("tactical", [0,1,2]), ("strategic", [3,4,5])]:
        pm = precision[:,idx]; pm = pm / pm.sum(axis=1, keepdims=True)
        out[f"{name}_expected_return_per_session"] = (pm * mus[:,idx]).sum(axis=1)
        out[f"{name}_positive_share"] = (pm * (mus[:,idx] > 0).astype(float)).sum(axis=1)
        pa = ap[:,idx]; pa = pa / pa.sum(axis=1, keepdims=True)
        out[f"{name}_expected_robust_alpha_per_session"] = (pa * alphas[:,idx]).sum(axis=1)
        # Legacy column retained only for compatibility; its meaning is benchmark alpha.
        out[f"{name}_expected_excess_per_session"] = out[f"{name}_expected_robust_alpha_per_session"]
    out["advisor_conviction_z"] = out["expected_return_per_session"] / out["uncertainty_per_session"].replace(0,np.nan)
    out["advisor_alpha_z"] = out["expected_robust_alpha_per_session"] / out["alpha_uncertainty_per_session"].replace(0,np.nan)
    return out.sort_values(["signal_date","ticker"]).reset_index(drop=True)

def load_price_surface(source: Path, cfg: Cfg) -> tuple[pd.DataFrame, dict[str,pd.Timestamp]]:
    p = pd.read_parquet(source / cfg.p["source_return_price_layer"], columns=["date","ticker","research_eligible","target_total_return_price"])
    p["date"] = _date(p["date"]); p["ticker"] = _ticker(p["ticker"])
    p["target_total_return_price"] = pd.to_numeric(p["target_total_return_price"], errors="coerce")
    hold = pd.Timestamp(cfg.p["holdout_start"])
    p = p[(p["date"] < hold) & p["research_eligible"].fillna(False).astype(bool) & (p["target_total_return_price"] > 0)].copy()
    terminals={}
    ov=source/cfg.p["source_terminal_overlay"]
    if ov.exists():
        t=pd.read_csv(ov)
        if len(t):
            t["ticker"]=_ticker(t["ticker"]); t["terminal_price_date"]=_date(t["terminal_price_date"])
            valid=t.get("overlay_validated", True)
            if not isinstance(valid,pd.Series): valid=pd.Series(True,index=t.index)
            if valid.dtype != bool: valid=valid.astype(str).str.lower().isin(["true","1","yes"])
            terminals={str(r.ticker):pd.Timestamp(r.terminal_price_date) for r in t.loc[valid].itertuples() if pd.notna(r.terminal_price_date)}
    return p.sort_values(["date","ticker"]), terminals


def prepare_market(prices: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, lookback: int) -> dict:
    # Include enough pre-period history for the first day's causal risk estimate.
    all_dates = pd.DatetimeIndex(sorted(prices["date"].dropna().unique()))
    prior = all_dates[all_dates < start]
    lb_start = prior[max(0, len(prior)-lookback-2)] if len(prior) else start
    px = prices[(prices["date"] >= lb_start) & (prices["date"] < end)].copy()
    calendar = pd.DatetimeIndex(sorted(px["date"].dropna().unique()))
    raw = px.pivot_table(index="date", columns="ticker", values="target_total_return_price", aggfunc="last").reindex(calendar)
    presence = raw.notna()
    ff = raw.ffill()
    rets = ff.pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan).where(presence)
    return {"calendar":calendar,"raw":raw,"presence":presence,"returns":rets}


def prepare_risk_panel(market: dict, spy_ret: pd.Series, lookback: int, min_obs: int) -> dict:
    rets=market["returns"]
    m=spy_ret.reindex(rets.index)
    mvar=m.rolling(int(lookback),min_periods=int(min_obs)).var().clip(lower=1e-8)
    beta=pd.DataFrame(index=rets.index,columns=rets.columns,dtype="float32")
    idio=pd.DataFrame(index=rets.index,columns=rets.columns,dtype="float32")
    for t in rets.columns:
        r=rets[t]
        cov=r.rolling(int(lookback),min_periods=int(min_obs)).cov(m)
        vr=r.rolling(int(lookback),min_periods=int(min_obs)).var()
        b=(cov/mvar).replace([np.inf,-np.inf],np.nan)
        iv=(vr-b*b*mvar).clip(lower=1e-6)
        beta[t]=b.astype("float32"); idio[t]=iv.astype("float32")
    return {"beta":beta,"idio":idio,"market_var":mvar}


def _risk_stats_cached(risk: dict, d: pd.Timestamp, names: list[str]) -> tuple[np.ndarray,np.ndarray,float]:
    b=risk["beta"].loc[d].reindex(names).to_numpy(float) if d in risk["beta"].index else np.full(len(names),np.nan)
    iv=risk["idio"].loc[d].reindex(names).to_numpy(float) if d in risk["idio"].index else np.full(len(names),np.nan)
    vm=float(risk["market_var"].get(d,np.nan))
    b=np.where(np.isfinite(b),b,1.0); iv=np.where(np.isfinite(iv),np.maximum(iv,1e-6),0.0004); vm=vm if np.isfinite(vm) and vm>0 else 0.0001
    return b,iv,vm


def _risk_stats_for_date(rets: pd.DataFrame, d: pd.Timestamp, names: list[str], spy_ret: pd.Series, lookback: int, min_obs: int) -> tuple[np.ndarray,np.ndarray,float]:
    hist_dates = rets.index[rets.index < d][-lookback:]
    if len(hist_dates) < min_obs:
        return np.ones(len(names)), np.full(len(names), 0.0004), 0.0001
    m = spy_ret.reindex(hist_dates).to_numpy(float)
    vm = float(np.nanvar(m, ddof=1)) if np.isfinite(m).sum() >= min_obs else 0.0001
    vm = max(vm, 1e-8)
    beta=[]; idio=[]
    for t in names:
        if t not in rets.columns:
            beta.append(1.0); idio.append(0.0004); continue
        r = rets.loc[hist_dates,t].to_numpy(float)
        ok=np.isfinite(r)&np.isfinite(m)
        if ok.sum() < min_obs:
            v=float(np.nanvar(r,ddof=1)) if np.isfinite(r).sum()>=5 else 0.0004
            beta.append(1.0); idio.append(max(v-vm,1e-6)); continue
        rr=r[ok]; mm=m[ok]
        cov=float(np.cov(rr,mm,ddof=1)[0,1]); b=cov/vm
        vr=float(np.var(rr,ddof=1)); iv=max(vr-b*b*vm,1e-6)
        beta.append(b); idio.append(iv)
    return np.asarray(beta,float), np.asarray(idio,float), vm


def one_factor_kelly_weights(edge: dict[str,float], beta: np.ndarray, idio_var: np.ndarray, market_var: float) -> dict[str,float]:
    names=list(edge); mu=np.asarray([max(0.0,float(edge[t])) for t in names],float)
    if not names or not np.any(mu>0): return {}
    d_inv=1.0/np.maximum(np.asarray(idio_var,float),1e-8)
    b=np.asarray(beta,float); vm=max(float(market_var),1e-8)
    # Sherman-Morrison inverse of D + vm*b*b'.
    dinv_mu=d_inv*mu; dinv_b=d_inv*b
    denom=(1.0/vm)+float(np.dot(b,dinv_b))
    raw=dinv_mu-dinv_b*(float(np.dot(b,dinv_mu))/denom)
    raw=np.maximum(raw,0.0)
    if raw.sum() <= 0: raw=np.maximum(dinv_mu,0.0)
    gross=float(raw.sum())
    if gross <= 0: return {}
    # Full-Kelly growth approximation with cash allowed; scale down only if gross leverage would exceed 100%.
    if gross > 1.0: raw=raw/gross
    return {t:float(w) for t,w in zip(names,raw) if w>1e-10}


def _portfolio_metrics(daily: pd.DataFrame) -> dict:
    if daily.empty:
        return {"days":0,"total_return":math.nan,"cagr":math.nan,"max_drawdown":math.nan,"annual_turnover":math.nan}
    nav=pd.to_numeric(daily["nav"],errors="coerce"); n=len(nav)
    total=float(nav.iloc[-1]-1.0); cagr=float(nav.iloc[-1]**(252.0/max(n,1))-1.0) if nav.iloc[-1]>0 else -1.0
    dd=nav/nav.cummax()-1.0; yrs=n/252.0
    monthly=pd.to_numeric(daily["net_return"],errors="coerce").fillna(0).groupby(pd.to_datetime(daily["date"]).dt.to_period("M")).apply(lambda x:float(np.prod(1+x)-1))
    return {"days":int(n),"total_return":total,"cagr":cagr,"max_drawdown":float(dd.min()),"annual_turnover":float(daily["turnover"].sum()/yrs) if yrs>0 else math.nan,"trade_days":int((daily["turnover"]>1e-12).sum()),"execution_skips":int(daily["execution_skipped"].sum()),"positive_month_share":float((monthly>0).mean()) if len(monthly) else math.nan,"median_holdings":float(daily["holdings"].median()),"min_holdings":int(daily["holdings"].min()),"max_holdings":int(daily["holdings"].max()),"mean_cash_weight":float(daily["cash_weight"].mean()),"median_max_name_weight":float(daily["max_name_weight"].median()),"p95_max_name_weight":float(daily["max_name_weight"].quantile(.95))}


def _benchmark_series(source: Path, cfg: Cfg, prices: pd.DataFrame, market: dict) -> dict[str,pd.Series]:
    out={}
    for sym,key in [("SPY","source_spy_benchmark"),("QQQ","source_qqq_benchmark")]:
        x=pd.read_parquet(source/cfg.p[key]); x["date"]=_date(x["date"]); x[sym]=pd.to_numeric(x[sym],errors="coerce")
        s=x.set_index("date")[sym].sort_index().pct_change(fill_method=None).replace([np.inf,-np.inf],np.nan)
        out[sym]=s
    r=market["returns"]
    out["UNIVERSE_EQUAL_WEIGHT"]=r.mean(axis=1,skipna=True)
    return out


def benchmark_metrics(series: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    x=series[(series.index>=start)&(series.index<end)].dropna()
    if len(x)==0: return {"cagr":math.nan,"total_return":math.nan,"max_drawdown":math.nan}
    nav=(1.0+x).cumprod(); total=float(nav.iloc[-1]-1.0); cagr=float(nav.iloc[-1]**(252.0/len(nav))-1.0)
    dd=nav/nav.cummax()-1.0
    return {"cagr":cagr,"total_return":total,"max_drawdown":float(dd.min())}


def build_target_path(advisor: pd.DataFrame, risk: dict, uncertainty_z: float, entry_hurdle_bps: float) -> dict[pd.Timestamp,dict[str,float]]:
    hurdle=float(entry_hurdle_bps)/10000.0
    out={}
    for d,g in advisor.groupby("signal_date",sort=False):
        gg=g.set_index("ticker")
        mu=pd.to_numeric(gg["expected_return_per_session"],errors="coerce")
        se=pd.to_numeric(gg["uncertainty_per_session"],errors="coerce")
        eff=pd.to_numeric(gg["effective_horizon_sessions"],errors="coerce").clip(lower=1.0)
        lcb=mu-float(uncertainty_z)*se-hurdle/eff
        eligible=lcb[np.isfinite(lcb)&(lcb>0)].index
        # Robust LCB determines eligibility; posterior mean return determines Kelly sizing.
        # This prevents uncertainty from being subtracted twice.
        edge={str(t):float(mu.loc[t]) for t in eligible if np.isfinite(mu.loc[t]) and float(mu.loc[t])>0}
        if edge:
            names=list(edge); beta,idio,vm=_risk_stats_cached(risk,pd.Timestamp(d),names)
            out[pd.Timestamp(d)]=one_factor_kelly_weights(edge,beta,idio,vm)
        else:
            out[pd.Timestamp(d)]={}
    return out


def _partial_execution_target(
    current_weights: dict[str,float],
    desired_target: dict[str,float],
    presence_row: pd.Series,
) -> tuple[dict[str,float], dict]:
    """Translate a desired target into the actually executable close-to-close target.

    A missing price for one ticker must NEVER cancel the whole rebalance.
    Unavailable held names remain at their current weight; unavailable new names
    are not opened. Executable desired weights are scaled only when locked
    unavailable holdings consume capital. Cash absorbs any remaining capacity.
    """
    cur={str(t):max(0.0,float(w)) for t,w in current_weights.items() if float(w)>1e-14}
    des={str(t):max(0.0,float(w)) for t,w in desired_target.items() if float(w)>1e-14}
    union=set(cur)|set(des)
    requested=float(sum(abs(des.get(t,0.0)-cur.get(t,0.0)) for t in union))
    if requested <= 1e-14:
        return dict(cur), {"requested_notional":0.0,"executed_notional":0.0,"unfilled_notional":0.0,"blocked_names":0,"partial":False,"full_skip":False}
    trade_names={t for t in union if abs(des.get(t,0.0)-cur.get(t,0.0))>1e-12}
    unavailable={t for t in trade_names if (t not in presence_row.index or not bool(presence_row.get(t,False)))}
    locked={t:cur[t] for t in unavailable if cur.get(t,0.0)>1e-14}
    free_cap=max(0.0,1.0-sum(locked.values()))
    desired_exec={t:w for t,w in des.items() if t not in unavailable}
    desired_sum=float(sum(desired_exec.values()))
    scale=min(1.0, free_cap/desired_sum) if desired_sum>1e-14 else 0.0
    actual=dict(locked)
    for t,w in desired_exec.items():
        ww=float(w)*scale
        if ww>1e-14: actual[t]=ww
    actual_sum=float(sum(actual.values()))
    if actual_sum>1.0+1e-10:
        # Numerical guard only; economics are preserved by proportional scaling.
        actual={t:w/actual_sum for t,w in actual.items()}
    executed=float(sum(abs(actual.get(t,0.0)-cur.get(t,0.0)) for t in set(cur)|set(actual)))
    unfilled=float(sum(abs(des.get(t,0.0)-actual.get(t,0.0)) for t in union))
    partial=unfilled>1e-10
    full_skip=executed<=1e-12 and requested>1e-12
    return actual, {
        "requested_notional":requested,
        "executed_notional":executed,
        "unfilled_notional":unfilled,
        "blocked_names":int(len(unavailable)),
        "partial":bool(partial),
        "full_skip":bool(full_skip),
    }


def simulate_dynamic_portfolio(
    advisor: pd.DataFrame,
    prices: pd.DataFrame,
    terminals: dict[str,pd.Timestamp],
    benchmark_returns: dict[str,pd.Series],
    start: pd.Timestamp,
    end: pd.Timestamp,
    uncertainty_z: float,
    entry_hurdle_bps: float,
    rebalance_extra_edge_bps: float,
    round_trip_bps: float,
    cfg: Cfg,
    initial_weights: dict[str,float] | None=None,
    initial_cash: float=1.0,
    prepared_market: dict | None=None,
    prepared_risk: dict | None=None,
    target_path: dict[pd.Timestamp,dict[str,float]] | None=None,
) -> tuple[dict,pd.DataFrame,dict[str,float],float]:
    start=pd.Timestamp(start); end=pd.Timestamp(end)
    market=prepared_market if prepared_market is not None else prepare_market(prices,start,end,int(cfg.p["risk_lookback_sessions"]))
    cal=market["calendar"][(market["calendar"]>=start)&(market["calendar"]<end)]
    rets=market["returns"]; presence=market["presence"]
    spy_ret=benchmark_returns["SPY"]
    by_date={pd.Timestamp(d):g.set_index("ticker") for d,g in advisor[(advisor["signal_date"]>=start)&(advisor["signal_date"]<end)].groupby("signal_date",sort=False)}
    weights=dict(initial_weights or {}); cash=float(initial_cash); nav=1.0; pending=None
    rows=[]; one_way=float(round_trip_bps)/2.0/10000.0
    entry_hurdle=float(entry_hurdle_bps)/10000.0
    extra=float(rebalance_extra_edge_bps)/10000.0
    for d in cal:
        d=pd.Timestamp(d); prev_nav=nav
        gross=0.0
        if weights:
            rr=rets.loc[d]
            gross=float(sum(w*(float(rr.get(t,0.0)) if np.isfinite(rr.get(t,np.nan)) else 0.0) for t,w in weights.items()))
        nav*=max(0.0,1.0+gross)
        if weights:
            vals={t:w*(1.0+(float(rets.at[d,t]) if t in rets.columns and np.isfinite(rets.at[d,t]) else 0.0)) for t,w in weights.items()}
            total=cash+sum(vals.values())
            if total>0:
                weights={t:v/total for t,v in vals.items() if v>1e-14}; cash=cash/total
        turnover=0.0; cost=0.0; skipped=False; partial_execution=False
        requested_trade_notional=0.0; executed_trade_notional=0.0; unfilled_trade_notional=0.0; blocked_trade_names=0
        if pending is not None:
            target=pending
            prow=presence.loc[d] if d in presence.index else pd.Series(dtype=bool)
            actual_target, exmeta=_partial_execution_target(weights,target,prow)
            requested_trade_notional=float(exmeta["requested_notional"])
            executed_trade_notional=float(exmeta["executed_notional"])
            unfilled_trade_notional=float(exmeta["unfilled_notional"])
            blocked_trade_names=int(exmeta["blocked_names"])
            partial_execution=bool(exmeta["partial"])
            skipped=bool(exmeta["full_skip"])
            if executed_trade_notional>1e-12:
                turnover=0.5*executed_trade_notional; cost=one_way*executed_trade_notional; nav*=max(0.0,1.0-cost)
                weights={t:float(w) for t,w in actual_target.items() if w>1e-10}; cash=max(0.0,1.0-sum(weights.values()))
            pending=None
        for t in [t for t in list(weights) if terminals.get(t)==d]:
            cash+=weights.pop(t)
        g=by_date.get(d)
        decision=False; expected_benefit=0.0; target={}
        if g is not None and len(g):
            mu=pd.to_numeric(g["expected_return_per_session"],errors="coerce")
            se=pd.to_numeric(g["uncertainty_per_session"],errors="coerce")
            eff=pd.to_numeric(g["effective_horizon_sessions"],errors="coerce").clip(lower=1.0)
            if target_path is not None:
                target=dict(target_path.get(d,{}))
            else:
                lcb=mu-float(uncertainty_z)*se-entry_hurdle/eff
                cand=lcb[np.isfinite(lcb)&(lcb>0)]
                edge={str(t):float(v) for t,v in cand.items()}
                if edge:
                    names=list(edge)
                    beta,idio,vm=(_risk_stats_cached(prepared_risk,d,names) if prepared_risk is not None else _risk_stats_for_date(rets,d,names,spy_ret,int(cfg.p["risk_lookback_sessions"]),int(cfg.p["minimum_risk_observations"])))
                    target=one_factor_kelly_weights(edge,beta,idio,vm)
            union=set(weights)|set(target)
            delta={t:float(target.get(t,0))-float(weights.get(t,0)) for t in union}
            mu_map={str(t):float(mu.get(t,0.0)) if np.isfinite(mu.get(t,np.nan)) else 0.0 for t in union}
            eff_map={str(t):float(eff.get(t,1.0)) if np.isfinite(eff.get(t,np.nan)) else 1.0 for t in union}
            expected_benefit=sum(delta[t]*mu_map[t]*eff_map[t] for t in union)
            estimated_cost=one_way*sum(abs(v) for v in delta.values())
            forced_exit=any(t not in g.index for t in weights)
            if sum(abs(v) for v in delta.values())>1e-10 and (forced_exit or expected_benefit>estimated_cost+extra):
                pending=target; decision=True
        rows.append({"date":d,"nav":nav,"net_return":nav/prev_nav-1.0 if prev_nav>0 else -1.0,"gross_return":gross,"turnover":turnover,"cost_fraction":cost,"execution_skipped":int(skipped),"partial_execution":int(partial_execution),"requested_trade_notional":requested_trade_notional,"executed_trade_notional":executed_trade_notional,"unfilled_trade_notional":unfilled_trade_notional,"blocked_trade_names":blocked_trade_names,"holdings":len(weights),"cash_weight":cash,"max_name_weight":max(weights.values()) if weights else 0.0,"rebalance_scheduled":int(decision),"expected_incremental_excess_over_effective_horizon":expected_benefit})
    daily=pd.DataFrame(rows); met=_portfolio_metrics(daily)
    requested=float(daily["requested_trade_notional"].sum()) if len(daily) else 0.0
    unfilled=float(daily["unfilled_trade_notional"].sum()) if len(daily) else 0.0
    met["execution_skip_rate"]=float(unfilled/requested) if requested>1e-14 else 0.0
    met["execution_shortfall_notional_rate"]=met["execution_skip_rate"]
    met["full_execution_skip_days"]=int(daily["execution_skipped"].sum()) if len(daily) else 0
    met["partial_execution_days"]=int(daily["partial_execution"].sum()) if len(daily) else 0
    met["blocked_trade_names"]=int(daily["blocked_trade_names"].sum()) if len(daily) else 0
    met["requested_trade_notional"]=requested
    met["executed_trade_notional"]=float(daily["executed_trade_notional"].sum()) if len(daily) else 0.0
    met["unfilled_trade_notional"]=unfilled
    met["scheduled_rebalances"]=int(daily["rebalance_scheduled"].sum()) if len(daily) else 0
    return met,daily,weights,cash


def enrich_with_benchmarks(metrics: dict, benchmark_returns: dict[str,pd.Series], start: pd.Timestamp, end: pd.Timestamp) -> dict:
    out=dict(metrics); c=[]
    for k,s in benchmark_returns.items():
        b=benchmark_metrics(s,start,end); out[f"{k.lower()}_cagr"]=b["cagr"]; out[f"excess_cagr_vs_{k.lower()}"]=float(metrics["cagr"]-b["cagr"]) if np.isfinite(metrics.get("cagr",np.nan)) and np.isfinite(b["cagr"]) else math.nan
        c.append(out[f"excess_cagr_vs_{k.lower()}"])
    out["robust_excess_cagr"]=float(np.nanmin(c)) if any(np.isfinite(c)) else math.nan
    return out


def candidate_specs(cfg: Cfg) -> list[dict]:
    rows=[]
    for z in cfg.p["uncertainty_z_grid"]:
        for sc in cfg.p["entry_hurdle_bps_grid"]:
            for re in cfg.p["rebalance_extra_edge_bps_grid"]:
                rows.append({"uncertainty_z":float(z),"entry_hurdle_bps":float(sc),"rebalance_extra_edge_bps":float(re)})
    return rows


def rank_policies(df: pd.DataFrame) -> pd.DataFrame:
    x=df.copy()
    x=x.sort_values(["qualified","robust_excess_cagr_20bps","cagr_20bps","robust_excess_cagr_40bps","max_drawdown_20bps","annual_turnover_20bps"],ascending=[False,False,False,False,False,True]).reset_index(drop=True)
    x["return_first_rank"]=np.arange(1,len(x)+1)
    return x


def evaluate_gate(parts: dict, cfg: Cfg) -> tuple[pd.DataFrame,str]:
    rows=[]
    def add(test,ok,value,rule,blocking=True): rows.append({"test":test,"status":"PASS" if ok else "FAIL","blocking":blocking,"value":value,"rule":rule})
    add("PHASE2_INPUT_PASS",parts["phase2_status"]=="PASS",parts["phase2_status"],"Phase 2 must PASS")
    add("FINAL_HOLDOUT_NOT_LOADED",parts["max_score_date"]<pd.Timestamp(cfg.p["holdout_start"]),str(parts["max_score_date"].date()),"all dense/advisor scores < 2025-01-01")
    add("DENSE_ALL_SIX_HORIZONS",parts["dense_horizons"]==list(HORIZONS),parts["dense_horizons"],str(list(HORIZONS)))
    add("DAILY_COMPLETE_TERM_STRUCTURE",parts["minimum_daily_horizon_count"]==6,parts["minimum_daily_horizon_count"],"every emitted advisor row must have all six horizon forecasts")
    add("NO_FIXED_CARDINALITY",parts["fixed_cardinality"] is False,parts["fixed_cardinality"],"must remain false")
    add("NO_FIXED_POSITION_CAP",parts["fixed_position_cap"] is False,parts["fixed_position_cap"],"must remain false")
    add("QUALIFIED_DYNAMIC_POLICY_EXISTS",parts["qualified_policies"]>0,parts["qualified_policies"],">=1 policy with positive robust excess CAGR at base/stress costs")
    add("VALIDATION_NOT_USED_FOR_SELECTION",parts["validation_used_for_selection"] is False,parts["validation_used_for_selection"],"2023-2024 confirmation only")
    add("VALIDATION_CONFIRMATION",bool(parts["validation_confirmed"]),parts["validation_confirmed"],"diagnostic: selected policy remains positive robust excess in 2023-2024",blocking=False)
    g=pd.DataFrame(rows); status="PASS" if not ((g.blocking==True)&(g.status=="FAIL")).any() else "FAIL"
    return g,status


def horizon_influence_summary(advisor: pd.DataFrame, role: str) -> pd.DataFrame:
    rows=[]
    for h in HORIZONS:
        rc=f"return_horizon_weight_{h}d"; ac=f"alpha_horizon_weight_{h}d"
        rows.append({
            "role":role,"horizon_sessions":h,
            "mean_return_weight":float(pd.to_numeric(advisor[rc],errors="coerce").mean()),
            "median_return_weight":float(pd.to_numeric(advisor[rc],errors="coerce").median()),
            "mean_alpha_weight":float(pd.to_numeric(advisor[ac],errors="coerce").mean()),
            "median_alpha_weight":float(pd.to_numeric(advisor[ac],errors="coerce").median()),
        })
    return pd.DataFrame(rows)


def benchmark_audit(source: Path, cfg: Cfg, benches: dict[str,pd.Series], market: dict, periods: list[tuple[str,pd.Timestamp,pd.Timestamp]]) -> pd.DataFrame:
    levels={}
    for sym,key in [("SPY","source_spy_benchmark"),("QQQ","source_qqq_benchmark")]:
        x=pd.read_parquet(source/cfg.p[key]); x["date"]=_date(x["date"]); x[sym]=pd.to_numeric(x[sym],errors="coerce")
        levels[sym]=x.dropna(subset=[sym]).set_index("date")[sym].sort_index()
    rows=[]
    for role,start,end in periods:
        for sym in ["SPY","QQQ"]:
            bm=benchmark_metrics(benches[sym],start,end)
            lv=levels[sym]
            inside=lv[(lv.index>=start)&(lv.index<end)]
            prev=lv[lv.index<start]
            direct_total=math.nan; direct_cagr=math.nan
            if len(inside) and len(prev):
                first=float(prev.iloc[-1]); last=float(inside.iloc[-1]); n=int(benches[sym][(benches[sym].index>=start)&(benches[sym].index<end)].dropna().shape[0])
                if first>0 and last>0 and n>0:
                    direct_total=last/first-1.0; direct_cagr=(last/first)**(252.0/n)-1.0
            rows.append({"role":role,"benchmark":sym,"start":start,"end":end,"cagr_from_returns":bm["cagr"],"direct_price_cagr":direct_cagr,"cagr_abs_diff":abs(bm["cagr"]-direct_cagr) if np.isfinite(bm["cagr"]) and np.isfinite(direct_cagr) else math.nan,"total_return":bm["total_return"],"median_active_names":math.nan,"min_active_names":math.nan,"max_active_names":math.nan})
        bm=benchmark_metrics(benches["UNIVERSE_EQUAL_WEIGHT"],start,end)
        active=market["returns"].loc[(market["returns"].index>=start)&(market["returns"].index<end)].notna().sum(axis=1)
        rows.append({"role":role,"benchmark":"UNIVERSE_EQUAL_WEIGHT","start":start,"end":end,"cagr_from_returns":bm["cagr"],"direct_price_cagr":math.nan,"cagr_abs_diff":math.nan,"total_return":bm["total_return"],"median_active_names":float(active.median()) if len(active) else math.nan,"min_active_names":int(active.min()) if len(active) else 0,"max_active_names":int(active.max()) if len(active) else 0})
    return pd.DataFrame(rows)


def build_phase3(workspace: Path) -> dict:
    cfg=load_cfg(workspace); p0,p2,champs,leader,source=load_contracts(workspace,cfg)
    features,targets=load_phase1_frames(workspace,cfg); p2cfg=load_p2_cfg(workspace)
    dense=regenerate_dense_scores(features,targets,champs,leader,p2cfg,cfg)
    # Calibration for policy selection: ONLY 2019-2020 OOF.
    cal_19_20=fit_all_calibrations(dense,targets,"OOF_2019_2020_DENSE",cfg,pd.Timestamp(cfg.p["selection_start"]))
    advisor_sel=build_advisor_surface(dense,cal_19_20,"OOF_2021_2022_DENSE")
    # Final pre-validation calibration can use all nested OOF 2019-2022, but no 2023-2024 labels.
    dense_oof=dense[dense["role"].isin(["OOF_2019_2020_DENSE","OOF_2021_2022_DENSE"])].copy()
    dense_oof=dense_oof.assign(role="OOF_2019_2022_REFIT")
    cal_19_22=fit_all_calibrations(dense_oof,targets,"OOF_2019_2022_REFIT",cfg,pd.Timestamp(cfg.p["validation_start"]))
    advisor_oof_refit=build_advisor_surface(dense_oof,cal_19_22,"OOF_2019_2022_REFIT")
    advisor_val=build_advisor_surface(dense,cal_19_22,"VALIDATION_2023_2024_DENSE")
    prices,terminals=load_price_surface(source,cfg)
    market=prepare_market(prices,pd.Timestamp(cfg.p["selection_start"]),pd.Timestamp(cfg.p["holdout_start"]),int(cfg.p["risk_lookback_sessions"]))
    benches=_benchmark_series(source,cfg,prices,market)
    risk=prepare_risk_panel(market,benches["SPY"],int(cfg.p["risk_lookback_sessions"]),int(cfg.p["minimum_risk_observations"]))
    selection_start=pd.Timestamp(cfg.p["selection_start"]); validation_start=pd.Timestamp(cfg.p["validation_start"]); hold=pd.Timestamp(cfg.p["holdout_start"])
    rows=[]
    specs=candidate_specs(cfg)
    target_cache={}
    for spec in specs:
        key=(float(spec["uncertainty_z"]),float(spec["entry_hurdle_bps"]))
        if key not in target_cache:
            target_cache[key]=build_target_path(advisor_sel,risk,*key)
    for spec in specs:
        key=(float(spec["uncertainty_z"]),float(spec["entry_hurdle_bps"]))
        tp=target_cache[key]
        b,_,_,_=simulate_dynamic_portfolio(advisor_sel,prices,terminals,benches,selection_start,validation_start,round_trip_bps=float(cfg.p["base_round_trip_cost_bps"]),cfg=cfg,prepared_market=market,prepared_risk=risk,target_path=tp,**spec)
        s,_,_,_=simulate_dynamic_portfolio(advisor_sel,prices,terminals,benches,selection_start,validation_start,round_trip_bps=float(cfg.p["stress_round_trip_cost_bps"]),cfg=cfg,prepared_market=market,prepared_risk=risk,target_path=tp,**spec)
        b=enrich_with_benchmarks(b,benches,selection_start,validation_start); s=enrich_with_benchmarks(s,benches,selection_start,validation_start)
        qualified=(np.isfinite(b["robust_excess_cagr"]) and b["robust_excess_cagr"]>0 and np.isfinite(s["robust_excess_cagr"]) and s["robust_excess_cagr"]>0 and b["execution_skip_rate"]<=float(cfg.p["maximum_execution_skip_rate"]))
        rows.append({**spec,"cagr_20bps":b["cagr"],"spy_cagr":b.get("spy_cagr"),"qqq_cagr":b.get("qqq_cagr"),"universe_equal_weight_cagr":b.get("universe_equal_weight_cagr"),"excess_cagr_vs_spy_20bps":b.get("excess_cagr_vs_spy"),"excess_cagr_vs_qqq_20bps":b.get("excess_cagr_vs_qqq"),"excess_cagr_vs_uew_20bps":b.get("excess_cagr_vs_universe_equal_weight"),"robust_excess_cagr_20bps":b["robust_excess_cagr"],"max_drawdown_20bps":b["max_drawdown"],"annual_turnover_20bps":b["annual_turnover"],"median_holdings_20bps":b["median_holdings"],"min_holdings_20bps":b["min_holdings"],"max_holdings_20bps":b["max_holdings"],"median_max_name_weight_20bps":b["median_max_name_weight"],"p95_max_name_weight_20bps":b["p95_max_name_weight"],"mean_cash_weight_20bps":b["mean_cash_weight"],"scheduled_rebalances_20bps":b["scheduled_rebalances"],"execution_skip_rate_20bps":b["execution_skip_rate"],"partial_execution_days_20bps":b.get("partial_execution_days",0),"unfilled_trade_notional_20bps":b.get("unfilled_trade_notional",0.0),"cagr_40bps":s["cagr"],"robust_excess_cagr_40bps":s["robust_excess_cagr"],"max_drawdown_40bps":s["max_drawdown"],"annual_turnover_40bps":s["annual_turnover"],"qualified":bool(qualified)})
    leaderboard=rank_policies(pd.DataFrame(rows)); qual=leaderboard[leaderboard["qualified"]]
    champion=(qual.iloc[0] if len(qual) else leaderboard.iloc[0]).to_dict()
    policy_spec={k:float(champion[k]) for k in ["uncertainty_z","entry_hurdle_bps","rebalance_extra_edge_bps"]}
    # Build carry-in state with frozen policy and OOF-refit calibration, then confirm 2023-2024 only.
    pre_val=advisor_oof_refit[(advisor_oof_refit["signal_date"]>=selection_start)&(advisor_oof_refit["signal_date"]<validation_start)]
    tp_pre=build_target_path(pre_val,risk,float(policy_spec["uncertainty_z"]),float(policy_spec["entry_hurdle_bps"]))
    tp_val=build_target_path(advisor_val,risk,float(policy_spec["uncertainty_z"]),float(policy_spec["entry_hurdle_bps"]))
    _,_,carry_w,carry_c=simulate_dynamic_portfolio(pre_val,prices,terminals,benches,selection_start,validation_start,round_trip_bps=float(cfg.p["base_round_trip_cost_bps"]),cfg=cfg,prepared_market=market,prepared_risk=risk,target_path=tp_pre,**policy_spec)
    _,_,carry_ws,carry_cs=simulate_dynamic_portfolio(pre_val,prices,terminals,benches,selection_start,validation_start,round_trip_bps=float(cfg.p["stress_round_trip_cost_bps"]),cfg=cfg,prepared_market=market,prepared_risk=risk,target_path=tp_pre,**policy_spec)
    vb,vnav,_,_=simulate_dynamic_portfolio(advisor_val,prices,terminals,benches,validation_start,hold,round_trip_bps=float(cfg.p["base_round_trip_cost_bps"]),cfg=cfg,initial_weights=carry_w,initial_cash=carry_c,prepared_market=market,prepared_risk=risk,target_path=tp_val,**policy_spec)
    vs,_,_,_=simulate_dynamic_portfolio(advisor_val,prices,terminals,benches,validation_start,hold,round_trip_bps=float(cfg.p["stress_round_trip_cost_bps"]),cfg=cfg,initial_weights=carry_ws,initial_cash=carry_cs,prepared_market=market,prepared_risk=risk,target_path=tp_val,**policy_spec)
    vb=enrich_with_benchmarks(vb,benches,validation_start,hold); vs=enrich_with_benchmarks(vs,benches,validation_start,hold)
    validation_confirmed=bool(vb["robust_excess_cagr"]>0 and vs["robust_excess_cagr"]>0)
    influence=pd.concat([horizon_influence_summary(advisor_sel,"POLICY_SELECTION_2021_2022"),horizon_influence_summary(advisor_val,"VALIDATION_2023_2024")],ignore_index=True)
    bench_audit=benchmark_audit(source,cfg,benches,market,[("POLICY_SELECTION_2021_2022",selection_start,validation_start),("VALIDATION_2023_2024",validation_start,hold)])
    # integrity / term structure counts
    wide=dense.pivot_table(index=["signal_date","ticker","role"],columns="horizon_sessions",values="score",aggfunc="first")
    horizon_counts=wide.notna().sum(axis=1)
    parts={"phase2_status":p2["status"],"max_score_date":dense["signal_date"].max(),"dense_horizons":sorted(dense["horizon_sessions"].astype(int).unique().tolist()),"minimum_daily_horizon_count":int(horizon_counts.min()) if len(horizon_counts) else 0,"fixed_cardinality":False,"fixed_position_cap":False,"qualified_policies":int(leaderboard["qualified"].sum()),"validation_used_for_selection":False,"validation_confirmed":validation_confirmed}
    gate,status=evaluate_gate(parts,cfg)
    out=workspace/"outputs"; out.mkdir(parents=True,exist_ok=True)
    dense.to_parquet(out/"v13_phase3_dense_horizon_scores.parquet",index=False)
    pd.concat([advisor_sel.assign(role="POLICY_SELECTION_2021_2022"),advisor_val.assign(role="VALIDATION_2023_2024")],ignore_index=True).to_parquet(out/"v13_phase3_advisor_surface.parquet",index=False)
    cal_19_20.to_csv(out/"v13_phase3_calibration_2019_2020.csv",index=False); cal_19_22.to_csv(out/"v13_phase3_calibration_refit_2019_2022.csv",index=False)
    leaderboard.to_csv(out/"v13_phase3_dynamic_portfolio_leaderboard.csv",index=False)
    influence.to_csv(out/"v13_phase3_horizon_influence_audit.csv",index=False)
    bench_audit.to_csv(out/"v13_phase3_benchmark_audit.csv",index=False)
    pd.DataFrame([{**policy_spec,"selection_cagr_20bps":champion.get("cagr_20bps"),"selection_robust_excess_cagr_20bps":champion.get("robust_excess_cagr_20bps"),"selection_cagr_40bps":champion.get("cagr_40bps"),"selection_robust_excess_cagr_40bps":champion.get("robust_excess_cagr_40bps")}]).to_csv(out/"v13_phase3_selected_policy.csv",index=False)
    pd.DataFrame([{"cost_bps":cfg.p["base_round_trip_cost_bps"],**vb},{"cost_bps":cfg.p["stress_round_trip_cost_bps"],**vs}]).to_csv(out/"v13_phase3_validation_confirmation.csv",index=False)
    vnav.to_csv(out/"v13_phase3_validation_nav_base.csv",index=False)
    gate.to_csv(out/"v13_phase3_gate.csv",index=False)
    advisor_spec={"build":BUILD,"advisor":"SIMULTANEOUS_SIX_HORIZON_TERM_STRUCTURE","horizons":list(HORIZONS),"horizon_discarded":False,"holding_period_fixed":False,"daily_reevaluation":True,"aggregation":"each horizon score -> two OOF calibrations: absolute expected return for sizing and robust benchmark alpha for diagnostics; precision-weighted across all six; uncertainty includes cross-horizon disagreement","tactical_horizons":[5,10,20],"strategic_horizons":[60,120,252],"portfolio":{"cardinality":"ENDOGENOUS_POSITIVE_RETURN_LCB","position_cap":None,"position_floor":None,"sizing":"LONG_ONLY_ONE_FACTOR_KELLY_ON_POSTERIOR_MEAN_RETURN_WITH_LCB_ADMISSION_AND_CASH","covariance":"CAUSAL_TRAILING_ONE_FACTOR_SPY_PLUS_IDIOSYNCRATIC_VARIANCE","execution":"evaluate every session; trade t+1 only when expected incremental portfolio return over each name's endogenous effective horizon > cost + learned extra edge; benchmark excess is enforced at portfolio qualification","selected_policy":policy_spec},"selection_period":"2021-2022 only after calibration on 2019-2020","validation_period":"2023-2024 confirmation only","holdout_start":cfg.p["holdout_start"],"holdout_used":False}
    (out/"v13_phase3_advisor_spec.json").write_text(json.dumps(advisor_spec,indent=2,default=str),encoding="utf-8")
    summary={"status":status,"phase":"V13-P3","build":BUILD,"name":cfg.p["name"],"objective":cfg.p["objective"],"phase2_input":{"status":p2["status"],"build":p2["build"]},"advisor":{"horizons":list(HORIZONS),"simultaneous":True,"daily_reevaluation":True,"fixed_holding_period":False,"tactical_horizons":[5,10,20],"strategic_horizons":[60,120,252],"dense_score_rows":int(len(dense)),"selection_advisor_rows":int(len(advisor_sel)),"validation_advisor_rows":int(len(advisor_val))},"dynamic_portfolio":{"fixed_cardinality":False,"fixed_min_weight":False,"fixed_max_weight":False,"cash_allowed":True,"candidate_policies":int(len(leaderboard)),"qualified_policies":int(leaderboard["qualified"].sum()),"selected_policy":policy_spec,"selection_metrics":{"cagr_20bps":champion.get("cagr_20bps"),"robust_excess_cagr_20bps":champion.get("robust_excess_cagr_20bps"),"median_holdings":champion.get("median_holdings_20bps"),"max_holdings":champion.get("max_holdings_20bps"),"median_max_name_weight":champion.get("median_max_name_weight_20bps"),"p95_max_name_weight":champion.get("p95_max_name_weight_20bps"),"execution_shortfall_notional_rate_20bps":champion.get("execution_skip_rate_20bps")},"horizon_influence":influence.to_dict(orient="records"),"benchmark_audit":bench_audit.to_dict(orient="records")},"validation":{"confirmed":validation_confirmed,"base":vb,"stress":vs,"used_for_selection":False},"holdout":{"start":cfg.p["holdout_start"],"used":False},"gate":gate.to_dict(orient="records"),"readiness":("READY_FOR_PRE2025_ADVISOR_STRESS_AND_FREEZE_RESEARCH" if status=="PASS" and validation_confirmed else ("RESEARCH_PASS_VALIDATION_NOT_CONFIRMED" if status=="PASS" else "NOT_READY")),"next_gate":"If PASS: Phase 4 stress-tests advisor persistence, benchmark alpha, concentration and turnover pre-2025; then freezes V13 before the code-blinded 2025+ confirmation."}
    (out/"v13_phase3_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    return summary
