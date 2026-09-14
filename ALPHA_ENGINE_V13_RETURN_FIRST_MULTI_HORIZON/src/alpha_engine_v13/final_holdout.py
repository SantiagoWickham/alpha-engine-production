from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tomllib
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import Ridge

from alpha_engine_v13 import active_alpha_persistent_portfolio as p3y
from alpha_engine_v13 import adaptive_alpha_rebuild as p2r
from alpha_engine_v13 import alpha_factory as p1
from alpha_engine_v13 import economic_portfolio_closure as p3v
from alpha_engine_v13 import event_sector_incremental_alpha as p2u
from alpha_engine_v13 import roundtrip_resize_hysteresis as p3z

BUILD = "V13_P4_ONE_SHOT_CODE_BLINDED_HOLDOUT_2026-09-13"
HORIZONS = (5, 10, 20, 60, 120, 252)


@dataclass(frozen=True)
class Cfg:
    p: dict


def _date(s):
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")


def _ticker(s):
    return s.astype(str).str.upper().str.replace(".", "-", regex=False).str.strip()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_payload(x) -> str:
    raw = json.dumps(x, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _git(workspace: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def load_cfg(workspace: Path) -> Cfg:
    with (workspace / "config" / "v13_phase4.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase4"])


def source_root_from_phase0(workspace: Path) -> Path:
    p = workspace / "outputs" / "v13_phase0_summary.json"
    x = json.loads(p.read_text(encoding="utf-8"))
    src = x.get("source_manifest", {}).get("source_v12_root")
    if not src:
        raise RuntimeError("source_v12_root missing from Phase0")
    return Path(src)


def verify_research_freeze(workspace: Path, cfg: Cfg) -> dict:
    s = json.loads((workspace / cfg.p["phase3aa_summary"]).read_text(encoding="utf-8"))
    m = json.loads((workspace / cfg.p["phase3aa_freeze_manifest"]).read_text(encoding="utf-8"))
    if s.get("status") != "PASS" or s.get("holdout_used") is not False:
        raise RuntimeError("Phase3AA must PASS with holdout unused")
    if s.get("policy_changed") is not False or s.get("predictor_retrained") is not False:
        raise RuntimeError("Phase3AA research freeze is not immutable")
    if str(m.get("freeze_id")) != str(cfg.p["expected_research_freeze_id"]):
        raise RuntimeError("Unexpected research freeze_id")
    bad = []
    for r in m.get("files", []):
        p = workspace / str(r["path"])
        if not p.exists():
            bad.append((str(r["path"]), "MISSING"))
        elif _sha256_file(p) != str(r["sha256"]):
            bad.append((str(r["path"]), "SHA256_MISMATCH"))
    if bad:
        raise RuntimeError(f"Research freeze file mismatch: {bad[:3]}")
    tag_commit = _git(workspace, "rev-parse", f"{cfg.p['expected_research_tag']}^{{commit}}")
    if tag_commit != str(cfg.p["expected_research_commit"]):
        raise RuntimeError(f"Research tag points to {tag_commit}, expected {cfg.p['expected_research_commit']}")
    return {"summary": s, "manifest": m, "tag_commit": tag_commit}



def _valid_local_seal(workspace: Path, cfg: Cfg):
    mp = workspace / cfg.p["seal_manifest"]; bp = workspace / cfg.p["sealed_model_bundle"]
    if not mp.exists() or not bp.exists(): return None
    try:
        m = json.loads(mp.read_text(encoding="utf-8")); core = {k: v for k, v in m.items() if k != "seal_id"}
        if _sha256_payload(core) != m.get("seal_id"): return None
        for r in m.get("files", []):
            p = workspace / r["path"]
            if not p.exists() or _sha256_file(p) != r["sha256"]: return None
        return m
    except Exception:
        return None

def _preholdout_inputs(workspace: Path, hold: pd.Timestamp):
    f = pd.read_parquet(workspace / "outputs" / "v13_phase1_feature_library.parquet")
    t = pd.read_parquet(workspace / "outputs" / "v13_phase1_research_targets.parquet")
    for x in (f, t):
        x["signal_date"] = _date(x["signal_date"])
        x["ticker"] = _ticker(x["ticker"])
        if (x["signal_date"] >= hold).any():
            raise RuntimeError("SEAL HOLDOUT BREACH")
    return f.sort_values(["signal_date", "ticker"]), t.sort_values(["signal_date", "ticker"])


def _base_train_rows(df: pd.DataFrame, h: int, hold: pd.Timestamp, cfg2r) -> pd.DataFrame:
    start = max(pd.Timestamp(cfg2r.p["research_start"]), hold - pd.DateOffset(years=int(cfg2r.p["max_train_years"])))
    ec, rc, yc = f"target_end_date_{h}d", f"target_resolved_{h}d", f"fwd_return_{h}d"
    q = df[(df.signal_date >= start) & (df.signal_date < hold) & df[rc].fillna(False) & df[ec].notna() & (df[ec] < hold) & df[yc].notna()].copy()
    if len(q) and not (q[ec] < hold).all():
        raise RuntimeError("FINAL BASE TRAIN PURGE BREACH")
    return q


def _fit_base_bundle(train: pd.DataFrame, cols: list[str], h: int, cfg2r, expert_weights: dict) -> dict:
    w = p2r.recency_weights(train.signal_date, int(cfg2r.p["recency_half_life_sessions"]))
    y_rank = p2r._daily_rank(train, f"fwd_return_{h}d")
    y_abs, _ = p2r._clip_train_apply(pd.to_numeric(train[f"fwd_return_{h}d"], errors="coerce").to_numpy(float))
    ex = np.nanmin(train[[f"excess_spy_{h}d", f"excess_qqq_{h}d"]].to_numpy(float), axis=1)
    y_ex, _ = p2r._clip_train_apply(ex)
    winner = (y_rank >= float(cfg2r.p["winner_quantile"])).astype(int)
    x = p2r._mat(train, cols)
    mu = np.average(x, axis=0, weights=w)
    var = np.average((x - mu) ** 2, axis=0, weights=w)
    sd = np.sqrt(np.maximum(var, 1e-8))
    ok = np.isfinite(y_rank)
    ridge = Ridge(alpha=float(cfg2r.p["ridge_alpha"]))
    ridge.fit(((x - mu) / sd)[ok], y_rank[ok], sample_weight=w[ok])
    hp = dict(loss="squared_error", learning_rate=float(cfg2r.p["hgb_learning_rate"]), max_iter=int(cfg2r.p["hgb_max_iter"]), max_leaf_nodes=int(cfg2r.p["hgb_max_leaf_nodes"]), min_samples_leaf=int(cfg2r.p["hgb_min_samples_leaf"]), l2_regularization=float(cfg2r.p["hgb_l2"]), random_state=int(cfg2r.p["random_state"]))
    models = {"RIDGE_RANK_DECAY": ridge}
    for name, y in [("HGB_RANK_DECAY", y_rank), ("HGB_ABS_RETURN_DECAY", y_abs), ("HGB_BENCH_EXCESS_DECAY", y_ex)]:
        good = np.isfinite(y)
        m = HistGradientBoostingRegressor(**hp)
        m.fit(x[good], y[good], sample_weight=w[good])
        models[name] = m
    cp = dict(learning_rate=float(cfg2r.p["hgb_learning_rate"]), max_iter=int(cfg2r.p["hgb_max_iter"]), max_leaf_nodes=int(cfg2r.p["hgb_max_leaf_nodes"]), min_samples_leaf=int(cfg2r.p["hgb_min_samples_leaf"]), l2_regularization=float(cfg2r.p["hgb_l2"]), random_state=int(cfg2r.p["random_state"]))
    c = HistGradientBoostingClassifier(**cp)
    c.fit(x[ok], winner[ok], sample_weight=w[ok])
    models["HGB_WINNER_DECAY"] = c
    return {"features": cols, "models": models, "ridge_mu": mu, "ridge_sd": sd, "expert_weights": expert_weights, "train_rows": int(len(train))}


def _fit_meta_bundle(train: pd.DataFrame, cols: list[str], cfg2u, expert_weights: dict) -> dict:
    x = p2u._mat(train, cols)
    yr = pd.to_numeric(train._alpha_rank, errors="coerce").to_numpy(float)
    ya = pd.to_numeric(train._robust_alpha, errors="coerce").clip(train._robust_alpha.quantile(.01), train._robust_alpha.quantile(.99)).to_numpy(float)
    win = train._winner.to_numpy(int)
    lose = train._loser.to_numpy(int)
    mu = np.nanmean(x, axis=0)
    sd = np.nanstd(x, axis=0)
    sd = np.where(sd > 1e-6, sd, 1.0)
    ridge = Ridge(alpha=float(cfg2u.p["ridge_alpha"]))
    ridge.fit((x - mu) / sd, yr)
    hp = dict(loss="squared_error", learning_rate=float(cfg2u.p["hgb_learning_rate"]), max_iter=int(cfg2u.p["hgb_max_iter"]), max_leaf_nodes=int(cfg2u.p["hgb_max_leaf_nodes"]), min_samples_leaf=int(cfg2u.p["hgb_min_samples_leaf"]), l2_regularization=float(cfg2u.p["hgb_l2"]), random_state=int(cfg2u.p["random_state"]))
    models = {"RIDGE_NEWINFO": ridge}
    for name, y in [("HGB_NEWINFO_RANK", yr), ("HGB_NEWINFO_RETURN", ya)]:
        m = HistGradientBoostingRegressor(**hp)
        m.fit(x, y)
        models[name] = m
    cp = {k: v for k, v in hp.items() if k != "loss"}
    cw = HistGradientBoostingClassifier(**cp); cw.fit(x, win); models["HGB_NEWINFO_WINNER"] = cw
    cd = HistGradientBoostingClassifier(**cp); cd.fit(x, lose); models["HGB_NEWINFO_AVOID"] = cd
    return {"features": cols, "models": models, "ridge_mu": mu, "ridge_sd": sd, "expert_weights": expert_weights, "train_rows": int(len(train))}


def _fit_iso_object(score, y):
    x = np.asarray(score, float); z = np.asarray(y, float); ok = np.isfinite(x) & np.isfinite(z); x = x[ok]; z = p3y._winsor(z[ok])
    if len(x) < 500 or np.unique(x).size < 10:
        return {"kind": "constant", "value": float(np.nanmean(z)) if len(z) else 0.0, "sd": max(float(np.nanstd(z)) if len(z) > 1 else 1e-4, 1e-6), "n": int(len(x))}
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip").fit(x, z)
    pred = iso.predict(x)
    return {"kind": "isotonic", "model": iso, "sd": max(float(np.nanstd(z - pred)), 1e-6), "n": int(len(x))}


def _predict_iso(bundle: dict, q) -> np.ndarray:
    a = np.asarray(q, float)
    if bundle["kind"] == "constant":
        return np.full(len(a), float(bundle["value"]), float)
    return bundle["model"].predict(a)


def seal_final_models(workspace: Path) -> dict:
    cfg = load_cfg(workspace); hold = pd.Timestamp(cfg.p["holdout_start"])
    verify_research_freeze(workspace, cfg)
    marker = workspace / cfg.p["holdout_open_marker"]
    if marker.exists():
        raise RuntimeError("Cannot seal/reseal after the 2025+ holdout has been opened")
    existing = _valid_local_seal(workspace, cfg)
    if existing is not None:
        artifact = workspace / cfg.p["seal_artifact_copy"]; artifact.parent.mkdir(parents=True, exist_ok=True); artifact.write_text((workspace / cfg.p["seal_manifest"]).read_text(encoding="utf-8"), encoding="utf-8")
        return existing
    raw, targets = _preholdout_inputs(workspace, hold)
    cfg2r = p2r.load_cfg(workspace); cfg2u = p2u.load_cfg(workspace); cfg3z = p3z.load_cfg(workspace)
    base_features = p2r.usable_features(raw, cfg2r)
    ranked = p2r.cross_sectional_rank_features(raw, base_features)
    transformed, extra = p2r.add_regime_features(raw, ranked)
    all_features = base_features + extra
    spec_path = workspace / cfg.p["phase2r_model_spec"]
    p2r_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec_by_h = {int(r["horizon_sessions"]): r for r in p2r_spec["selected_horizon_ensembles"]}
    p2r_oof = pd.read_parquet(workspace / cfg.p["phase2r_oof_scores"]); p2r_oof["signal_date"] = _date(p2r_oof.signal_date); p2r_oof["ticker"] = _ticker(p2r_oof.ticker)
    p2u_oof = pd.read_parquet(workspace / cfg.p["phase2u_oof_scores"]); p2u_oof["signal_date"] = _date(p2u_oof.signal_date); p2u_oof["ticker"] = _ticker(p2u_oof.ticker)
    info = pd.read_parquet(workspace / cfg.p["phase2u_newinfo_surface"]); info["signal_date"] = _date(info.signal_date); info["ticker"] = _ticker(info.ticker)
    if max(p2r_oof.signal_date.max(), p2u_oof.signal_date.max(), info.signal_date.max()) >= hold:
        raise RuntimeError("SEAL HOLDOUT BREACH in cached OOF/new-info surfaces")
    ev = pd.read_csv(workspace / cfg.p["phase2u_expert_evidence"])
    ev = ev[ev.expert.astype(str).ne("META_BLEND")].copy()
    meta_weights = p2u.expert_weights(ev, cfg2u)
    bundle = {"build": BUILD, "holdout_start": str(hold.date()), "horizons": list(HORIZONS), "base_feature_universe": list(base_features), "base": {}, "meta": {}, "calibration": {}, "phase3z_policy": dict(cfg3z.p)}
    selected_rows = []
    skills = {}
    for h in HORIZONS:
        d = p2r.merge_horizon(transformed, targets, h)
        tr = _base_train_rows(d, h, hold, cfg2r)
        if len(tr) < 5000:
            raise RuntimeError(f"Insufficient final base train rows h={h}: {len(tr)}")
        cols, _ = p2r.select_features(tr, all_features, h, cfg2r)
        ew = spec_by_h[h]["final_expert_weights"]
        if isinstance(ew, str): ew = json.loads(ew)
        bundle["base"][h] = _fit_base_bundle(tr, cols, h, cfg2r, ew)
        selected_rows.extend([{"layer": "BASE", "horizon_sessions": h, "feature": c} for c in cols])
        dm = p2u.horizon_frame(p2r_oof, targets, info, h)
        ec, rc = f"target_end_date_{h}d", f"target_resolved_{h}d"
        mt = dm[dm[rc].fillna(False) & dm[ec].notna() & (dm[ec] < hold) & dm._robust_alpha.notna()].copy()
        if len(mt) < 5000:
            raise RuntimeError(f"Insufficient final meta train rows h={h}: {len(mt)}")
        candidates = ["base_score"] + [c for c in info.columns if c not in {"signal_date", "ticker"}]
        mcols = p2u.select_features(mt, candidates, cfg2u)
        bundle["meta"][h] = _fit_meta_bundle(mt, mcols, cfg2u, meta_weights)
        selected_rows.extend([{"layer": "META", "horizon_sessions": h, "feature": c} for c in mcols])
        ctr = p3y._train_rows(p2u_oof, targets, h, hold, cfg3z)
        skills[h] = p3y._skill(ctr, h)
        bundle["calibration"][h] = _fit_iso_object(ctr.score, ctr.active_day)
    bundle["horizon_reliability"] = p3y._softmax(skills, float(cfg3z.p["horizon_weight_floor"]), float(cfg3z.p["horizon_skill_temperature"]))
    model_path = workspace / cfg.p["sealed_model_bundle"]; model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_path, compress=3)
    selected = pd.DataFrame(selected_rows)
    selected_path = workspace / "outputs" / "v13_phase4_sealed_features.csv"; selected.to_csv(selected_path, index=False)
    input_paths = [
        workspace / cfg.p["phase3aa_freeze_manifest"], spec_path,
        workspace / cfg.p["phase2r_oof_scores"], workspace / cfg.p["phase2u_oof_scores"],
        workspace / cfg.p["phase2u_newinfo_surface"], workspace / cfg.p["phase2u_expert_evidence"],
        workspace / cfg.p["research_feature_library"], workspace / cfg.p["research_targets"],
        workspace / "config" / "v13_phase1.toml", workspace / "config" / "v13_phase2r.toml", workspace / "config" / "v13_phase2u.toml", workspace / "config" / "v13_phase3z.toml", workspace / "config" / "v13_phase4.toml",
        workspace / "src" / "alpha_engine_v13" / "alpha_factory.py", workspace / "src" / "alpha_engine_v13" / "adaptive_alpha_rebuild.py", workspace / "src" / "alpha_engine_v13" / "event_sector_incremental_alpha.py", workspace / "src" / "alpha_engine_v13" / "active_alpha_persistent_portfolio.py", workspace / "src" / "alpha_engine_v13" / "roundtrip_resize_hysteresis.py", workspace / "src" / "alpha_engine_v13" / "economic_portfolio_closure.py", workspace / "src" / "alpha_engine_v13" / "final_holdout.py",
    ]
    files = [{"path": str(p.relative_to(workspace)).replace("\\", "/"), "sha256": _sha256_file(p), "bytes": p.stat().st_size} for p in input_paths]
    files += [
        {"path": str(model_path.relative_to(workspace)).replace("\\", "/"), "sha256": _sha256_file(model_path), "bytes": model_path.stat().st_size},
        {"path": str(selected_path.relative_to(workspace)).replace("\\", "/"), "sha256": _sha256_file(selected_path), "bytes": selected_path.stat().st_size},
    ]
    core = {"build": BUILD, "research_freeze_id": cfg.p["expected_research_freeze_id"], "research_tag": cfg.p["expected_research_tag"], "holdout_start": cfg.p["holdout_start"], "files": files, "horizon_reliability": bundle["horizon_reliability"], "models_retrained_using_2025_plus": False}
    core["seal_id"] = _sha256_payload(core)
    manifest_path = workspace / cfg.p["seal_manifest"]; manifest_path.write_text(json.dumps(core, indent=2, default=str), encoding="utf-8")
    artifact = workspace / cfg.p["seal_artifact_copy"]; artifact.parent.mkdir(parents=True, exist_ok=True); artifact.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
    return core


