from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
import concurrent.futures as cf
import json
import math
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd


PHASE2C_BUILD = "FIX3_FLAT_2026-09-12"


@dataclass(frozen=True)
class Phase2CConfig:
    name: str
    objective: str
    panel_path: str
    requirements_path: str
    cache_dir: str
    actions_path: str
    local_adjusted_reference: str
    policies: dict[str, object]


def load_phase2c_config(path: Path) -> Phase2CConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))["phase2c"]
    return Phase2CConfig(
        name=raw["name"],
        objective=raw["objective"],
        panel_path=raw["panel_path"],
        requirements_path=raw["requirements_path"],
        cache_dir=raw["cache_dir"],
        actions_path=raw["actions_path"],
        local_adjusted_reference=raw["local_adjusted_reference"],
        policies=dict(raw["policies"]),
    )


def _norm_ticker(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.upper()


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.normalize().astype("datetime64[ns]")


def _require_columns(df: pd.DataFrame, cols: Iterable[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label}: missing required columns {missing}")


def _rel_diff(a: pd.Series, b: pd.Series) -> pd.Series:
    aa = pd.to_numeric(a, errors="coerce").astype(float)
    bb = pd.to_numeric(b, errors="coerce").astype(float)
    denom = np.maximum(np.maximum(np.abs(aa), np.abs(bb)), 1e-12)
    return np.abs(aa - bb) / denom


def yahoo_symbol_candidates(ticker: str) -> list[str]:
    t = str(ticker).strip().upper()
    vals = [t]
    transformed = t.replace(".", "-").replace("/", "-")
    if transformed not in vals:
        vals.append(transformed)
    return vals


def _epoch(d: pd.Timestamp) -> int:
    ts = pd.Timestamp(d)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.timestamp())


def _fetch_json(url: str, timeout: int, retries: int, backoff: float) -> dict:
    last: Exception | None = None
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AlphaEngineV12/1.0)",
        "Accept": "application/json,text/plain,*/*",
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            return json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(backoff * (2 ** attempt))
    raise RuntimeError(f"request failed after {retries} attempts: {last}")


