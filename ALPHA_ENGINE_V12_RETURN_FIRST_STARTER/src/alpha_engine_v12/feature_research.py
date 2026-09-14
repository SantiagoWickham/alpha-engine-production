from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import norm

PHASE4_BUILD = "V1_PURGED_PRE_OOS_2026-09-12"

FUNDAMENTAL_METRICS = (
    "assets", "capex", "cash", "current_assets", "current_liabilities",
    "eps_diluted", "equity", "long_term_debt", "net_income",
    "operating_cash_flow", "operating_income", "revenue", "shares_outstanding",
)

FORBIDDEN_FEATURE_PREFIXES = (
    "fwd_", "winner_", "target_", "mfe_", "mae_", "cs_rank_pct_",
)


@dataclass(frozen=True)
class Phase4Config:
    name: str
    objective: str
    panel_path: str
    targets_path: str
    phase3_summary_path: str
    exclusions_path: str
    adjusted_cache_dir: str
    output_feature_library_path: str
    research_horizons: tuple[int, ...]
    partitions: dict[str, pd.Timestamp]
    policies: dict[str, object]
    windows: dict[str, tuple[int, ...]]


def _as_date(s: pd.Series) -> pd.Series:
    out = pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize()
    return out.astype("datetime64[ns]")


def _norm_ticker(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.replace(".", "-", regex=False).str.strip()


def _require_columns(df: pd.DataFrame, cols: Iterable[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")


def load_config(root: Path) -> Phase4Config:
    path = root / "config" / "phase4.toml"
    with path.open("rb") as f:
        raw = tomllib.load(f)
    p = raw["phase4"]
    part = {k: pd.Timestamp(v).normalize() for k, v in p["partitions"].items()}
    if not (part["development_start"] < part["validation_start"] < part["final_oos_start"]):
        raise ValueError("Phase 4 partitions must satisfy development_start < validation_start < final_oos_start")
    return Phase4Config(
        name=str(p["name"]),
        objective=str(p["objective"]),
        panel_path=str(p["panel_path"]),
        targets_path=str(p["phase3_targets_path"]),
        phase3_summary_path=str(p["phase3_summary_path"]),
        exclusions_path=str(p["research_exclusions_path"]),
        adjusted_cache_dir=str(p["adjusted_cache_dir"]),
        output_feature_library_path=str(p["output_feature_library_path"]),
        research_horizons=tuple(int(x) for x in p["research_horizons"]),
        partitions=part,
        policies=dict(p["policies"]),
        windows={k: tuple(int(x) for x in v) for k, v in p["windows"].items()},
    )


def validate_phase3_summary(summary: dict) -> None:
    if summary.get("status") != "PASS":
        raise RuntimeError("Phase 3 must PASS before Phase 4")
    if summary.get("build") != "V3_TERMINAL_OVERLAY_2026-09-12":
        raise RuntimeError("Phase 4 requires Phase 3 V3 terminal-overlay targets")
    fw = summary.get("target_firewall") or {}
    if fw.get("feature_allowed") is not False:
        raise RuntimeError("Phase 3 targets must remain feature-forbidden")


def _panel_columns() -> list[str]:
    cols = [
        "date", "ticker", "close", "volume", "adj_close", "research_eligible",
    ]
    for m in FUNDAMENTAL_METRICS:
        cols.extend([m, f"{m}__available_date", f"{m}__period_end"])
    return cols


def load_panel(root: Path, cfg: Phase4Config) -> pd.DataFrame:
    path = root / cfg.panel_path
    if not path.exists():
        raise FileNotFoundError(str(path))
    df = pd.read_parquet(path, columns=_panel_columns())
    df["date"] = _as_date(df["date"])
    df["ticker"] = _norm_ticker(df["ticker"])
    df["research_eligible"] = df["research_eligible"].fillna(False).astype(bool)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["adj_close"] = pd.to_numeric(df["adj_close"], errors="coerce")
    for m in FUNDAMENTAL_METRICS:
        df[m] = pd.to_numeric(df[m], errors="coerce")
        df[f"{m}__available_date"] = _as_date(df[f"{m}__available_date"])
        df[f"{m}__period_end"] = _as_date(df[f"{m}__period_end"])
    df = df[df["research_eligible"]].copy()
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def load_exclusions(root: Path, cfg: Phase4Config) -> pd.DataFrame:
    path = root / cfg.exclusions_path
    if not path.exists():
        return pd.DataFrame(columns=["ticker", "effective_start_date", "effective_end_date", "research_eligible", "feature_allowed"])
    x = pd.read_csv(path)
    if x.empty:
        return x
    _require_columns(x, ["ticker", "effective_start_date", "effective_end_date", "research_eligible", "feature_allowed"], "Phase 3C exclusions")
    x["ticker"] = _norm_ticker(x["ticker"])
    x["effective_start_date"] = _as_date(x["effective_start_date"])
    x["effective_end_date"] = _as_date(x["effective_end_date"])
    return x


def apply_research_exclusions(panel: pd.DataFrame, exclusions: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if exclusions.empty:
        return panel.copy(), 0
    keep = pd.Series(True, index=panel.index)
    for _, r in exclusions.iterrows():
        m = panel["ticker"].eq(str(r["ticker"]))
        m &= panel["date"].between(r["effective_start_date"], r["effective_end_date"], inclusive="both")
        keep &= ~m
    return panel.loc[keep].copy().reset_index(drop=True), int((~keep).sum())


def _cache_file(cache_dir: Path, ticker: str) -> Path:
    return cache_dir / f"{ticker.replace('/', '_').replace('\\\\', '_')}.parquet"


def build_feature_safe_adjusted_price(panel: pd.DataFrame, cache_dir: Path) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Build a temporary adjusted-price surface from source data only.

    The adjusted level is never exported as a feature. It is used only for backward-looking,
    scale-invariant transformations. Future corporate-action rescalings multiply all pre-event
    adjusted observations by a common factor, which cancels in ratios/trends/returns.
    """
    base = panel[["date", "ticker", "adj_close"]].copy()
    base = base.rename(columns={"adj_close": "source_adj_close"})
    base["price_source"] = np.where(base["source_adj_close"].notna() & (base["source_adj_close"] > 0), "PANEL_ADJ", None)

    missing_tickers = sorted(base.loc[~(base["source_adj_close"].notna() & (base["source_adj_close"] > 0)), "ticker"].unique())
    frames: list[pd.DataFrame] = []
    manifest: list[dict] = []
    for t in missing_tickers:
        cp = _cache_file(cache_dir, str(t))
        if not cp.exists():
            manifest.append({"ticker": t, "cache_exists": False, "rows": 0, "first_date": "", "last_date": ""})
            continue
        try:
            x = pd.read_parquet(cp, columns=["date", "ticker", "adj_close"])
            x["date"] = _as_date(x["date"])
            x["ticker"] = _norm_ticker(x["ticker"])
            x["adj_close"] = pd.to_numeric(x["adj_close"], errors="coerce")
            x = x[x["adj_close"].notna() & (x["adj_close"] > 0)]
            x = x.sort_values("date").drop_duplicates(["date", "ticker"], keep="last")
            if len(x):
                frames.append(x.rename(columns={"adj_close": "cache_adj_close"}))
            manifest.append({
                "ticker": t, "cache_exists": True, "rows": int(len(x)),
                "first_date": str(x["date"].min().date()) if len(x) else "",
                "last_date": str(x["date"].max().date()) if len(x) else "",
            })
        except Exception as exc:
            manifest.append({"ticker": t, "cache_exists": True, "rows": 0, "first_date": "", "last_date": "", "error": str(exc)})

    if frames:
        cache = pd.concat(frames, ignore_index=True)
        base = base.merge(cache, on=["date", "ticker"], how="left")
    else:
        base["cache_adj_close"] = np.nan
    panel_ok = base["source_adj_close"].notna() & (base["source_adj_close"] > 0)
    cache_ok = base["cache_adj_close"].notna() & (base["cache_adj_close"] > 0)
    base["feature_adj_price"] = np.where(panel_ok, base["source_adj_close"], np.where(cache_ok, base["cache_adj_close"], np.nan))
    base.loc[~panel_ok & cache_ok, "price_source"] = "V12_YAHOO_CACHE_ADJ_RETURN_ONLY"
    covered = base["feature_adj_price"].notna() & (base["feature_adj_price"] > 0)
    meta = {
        "rows": int(len(base)),
        "covered_rows": int(covered.sum()),
        "coverage": float(covered.mean()) if len(base) else math.nan,
        "tickers": int(base["ticker"].nunique()),
        "covered_tickers": int(base.loc[covered, "ticker"].nunique()),
        "panel_adj_rows": int(panel_ok.sum()),
        "cache_adj_rows": int((~panel_ok & cache_ok).sum()),
    }
    return base[["date", "ticker", "feature_adj_price"]], meta, pd.DataFrame(manifest)


def _safe_div(num: pd.Series, den: pd.Series, positive_den: bool = False) -> pd.Series:
    n = pd.to_numeric(num, errors="coerce").astype(float)
    d = pd.to_numeric(den, errors="coerce").astype(float)
    ok = np.isfinite(n) & np.isfinite(d) & (d.abs() > 1e-12)
    if positive_den:
        ok &= d > 0
    out = pd.Series(np.nan, index=num.index, dtype=float)
    out.loc[ok] = n.loc[ok] / d.loc[ok]
    return out


def _positive_growth(cur: pd.Series, lag: pd.Series) -> pd.Series:
    c = pd.to_numeric(cur, errors="coerce").astype(float)
    l = pd.to_numeric(lag, errors="coerce").astype(float)
    ok = np.isfinite(c) & np.isfinite(l) & (c > 0) & (l > 0)
    out = pd.Series(np.nan, index=cur.index, dtype=float)
    out.loc[ok] = c.loc[ok] / l.loc[ok] - 1.0
    return out


def _rolling_min_periods(w: int) -> int:
    return max(3, int(math.ceil(w * 0.80)))


def _per_ticker_features(g: pd.DataFrame, cfg: Phase4Config) -> pd.DataFrame:
    g = g.sort_values("date").copy()
    idx = g.index
    p = pd.to_numeric(g["feature_adj_price"], errors="coerce").astype(float)
    r1 = p.pct_change(1, fill_method=None)
    out = pd.DataFrame(index=idx)

    # Price / trend family: only backward-looking, scale-invariant transforms of adjusted source prices.
    for w in cfg.windows["return_windows"]:
        out[f"mom_{w}d"] = p / p.shift(w) - 1.0
    out["mom_skip_20_5"] = p.shift(5) / p.shift(20) - 1.0
    out["mom_skip_60_5"] = p.shift(5) / p.shift(60) - 1.0
    out["mom_skip_120_20"] = p.shift(20) / p.shift(120) - 1.0
    out["mom_skip_252_20"] = p.shift(20) / p.shift(252) - 1.0

    for w in cfg.windows["trend_windows"]:
        minp = _rolling_min_periods(w)
        roll_mean = p.rolling(w, min_periods=minp).mean()
        roll_max = p.rolling(w, min_periods=minp).max()
        roll_min = p.rolling(w, min_periods=minp).min()
        out[f"trend_sma_{w}d"] = p / roll_mean - 1.0
        out[f"drawdown_high_{w}d"] = p / roll_max - 1.0
        out[f"distance_low_{w}d"] = p / roll_min - 1.0

    for w in cfg.windows["vol_windows"]:
        minp = _rolling_min_periods(w)
        out[f"vol_{w}d"] = r1.rolling(w, min_periods=minp).std(ddof=1) * math.sqrt(252.0)
    for w in (20, 60):
        minp = _rolling_min_periods(w)
        down = r1.clip(upper=0.0)
        out[f"downside_vol_{w}d"] = np.sqrt((down.pow(2)).rolling(w, min_periods=minp).mean()) * math.sqrt(252.0)
        out[f"worst_day_{w}d"] = r1.rolling(w, min_periods=minp).min()
    out["skew_60d"] = r1.rolling(60, min_periods=_rolling_min_periods(60)).skew()

    def avg_log_return(w: int) -> pd.Series:
        ratio = p / p.shift(w)
        return np.log(ratio.where(ratio > 0)) / float(w)
    out["mom_accel_20_60"] = avg_log_return(20) - avg_log_return(60)
    out["mom_accel_60_120"] = avg_log_return(60) - avg_log_return(120)
    out["mom_accel_120_252"] = avg_log_return(120) - avg_log_return(252)

    # Liquidity uses observable raw close/volume at t and causal return to t.
    close = pd.to_numeric(g["close"], errors="coerce").astype(float)
    vol = pd.to_numeric(g["volume"], errors="coerce").astype(float)
    dollar = (close * vol).where((close > 0) & (vol >= 0))
    for w in cfg.windows["liquidity_windows"]:
        minp = _rolling_min_periods(w)
        dmean = dollar.rolling(w, min_periods=minp).mean()
        out[f"liq_log_dollar_volume_{w}d"] = np.log1p(dmean.where(dmean >= 0))
        amihud = (r1.abs() / dollar.replace(0, np.nan)).rolling(w, min_periods=minp).mean()
        out[f"liq_amihud_{w}d"] = np.log1p(amihud * 1e9)
    dv20 = dollar.rolling(20, min_periods=_rolling_min_periods(20)).mean()
    dv60 = dollar.rolling(60, min_periods=_rolling_min_periods(60)).mean()
    out["liq_dollar_volume_trend_20_60"] = np.log((dv20 / dv60).where((dv20 > 0) & (dv60 > 0)))
    out["liq_zero_volume_20d"] = vol.eq(0).rolling(20, min_periods=_rolling_min_periods(20)).mean()

    # Fundamental snapshot features. Flow metrics are intentionally labelled reported/snapshot, not TTM.
    assets = g["assets"]
    revenue = g["revenue"]
    equity = g["equity"]
    debt = g["long_term_debt"]
    cash = g["cash"]
    ni = g["net_income"]
    opi = g["operating_income"]
    ocf = g["operating_cash_flow"]
    capex = g["capex"]
    ca = g["current_assets"]
    cl = g["current_liabilities"]
    shares = g["shares_outstanding"]
    eps = g["eps_diluted"]

    market_cap = (close * shares).where((close > 0) & (shares > 0))
    out["size_log_market_cap"] = np.log(market_cap.where(market_cap > 0))
    out["size_log_assets"] = np.log(pd.to_numeric(assets, errors="coerce").where(pd.to_numeric(assets, errors="coerce") > 0))
    out["size_log_shares"] = np.log(pd.to_numeric(shares, errors="coerce").where(pd.to_numeric(shares, errors="coerce") > 0))

    out["fund_cash_assets"] = _safe_div(cash, assets, positive_den=True)
    out["fund_debt_assets"] = _safe_div(debt, assets, positive_den=True)
    out["fund_equity_assets"] = _safe_div(equity, assets, positive_den=True)
    out["fund_current_ratio"] = _safe_div(ca, cl, positive_den=True)
    out["fund_net_debt_assets"] = _safe_div(pd.to_numeric(debt, errors="coerce") - pd.to_numeric(cash, errors="coerce"), assets, positive_den=True)

    out["quality_profit_assets_reported"] = _safe_div(ni, assets, positive_den=True)
    out["quality_operating_income_assets_reported"] = _safe_div(opi, assets, positive_den=True)
    out["quality_ocf_assets_reported"] = _safe_div(ocf, assets, positive_den=True)
    out["quality_fcf_assets_reported"] = _safe_div(pd.to_numeric(ocf, errors="coerce") - pd.to_numeric(capex, errors="coerce"), assets, positive_den=True)
    out["quality_accruals_assets_reported"] = _safe_div(pd.to_numeric(ni, errors="coerce") - pd.to_numeric(ocf, errors="coerce"), assets, positive_den=True)
    out["quality_profit_margin_reported"] = _safe_div(ni, revenue, positive_den=True)
    out["quality_operating_margin_reported"] = _safe_div(opi, revenue, positive_den=True)
    out["quality_ocf_margin_reported"] = _safe_div(ocf, revenue, positive_den=True)

    out["value_book_to_market_snapshot"] = _safe_div(equity, market_cap, positive_den=True)
    out["value_sales_yield_reported"] = _safe_div(revenue, market_cap, positive_den=True)
    out["value_earnings_yield_reported"] = _safe_div(ni, market_cap, positive_den=True)
    out["value_ocf_yield_reported"] = _safe_div(ocf, market_cap, positive_den=True)
    out["value_fcf_yield_reported"] = _safe_div(pd.to_numeric(ocf, errors="coerce") - pd.to_numeric(capex, errors="coerce"), market_cap, positive_den=True)
    out["value_eps_yield_reported"] = _safe_div(eps, close, positive_den=True)

    # Fundamental freshness and event-intensity features.
    avail_cols = [f"{m}__available_date" for m in FUNDAMENTAL_METRICS]
    latest = g[avail_cols].max(axis=1)
    out["fund_latest_update_age_days"] = (g["date"] - latest).dt.days.astype(float)
    for m, short in [("revenue", "revenue"), ("net_income", "net_income"), ("operating_cash_flow", "ocf")]:
        out[f"fund_{short}_age_days"] = (g["date"] - g[f"{m}__available_date"]).dt.days.astype(float)

    update_events = pd.Series(0.0, index=g.index)
    for m in FUNDAMENTAL_METRICS:
        a = g[f"{m}__available_date"]
        changed = a.notna() & a.ne(a.shift(1)) & a.eq(g["date"])
        update_events = update_events + changed.astype(float)
    out["fund_update_count_20d"] = update_events.rolling(20, min_periods=1).sum()
    out["fund_update_count_60d"] = update_events.rolling(60, min_periods=1).sum()

    # Causal changes over observed ticker sessions.
    for w in cfg.windows["fundamental_change_windows"]:
        out[f"growth_revenue_{w}s"] = _positive_growth(revenue, revenue.shift(w))
        if w == 252:
            out[f"growth_assets_{w}s"] = _positive_growth(assets, assets.shift(w))
            out[f"growth_shares_{w}s"] = _positive_growth(shares, shares.shift(w))
        out[f"delta_profit_assets_{w}s"] = out["quality_profit_assets_reported"] - out["quality_profit_assets_reported"].shift(w)
        out[f"delta_ocf_assets_{w}s"] = out["quality_ocf_assets_reported"] - out["quality_ocf_assets_reported"].shift(w)
        out[f"delta_operating_margin_{w}s"] = out["quality_operating_margin_reported"] - out["quality_operating_margin_reported"].shift(w)
        if w == 126:
            out[f"delta_cash_assets_{w}s"] = out["fund_cash_assets"] - out["fund_cash_assets"].shift(w)

    return out


def feature_family(name: str) -> str:
    if name.startswith("mom_") or name.startswith("trend_") or name.startswith("drawdown_") or name.startswith("distance_") or name.startswith("vol_") or name.startswith("downside_") or name.startswith("worst_") or name.startswith("skew_") or name.startswith("rel_mom_"):
        return "MARKET_TREND_RISK"
    if name.startswith("liq_"):
        return "LIQUIDITY"
    if name.startswith("size_"):
        return "SIZE"
    if name.startswith("fund_"):
        return "BALANCE_SHEET_OR_FRESHNESS"
    if name.startswith("quality_"):
        return "QUALITY"
    if name.startswith("value_"):
        return "VALUATION"
    if name.startswith("growth_") or name.startswith("delta_"):
        return "FUNDAMENTAL_CHANGE"
    return "OTHER"


def build_feature_library(panel: pd.DataFrame, price_surface: pd.DataFrame, cfg: Phase4Config) -> tuple[pd.DataFrame, list[str], dict]:
    x = panel.merge(price_surface, on=["date", "ticker"], how="left", validate="one_to_one")
    x = x.sort_values(["ticker", "date"]).reset_index(drop=True)
    parts: list[pd.DataFrame] = []
    for _, g in x.groupby("ticker", sort=False):
        parts.append(_per_ticker_features(g, cfg))
    feat = pd.concat(parts, axis=0).sort_index()
    result = pd.concat([x[["date", "ticker"]], feat], axis=1)

    # Cross-sectional relative momentum is date-local and therefore causal at the close.
    for w in (20, 60, 120, 252):
        c = f"mom_{w}d"
        med = result.groupby("date", observed=True)[c].transform("median")
        result[f"rel_mom_{w}d"] = result[c] - med

    feature_cols = [c for c in result.columns if c not in {"date", "ticker"}]
    for c in feature_cols:
        result[c] = pd.to_numeric(result[c], errors="coerce").replace([np.inf, -np.inf], np.nan).astype("float32")
    result["feature_allowed"] = True
    result = result.sort_values(["date", "ticker"]).reset_index(drop=True)

    meta = {
        "rows": int(len(result)),
        "tickers": int(result["ticker"].nunique()),
        "first_date": str(result["date"].min().date()) if len(result) else None,
        "last_date": str(result["date"].max().date()) if len(result) else None,
        "feature_count": int(len(feature_cols)),
    }
    return result, feature_cols, meta


def feature_coverage(features: pd.DataFrame, feature_cols: list[str], cfg: Phase4Config) -> pd.DataFrame:
    dev0 = cfg.partitions["development_start"]
    val0 = cfg.partitions["validation_start"]
    oos0 = cfg.partitions["final_oos_start"]
    rows = []
    for c in feature_cols:
        s = pd.to_numeric(features[c], errors="coerce")
        finite = np.isfinite(s)
        def cov(mask: pd.Series) -> float:
            n = int(mask.sum())
            return float((finite & mask).sum() / n) if n else math.nan
        overall = pd.Series(True, index=features.index)
        dev = (features["date"] >= dev0) & (features["date"] < val0)
        val = (features["date"] >= val0) & (features["date"] < oos0)
        oos = features["date"] >= oos0
        valid_dates = features.loc[finite, "date"]
        rows.append({
            "feature": c,
            "family": feature_family(c),
            "overall_coverage": cov(overall),
            "development_coverage": cov(dev),
            "validation_signal_date_coverage": cov(val),
            "oos_feature_coverage_no_labels": cov(oos),
            "first_finite_date": str(valid_dates.min().date()) if len(valid_dates) else "",
            "last_finite_date": str(valid_dates.max().date()) if len(valid_dates) else "",
        })
    return pd.DataFrame(rows).sort_values(["family", "feature"]).reset_index(drop=True)


def _newey_west_mean_stats(x: np.ndarray, max_lag: int) -> tuple[float, float, float, float, int]:
    arr = np.asarray(x, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = int(len(arr))
    if n < 5:
        return math.nan, math.nan, math.nan, math.nan, n
    mean = float(arr.mean())
    u = arr - mean
    gamma0 = float(np.dot(u, u) / n)
    lag = min(int(max_lag), n - 1)
    long_var = gamma0
    for k in range(1, lag + 1):
        weight = 1.0 - k / (lag + 1.0)
        gamma = float(np.dot(u[k:], u[:-k]) / n)
        long_var += 2.0 * weight * gamma
    long_var = max(long_var, 0.0)
    se = math.sqrt(long_var / n) if long_var > 0 else 0.0
    if se == 0:
        t = math.inf if mean > 0 else (-math.inf if mean < 0 else 0.0)
        p = 0.0 if mean != 0 else 1.0
    else:
        t = mean / se
        p = float(2.0 * norm.sf(abs(t)))
    return mean, se, float(t), p, n


def _bh_qvalues(p: pd.Series) -> pd.Series:
    pnum = pd.to_numeric(p, errors="coerce")
    out = pd.Series(np.nan, index=p.index, dtype=float)
    valid = pnum.notna() & np.isfinite(pnum)
    if not valid.any():
        return out
    vals = pnum.loc[valid].clip(0, 1).to_numpy(float)
    order = np.argsort(vals)
    ranked = vals[order]
    m = len(ranked)
    q = ranked * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0, 1)
    original = np.empty(m, dtype=float)
    original[order] = q
    out.loc[valid] = original
    return out


def _daily_rank_correlations(df: pd.DataFrame, feature_cols: list[str], y_col: str, min_cs: int) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", *feature_cols])
    work = df[["signal_date", y_col, *feature_cols]].copy()
    ranks = work.groupby("signal_date", observed=True)[feature_cols].rank(method="average", pct=True)
    y = pd.to_numeric(work[y_col], errors="coerce").to_numpy(dtype=float)
    dates = work["signal_date"].to_numpy()
    unique_dates, starts = np.unique(dates, return_index=True)
    ends = np.r_[starts[1:], len(work)]
    out = np.full((len(unique_dates), len(feature_cols)), np.nan, dtype=float)
    X = ranks.to_numpy(dtype=float)
    for i, (a, b) in enumerate(zip(starts, ends)):
        xb = X[a:b]
        yb = y[a:b]
        y_ok = np.isfinite(yb)
        if y_ok.sum() < min_cs:
            continue
        valid = np.isfinite(xb) & y_ok[:, None]
        n = valid.sum(axis=0).astype(float)
        enough = n >= float(min_cs)
        if not enough.any():
            continue
        xv = np.where(valid, xb, 0.0)
        ymat = np.where(valid, yb[:, None], 0.0)
        sx = xv.sum(axis=0)
        sy = ymat.sum(axis=0)
        sxx = (xv * xv).sum(axis=0)
        syy = (ymat * ymat).sum(axis=0)
        sxy = (xv * ymat).sum(axis=0)
        cov = sxy - sx * sy / np.where(n > 0, n, 1.0)
        vx = sxx - sx * sx / np.where(n > 0, n, 1.0)
        vy = syy - sy * sy / np.where(n > 0, n, 1.0)
        den = np.sqrt(np.maximum(vx * vy, 0.0))
        corr = np.where((den > 0) & enough, cov / den, np.nan)
        out[i] = corr
    return pd.DataFrame(out, index=pd.to_datetime(unique_dates), columns=feature_cols).rename_axis("date").reset_index()


def _partition_for_horizon(joined: pd.DataFrame, h: int, cfg: Phase4Config, which: str) -> pd.DataFrame:
    end_col = f"target_end_date_{h}d"
    resolved_col = f"target_resolved_{h}d"
    if which == "DEVELOPMENT":
        m = (joined["signal_date"] >= cfg.partitions["development_start"])
        m &= joined["signal_date"] < cfg.partitions["validation_start"]
        m &= joined[end_col].notna() & (joined[end_col] < cfg.partitions["validation_start"])
    elif which == "VALIDATION":
        m = joined["signal_date"] >= cfg.partitions["validation_start"]
        m &= joined["signal_date"] < cfg.partitions["final_oos_start"]
        m &= joined[end_col].notna() & (joined[end_col] < cfg.partitions["final_oos_start"])
    else:
        raise ValueError(which)
    m &= joined[resolved_col].fillna(False).astype(bool)
    return joined.loc[m].copy()


def research_partition_manifest(targets: pd.DataFrame, cfg: Phase4Config) -> pd.DataFrame:
    rows = []
    for h in cfg.research_horizons:
        for part in ("DEVELOPMENT", "VALIDATION"):
            x = _partition_for_horizon(targets, h, cfg, part)
            rows.append({
                "horizon_sessions": h,
                "partition": part,
                "rows": int(len(x)),
                "dates": int(x["signal_date"].nunique()) if len(x) else 0,
                "first_signal_date": str(x["signal_date"].min().date()) if len(x) else "",
                "last_signal_date": str(x["signal_date"].max().date()) if len(x) else "",
                "max_target_end_date": str(x[f"target_end_date_{h}d"].max().date()) if len(x) else "",
            })
    return pd.DataFrame(rows)


def _rich_validation_metrics(df: pd.DataFrame, feature: str, h: int, direction: int, min_cs: int) -> dict:
    if df.empty:
        return {}
    rank = df.groupby("signal_date", observed=True)[feature].rank(method="average", pct=True)
    count = df.groupby("signal_date", observed=True)[feature].transform("count")
    rank = rank.where(count >= min_cs)
    if direction < 0:
        score = 1.0 - rank
    else:
        score = rank
    ret = pd.to_numeric(df[f"fwd_return_{h}d"], errors="coerce")
    win = df[f"winner_top_decile_{h}d"].astype("boolean")
    tmp = pd.DataFrame({"date": df["signal_date"], "score": score, "ret": ret, "win": win})
    tmp = tmp[tmp["score"].notna() & tmp["ret"].notna()]
    if tmp.empty:
        return {}
    top = tmp["score"] >= 0.80
    bot = tmp["score"] <= 0.20
    def date_mean(mask: pd.Series, col: str) -> pd.Series:
        z = tmp.loc[mask, ["date", col]].dropna()
        return z.groupby("date", observed=True)[col].mean() if len(z) else pd.Series(dtype=float)
    top_ret = date_mean(top, "ret")
    bot_ret = date_mean(bot, "ret")
    common = top_ret.index.intersection(bot_ret.index)
    spread = (top_ret.reindex(common) - bot_ret.reindex(common)).dropna()
    top_win = date_mean(top & tmp["win"].notna(), "win")
    all_win = date_mean(tmp["win"].notna(), "win")
    commonw = top_win.index.intersection(all_win.index)
    lifts = (top_win.reindex(commonw) / all_win.reindex(commonw).replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "validation_top_bottom_return_spread_mean": float(spread.mean()) if len(spread) else math.nan,
        "validation_top_bottom_return_spread_median": float(spread.median()) if len(spread) else math.nan,
        "validation_winner_top_decile_lift": float(lifts.mean()) if len(lifts) else math.nan,
        "validation_rich_dates": int(len(spread)),
    }


def predictive_research(features: pd.DataFrame, targets: pd.DataFrame, feature_cols: list[str], cfg: Phase4Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # Join is explicitly isolated in research code. The feature parquet itself never contains targets.
    target_cols = ["signal_date", "ticker"]
    for h in cfg.research_horizons:
        target_cols += [
            f"target_end_date_{h}d", f"target_resolved_{h}d", f"fwd_return_{h}d",
            f"cs_rank_pct_{h}d", f"winner_top_decile_{h}d",
        ]
    t = targets[target_cols].copy()
    t["signal_date"] = _as_date(t["signal_date"])
    t["ticker"] = _norm_ticker(t["ticker"])
    for h in cfg.research_horizons:
        t[f"target_end_date_{h}d"] = _as_date(t[f"target_end_date_{h}d"])

    f = features[["date", "ticker", *feature_cols]].rename(columns={"date": "signal_date"})
    joined = f.merge(t, on=["signal_date", "ticker"], how="inner", validate="one_to_one")
    joined = joined[joined["signal_date"] < cfg.partitions["final_oos_start"]].copy()
    joined = joined.sort_values(["signal_date", "ticker"]).reset_index(drop=True)

    min_cs = int(cfg.policies["minimum_cross_section_size"])
    batch_size = int(cfg.policies["feature_rank_batch_size"])
    lag_cap = int(cfg.policies["hac_lag_cap"])
    rows: list[dict] = []

    for h in cfg.research_horizons:
        dev = _partition_for_horizon(joined, h, cfg, "DEVELOPMENT")
        val = _partition_for_horizon(joined, h, cfg, "VALIDATION")
        y = f"cs_rank_pct_{h}d"
        per_feature: dict[str, dict] = {}
        for a in range(0, len(feature_cols), batch_size):
            batch = feature_cols[a:a + batch_size]
            dev_ic = _daily_rank_correlations(dev, batch, y, min_cs)
            val_ic = _daily_rank_correlations(val, batch, y, min_cs)
            for c in batch:
                dvals = dev_ic[c].to_numpy(float) if c in dev_ic else np.array([])
                vvals = val_ic[c].to_numpy(float) if c in val_ic else np.array([])
                dmean, dse, dt, dp, dn = _newey_west_mean_stats(dvals, min(h, lag_cap))
                vmean, vse, vt, vp, vn = _newey_west_mean_stats(vvals, min(h, lag_cap))
                dcov = float(np.isfinite(pd.to_numeric(dev[c], errors="coerce")).mean()) if len(dev) else math.nan
                vcov = float(np.isfinite(pd.to_numeric(val[c], errors="coerce")).mean()) if len(val) else math.nan
                per_feature[c] = {
                    "feature": c, "family": feature_family(c), "horizon_sessions": h,
                    "development_rows": int(len(dev)), "validation_rows": int(len(val)),
                    "development_ic_dates": dn, "validation_ic_dates": vn,
                    "development_coverage": dcov, "validation_coverage": vcov,
                    "development_mean_spearman_ic": dmean, "development_hac_se": dse,
                    "development_hac_t": dt, "development_pvalue": dp,
                    "validation_mean_spearman_ic": vmean, "validation_hac_se": vse,
                    "validation_hac_t": vt, "validation_pvalue": vp,
                }
        hdf = pd.DataFrame(per_feature.values())
        hdf["development_fdr_q"] = _bh_qvalues(hdf["development_pvalue"])
        hdf["direction"] = np.where(hdf["development_mean_spearman_ic"] >= 0, 1, -1)
        hdf["validation_aligned_ic"] = hdf["direction"] * hdf["validation_mean_spearman_ic"]
        hdf["validation_aligned_hac_t"] = hdf["direction"] * hdf["validation_hac_t"]
        min_cov = float(cfg.policies["minimum_feature_coverage"])
        disc_q = float(cfg.policies["discovery_fdr_q"])
        watch_q = float(cfg.policies["watch_fdr_q"])
        min_dev_ic = float(cfg.policies["minimum_abs_development_ic"])
        min_val_ic = float(cfg.policies["minimum_validation_aligned_ic"])
        min_val_t = float(cfg.policies["minimum_validation_aligned_t"])
        eligible = (hdf["development_coverage"] >= min_cov) & (hdf["validation_coverage"] >= min_cov)
        discovery = eligible & (hdf["development_fdr_q"] <= disc_q) & (hdf["development_mean_spearman_ic"].abs() >= min_dev_ic)
        validated = discovery & (hdf["validation_aligned_ic"] > min_val_ic) & (hdf["validation_aligned_hac_t"] >= min_val_t)
        watch = eligible & ~validated & (hdf["development_fdr_q"] <= watch_q) & (hdf["validation_aligned_ic"] > 0)
        hdf["research_status"] = np.select([validated, discovery, watch], ["VALIDATED", "DISCOVERY_ONLY", "WATCH"], default="NO_EVIDENCE")

        # Rich winner/spread diagnostics only for statistically plausible candidates to control runtime and multiple testing noise.
        rich_q = float(cfg.policies["rich_diagnostics_q_threshold"])
        rich_mask = eligible & (hdf["development_fdr_q"] <= rich_q)
        for ix in hdf.index[rich_mask]:
            c = str(hdf.at[ix, "feature"])
            direction = int(hdf.at[ix, "direction"])
            rich = _rich_validation_metrics(val, c, h, direction, min_cs)
            for k, v in rich.items():
                hdf.at[ix, k] = v
        rows.extend(hdf.to_dict(orient="records"))

    diag = pd.DataFrame(rows)
    if diag.empty:
        return diag, pd.DataFrame(), pd.DataFrame()
    diag = diag.sort_values(["horizon_sessions", "research_status", "development_fdr_q", "feature"]).reset_index(drop=True)

    # Per-feature candidate summary: choose strongest validation-confirmed horizon without peeking at final OOS.
    priority = {"VALIDATED": 3, "WATCH": 2, "DISCOVERY_ONLY": 1, "NO_EVIDENCE": 0}
    d2 = diag.copy()
    d2["status_priority"] = d2["research_status"].map(priority).fillna(0)
    d2["score"] = d2["status_priority"] * 100.0 + d2["validation_aligned_hac_t"].fillna(-99).clip(-99, 99) + 10.0 * d2["validation_aligned_ic"].fillna(-9).clip(-9, 9)
    best = d2.sort_values(["feature", "score"], ascending=[True, False]).groupby("feature", as_index=False).first()
    keep = [
        "feature", "family", "research_status", "horizon_sessions", "direction",
        "development_mean_spearman_ic", "development_hac_t", "development_fdr_q",
        "validation_mean_spearman_ic", "validation_aligned_ic", "validation_aligned_hac_t",
        "development_coverage", "validation_coverage",
        "validation_top_bottom_return_spread_mean", "validation_top_bottom_return_spread_median",
        "validation_winner_top_decile_lift", "validation_rich_dates",
    ]
    for c in keep:
        if c not in best.columns:
            best[c] = np.nan
    candidates = best[keep].copy()
    candidates["_priority"] = candidates["research_status"].map(priority).fillna(0)
    candidates = candidates.sort_values(
        ["_priority", "validation_aligned_hac_t", "validation_aligned_ic"],
        ascending=[False, False, False],
    ).drop(columns="_priority").reset_index(drop=True)

    fam = candidates.groupby("family", as_index=False).agg(
        features=("feature", "count"),
        validated=("research_status", lambda s: int((s == "VALIDATED").sum())),
        watch=("research_status", lambda s: int((s == "WATCH").sum())),
        discovery_only=("research_status", lambda s: int((s == "DISCOVERY_ONLY").sum())),
        median_best_validation_aligned_ic=("validation_aligned_ic", "median"),
        max_best_validation_aligned_hac_t=("validation_aligned_hac_t", "max"),
    ).sort_values(["validated", "watch", "features"], ascending=[False, False, False])
    return diag, candidates, fam


def load_targets_for_research(root: Path, cfg: Phase4Config) -> pd.DataFrame:
    path = root / cfg.targets_path
    if not path.exists():
        raise FileNotFoundError(str(path))
    cols = ["signal_date", "ticker"]
    for h in cfg.research_horizons:
        cols += [f"target_end_date_{h}d", f"target_resolved_{h}d", f"fwd_return_{h}d", f"cs_rank_pct_{h}d", f"winner_top_decile_{h}d"]
    t = pd.read_parquet(path, columns=cols)
    t["signal_date"] = _as_date(t["signal_date"])
    t["ticker"] = _norm_ticker(t["ticker"])
    for h in cfg.research_horizons:
        t[f"target_end_date_{h}d"] = _as_date(t[f"target_end_date_{h}d"])
    return t


def evaluate_gate(
    features: pd.DataFrame,
    feature_cols: list[str],
    coverage: pd.DataFrame,
    price_meta: dict,
    exclusions_removed: int,
    targets: pd.DataFrame,
    partitions: pd.DataFrame,
    cfg: Phase4Config,
) -> tuple[pd.DataFrame, str]:
    rows = []
    def add(test: str, ok: bool, value: object, rule: str, blocking: bool = True) -> None:
        rows.append({"test": test, "status": "PASS" if ok else "FAIL", "blocking": blocking, "value": value, "rule": rule})

    add("PHASE3_INPUT_PASS", True, "PASS", "Phase 3 V3 status validated before Phase 4")
    dups = int(features.duplicated(["date", "ticker"]).sum())
    add("UNIQUE_FEATURE_KEY", dups == 0, dups, "0 duplicate date,ticker rows")
    price_cov = float(price_meta.get("coverage", math.nan))
    req = float(cfg.policies["feature_return_price_coverage_required"])
    add("FEATURE_SAFE_RETURN_PRICE_COVERAGE", np.isfinite(price_cov) and price_cov >= req, price_cov, f">= {req:.3f}; adjusted levels are temporary and never exported")

    forbidden = [c for c in feature_cols if c.startswith(FORBIDDEN_FEATURE_PREFIXES) or "adj_close" in c or "target_total_return_price" in c]
    add("NO_TARGET_OR_ADJUSTED_LEVEL_FEATURES", len(forbidden) == 0, len(forbidden), "0 target columns or adjusted price levels exposed as features")
    flags = features["feature_allowed"].fillna(False).astype(bool)
    add("FEATURE_ALLOWED_FLAGS", bool(flags.all()), int((~flags).sum()), "all feature rows feature_allowed=True")

    # Exact signal-key alignment with Phase 3 after Phase 3C exclusion.
    fkeys = features[["date", "ticker"]].rename(columns={"date": "signal_date"})
    tkeys = targets[["signal_date", "ticker"]]
    overlap = fkeys.merge(tkeys, on=["signal_date", "ticker"], how="inner")
    alignment = float(len(overlap) / len(tkeys)) if len(tkeys) else math.nan
    add("PHASE3_SIGNAL_KEY_ALIGNMENT", np.isfinite(alignment) and alignment >= 0.999999, alignment, ">= 0.999999 of Phase 3 target keys have feature rows")
    add("RESEARCH_EXCLUSIONS_APPLIED", exclusions_removed > 0, exclusions_removed, "Phase 3C research exclusions must remove their contaminated rows")

    # Feature coverage gate is about library usability, not alpha strength.
    usable_thr = float(cfg.policies["minimum_usable_feature_coverage"])
    usable = int((coverage["development_coverage"] >= usable_thr).sum())
    usable_req = int(cfg.policies["minimum_usable_feature_count"])
    add("USABLE_FEATURE_COUNT", usable >= usable_req, usable, f">= {usable_req} features with development coverage >= {usable_thr:.2f}")

    # Causal fundamental timestamps: availability may never exceed signal date.
    # This rechecks the critical Phase 2 invariant at the Phase 4 boundary.
    causal_viol = 0
    # availability columns are intentionally not persisted in feature library, so checked upstream in build_phase4 and passed via attrs.
    causal_viol = int(features.attrs.get("fundamental_future_availability_violations", 0))
    add("FUNDAMENTAL_CAUSALITY_RECHECK", causal_viol == 0, causal_viol, "0 fundamental available_at dates after feature date")

    # Final OOS labels are never admitted to predictive research.
    max_research_signal = pd.to_datetime(partitions.loc[partitions["rows"] > 0, "last_signal_date"], errors="coerce").max()
    oos0 = cfg.partitions["final_oos_start"]
    add("FINAL_OOS_LABEL_FIREWALL", pd.isna(max_research_signal) or max_research_signal < oos0,
        str(max_research_signal.date()) if pd.notna(max_research_signal) else "", f"max research signal date < {oos0.date()}")
    purge_viol = 0
    for _, r in partitions.iterrows():
        if not r["max_target_end_date"]:
            continue
        mx = pd.Timestamp(r["max_target_end_date"])
        boundary = cfg.partitions["validation_start"] if r["partition"] == "DEVELOPMENT" else cfg.partitions["final_oos_start"]
        if mx >= boundary:
            purge_viol += 1
    add("PURGED_OUTCOME_BOUNDARIES", purge_viol == 0, purge_viol, "0 development/validation outcomes cross into the next partition")

    gate = pd.DataFrame(rows)
    fail = gate["blocking"].astype(bool) & gate["status"].eq("FAIL")
    return gate, "PASS" if not fail.any() else "FAIL"


def feature_schema(feature_cols: list[str], cfg: Phase4Config) -> dict:
    definitions = {}
    for c in feature_cols:
        definitions[c] = {
            "family": feature_family(c),
            "feature_allowed": True,
            "causal_semantics": "computed only from observations available at or before the feature date",
        }
    return {
        "build": PHASE4_BUILD,
        "keys": ["date", "ticker"],
        "feature_count": len(feature_cols),
        "features": definitions,
        "partitions": {k: str(v.date()) for k, v in cfg.partitions.items()},
        "price_transform_contract": {
            "direct_adjusted_price_level_exported": False,
            "target_total_return_price_read_for_feature_generation": False,
            "allowed_use": "source adjusted prices may be used only inside backward-looking scale-invariant transformations; levels are discarded",
        },
        "fundamental_contract": "Phase 2 strict-next-session filing availability is preserved; reported flow metrics are snapshot/reported values and are not labelled TTM.",
        "target_firewall": "Phase 3 targets are joined only inside predictive_research after feature library construction; no target column is written to the feature parquet.",
        "final_oos_firewall": f"signal dates >= {cfg.partitions['final_oos_start'].date()} are excluded from all predictive diagnostics and feature selection.",
    }


def build_phase4(root: Path) -> dict:
    cfg = load_config(root)
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    with (root / cfg.phase3_summary_path).open("r", encoding="utf-8") as f:
        phase3_summary = json.load(f)
    validate_phase3_summary(phase3_summary)

    panel = load_panel(root, cfg)
    # Recheck causal filing availability before dropping metadata from feature output.
    fund_future_viol = 0
    for m in FUNDAMENTAL_METRICS:
        a = panel[f"{m}__available_date"]
        fund_future_viol += int((a.notna() & (a > panel["date"])).sum())

    exclusions = load_exclusions(root, cfg)
    panel, exclusions_removed = apply_research_exclusions(panel, exclusions)
    price_surface, price_meta, price_manifest = build_feature_safe_adjusted_price(panel, root / cfg.adjusted_cache_dir)
    features, feature_cols, feature_meta = build_feature_library(panel, price_surface, cfg)
    features.attrs["fundamental_future_availability_violations"] = fund_future_viol
    coverage = feature_coverage(features, feature_cols, cfg)

    targets = load_targets_for_research(root, cfg)
    partitions = research_partition_manifest(targets, cfg)
    diagnostics, candidates, family_summary = predictive_research(features, targets, feature_cols, cfg)
    gate, status = evaluate_gate(features, feature_cols, coverage, price_meta, exclusions_removed, targets, partitions, cfg)

    # Predictive readiness is intentionally separate from integrity PASS; zero evidence triggers expansion, not a fake model.
    validated_count = int((candidates["research_status"] == "VALIDATED").sum()) if len(candidates) else 0
    validated_families = int(candidates.loc[candidates["research_status"] == "VALIDATED", "family"].nunique()) if len(candidates) else 0
    watch_count = int((candidates["research_status"] == "WATCH").sum()) if len(candidates) else 0
    if validated_count >= 3 and validated_families >= 2:
        readiness = "READY_FOR_MODEL_RESEARCH"
    elif validated_count >= 1 or watch_count >= 3:
        readiness = "REVIEW_BEFORE_MODEL_RESEARCH"
    else:
        readiness = "NEEDS_FEATURE_EXPANSION"

    features.to_parquet(root / cfg.output_feature_library_path, index=False)
    coverage.to_csv(outputs / "phase4_feature_coverage.csv", index=False)
    price_manifest.to_csv(outputs / "phase4_price_source_manifest.csv", index=False)
    diagnostics.to_csv(outputs / "phase4_predictive_diagnostics.csv", index=False)
    candidates.to_csv(outputs / "phase4_candidate_features.csv", index=False)
    family_summary.to_csv(outputs / "phase4_family_summary.csv", index=False)
    partitions.to_csv(outputs / "phase4_research_partitions.csv", index=False)
    gate.to_csv(outputs / "phase4_gate.csv", index=False)
    schema = feature_schema(feature_cols, cfg)
    (outputs / "phase4_feature_schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")

    summary = {
        "status": status,
        "phase": 4,
        "build": PHASE4_BUILD,
        "name": cfg.name,
        "objective": cfg.objective,
        "phase3_input": {"status": phase3_summary.get("status"), "build": phase3_summary.get("build")},
        "feature_library": feature_meta,
        "feature_safe_return_price": price_meta,
        "research_exclusions_removed_rows": exclusions_removed,
        "fundamental_future_availability_violations": fund_future_viol,
        "partitions": {k: str(v.date()) for k, v in cfg.partitions.items()},
        "research_horizons": list(cfg.research_horizons),
        "predictive_evidence": {
            "validated_features": validated_count,
            "validated_families": validated_families,
            "watch_features": watch_count,
            "readiness": readiness,
        },
        "feature_firewall": {
            "target_total_return_price_used": False,
            "phase3_target_columns_written_to_feature_library": False,
            "direct_adjusted_price_level_written": False,
            "feature_allowed": True,
        },
        "final_oos_firewall": {
            "final_oos_start": str(cfg.partitions["final_oos_start"].date()),
            "used_for_predictive_research": False,
            "purged_by_target_end_date": True,
        },
        "next_gate": "If status PASS, inspect candidate-feature stability. Proceed to model architecture research only if predictive_evidence.readiness is READY_FOR_MODEL_RESEARCH or after explicit review of REVIEW_BEFORE_MODEL_RESEARCH; never use final OOS for model selection.",
    }
    (outputs / "phase4_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