def _apply_base_models(test: pd.DataFrame, b: dict) -> dict[str, np.ndarray]:
    cols = b["features"]; x = p2r._mat(test, cols); out = {}
    out["RIDGE_RANK_DECAY"] = b["models"]["RIDGE_RANK_DECAY"].predict((x - b["ridge_mu"]) / b["ridge_sd"])
    for n in ["HGB_RANK_DECAY", "HGB_ABS_RETURN_DECAY", "HGB_BENCH_EXCESS_DECAY"]:
        out[n] = b["models"][n].predict(x)
    out["HGB_WINNER_DECAY"] = b["models"]["HGB_WINNER_DECAY"].predict_proba(x)[:, 1]
    return out


def _apply_meta_models(test: pd.DataFrame, b: dict) -> dict[str, np.ndarray]:
    cols = b["features"]; x = p2u._mat(test, cols); out = {"BASE_OOF": pd.to_numeric(test.base_score, errors="coerce").to_numpy(float)}
    out["RIDGE_NEWINFO"] = b["models"]["RIDGE_NEWINFO"].predict((x - b["ridge_mu"]) / b["ridge_sd"])
    for n in ["HGB_NEWINFO_RANK", "HGB_NEWINFO_RETURN"]: out[n] = b["models"][n].predict(x)
    out["HGB_NEWINFO_WINNER"] = b["models"]["HGB_NEWINFO_WINNER"].predict_proba(x)[:, 1]
    out["HGB_NEWINFO_AVOID"] = 1 - b["models"]["HGB_NEWINFO_AVOID"].predict_proba(x)[:, 1]
    return out