def _parse_yahoo_chart(payload: dict, ticker: str, provider_symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise ValueError(str(chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise ValueError("Yahoo chart returned no result")
    r = results[0]
    stamps = r.get("timestamp") or []
    quote = (((r.get("indicators") or {}).get("quote") or [{}])[0])
    adj = (((r.get("indicators") or {}).get("adjclose") or [{}])[0]).get("adjclose") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    n = len(stamps)

    def pad(v):
        return list(v) + [None] * max(0, n - len(v))

    closes, adj, volumes, opens, highs, lows = map(pad, [closes, adj, volumes, opens, highs, lows])
    dates = [pd.Timestamp(datetime.fromtimestamp(int(ts), tz=timezone.utc).date()) for ts in stamps]
    prices = pd.DataFrame({
        "date": dates,
        "ticker": ticker,
        "provider_symbol": provider_symbol,
        "open": opens[:n],
        "high": highs[:n],
        "low": lows[:n],
        "close": closes[:n],
        "adj_close": adj[:n],
        "volume": volumes[:n],
    })
    for c in ["open", "high", "low", "close", "adj_close", "volume"]:
        prices[c] = pd.to_numeric(prices[c], errors="coerce")
    prices["date"] = _as_date(prices["date"])
    prices = prices.dropna(subset=["date", "close", "adj_close"])
    prices = prices[(prices["close"] > 0) & (prices["adj_close"] > 0)]
    prices = prices.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)

    action_rows: list[dict] = []
    events = r.get("events") or {}
    for _, ev in (events.get("dividends") or {}).items():
        ts = ev.get("date")
        action_rows.append({
            "date": pd.Timestamp(datetime.fromtimestamp(int(ts), tz=timezone.utc).date()) if ts is not None else pd.NaT,
            "ticker": ticker,
            "provider_symbol": provider_symbol,
            "event_type": "DIVIDEND",
            "value": ev.get("amount"),
            "numerator": np.nan,
            "denominator": np.nan,
            "split_ratio": None,
        })
    for _, ev in (events.get("splits") or {}).items():
        ts = ev.get("date")
        action_rows.append({
            "date": pd.Timestamp(datetime.fromtimestamp(int(ts), tz=timezone.utc).date()) if ts is not None else pd.NaT,
            "ticker": ticker,
            "provider_symbol": provider_symbol,
            "event_type": "SPLIT",
            "value": np.nan,
            "numerator": ev.get("numerator"),
            "denominator": ev.get("denominator"),
            "split_ratio": ev.get("splitRatio"),
        })
    actions = pd.DataFrame(action_rows, columns=[
        "date", "ticker", "provider_symbol", "event_type", "value", "numerator", "denominator", "split_ratio"
    ])
    if len(actions):
        actions["date"] = _as_date(actions["date"])
    return prices, actions


def fetch_yahoo_history(
    ticker: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    timeout: int = 30,
    retries: int = 4,
    backoff: float = 1.5,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    period1 = _epoch(pd.Timestamp(start) - pd.Timedelta(days=5))
    period2 = _epoch(pd.Timestamp(end) + pd.Timedelta(days=5))
    errors = []
    for symbol in yahoo_symbol_candidates(ticker):
        enc = urllib.parse.quote(symbol, safe="")
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}"
            f"?period1={period1}&period2={period2}&interval=1d"
            "&events=div%2Csplits&includeAdjustedClose=true"
        )
        try:
            payload = _fetch_json(url, timeout=timeout, retries=retries, backoff=backoff)
            prices, actions = _parse_yahoo_chart(payload, ticker, symbol)
            if len(prices):
                return prices, actions, symbol
            errors.append(f"{symbol}: empty")
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
    raise RuntimeError("; ".join(errors))


def load_panel(root: Path, cfg: Phase2CConfig) -> pd.DataFrame:
    path = root / cfg.panel_path
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Phase 2 must pass before Phase 2C.")
    panel = pd.read_parquet(path)
    _require_columns(panel, ["date", "ticker", "close", "adj_close", "research_eligible"], str(path))
    panel = panel.copy()
    panel["date"] = _as_date(panel["date"])
    panel["ticker"] = _norm_ticker(panel["ticker"])
    panel["close"] = pd.to_numeric(panel["close"], errors="coerce")
    panel["adj_close"] = pd.to_numeric(panel["adj_close"], errors="coerce")
    panel["research_eligible"] = panel["research_eligible"].fillna(False).astype(bool)
    return panel.sort_values(["ticker", "date"]).reset_index(drop=True)


def load_requirements(root: Path, cfg: Phase2CConfig, panel: pd.DataFrame) -> pd.DataFrame:
    path = root / cfg.requirements_path
    if path.exists():
        req = pd.read_csv(path)
        _require_columns(req, ["ticker", "first_date", "last_date", "needs_adjusted_history"], str(path))
        req["ticker"] = _norm_ticker(req["ticker"])
        req["first_date"] = _as_date(req["first_date"])
        req["last_date"] = _as_date(req["last_date"])
        if req["needs_adjusted_history"].dtype == bool:
            mask = req["needs_adjusted_history"]
        else:
            mask = req["needs_adjusted_history"].astype(str).str.lower().isin(["true", "1", "yes"])
        return req.loc[mask, ["ticker", "first_date", "last_date"]].drop_duplicates("ticker")

    x = panel[panel["research_eligible"]].copy()
    x["adj_ok"] = np.isfinite(x["adj_close"]) & (x["adj_close"] > 0)
    agg = x.groupby("ticker", observed=True).agg(
        first_date=("date", "min"),
        last_date=("date", "max"),
        rows=("date", "size"),
        adj_rows=("adj_ok", "sum"),
    ).reset_index()
    agg["coverage"] = agg["adj_rows"] / agg["rows"]
    return agg.loc[
        agg["coverage"] < float(cfg.policies["per_ticker_coverage_required"]),
        ["ticker", "first_date", "last_date"],
    ]


def _cache_path(cache_dir: Path, ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_")
    return cache_dir / f"{safe}.parquet"


def _cache_covers(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, tail_days: int) -> bool:
    if df.empty:
        return False
    first = pd.to_datetime(df["date"], errors="coerce").min()
    last = pd.to_datetime(df["date"], errors="coerce").max()
    return bool(first <= start + pd.Timedelta(days=7) and last >= end - pd.Timedelta(days=tail_days))


def acquire_one(row: dict, cache_dir: Path, policies: dict[str, object]) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    ticker = str(row["ticker"])
    start = pd.Timestamp(row["first_date"])
    end = pd.Timestamp(row["last_date"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    cp = _cache_path(cache_dir, ticker)
    tail_days = int(policies["cache_refresh_tail_days"])

    if cp.exists():
        try:
            cached = pd.read_parquet(cp)
            _require_columns(cached, ["date", "ticker", "close", "adj_close", "provider_symbol"], str(cp))
            cached["date"] = _as_date(cached["date"])
            if _cache_covers(cached, start, end, tail_days):
                manifest = {
                    "ticker": ticker,
                    "status": "CACHE_HIT",
                    "provider_symbol": str(cached["provider_symbol"].dropna().iloc[0]) if cached["provider_symbol"].notna().any() else ticker,
                    "rows": int(len(cached)),
                    "first_date": str(cached["date"].min().date()),
                    "last_date": str(cached["date"].max().date()),
                    "error": "",
                }
                return manifest, cached, pd.DataFrame()
        except Exception:
            pass

    try:
        prices, actions, provider_symbol = fetch_yahoo_history(
            ticker,
            start,
            end,
            timeout=int(policies["request_timeout_seconds"]),
            retries=int(policies["request_retries"]),
            backoff=float(policies["backoff_seconds"]),
        )
        prices.to_parquet(cp, index=False)
        manifest = {
            "ticker": ticker,
            "status": "DOWNLOADED",
            "provider_symbol": provider_symbol,
            "rows": int(len(prices)),
            "first_date": str(prices["date"].min().date()) if len(prices) else "",
            "last_date": str(prices["date"].max().date()) if len(prices) else "",
            "error": "",
        }
        return manifest, prices, actions
    except Exception as exc:
        return {
            "ticker": ticker,
            "status": "FAILED",
            "provider_symbol": "",
            "rows": 0,
            "first_date": "",
            "last_date": "",
            "error": str(exc),
        }, pd.DataFrame(), pd.DataFrame()


def acquire_histories(root: Path, cfg: Phase2CConfig, requirements: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cache_dir = root / cfg.cache_dir
    rows = requirements.to_dict(orient="records")
    manifests: list[dict] = []
    price_frames: list[pd.DataFrame] = []
    action_frames: list[pd.DataFrame] = []
    workers = max(1, int(cfg.policies["max_workers"]))

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(acquire_one, row, cache_dir, cfg.policies) for row in rows]
        for fut in cf.as_completed(futs):
            manifest, prices, actions = fut.result()
            manifests.append(manifest)
            if len(prices):
                price_frames.append(prices)
            if len(actions):
                action_frames.append(actions)
            print(f"  {manifest['ticker']}: {manifest['status']} rows={manifest['rows']}")

    manifest_df = pd.DataFrame(manifests).sort_values("ticker") if manifests else pd.DataFrame()
    prices = pd.concat(price_frames, ignore_index=True) if price_frames else pd.DataFrame(
        columns=["date", "ticker", "provider_symbol", "close", "adj_close"]
    )
    if len(prices):
        prices["date"] = _as_date(prices["date"])
        prices["ticker"] = _norm_ticker(prices["ticker"])
        prices = prices.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")
    actions = pd.concat(action_frames, ignore_index=True) if action_frames else pd.DataFrame(
        columns=["date", "ticker", "provider_symbol", "event_type", "value", "numerator", "denominator", "split_ratio"]
    )
    return manifest_df, prices.reset_index(drop=True), actions.reset_index(drop=True)


def validate_provider_identity(panel: pd.DataFrame, downloaded: pd.DataFrame, cfg: Phase2CConfig) -> pd.DataFrame:
    """Validate that each downloaded Yahoo series is the same economic security.

    The Phase-2 panel may contain either raw-close-like or adjusted-close-like prices
    depending on the upstream source. Identity therefore passes when the panel close
    matches *either* Yahoo raw close or Yahoo adjusted close at the configured rate.
    The adjusted Yahoo series remains target-only regardless of this classification.
    """
    base = panel.loc[panel["research_eligible"], ["date", "ticker", "close"]].rename(
        columns={"close": "panel_close"}
    )
    panel_counts = base.groupby("ticker", observed=True).size().rename("eligible_panel_rows")
    ref = downloaded[["date", "ticker", "close", "adj_close"]].rename(
        columns={"close": "provider_close", "adj_close": "provider_adj_close"}
    )
    m = base.merge(ref, on=["date", "ticker"], how="inner")
    if m.empty:
        return pd.DataFrame(columns=[
            "ticker", "eligible_panel_rows", "overlap_rows",
            "raw_identity_match_rate", "adjusted_identity_match_rate",
            "identity_match_rate", "panel_price_semantics",
            "median_rel_diff_to_raw", "median_rel_diff_to_adjusted",
            "required_validation_rows", "status"
        ])

    m["rel_diff_raw"] = _rel_diff(m["panel_close"], m["provider_close"])
    m["rel_diff_adjusted"] = _rel_diff(m["panel_close"], m["provider_adj_close"])
    tol = float(cfg.policies["raw_identity_relative_tolerance"])
    min_rows_cfg = int(cfg.policies["minimum_validation_rows"])
    floor_rows = int(cfg.policies.get("minimum_short_history_validation_rows", 20))
    required_rate = float(cfg.policies["raw_identity_match_required"])

    rows = []
    for ticker, g in m.groupby("ticker", observed=True):
        n = len(g)
        eligible_n = int(panel_counts.get(ticker, n))
        raw_rate = float((g["rel_diff_raw"] <= tol).mean())
        adj_rate = float((g["rel_diff_adjusted"] <= tol).mean())
        best_rate = max(raw_rate, adj_rate)
        if raw_rate >= required_rate and adj_rate >= required_rate:
            semantics = "RAW_AND_ADJUSTED_EQUIVALENT"
        elif raw_rate >= adj_rate:
            semantics = "RAW_CLOSE_LIKE"
        else:
            semantics = "ADJUSTED_CLOSE_LIKE"

        # A newly listed security cannot manufacture 100 historical observations.
        # Require all available history when the eligible lifetime is shorter than
        # the standard validation window, subject to a small absolute floor.
        required_rows = min(min_rows_cfg, eligible_n)
        enough_history = n >= required_rows and n >= min(floor_rows, eligible_n)
        status = "PASS" if (enough_history and best_rate >= required_rate) else "FAIL"
        rows.append({
            "ticker": ticker,
            "eligible_panel_rows": eligible_n,
            "overlap_rows": int(n),
            "raw_identity_match_rate": raw_rate,
            "adjusted_identity_match_rate": adj_rate,
            "identity_match_rate": best_rate,
            "panel_price_semantics": semantics,
            "median_rel_diff_to_raw": float(g["rel_diff_raw"].median()),
            "median_rel_diff_to_adjusted": float(g["rel_diff_adjusted"].median()),
            "required_validation_rows": int(required_rows),
            "status": status,
        })
    return pd.DataFrame(rows).sort_values(["status", "identity_match_rate", "ticker"]).reset_index(drop=True)

def validate_local_adjusted_reference(root: Path, downloaded: pd.DataFrame, cfg: Phase2CConfig) -> tuple[pd.DataFrame, dict]:
    path = root / cfg.local_adjusted_reference
    if not path.exists():
        return pd.DataFrame(), {"status": "MISSING", "overlap_rows": 0, "match_rate": math.nan}
    local = pd.read_parquet(path)
    if not {"date", "ticker", "adj_close"}.issubset(local.columns):
        return pd.DataFrame(), {"status": "INVALID_SCHEMA", "overlap_rows": 0, "match_rate": math.nan}
    local = local[["date", "ticker", "adj_close"]].copy()
    local["date"] = _as_date(local["date"])
    local["ticker"] = _norm_ticker(local["ticker"])
    local["adj_close"] = pd.to_numeric(local["adj_close"], errors="coerce")
    ref = downloaded[["date", "ticker", "adj_close"]].rename(columns={"adj_close": "download_adj_close"})
    m = local.rename(columns={"adj_close": "local_adj_close"}).merge(
        ref, on=["date", "ticker"], how="inner"
    ).dropna()
    if m.empty:
        return m, {"status": "NO_OVERLAP", "overlap_rows": 0, "match_rate": math.nan}
    m["rel_diff"] = _rel_diff(m["local_adj_close"], m["download_adj_close"])
    tol = float(cfg.policies["local_adjusted_relative_tolerance"])
    rate = float((m["rel_diff"] <= tol).mean())
    status = "PASS" if (
        len(m) >= int(cfg.policies["minimum_validation_rows"])
        and rate >= float(cfg.policies["local_adjusted_match_required"])
    ) else "FAIL"
    return m, {
        "status": status,
        "overlap_rows": int(len(m)),
        "overlap_tickers": int(m["ticker"].nunique()),
        "match_rate": rate,
        "median_rel_diff": float(m["rel_diff"].median()),
    }


def build_return_price_layer(panel: pd.DataFrame, downloaded: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    p = panel[["date", "ticker", "close", "adj_close", "research_eligible", "market_source"]].copy()
    if len(downloaded):
        dl = downloaded[["date", "ticker", "adj_close", "provider_symbol"]].rename(
            columns={"adj_close": "downloaded_adj_close"}
        )
    else:
        dl = pd.DataFrame(columns=["date", "ticker", "downloaded_adj_close", "provider_symbol"])
    x = p.merge(dl, on=["date", "ticker"], how="left")
    existing_ok = np.isfinite(x["adj_close"]) & (x["adj_close"] > 0)
    downloaded_ok = np.isfinite(x["downloaded_adj_close"]) & (x["downloaded_adj_close"] > 0)
    x["target_total_return_price"] = np.where(
        existing_ok,
        x["adj_close"],
        np.where(downloaded_ok, x["downloaded_adj_close"], np.nan),
    )
    x["target_price_source"] = np.where(
        existing_ok,
        "PHASE2_EXISTING_ADJ_CLOSE",
        np.where(downloaded_ok, "V12_YAHOO_ADJ_CLOSE", "MISSING"),
    )
    x["target_price_feature_allowed"] = False
    layer = x[[
        "date", "ticker", "research_eligible", "close", "market_source",
        "target_total_return_price", "target_price_source",
        "target_price_feature_allowed", "provider_symbol",
    ]].copy().sort_values(["ticker", "date"]).reset_index(drop=True)

    e = layer[layer["research_eligible"]].copy()
    e["covered"] = np.isfinite(e["target_total_return_price"]) & (e["target_total_return_price"] > 0)
    by_ticker = e.groupby("ticker", observed=True).agg(
        first_date=("date", "min"),
        last_date=("date", "max"),
        rows=("date", "size"),
        covered_rows=("covered", "sum"),
    ).reset_index()
    by_ticker["coverage"] = by_ticker["covered_rows"] / by_ticker["rows"]
    by_ticker["first_date"] = by_ticker["first_date"].dt.strftime("%Y-%m-%d")
    by_ticker["last_date"] = by_ticker["last_date"].dt.strftime("%Y-%m-%d")
    meta = {
        "eligible_rows": int(len(e)),
        "covered_rows": int(e["covered"].sum()),
        "coverage": float(e["covered"].mean()) if len(e) else 0.0,
        "eligible_tickers": int(e["ticker"].nunique()),
    }
    return layer, by_ticker.sort_values(["coverage", "ticker"]).reset_index(drop=True), meta


def evaluate_gate(
    manifest: pd.DataFrame,
    provider_validation: pd.DataFrame,
    local_validation_meta: dict,
    ticker_coverage: pd.DataFrame,
    coverage_meta: dict,
    cfg: Phase2CConfig,
) -> tuple[pd.DataFrame, str]:
    overall_req = float(cfg.policies["coverage_required"])
    per_req = float(cfg.policies["per_ticker_coverage_required"])
    identity_req = float(cfg.policies["raw_identity_match_required"])
    failures = int((manifest["status"] == "FAILED").sum()) if len(manifest) else 0
    low_cov = int((ticker_coverage["coverage"] < per_req).sum()) if len(ticker_coverage) else 0

    if len(provider_validation):
        weighted_rate = float(np.average(
            provider_validation["identity_match_rate"],
            weights=np.maximum(provider_validation["overlap_rows"], 1),
        ))
        identity_fail_tickers = int((provider_validation["status"] != "PASS").sum())
    else:
        weighted_rate = 0.0
        identity_fail_tickers = len(manifest)

    local_status = str(local_validation_meta.get("status", "MISSING"))
    local_match = local_validation_meta.get("match_rate", math.nan)
    local_blocking = local_status not in {"NO_OVERLAP", "MISSING"}
    if local_status == "PASS":
        local_gate_status = "PASS"
    elif local_blocking:
        local_gate_status = "FAIL"
    else:
        local_gate_status = "NOT_APPLICABLE"

    rows = [
        {"test": "DOWNLOAD_FAILURES", "status": "PASS" if failures == 0 else "FAIL", "blocking": True, "value": failures, "rule": "0 failed required tickers"},
        {"test": "ELIGIBLE_TOTAL_RETURN_PRICE_COVERAGE", "status": "PASS" if coverage_meta["coverage"] >= overall_req else "FAIL", "blocking": True, "value": coverage_meta["coverage"], "rule": f">= {overall_req:.3f}"},
        {"test": "PER_TICKER_TOTAL_RETURN_PRICE_COVERAGE", "status": "PASS" if low_cov == 0 else "FAIL", "blocking": True, "value": low_cov, "rule": f"0 tickers below {per_req:.3f}"},
        {"test": "PROVIDER_SECURITY_IDENTITY", "status": "PASS" if (weighted_rate >= identity_req and identity_fail_tickers == 0) else "FAIL", "blocking": True, "value": weighted_rate, "rule": f"weighted best(raw, adjusted) close identity >= {identity_req:.3f} and 0 failing tickers"},
        {"test": "LOCAL_ADJUSTED_REFERENCE_CROSSCHECK", "status": local_gate_status, "blocking": local_blocking, "value": local_match, "rule": "diagnostic reference: blocking only when overlapping observations exist; disjoint universe => NOT_APPLICABLE"},
    ]
    gate = pd.DataFrame(rows)
    blocking = gate[gate["blocking"]]
    status = "PASS" if len(blocking) and (blocking["status"] == "PASS").all() else "FAIL"
    return gate, status

def build_phase2c(root: Path) -> dict:
    cfg = load_phase2c_config(root / "config" / "phase2c.toml")
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    panel = load_panel(root, cfg)
    requirements = load_requirements(root, cfg, panel)
    print(f"Required adjusted histories: {len(requirements)}")
    manifest, downloaded, actions = acquire_histories(root, cfg, requirements)

    provider_validation = validate_provider_identity(panel, downloaded, cfg)
    local_validation_rows, local_validation_meta = validate_local_adjusted_reference(root, downloaded, cfg)
    layer, ticker_coverage, coverage_meta = build_return_price_layer(panel, downloaded)
    gate, status = evaluate_gate(
        manifest, provider_validation, local_validation_meta, ticker_coverage, coverage_meta, cfg
    )

    manifest.to_csv(outputs / "phase2c_download_manifest.csv", index=False)
    provider_validation.to_csv(outputs / "phase2c_provider_validation.csv", index=False)
    ticker_coverage.to_csv(outputs / "phase2c_ticker_coverage.csv", index=False)
    gate.to_csv(outputs / "phase2c_gate.csv", index=False)
    layer.to_parquet(outputs / "phase2c_return_price_layer.parquet", index=False)

    if len(actions):
        actions_path = root / cfg.actions_path
        actions_path.parent.mkdir(parents=True, exist_ok=True)
        clean_actions = actions.sort_values(["ticker", "date", "event_type"]).drop_duplicates()
        clean_actions.to_parquet(actions_path, index=False)
        clean_actions.to_parquet(outputs / "phase2c_corporate_actions.parquet", index=False)
    if len(local_validation_rows):
        local_validation_rows.head(200000).to_csv(
            outputs / "phase2c_local_adjusted_crosscheck.csv", index=False
        )

    summary = {
        "status": status,
        "phase": "2C",
        "build": PHASE2C_BUILD,
        "name": cfg.name,
        "objective": cfg.objective,
        "required_tickers": int(len(requirements)),
        "download": {
            "success_or_cache": int((manifest["status"] != "FAILED").sum()) if len(manifest) else 0,
            "failed": int((manifest["status"] == "FAILED").sum()) if len(manifest) else 0,
            "downloaded_rows": int(len(downloaded)),
            "downloaded_tickers": int(downloaded["ticker"].nunique()) if len(downloaded) else 0,
        },
        "coverage": coverage_meta,
        "provider_identity": {
            "validated_tickers": int(len(provider_validation)),
            "failing_tickers": int((provider_validation["status"] != "PASS").sum()) if len(provider_validation) else 0,
            "median_match_rate": float(provider_validation["identity_match_rate"].median()) if len(provider_validation) else math.nan,
            "raw_like_tickers": int((provider_validation["panel_price_semantics"].isin(["RAW_CLOSE_LIKE", "RAW_AND_ADJUSTED_EQUIVALENT"])).sum()) if len(provider_validation) else 0,
            "adjusted_like_tickers": int((provider_validation["panel_price_semantics"] == "ADJUSTED_CLOSE_LIKE").sum()) if len(provider_validation) else 0,
        },
        "local_adjusted_crosscheck": local_validation_meta,
        "gate": gate.to_dict(orient="records"),
        "target_price_policy": {
            "column": "target_total_return_price",
            "feature_allowed": False,
            "purpose": "TARGET_CONSTRUCTION_ONLY",
            "execution_price_column": "close",
            "principle": "Never substitute target adjusted price for observable execution close.",
        },
        "next_gate": "If PASS: Phase 3 may construct forward-return labels. If FAIL: repair only the failing mappings/coverage; do not train alpha.",
    }
    (outputs / "phase2c_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return summary