def _load_full_market(source: Path, cfg1_full) -> tuple[pd.DataFrame, dict]:
    path = source / cfg1_full.p["source_canonical_pit_panel"]
    cols = ["date", "ticker", "close", "adj_close", "volume", "research_eligible"]
    x = pd.read_parquet(path, columns=cols); x["date"] = _date(x.date); x["ticker"] = _ticker(x.ticker)
    for c in ["close", "adj_close", "volume"]: x[c] = pd.to_numeric(x[c], errors="coerce")
    x["research_eligible"] = x.research_eligible.fillna(False).astype(bool)
    x = x[x.research_eligible & x.close.gt(0) & x.ticker.ne("")].copy()
    x, meta = p1.add_feature_price(x, source, cfg1_full)
    return x.sort_values(["ticker", "date"]), meta


def _fetch_adjusted(symbol: str, end: pd.Timestamp) -> pd.DataFrame:
    p1 = int(pd.Timestamp("2013-01-01", tz="UTC").timestamp()); p2 = int((end + pd.Timedelta(days=2)).tz_localize("UTC").timestamp())
    q = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits&includeAdjustedClose=true"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AlphaEngineV13/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r: payload = json.loads(r.read().decode("utf-8"))
    res = payload["chart"]["result"][0]; ts = res.get("timestamp", []); adj = ((res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or [])
    if not ts or len(ts) != len(adj): raise RuntimeError(f"Adjusted benchmark download failed for {symbol}")
    return pd.DataFrame({"date": pd.to_datetime(ts, unit="s", utc=True).tz_convert(None).normalize(), symbol: pd.to_numeric(pd.Series(adj), errors="coerce")}).dropna().drop_duplicates("date", keep="last")


def _load_full_bench(source: Path, cfg1_full, market: pd.DataFrame) -> pd.DataFrame:
    frames = []; target_end = pd.Timestamp(market.date.max())
    for sym in ["SPY", "QQQ"]:
        q = market[market.ticker.eq(sym)][["date", "feature_price"]].dropna().rename(columns={"feature_price": sym})
        fresh = len(q) >= 500 and pd.Timestamp(q.date.max()) >= target_end - pd.Timedelta(days=10)
        if not fresh:
            p = source / cfg1_full.p["adjusted_cache_dir"] / f"{sym}.parquet"
            if p.exists():
                z = pd.read_parquet(p); z["date"] = _date(z.date); z[sym] = pd.to_numeric(z["adj_close"], errors="coerce"); q = z[["date", sym]].dropna()
                fresh = len(q) >= 500 and pd.Timestamp(q.date.max()) >= target_end - pd.Timedelta(days=10)
        if not fresh:
            q = _fetch_adjusted(sym, target_end)
        frames.append(q.drop_duplicates("date", keep="last"))
    b = frames[0].merge(frames[1], on="date", how="outer").sort_values("date")
    if pd.Timestamp(b.date.max()) < target_end - pd.Timedelta(days=10): raise RuntimeError("Benchmark histories do not cover the holdout window")
    return b


def _rotation_full(cfg2u, end: pd.Timestamp) -> pd.DataFrame:
    frames = []
    for sym in list(cfg2u.p["sector_symbols"]) + list(cfg2u.p["macro_symbols"]):
        x = p2u._yahoo_raw_close(sym, start="2013-01-01", end=str((end + pd.Timedelta(days=2)).date()))
        frames.append(x[["date", sym]])
    z = frames[0]
    for x in frames[1:]: z = z.merge(x, on="date", how="outer", validate="one_to_one")
    return z.sort_values("date").reset_index(drop=True)


def _newinfo_holdout(source: Path, cfg2u, keys: pd.DataFrame, hold_features: pd.DataFrame, market: pd.DataFrame, end: pd.Timestamp) -> pd.DataFrame:
    raw = _rotation_full(cfg2u, end); daily, _, _ = p2u.rotation_daily_features(raw, cfg2u); ss = p2u.stock_sector_features(market[["date", "ticker", "close", "volume"]], raw, keys, cfg2u)
    fullcfg = p2u.Cfg({**cfg2u.p, "holdout_start": "2100-01-01"})
    events, _ = p2u.sec_event_table(source, market[["date", "ticker", "close", "volume"]], fullcfg); ef = p2u.attach_event_features(keys, events, market[["date", "ticker", "close", "volume"]])
    state = [c for c in ["mom_5d", "mom_20d", "mom_60d", "mom_120d", "rel_mom_spy_20", "rel_mom_qqq_20", "downside_vol_20", "downside_vol_60", "size_log_market_cap", "earnings_yield", "cash_assets", "fundamental_freshness_mean_days"] if c in hold_features.columns]
    z = keys.merge(hold_features[["signal_date", "ticker"] + state], on=["signal_date", "ticker"], how="left", validate="one_to_one").merge(daily, on="signal_date", how="left", validate="many_to_one").merge(ss, on=["signal_date", "ticker"], how="left", validate="one_to_one").merge(ef, on=["signal_date", "ticker"], how="left", validate="one_to_one")
    for h in (20, 60, 120):
        if f"mom_{h}d" in z and f"sector_implied_mom_{h}" in z: z[f"sector_residual_mom_{h}"] = pd.to_numeric(z[f"mom_{h}d"], errors="coerce") - pd.to_numeric(z[f"sector_implied_mom_{h}"], errors="coerce")
    if "earn_surprise_composite" in z and "sector_residual_mom_20" in z: z["ix_earn_surprise_sector_resid20"] = z.earn_surprise_composite * z.sector_residual_mom_20
    if "earn_surprise_composite" in z and "downside_vol_20" in z: z["ix_earn_surprise_downvol20"] = z.earn_surprise_composite * pd.to_numeric(z.downside_vol_20, errors="coerce")
    if "available_date" in z: z = z.drop(columns=["available_date"])
    for c in [c for c in z.columns if c not in {"signal_date", "ticker"}]: z[c] = pd.to_numeric(z[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
    return z.sort_values(["signal_date", "ticker"])


def _advisor_from_sealed(scores: pd.DataFrame, bundle: dict) -> pd.DataFrame:
    pieces = []
    prior = bundle["horizon_reliability"]
    for h in HORIZONS:
        q = scores[scores.horizon_sessions.eq(h)][["signal_date", "ticker", "score"]].copy()
        cal = bundle["calibration"][h]; q[f"active_{h}"] = _predict_iso(cal, q.score.to_numpy(float)); q[f"sigma_{h}"] = float(cal["sd"]); q[f"score_{h}"] = q.score; q = q.drop(columns="score"); pieces.append(q)
    z = pieces[0]
    for q in pieces[1:]: z = z.merge(q, on=["signal_date", "ticker"], how="outer", validate="one_to_one")
    sm = np.column_stack([pd.to_numeric(z.get(f"score_{h}"), errors="coerce") for h in HORIZONS]); am = np.column_stack([pd.to_numeric(z.get(f"active_{h}"), errors="coerce") for h in HORIZONS]); sig = np.column_stack([pd.to_numeric(z.get(f"sigma_{h}"), errors="coerce") for h in HORIZONS])
    pw = np.array([float(prior[h]) for h in HORIZONS], float)[None, :]; ok = np.isfinite(sm) & np.isfinite(am); dyn = pw * (.25 + np.abs(sm - .5)); dyn = np.where(ok, dyn, 0.0); den = dyn.sum(1, keepdims=True); w = np.divide(dyn, den, out=np.zeros_like(dyn), where=den > 0)
    z["expected_active_per_session"] = np.nansum(w * am, axis=1); z["uncertainty_per_session"] = np.sqrt(np.nansum((w * sig) ** 2, axis=1)); z["positive_active_horizon_share"] = np.nansum(w * (am > 0), axis=1); z["effective_horizon_sessions"] = np.nansum(w * np.array(HORIZONS, float)[None, :], axis=1); z["fold"] = "FINAL_HOLDOUT"
    for j, h in enumerate(HORIZONS): z[f"horizon_weight_{h}d"] = w[:, j]
    keep = ["signal_date", "ticker", "fold", "expected_active_per_session", "uncertainty_per_session", "positive_active_horizon_share", "effective_horizon_sessions"] + [f"horizon_weight_{h}d" for h in HORIZONS]
    return z[keep].sort_values(["signal_date", "ticker"])


def _holdout_target_keys(source: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    p = source / "outputs" / "phase3_return_targets.parquet"
    try: x = pd.read_parquet(p, columns=["signal_date", "ticker"], filters=[("signal_date", ">=", start.to_pydatetime())])
    except Exception:
        x = pd.read_parquet(p, columns=["signal_date", "ticker"]); x["signal_date"] = _date(x.signal_date); x = x[x.signal_date >= start]
    x["signal_date"] = _date(x.signal_date); x["ticker"] = _ticker(x.ticker); x = x[(x.signal_date >= start) & (x.signal_date <= end)]
    return x.drop_duplicates(["signal_date", "ticker"]).sort_values(["signal_date", "ticker"])


def _load_holdout_targets(source: Path, start: pd.Timestamp, end: pd.Timestamp, bench: pd.DataFrame) -> pd.DataFrame:
    p = source / "outputs" / "phase3_return_targets.parquet"
    cols = ["signal_date", "ticker", "entry_date"]
    for h in HORIZONS: cols += [f"target_end_date_{h}d", f"target_resolved_{h}d", f"fwd_return_{h}d", f"winner_top_decile_{h}d"]
    x = pd.read_parquet(p, columns=cols); x["signal_date"] = _date(x.signal_date); x["ticker"] = _ticker(x.ticker); x = x[(x.signal_date >= start) & (x.signal_date <= end)].copy(); x["entry_date"] = _date(x.entry_date)
    for h in HORIZONS:
        x[f"target_end_date_{h}d"] = _date(x[f"target_end_date_{h}d"]); x[f"target_resolved_{h}d"] = x[f"target_resolved_{h}d"].fillna(False).astype(bool); x[f"fwd_return_{h}d"] = pd.to_numeric(x[f"fwd_return_{h}d"], errors="coerce")
    fullcfg = p1.Cfg({"horizons": list(HORIZONS)})
    return p1.build_research_targets(x, bench, fullcfg)


def _economic_verdict(m20: dict, m40: dict, beta: pd.DataFrame) -> str:
    bm = beta.set_index("benchmark").to_dict(orient="index") if len(beta) else {}
    asp = bm.get("SPY", {}).get("alpha_ann", np.nan); au = bm.get("UEW", {}).get("alpha_ann", np.nan)
    if m20.get("cagr", -9) > m20.get("spy_cagr", 9) and m40.get("cagr", -9) > 0 and np.isfinite(asp) and asp > 0 and np.isfinite(au) and au > 0:
        return "STRONG_CONFIRMATION"
    if m20.get("cagr", -9) > 0 and m40.get("cagr", -9) > 0 and ((np.isfinite(asp) and asp > 0) or (np.isfinite(au) and au > 0)):
        return "PARTIAL_CONFIRMATION"
    return "NO_CONFIRMATION"


def _verify_seal(workspace: Path, cfg: Cfg) -> tuple[dict, dict]:
    mp = workspace / cfg.p["seal_manifest"]; bp = workspace / cfg.p["sealed_model_bundle"]
    if not mp.exists() or not bp.exists(): raise FileNotFoundError("Phase4 seal/model bundle missing")
    m = json.loads(mp.read_text(encoding="utf-8")); expected = m.get("seal_id"); core = {k: v for k, v in m.items() if k != "seal_id"}
    if _sha256_payload(core) != expected: raise RuntimeError("Phase4 seal_id does not recompute")
    for r in m.get("files", []):
        p = workspace / r["path"]
        if not p.exists() or _sha256_file(p) != r["sha256"]: raise RuntimeError(f"Phase4 seal file mismatch: {r['path']}")
    tag = f"v13-holdout-seal-{str(expected)[:8]}"
    shown = _git(workspace, "show", f"{tag}:artifacts/freeze/v13_phase4_model_seal_manifest.json")
    if hashlib.sha256(shown.encode("utf-8")).hexdigest() != hashlib.sha256((workspace / cfg.p["seal_artifact_copy"]).read_text(encoding="utf-8").encode("utf-8")).hexdigest():
        # Normalize trailing newline differences before giving up.
        if json.loads(shown) != json.loads((workspace / cfg.p["seal_artifact_copy"]).read_text(encoding="utf-8")):
            raise RuntimeError("Published Phase4 seal tag does not contain the local seal manifest")
    return m, joblib.load(bp)


def open_holdout_once(workspace: Path) -> dict:
    cfg = load_cfg(workspace); seal, bundle = _verify_seal(workspace, cfg); hold = pd.Timestamp(cfg.p["holdout_start"])
    marker = workspace / cfg.p["holdout_open_marker"]
    source_hash = _sha256_file(workspace / "src" / "alpha_engine_v13" / "final_holdout.py")
    if marker.exists():
        mk = json.loads(marker.read_text(encoding="utf-8"))
        if mk.get("state") == "COMPLETE": raise RuntimeError("2025+ holdout already opened and completed; second open is forbidden")
        if mk.get("seal_id") != seal["seal_id"] or mk.get("source_sha256") != source_hash: raise RuntimeError("Cannot resume holdout with changed seal or code")
    else:
        marker.write_text(json.dumps({"state": "OPENING", "seal_id": seal["seal_id"], "source_sha256": source_hash, "holdout_start": str(hold.date())}, indent=2), encoding="utf-8")
    source = source_root_from_phase0(workspace)
    cfg1 = p1.load_cfg(workspace); cfg1full = p1.Cfg({**cfg1.p, "holdout_start": "2100-01-01"})
    market_full, price_meta = _load_full_market(source, cfg1full); end = pd.Timestamp(market_full.date.max())
    if end < hold: raise RuntimeError("No 2025+ market data in canonical source")
    bench = _load_full_bench(source, cfg1full, market_full); keys = _holdout_target_keys(source, hold, end)
    hold_feat, _ = p1.build_feature_library(source, keys, cfg1full, market=market_full, bench=bench, price_meta=price_meta)
    research = pd.read_parquet(workspace / cfg.p["research_feature_library"]); research["signal_date"] = _date(research.signal_date); research["ticker"] = _ticker(research.ticker)
    combined = pd.concat([research, hold_feat], ignore_index=True, sort=False).sort_values(["signal_date", "ticker"])
    base_cols = list(bundle.get("base_feature_universe", []))
    missing_universe = [c for c in base_cols if c not in combined.columns]
    if missing_universe: raise RuntimeError(f"Holdout raw feature universe missing: {missing_universe[:8]}")
    ranked = p2r.cross_sectional_rank_features(combined, base_cols)
    transformed, _ = p2r.add_regime_features(combined, ranked)
    test_feat = transformed[transformed.signal_date >= hold].copy()
    base_parts = []
    for h in HORIZONS:
        b = bundle["base"][h]; missing = [c for c in b["features"] if c not in test_feat.columns]
        if missing: raise RuntimeError(f"Holdout base features missing h={h}: {missing[:8]}")
        pred = _apply_base_models(test_feat, b); sf = test_feat[["signal_date", "ticker"]].copy()
        for e, r in pred.items(): sf[e] = p2r.normalize(test_feat, r)
        score = p2r.normalize(test_feat, p2r.blend_scores(sf, b["expert_weights"]))
        q = test_feat[["signal_date", "ticker"]].copy(); q["horizon_sessions"] = h; q["fold"] = "FINAL_HOLDOUT"; q["score"] = score; base_parts.append(q)
    base_scores = pd.concat(base_parts, ignore_index=True)
    cfg2u = p2u.load_cfg(workspace); info = _newinfo_holdout(source, cfg2u, base_scores[["signal_date", "ticker"]].drop_duplicates(), hold_feat, market_full, end)
    meta_parts = []
    for h in HORIZONS:
        q = base_scores[base_scores.horizon_sessions.eq(h)][["signal_date", "ticker", "score"]].rename(columns={"score": "base_score"}).merge(info, on=["signal_date", "ticker"], how="left", validate="one_to_one")
        b = bundle["meta"][h]; missing = [c for c in b["features"] if c not in q.columns]
        if missing: raise RuntimeError(f"Holdout meta features missing h={h}: {missing[:8]}")
        pred = _apply_meta_models(q, b); sf = q[["signal_date", "ticker"]].copy()
        for e, r in pred.items(): sf[e] = p2u.daily_rank(q, r)
        score = p2u.daily_rank(q, p2u.blend(sf, b["expert_weights"]))
        o = q[["signal_date", "ticker"]].copy(); o["horizon_sessions"] = h; o["fold"] = "FINAL_HOLDOUT"; o["score"] = score; meta_parts.append(o)
    scores = pd.concat(meta_parts, ignore_index=True).sort_values(["signal_date", "ticker", "horizon_sessions"])
    advisor = _advisor_from_sealed(scores, bundle)
    cfg3z = p3z.load_cfg(workspace)
    c = pd.read_parquet(source / "outputs" / "phase2_canonical_pit_panel.parquet", columns=["date", "ticker", "close", "research_eligible"]); r = pd.read_parquet(source / "outputs" / "phase2c_return_price_layer.parquet", columns=["date", "ticker", "target_total_return_price"])
    c["date"] = _date(c.date); c["ticker"] = _ticker(c.ticker); r["date"] = _date(r.date); r["ticker"] = _ticker(r.ticker)
    surf = c.merge(r, on=["date", "ticker"], how="left"); surf["execution_close"] = pd.to_numeric(surf.close, errors="coerce"); surf["mark_price"] = pd.to_numeric(surf.target_total_return_price, errors="coerce"); surf["research_eligible"] = surf.research_eligible.fillna(False).astype(bool); surf = surf[["date", "ticker", "execution_close", "mark_price", "research_eligible"]]
    spy = bench.dropna(subset=["SPY"]).drop_duplicates("date").set_index("date")["SPY"]; qqq = bench.dropna(subset=["QQQ"]).drop_duplicates("date").set_index("date")["QQQ"]
    end_excl = end + pd.Timedelta(days=1); market = p3v.prepare_market(surf, spy, hold, end_excl, int(cfg3z.p["risk_lookback_sessions"])); benches = p3v.benchmark_returns(source, p3v.load_cfg(workspace), market, spy, qqq); terminals = p3v.load_terminals(source, p3v.load_cfg(workspace)); plans = p3z.build_plans(advisor, market, cfg3z)
    costs = [float(cfg.p["base_round_trip_cost_bps"]), float(cfg.p["stress_round_trip_cost_bps"]), float(cfg.p["extreme_round_trip_cost_bps"])]
    sims = {cst: p3y.simulate_persistent(plans, market, terminals, hold, end_excl, cst) for cst in costs}; mets = {cst: p3v._metrics(sims[cst], benches, hold, end_excl) for cst in costs}
    sr = sims[costs[0]].set_index("date").net_return; beta = pd.DataFrame([{"benchmark": k, **p3y._ols(sr, b.reindex(sr.index))} for k, b in benches.items()])
    hold_targets = _load_holdout_targets(source, hold, end, bench); evrows = []
    for h in HORIZONS:
        sc = scores[scores.horizon_sessions.eq(h)][["signal_date", "ticker", "score"]]; d = sc.merge(hold_targets, on=["signal_date", "ticker"], how="inner"); d = d[d[f"target_resolved_{h}d"].fillna(False) & d[f"target_end_date_{h}d"].notna()]
        evrows.append({"horizon_sessions": h, **p2u.evaluate(d, d.score.to_numpy(float), h, p2u.load_cfg(workspace))} if len(d) else {"horizon_sessions": h})
    evidence = pd.DataFrame(evrows)
    verdict = _economic_verdict(mets[costs[0]], mets[costs[1]], beta)
    out = workspace / "outputs"; out.mkdir(exist_ok=True)
    scores.to_parquet(out / "v13_phase4_holdout_scores.parquet", index=False); advisor.to_parquet(out / "v13_phase4_holdout_advisor.parquet", index=False); evidence.to_csv(out / "v13_phase4_holdout_horizon_evidence.csv", index=False); beta.to_csv(out / "v13_phase4_holdout_beta_attribution.csv", index=False)
    for cst, d in sims.items(): d.to_csv(out / f"v13_phase4_holdout_nav_{int(cst)}bps.csv", index=False)
    years = []
    d20 = sims[costs[0]].copy(); d20["year"] = pd.to_datetime(d20.date).dt.year
    for y, g in d20.groupby("year"):
        rr = pd.to_numeric(g.net_return, errors="coerce").fillna(0); years.append({"year": int(y), "strategy_return": float((1 + rr).prod() - 1), "sessions": int(len(g))})
    summary = {"status": "PASS", "phase": "V13-P4", "build": BUILD, "holdout_opened": True, "holdout_start": str(hold.date()), "holdout_end": str(end.date()), "seal_id": seal["seal_id"], "research_freeze_id": cfg.p["expected_research_freeze_id"], "economic_verdict": verdict, "metrics": {f"{int(c)}bps": mets[c] for c in costs}, "beta_attribution": beta.to_dict(orient="records"), "horizon_evidence": evidence.to_dict(orient="records"), "annual_returns": years, "policy_changed": False, "predictor_retrained_after_holdout_open": False, "next": "Do not retune on this holdout. Treat 2025+ as observed validation evidence and move to live/shadow production using the sealed model."}
    (workspace / cfg.p["summary"]).write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    marker.write_text(json.dumps({"state": "COMPLETE", "seal_id": seal["seal_id"], "source_sha256": source_hash, "holdout_start": str(hold.date()), "holdout_end": str(end.date()), "economic_verdict": verdict}, indent=2), encoding="utf-8")
    return summary
