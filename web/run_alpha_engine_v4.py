from __future__ import annotations

import concurrent.futures
import csv
import io
import json
import math
import mimetypes
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION")
WEB = ROOT / "web" / "v4"
STATE = ROOT / "public" / "data" / "alpha_product_state.json"
REC = ROOT / "ALPHA_ENGINE_DATA_RECOVERY_V1"
V13 = ROOT / "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
PRODUCT = ROOT / "PRODUCT"
MARKET_CSV = REC / "outputs" / "data_recovery_v1" / "live" / "mercado_riesgo_live_latest.csv"
FUND_CSV = REC / "outputs" / "data_recovery_v1" / "staging" / "fundamentales_payload_latest.csv"
V13_SUMMARY = V13 / "outputs" / "live_shadow" / "v13_live_shadow_summary.json"
V13_CONTRACT_LATEST = V13 / "outputs" / "live_shadow" / "v13_live_shadow_contract_latest.csv"
V13_CONTRACT_HISTORY = V13 / "outputs" / "live_shadow" / "v13_live_shadow_contract_history.csv"
NAV_CSV = PRODUCT / "nav_history.csv"
HOLDOUT_NAV = V13 / "outputs" / "v13_phase4_holdout_nav_20bps.csv"
LEDGER_JSON = PRODUCT / "personal_portfolio_ledger_v4.json"
LEDGER_CSV = PRODUCT / "personal_portfolio_ledger_v4.csv"
LEDGER_XLSX = PRODUCT / "AlphaEngine_Cartera_Real.xlsx"
PRICE_CACHE_DIR = REC / "outputs" / "data_recovery_v1" / "portfolio_price_cache"
FORWARD_NAV_JSON = REC / "outputs" / "data_recovery_v1" / "forward_v42" / "forward_nav_latest.json"
FORWARD_NAV_CSV = REC / "outputs" / "data_recovery_v1" / "forward_v42" / "forward_nav_latest.csv"
FORWARD_NAV_BUILDER = REC / "scripts" / "build_forward_nav_v42.py"
HOST = "127.0.0.1"
PORT = 8765

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/153 Safari/537.36"
)
YAHOO_BASES = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")

_lock = threading.RLock()
_forward_lock = threading.Lock()
_forward_job_lock = threading.Lock()
_market_refresh_lock = threading.Lock()
_market_job_lock = threading.Lock()
_quote_cache: dict[str, tuple[float, dict]] = {}
_history_cache: dict[str, tuple[float, list[dict]]] = {}
_market_job = {
    "status": "IDLE",
    "mode": "AUTO_5M_REGULAR_SESSION",
    "started_at": None,
    "finished_at": None,
    "last_pass_at": None,
    "error": None,
    "rows": None,
    "critical_rows": None,
    "asof": None,
}

_forward_job = {
    "status": "IDLE",
    "started_at": None,
    "finished_at": None,
    "runner": None,
    "error": None,
    "returncode": None,
    "stdout_tail": "",
    "stderr_tail": "",
}


def finite(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def clean(v):
    if v is None or isinstance(v, bool) or isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in {"", "nan", "none", "null", "<na>"}:
            return None
        x = finite(s)
        return x if x is not None else s
    if isinstance(v, list):
        return [clean(x) for x in v]
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    return str(v)


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [{k: clean(v) for k, v in row.items()} for row in csv.DictReader(f)]


def state() -> dict:
    s = load_json(STATE, {}) or {}
    if s.get("schema") != "ALPHA_ENGINE_PRODUCT_STATE_V1":
        raise RuntimeError("INVALID_PRODUCT_STATE_SCHEMA")
    if (s.get("system") or {}).get("status") != "PASS":
        raise RuntimeError("PRODUCT_STATE_NOT_PASS")
    return s


def _first_market(row: dict, *keys):
    for k in keys:
        if k in row and row.get(k) not in (None, ""):
            return clean(row.get(k))
    return None


def _normalize_market_row(r: dict) -> dict:
    # Data Recovery V1 canonical CSV uses the original 41 Spanish headers.
    # Product-state fallback already uses snake_case. Support both explicitly.
    aliases = {
        "ticker": ("ticker", "Ticker"),
        "market_symbol": ("market_symbol", "Yahoo Symbol"),
        "benchmark": ("benchmark", "Benchmark"),
        "price": ("price", "Precio"),
        "var_1d": ("var_1d", "Var 1D"),
        "ret_1m": ("ret_1m", "Ret 1M"),
        "ret_3m": ("ret_3m", "Ret 3M"),
        "ret_6m": ("ret_6m", "Ret 6M"),
        "ret_12m": ("ret_12m", "Ret 12M"),
        "sma20": ("sma20", "SMA20"),
        "sma50": ("sma50", "SMA50"),
        "sma200": ("sma200", "SMA200"),
        "dist_sma20": ("dist_sma20", "Dist SMA20"),
        "dist_sma50": ("dist_sma50", "Dist SMA50"),
        "dist_sma200": ("dist_sma200", "Dist SMA200"),
        "rsi14": ("rsi14", "RSI14"),
        "vol_20d": ("vol_20d", "Vol 20D"),
        "vol_60d": ("vol_60d", "Vol 60D"),
        "vol_1y": ("vol_1y", "Vol 1A"),
        "downside_dev_60d": ("downside_dev_60d", "Downside Dev 60D"),
        "max_drawdown_1y": ("max_drawdown_1y", "Max Drawdown 1A"),
        "avg_volume_20d": ("avg_volume_20d", "Avg Vol 20D"),
        "dollar_volume_20d": ("dollar_volume_20d", "Dollar Vol 20D"),
        "relative_volume_20v60": ("relative_volume_20v60", "Vol 20/60"),
        "rs_3m": ("rs_3m", "RS 3M"),
        "rs_6m": ("rs_6m", "RS 6M"),
        "beta_6m": ("beta_6m", "Beta 6M"),
        "corr_6m": ("corr_6m", "Corr 6M"),
        "dist_52w_high": ("dist_52w_high", "Dist 52W High"),
        "coverage": ("coverage", "Cobertura Mercado"),
        "source": ("source", "Fuente"),
        "updated_at": ("updated_at", "Actualización"),
    }
    out = {name: _first_market(r, *keys) for name, keys in aliases.items()}
    if out["ticker"] is not None:
        out["ticker"] = str(out["ticker"]).strip().upper()
    if out["market_symbol"] is not None:
        out["market_symbol"] = str(out["market_symbol"]).strip().upper()
    if out["benchmark"] is not None:
        out["benchmark"] = str(out["benchmark"]).strip().upper()
    return out


def latest_market_rows() -> list[dict]:
    rows = read_csv_rows(MARKET_CSV)
    if not rows:
        rows = (state().get("market") or {}).get("assets") or []
    out = [_normalize_market_row(r) for r in rows if isinstance(r, dict)]
    # Never report "200 rows" if the payload shape is present but the values are not.
    good = sum(
        1 for r in out
        if r.get("ticker") and finite(r.get("price")) is not None
        and finite(r.get("var_1d")) is not None
    )
    if out and good < min(190, len(out)):
        raise RuntimeError(
            f"MARKET_PAYLOAD_CRITICAL_VALUES_MISSING good={good} rows={len(out)}"
        )
    return out


def market_asof(rows: list[dict] | None = None):
    rows = rows if rows is not None else latest_market_rows()
    vals = [str(r.get("updated_at")) for r in rows if r.get("updated_at")]
    return max(vals) if vals else None


def fundamentals_rows() -> list[dict]:
    s = state()
    rows = (s.get("fundamentals") or {}).get("companies") or []
    if not rows:
        rows = read_csv_rows(FUND_CSV)
    return [clean(r) for r in rows if isinstance(r, dict)]


def fundamental_compact(r: dict) -> dict:
    aliases = {
        "ticker": ["ticker", "Ticker", "symbol"],
        "name": ["name", "company", "company_name", "Nombre", "longName", "shortName"],
        "sector": ["sector", "Sector", "sector_name"],
        "industry": ["industry", "Industry", "industria"],
        "price": ["price", "Precio", "regular_market_price", "current_price"],
        "market_cap": ["market_cap", "marketcap", "Market Cap", "marketCap"],
        "pe": ["pe", "trailing_pe", "trailingPE", "P/E"],
        "forward_pe": ["forward_pe", "forwardPE"],
        "price_book": ["price_book", "priceToBook", "pb"],
        "ev_ebitda": ["ev_ebitda", "enterpriseToEbitda"],
        "roe": ["roe", "returnOnEquity"],
        "roa": ["roa", "returnOnAssets"],
        "debt_to_equity": ["debt_to_equity", "debtToEquity"],
        "profit_margin": ["profit_margin", "profitMargins", "net_margin"],
        "revenue_growth": ["revenue_growth", "revenueGrowth"],
        "eps_growth": ["eps_growth", "earningsGrowth"],
        "fcf_yield": ["fcf_yield", "free_cash_flow_yield"],
        "revenue": ["revenue", "totalRevenue"],
        "net_income": ["net_income", "netIncome"],
        "source": ["source", "Fuente", "fundamental_source"],
        "coverage": ["coverage", "fundamental_coverage", "coverage_ratio"],
        "updated_at": ["updated_at", "asof", "as_of", "timestamp"],
    }
    def first(keys):
        for k in keys:
            if k in r and r.get(k) not in (None, ""):
                return clean(r.get(k))
        return None
    out = {k: first(v) for k, v in aliases.items()}
    if not out["ticker"]:
        out["ticker"] = str(r.get("market_symbol") or "").replace(".BA", "") or None
    return out


def yahoo_chart(symbol: str, range_: str = "1y", interval: str = "1d") -> dict:
    encoded = urllib.parse.quote(symbol, safe="")
    query = (
        f"/v8/finance/chart/{encoded}?range={range_}&interval={interval}"
        "&events=history&includeAdjustedClose=true&includePrePost=false"
    )
    last = None
    for base in YAHOO_BASES:
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    base + query,
                    headers={"User-Agent": UA, "Accept": "application/json,text/plain,*/*"},
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                err = (payload.get("chart") or {}).get("error")
                if err:
                    raise RuntimeError(str(err))
                result = ((payload.get("chart") or {}).get("result") or [])
                if not result:
                    raise RuntimeError("YAHOO_EMPTY_RESULT")
                return result[0]
            except Exception as exc:
                last = exc
                time.sleep(0.3 * (attempt + 1))
    raise RuntimeError(f"YAHOO_FAILED {symbol}: {last}")


def chart_daily(result: dict) -> list[dict]:
    ts = result.get("timestamp") or []
    q = ((((result.get("indicators") or {}).get("quote") or [{}])[0]) or {})
    adj = ((((result.get("indicators") or {}).get("adjclose") or [{}])[0]) or {}).get("adjclose") or []
    closes = q.get("close") or []
    rows = []
    for i, t in enumerate(ts):
        c = finite(adj[i] if i < len(adj) else None)
        if c is None:
            c = finite(closes[i] if i < len(closes) else None)
        if c is None:
            continue
        d = datetime.fromtimestamp(float(t), tz=timezone.utc).date().isoformat()
        rows.append({"date": d, "close": c})
    dedup = {r["date"]: r for r in rows}
    return [dedup[k] for k in sorted(dedup)]


def _inferred_market_state(meta: dict) -> str:
    direct = str(meta.get("marketState") or "").strip().upper()
    if direct in {"PRE", "PREPRE", "REGULAR", "POST", "POSTPOST", "CLOSED"}:
        return direct

    now = time.time()
    periods = meta.get("currentTradingPeriod") or {}

    def inside(name: str) -> bool:
        p = periods.get(name) or {}
        start = finite(p.get("start"))
        end = finite(p.get("end"))
        return bool(start is not None and end is not None and start <= now < end)

    if inside("regular"):
        return "REGULAR"
    if inside("pre"):
        return "PRE"
    if inside("post"):
        return "POST"
    return "CLOSED"

def current_quote(symbol: str) -> dict:
    symbol = str(symbol or "").strip().upper()
    now = time.time()
    cached = _quote_cache.get(symbol)
    if cached and now - cached[0] < 60:
        return cached[1]
    result = yahoo_chart(symbol, "3mo", "1d")
    meta = result.get("meta") or {}
    daily = chart_daily(result)
    price = finite(meta.get("regularMarketPrice"))
    if price is None and daily:
        price = daily[-1]["close"]

    market_time = (
        datetime.fromtimestamp(float(meta.get("regularMarketTime")), tz=timezone.utc)
        if meta.get("regularMarketTime") else None
    )
    market_date = market_time.date().isoformat() if market_time else None
    market_state = _inferred_market_state(meta)

    prev = None
    if daily:
        if market_date and daily[-1]["date"] == market_date:
            prev = daily[-2]["close"] if len(daily) >= 2 else None
        else:
            prev = daily[-1]["close"]

    change = (
        (price / prev - 1.0)
        if price is not None and prev not in (None, 0)
        else None
    )
    out = {
        "status": "PASS" if price is not None else "MISSING",
        "symbol": symbol,
        "regular_market_price": price,
        "previous_session_close": prev,
        "change_pct": change,
        "currency": meta.get("currency"),
        "exchange": meta.get("exchangeName") or meta.get("fullExchangeName"),
        "market_time": market_time.isoformat() if market_time else None,
        "market_state": market_state,
        "prepost": False,
        "source": "Yahoo Finance chart v8 / regular session",
    }
    _quote_cache[symbol] = (now, out)
    return out


def market_pulse() -> dict:
    specs = [
        ("SPY", "S&P 500"),
        ("QQQ", "Nasdaq"),
        ("IWM", "Russell 2000"),
        ("EEM", "Emerging"),
        ("^MERV", "S&P Merval"),
        ("ARS=X", "USD / ARS"),
    ]
    def one(item):
        symbol, name = item
        try:
            q = current_quote(symbol)
            return {
                "name": name,
                "ticker": symbol,
                "status": q.get("status"),
                "price": q.get("regular_market_price"),
                "var_1d": q.get("change_pct"),
                "currency": q.get("currency"),
                "exchange": q.get("exchange"),
                "market_time": q.get("market_time"),
                "market_state": q.get("market_state"),
                "source": q.get("source"),
                "prepost": False,
            }
        except Exception as exc:
            return {
                "name": name, "ticker": symbol, "status": "FAIL",
                "error": str(exc), "prepost": False
            }
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(one, specs))
    return clean({
        "status": "PASS" if sum(r.get("status") == "PASS" for r in rows) >= 4 else "DEGRADED",
        "rows": rows,
        "prepost": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


def latest_completed_us_session() -> str | None:
    result = yahoo_chart("SPY", "1mo", "1d")
    meta = result.get("meta") or {}
    daily = chart_daily(result)
    if not daily:
        return None

    state_ = _inferred_market_state(meta)
    periods = meta.get("currentTradingPeriod") or {}
    regular = periods.get("regular") or {}
    reg_start = finite(regular.get("start"))
    reg_end = finite(regular.get("end"))
    now = time.time()

    session_date = None
    if reg_start is not None:
        session_date = datetime.fromtimestamp(
            reg_start, tz=timezone.utc
        ).date().isoformat()

    last_date = daily[-1]["date"]
    current_session_incomplete = bool(
        session_date
        and last_date == session_date
        and (
            state_ in {"PRE", "PREPRE", "REGULAR"}
            or (reg_end is not None and now < reg_end)
        )
    )

    if current_session_incomplete and len(daily) >= 2:
        return daily[-2]["date"]

    if not session_date and state_ == "REGULAR":
        mt = (
            datetime.fromtimestamp(
                float(meta.get("regularMarketTime")), tz=timezone.utc
            )
            if meta.get("regularMarketTime")
            else None
        )
        mt_date = mt.date().isoformat() if mt else None
        if mt_date and last_date == mt_date and len(daily) >= 2:
            return daily[-2]["date"]

    return last_date


def history_for(symbol: str, range_: str = "2y") -> list[dict]:
    key = f"{symbol}|{range_}"
    now = time.time()
    cached = _history_cache.get(key)
    if cached and now - cached[0] < 900:
        return cached[1]
    PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = urllib.parse.quote(symbol, safe="").replace("%", "_")
    disk = PRICE_CACHE_DIR / f"{safe}_{range_}.json"
    if disk.exists() and now - disk.stat().st_mtime < 900:
        rows = load_json(disk, []) or []
        _history_cache[key] = (now, rows)
        return rows
    rows = chart_daily(yahoo_chart(symbol, range_, "1d"))
    disk.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    _history_cache[key] = (now, rows)
    return rows


def v13_status() -> dict:
    s = state()
    summ = load_json(V13_SUMMARY, {}) or (s.get("v13") or {}).get("summary") or {}
    latest_rows = read_csv_rows(V13_CONTRACT_LATEST)
    hist_rows = read_csv_rows(V13_CONTRACT_HISTORY)
    if not latest_rows:
        latest_rows = (s.get("v13") or {}).get("recommendations") or []
    targets = []
    for r in latest_rows:
        if not isinstance(r, dict):
            continue
        ticker = r.get("ticker")
        weight = r.get("model_target_weight")
        if weight is None:
            weight = r.get("target_weight")
        targets.append({
            "signal_date": r.get("signal_date"),
            "ticker": ticker,
            "target_weight": finite(weight),
            "expected_active_total": finite(r.get("expected_active_total")),
            "expected_active_per_session": finite(r.get("expected_active_per_session")),
            "effective_horizon_sessions": finite(r.get("effective_horizon_sessions")),
            "entry_ok": r.get("entry_ok"),
            "model_intent": r.get("model_intent"),
        })
    targets.sort(key=lambda r: (r["target_weight"] is None, -(r["target_weight"] or 0), r["ticker"] or ""))
    dates = sorted({str(r.get("signal_date")) for r in hist_rows if r.get("signal_date")})
    system = s.get("system") or {}
    runner = discover_forward_runner()
    return clean({
        "status": summ.get("status") or system.get("status"),
        "phase": summ.get("phase"),
        "build": summ.get("build"),
        "seal_id": summ.get("seal_id") or system.get("seal_id") or (s.get("data_recovery") or {}).get("v13_seal_id"),
        "holdout_verdict": summ.get("holdout_verdict") or system.get("holdout_verdict"),
        "oos_last_date": "2026-09-04",
        "latest_completed_session": summ.get("latest_completed_session"),
        "new_sessions": summ.get("new_sessions"),
        "universe": ((summ.get("universe") or {}).get("tickers")) or (s.get("overview") or {}).get("universe_count"),
        "market_coverage_latest": summ.get("market_coverage_latest"),
        "entry_eligible": summ.get("entry_eligible_latest") or (s.get("overview") or {}).get("entry_eligible_count"),
        "positive_targets": summ.get("positive_targets_latest") or (s.get("overview") or {}).get("positive_target_count"),
        "target_weight_sum": summ.get("target_weight_sum_latest"),
        "shadow_only": summ.get("shadow_only", True),
        "real_orders_sent": summ.get("real_orders_sent", False),
        "tuning_performed": summ.get("tuning_performed", False),
        "targets": targets,
        "top5": targets[:5],
        "history_signal_dates": dates[-30:],
        "contract_history_rows": len(hist_rows),
        "refresh_runner_available": bool(runner),
        "refresh_runner": runner[0] if runner else None,
        "summary_path": str(V13_SUMMARY),
        "contract_latest_path": str(V13_CONTRACT_LATEST),
    })


def nav_history() -> dict:
    rows = read_csv_rows(NAV_CSV)
    hold = read_csv_rows(HOLDOUT_NAV)
    out_rows = [r for r in rows if r.get("date")]
    hold_series = []
    if hold:
        base = finite(hold[0].get("nav")) or 1.0
        for r in hold:
            nav = finite(r.get("nav"))
            if nav is not None:
                hold_series.append({
                    "date": str(r.get("date"))[:10],
                    "value": 100.0 * nav / base,
                })

    fwd = forward_nav_status()
    live = []
    combined = list(hold_series)
    if fwd.get("status") == "PASS":
        live = [
            {"date": str(r.get("date"))[:10], "value": finite(r.get("base100"))}
            for r in (fwd.get("series") or [])
            if r.get("date") and finite(r.get("base100")) is not None
        ]
        if hold_series and live:
            seam = next(
                (r["value"] for r in hold_series if r["date"] == "2026-09-04"),
                hold_series[-1]["value"],
            )
            live_cont = [
                {"date": r["date"], "value": seam * float(r["value"]) / 100.0}
                for r in live
            ]
            combined = [r for r in hold_series if r["date"] <= "2026-09-04"]
            combined.extend([r for r in live_cont if r["date"] > "2026-09-04"])

    perf = (state().get("performance") or {}).get("summary") or {}
    return clean({
        "status": "PASS",
        "nav_history": out_rows,
        "oos_20bps": hold_series,
        "combined_20bps": combined,
        "forward_live_base100": live,
        "forward_summary": fwd if fwd.get("status") == "PASS" else {
            "status": fwd.get("status"),
            "start_date": "2026-09-04",
        },
        "markers": [
            {"date": "2025-01-02", "label": "OOS START"},
            {"date": "2026-09-04", "label": "LIVE FORWARD"},
        ],
        "summary": perf,
    })


def forward_nav_status() -> dict:
    payload = load_json(FORWARD_NAV_JSON, None)
    if not isinstance(payload, dict):
        return {
            "status": "NOT_BUILT",
            "start_date": "2026-09-04",
            "path": str(FORWARD_NAV_JSON),
        }
    return clean(payload)


def _latest_contract_frames():
    hist = read_csv_rows(V13_CONTRACT_HISTORY)
    if not hist:
        return [], [], None, None
    dates = sorted({
        str(r.get("signal_date"))[:10]
        for r in hist if r.get("signal_date")
    })
    if not dates:
        return [], [], None, None
    latest = dates[-1]
    prev = dates[-2] if len(dates) >= 2 else None
    current = [r for r in hist if str(r.get("signal_date"))[:10] == latest]
    previous = [r for r in hist if prev and str(r.get("signal_date"))[:10] == prev]
    return current, previous, latest, prev


def _model_recommendation_rows() -> list[dict]:
    current, previous, latest, prev = _latest_contract_frames()
    if not current:
        current = read_csv_rows(V13_CONTRACT_LATEST)
        latest = str(current[0].get("signal_date"))[:10] if current else None
    prev_map = {
        str(r.get("ticker") or "").upper(): finite(r.get("model_target_weight")) or 0.0
        for r in previous
    }
    rows = []
    for r in current:
        ticker = str(r.get("ticker") or "").upper()
        if not ticker:
            continue
        target = finite(r.get("model_target_weight"))
        if target is None:
            target = finite(r.get("target_weight")) or 0.0
        old = prev_map.get(ticker, 0.0)
        delta = target - old
        band = finite(r.get("resize_band")) or 0.0
        alpha = finite(r.get("expected_active_total"))
        entry = str(r.get("entry_ok")).lower() in {"true","1","yes"}
        threshold = max(0.0005, band * 0.25)
        if target <= 1e-14 and old > 1e-14:
            change = "TARGET_A_CERO"
        elif target > 1e-14 and old <= 1e-14:
            change = "NUEVA_EXPOSICION"
        elif delta > threshold:
            change = "SUBE_TARGET"
        elif delta < -threshold:
            change = "BAJA_TARGET"
        else:
            change = "MANTIENE_TARGET"
        rows.append({
            "signal_date": latest,
            "previous_signal_date": prev,
            "ticker": ticker,
            "model_change": change,
            "model_target_weight": target,
            "previous_target_weight": old,
            "target_delta_weight": delta,
            "expected_active_total": alpha,
            "expected_active_per_session": finite(r.get("expected_active_per_session")),
            "effective_horizon_sessions": finite(r.get("effective_horizon_sessions")),
            "entry_ok": entry,
            "resize_band": band,
            "model_intent": r.get("model_intent"),
        })
    rows.sort(key=lambda x: (-(x["model_target_weight"] or 0.0), x["ticker"]))
    return rows


def _economic_weight(current_weight: float, row: dict) -> float:
    c = max(0.0, float(current_weight or 0.0))
    target = max(0.0, float(row.get("model_target_weight") or 0.0))
    alpha = finite(row.get("expected_active_total"))
    band = max(0.0, float(row.get("resize_band") or 0.0))
    entry = bool(row.get("entry_ok"))
    if c <= 1e-14:
        return target if entry else 0.0
    if alpha is None or alpha <= 0:
        return 0.0
    if target <= 0:
        return c
    delta = target - c
    if abs(delta) <= band:
        return c
    return max(0.0, c + (1.0 if delta > 0 else -1.0) * (abs(delta) - band))


def recommendations() -> dict:
    model_rows = _model_recommendation_rows()
    ledger = load_ledger()
    book = compute_book(ledger.get("operations") or [])
    if not book["operations"]:
        return clean({
            "status": "PASS",
            "signal_date": model_rows[0].get("signal_date") if model_rows else None,
            "portfolio_status": "PENDING_REAL_PORTFOLIO",
            "message": (
                "Los targets del modelo ya están disponibles. "
                "Las cantidades BUY/SELL se activan automáticamente cuando cargues la cartera real."
            ),
            "rows": [{**r, "action": "PENDIENTE_CARTERA", "current_quantity": None,
                      "target_quantity": None, "delta_quantity": None,
                      "current_weight": None, "economic_target_weight": None,
                      "local_price": None, "execution_symbol": None}
                     for r in model_rows],
        })

    # Only produce actual nominal instructions when one economic currency is in use.
    positions = book["positions"]
    currencies = sorted({p.get("currency") for p in positions if p.get("currency")})
    if len(currencies) != 1:
        return clean({
            "status": "PASS",
            "signal_date": model_rows[0].get("signal_date") if model_rows else None,
            "portfolio_status": "MULTI_CURRENCY_REVIEW_REQUIRED",
            "message": "Cartera multi-moneda: se muestran targets, pero no se inventan cantidades sin una capa FX explícita.",
            "rows": [{**r, "action": "REVIEW", "current_quantity": None,
                      "target_quantity": None, "delta_quantity": None,
                      "current_weight": None, "economic_target_weight": None,
                      "local_price": None, "execution_symbol": None}
                     for r in model_rows],
        })

    currency = currencies[0]
    market = positions[0].get("market") if positions else ("BYMA" if currency == "ARS" else "US")
    if any(p.get("market") != market for p in positions):
        return clean({
            "status": "PASS",
            "signal_date": model_rows[0].get("signal_date") if model_rows else None,
            "portfolio_status": "MULTI_MARKET_REVIEW_REQUIRED",
            "message": "Cartera multi-mercado: cantidades automáticas pausadas hasta definir la traducción FX/local.",
            "rows": model_rows,
        })

    # Mark current positions.
    pos_by_ticker = {str(p["ticker"]).upper(): p for p in positions}
    quote_symbols = {}
    for r in model_rows:
        t = r["ticker"]
        p = pos_by_ticker.get(t)
        if p:
            quote_symbols[t] = p["market_symbol"]
        elif r["model_target_weight"] > 0 and r["entry_ok"]:
            quote_symbols[t] = t if market == "US" else (t if t.endswith(".BA") else t + ".BA")

    def get_quote(item):
        t, sym = item
        try:
            q = current_quote(sym)
            return t, sym, finite(q.get("regular_market_price")), q.get("status")
        except Exception as exc:
            return t, sym, None, f"FAIL:{exc}"

    quotes = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for t, sym, px, st in ex.map(get_quote, quote_symbols.items()):
            quotes[t] = {"symbol": sym, "price": px, "status": st}

    current_values = {}
    total_market = 0.0
    for t, p in pos_by_ticker.items():
        q = quotes.get(t)
        px = q.get("price") if q else None
        if px is None:
            continue
        mv = float(p["quantity"]) * px
        current_values[t] = mv
        total_market += mv
    positive_cash = max(0.0, float(book["cash"].get(currency, 0.0) or 0.0))
    equity = total_market + positive_cash
    if equity <= 0:
        return clean({
            "status": "PASS",
            "signal_date": model_rows[0].get("signal_date") if model_rows else None,
            "portfolio_status": "PORTFOLIO_VALUE_UNAVAILABLE",
            "message": "No hay valor de cartera positivo suficiente para convertir targets a nominales.",
            "rows": model_rows,
        })

    row_map = {r["ticker"]: r for r in model_rows}
    all_names = set(row_map) | set(pos_by_ticker)
    econ = {}
    for t in all_names:
        r = row_map.get(t)
        cw = current_values.get(t, 0.0) / equity
        if r is None:
            econ[t] = 0.0
        else:
            econ[t] = _economic_weight(cw, r)
    sw = sum(econ.values())
    if sw > 1.0 + 1e-12:
        econ = {t: w / sw for t, w in econ.items()}

    # Integer target allocation only over instruments that have an executable quote.
    alloc = {}
    desired_value = {}
    used = 0.0
    for t, w in econ.items():
        q = quotes.get(t)
        px = q.get("price") if q else None
        desired_value[t] = w * equity
        if px is None or px <= 0 or w <= 0:
            alloc[t] = 0
            continue
        n = int(math.floor(desired_value[t] / px))
        alloc[t] = max(0, n)
        used += alloc[t] * px

    remaining = max(0.0, equity - used)
    for _ in range(5000):
        best = None
        best_improvement = 0.0
        for t, n in alloc.items():
            q = quotes.get(t)
            px = q.get("price") if q else None
            if px is None or px <= 0 or px > remaining:
                continue
            target_value = desired_value.get(t, 0.0)
            before = abs(n * px - target_value)
            after = abs((n + 1) * px - target_value)
            improvement = before - after
            if improvement > best_improvement + 1e-9:
                best = t
                best_improvement = improvement
        if best is None:
            break
        px = quotes[best]["price"]
        alloc[best] += 1
        remaining -= px

    output = []
    for t in sorted(all_names, key=lambda x: (-econ.get(x,0.0), x)):
        r = row_map.get(t) or {
            "signal_date": model_rows[0].get("signal_date") if model_rows else None,
            "ticker": t,
            "model_target_weight": 0.0,
            "expected_active_total": None,
            "entry_ok": False,
            "resize_band": 0.0,
            "model_intent": "OUTSIDE_CURRENT_MODEL_TARGET",
            "model_change": "TARGET_A_CERO",
        }
        p = pos_by_ticker.get(t)
        cur_qty = float(p.get("quantity") or 0.0) if p else 0.0
        q = quotes.get(t, {})
        px = q.get("price")
        target_qty = alloc.get(t) if px is not None else None
        delta_qty = (target_qty - cur_qty) if target_qty is not None else None
        if delta_qty is None:
            action = "SIN_PRECIO_LOCAL"
        elif delta_qty > 0.5:
            action = "COMPRAR"
        elif delta_qty < -0.5:
            action = "VENDER"
        else:
            action = "MANTENER"
        output.append({
            **r,
            "action": action,
            "current_quantity": cur_qty,
            "target_quantity": target_qty,
            "delta_quantity": delta_qty,
            "current_weight": current_values.get(t,0.0) / equity,
            "economic_target_weight": econ.get(t,0.0),
            "local_price": px,
            "execution_symbol": q.get("symbol") or (p.get("market_symbol") if p else None),
            "quote_status": q.get("status"),
        })

    return clean({
        "status": "PASS",
        "signal_date": model_rows[0].get("signal_date") if model_rows else None,
        "portfolio_status": "READY",
        "market": market,
        "currency": currency,
        "portfolio_equity": equity,
        "cash_used_in_basis": positive_cash,
        "remaining_unallocated_cash": remaining,
        "message": "Cantidades enteras derivadas de la política económica sellada y del ledger real; no se envían órdenes.",
        "rows": output,
    })


def empty_ledger() -> dict:
    return {"schema": "ALPHA_ENGINE_PERSONAL_LEDGER_V4", "created_at": datetime.now(timezone.utc).isoformat(), "operations": []}


def load_ledger() -> dict:
    with _lock:
        ledger = load_json(LEDGER_JSON, None)
        if not isinstance(ledger, dict) or ledger.get("schema") != "ALPHA_ENGINE_PERSONAL_LEDGER_V4":
            ledger = empty_ledger()
            save_ledger(ledger)
        ledger.setdefault("operations", [])
        return ledger


def atomic_json(path: Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean(obj), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def normalize_operation(op: dict) -> dict:
    typ = str(op.get("type") or op.get("operation") or "").strip().upper()
    if typ not in {"BUY", "SELL", "DIVIDEND", "CASH_IN", "CASH_OUT"}:
        raise ValueError("INVALID_OPERATION_TYPE")
    market = str(op.get("market") or "US").strip().upper()
    if market not in {"US", "BYMA"}:
        raise ValueError("INVALID_MARKET")
    currency = str(op.get("currency") or ("ARS" if market == "BYMA" else "USD")).strip().upper()
    ticker = str(op.get("ticker") or "").strip().upper()
    symbol = str(op.get("market_symbol") or "").strip().upper()
    if typ in {"BUY", "SELL", "DIVIDEND"} and not ticker:
        raise ValueError("TICKER_REQUIRED")
    if not symbol and ticker:
        symbol = ticker if market == "US" else (ticker if ticker.endswith(".BA") else ticker + ".BA")
    qty = finite(op.get("quantity")) or 0.0
    price = finite(op.get("unit_price")) or 0.0
    fees = finite(op.get("fees")) or 0.0
    cash_amount = finite(op.get("cash_amount")) or 0.0
    if typ in {"BUY", "SELL"} and (qty <= 0 or price <= 0):
        raise ValueError("POSITIVE_QUANTITY_AND_PRICE_REQUIRED")
    if typ == "DIVIDEND" and cash_amount <= 0:
        if price > 0:
            cash_amount = price
        else:
            raise ValueError("DIVIDEND_AMOUNT_REQUIRED")
    if typ in {"CASH_IN", "CASH_OUT"} and cash_amount <= 0:
        raise ValueError("POSITIVE_CASH_AMOUNT_REQUIRED")
    dt = str(op.get("date") or "").strip()
    if not dt:
        dt = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        dt = parsed.isoformat(timespec="seconds")
    except ValueError:
        try:
            dt = datetime.combine(date.fromisoformat(dt), datetime.min.time()).isoformat(timespec="seconds")
        except ValueError as exc:
            raise ValueError("INVALID_OPERATION_DATE") from exc
    return clean({
        "id": str(op.get("id") or uuid.uuid4()),
        "date": dt,
        "type": typ,
        "market": market,
        "ticker": ticker,
        "market_symbol": symbol,
        "quantity": qty,
        "unit_price": price,
        "fees": fees,
        "currency": currency,
        "cash_amount": cash_amount,
        "note": str(op.get("note") or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def compute_book(ops: list[dict]) -> dict:
    states: dict[tuple[str, str], dict] = {}
    cash: dict[str, float] = {}
    realized: dict[str, float] = {}
    dividends: dict[str, float] = {}
    sorted_ops = sorted(ops, key=lambda o: (str(o.get("date") or ""), str(o.get("id") or "")))
    normalized = []
    for raw in sorted_ops:
        try:
            op = normalize_operation(raw)
        except Exception:
            continue
        normalized.append(op)
        cur = op["currency"]
        cash.setdefault(cur, 0.0)
        realized.setdefault(cur, 0.0)
        dividends.setdefault(cur, 0.0)
        typ = op["type"]
        if typ == "CASH_IN":
            cash[cur] += op["cash_amount"]
            continue
        if typ == "CASH_OUT":
            cash[cur] -= op["cash_amount"]
            continue
        if typ == "DIVIDEND":
            cash[cur] += op["cash_amount"]
            realized[cur] += op["cash_amount"]
            dividends[cur] += op["cash_amount"]
            continue
        key = (op["market"], op["ticker"])
        st = states.setdefault(key, {
            "market": op["market"], "ticker": op["ticker"], "market_symbol": op["market_symbol"],
            "currency": cur, "quantity": 0.0, "book_value": 0.0, "realized_pnl": 0.0,
        })
        if typ == "BUY":
            gross = op["quantity"] * op["unit_price"]
            total = gross + op["fees"]
            st["quantity"] += op["quantity"]
            st["book_value"] += total
            cash[cur] -= total
        elif typ == "SELL":
            sell_qty = min(op["quantity"], st["quantity"])
            if sell_qty <= 0:
                continue
            avg = st["book_value"] / st["quantity"] if st["quantity"] else 0.0
            proceeds = sell_qty * op["unit_price"] - op["fees"]
            basis = avg * sell_qty
            pnl = proceeds - basis
            st["quantity"] -= sell_qty
            st["book_value"] -= basis
            st["realized_pnl"] += pnl
            realized[cur] += pnl
            cash[cur] += proceeds
            if st["quantity"] <= 1e-12:
                st["quantity"] = 0.0
                st["book_value"] = 0.0
    positions = []
    for st in states.values():
        if st["quantity"] <= 1e-12:
            continue
        st = dict(st)
        st["avg_cost"] = st["book_value"] / st["quantity"] if st["quantity"] else None
        positions.append(st)
    positions.sort(key=lambda x: (x["currency"], x["ticker"]))
    return {"positions": positions, "cash": cash, "realized": realized, "dividends": dividends, "operations": normalized}


def live_portfolio() -> dict:
    ledger = load_ledger()
    book = compute_book(ledger.get("operations") or [])
    positions = []
    totals: dict[str, dict] = {}
    for p in book["positions"]:
        cur = p["currency"]
        totals.setdefault(cur, {"market_value": 0.0, "cost_basis": 0.0, "unrealized_pnl": 0.0, "realized_pnl": book["realized"].get(cur, 0.0), "dividends": book["dividends"].get(cur, 0.0), "cash": book["cash"].get(cur, 0.0)})
        q = None
        try:
            q = current_quote(p["market_symbol"])
        except Exception as exc:
            q = {"status": "MISSING", "error": str(exc), "symbol": p["market_symbol"]}
        px = finite(q.get("regular_market_price")) if isinstance(q, dict) else None
        mv = p["quantity"] * px if px is not None else None
        upnl = mv - p["book_value"] if mv is not None else None
        if mv is not None:
            totals[cur]["market_value"] += mv
            totals[cur]["cost_basis"] += p["book_value"]
            totals[cur]["unrealized_pnl"] += upnl
        positions.append(clean({**p, "live_price": px, "market_value": mv, "unrealized_pnl": upnl, "quote": q}))
    for cur, t in totals.items():
        t["total_pnl"] = t["realized_pnl"] + t["unrealized_pnl"]
        t["equity_including_cash"] = t["market_value"] + t["cash"]
    legacy = (state().get("personal") or {})
    return clean({
        "status": "PASS",
        "authority": "MANUAL_LEDGER_V4",
        "operations_count": len(book["operations"]),
        "positions": positions,
        "totals_by_currency": totals,
        "cash_by_currency": book["cash"],
        "realized_by_currency": book["realized"],
        "dividends_by_currency": book["dividends"],
        "operations": list(reversed(book["operations"][-200:])),
        "ledger_json": str(LEDGER_JSON),
        "ledger_csv": str(LEDGER_CSV),
        "excel_file": str(LEDGER_XLSX),
        "legacy_snapshot": {
            "status": legacy.get("status"),
            "source": legacy.get("source"),
            "valuation_mode": legacy.get("valuation_mode"),
            "position_rows": legacy.get("position_rows") or legacy.get("positions_count") or len(legacy.get("positions") or []),
            "positions": legacy.get("positions") or [],
            "note": "Snapshot auditado previo. No se mezcla automáticamente con el ledger V4 porque no tenemos un costo BYMA/fecha ejecutada certificado para cada posición.",
        },
    })


def xml_cell(ref: str, value, style: int = 0) -> str:
    s_attr = f' s="{style}"' if style else ""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return f'<c r="{ref}"{s_attr}><v>{value}</v></c>'
    txt = xml_escape("" if value is None else str(value))
    return f'<c r="{ref}" t="inlineStr"{s_attr}><is><t>{txt}</t></is></c>'


def col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def sheet_xml(headers: list[str], rows: list[list]) -> str:
    xml_rows = []
    for ri, vals in enumerate([headers] + rows, start=1):
        cells = "".join(xml_cell(f"{col_letter(ci)}{ri}", v, 1 if ri == 1 else 0) for ci, v in enumerate(vals, start=1))
        xml_rows.append(f'<row r="{ri}">{cells}</row>')
    dim = f"A1:{col_letter(max(1, len(headers)))}{max(1, len(rows)+1)}"
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="{dim}"/><sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15"/><sheetData>{''.join(xml_rows)}</sheetData><autoFilter ref="{dim}"/><pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>'''


def write_xlsx(operations: list[dict], positions: list[dict]):
    LEDGER_XLSX.parent.mkdir(parents=True, exist_ok=True)

    market_rows = latest_market_rows()
    fund_rows = [fundamental_compact(r) for r in fundamentals_rows()]
    v = v13_status()

    op_headers = [
        "ID", "Fecha", "Tipo", "Mercado", "Ticker", "Símbolo Yahoo",
        "Cantidad", "Precio unitario", "Costos", "Moneda", "Importe caja", "Nota"
    ]
    op_rows = [[
        o.get("id"), o.get("date"), o.get("type"), o.get("market"),
        o.get("ticker"), o.get("market_symbol"), o.get("quantity"),
        o.get("unit_price"), o.get("fees"), o.get("currency"),
        o.get("cash_amount"), o.get("note")
    ] for o in operations]

    pos_headers = [
        "Mercado", "Ticker", "Símbolo Yahoo", "Moneda", "Cantidad",
        "Costo medio", "Costo base", "P&L realizado"
    ]
    pos_rows = [[
        p.get("market"), p.get("ticker"), p.get("market_symbol"),
        p.get("currency"), p.get("quantity"), p.get("avg_cost"),
        p.get("book_value"), p.get("realized_pnl")
    ] for p in positions]

    summary_headers = ["Campo", "Valor"]
    summary_rows = [
        ["Autoridad cartera", "MANUAL_LEDGER_V4"],
        ["Archivo canónico", str(LEDGER_XLSX)],
        ["Operaciones", len(operations)],
        ["Posiciones", len(positions)],
        ["Mercado rows", len(market_rows)],
        ["Fundamentales rows", len(fund_rows)],
        ["Forward status", v.get("status")],
        ["Forward latest session", v.get("latest_completed_session")],
        ["OOS last date", v.get("oos_last_date")],
        ["V13 seal", v.get("seal_id")],
        ["LLM", "PAUSED"],
        ["Pre/Post", "DISABLED"],
        ["Generado UTC", datetime.now(timezone.utc).isoformat()],
        ["Nota", "Analizador_Financiero_Automatico_* es legado y no es la autoridad de esta V4."],
    ]

    market_headers = [
        "Ticker", "Yahoo Symbol", "Benchmark", "Precio", "Var 1D",
        "Ret 1M", "Ret 3M", "Ret 6M", "Ret 12M", "RSI14",
        "Vol 20D", "Beta 6M", "Max Drawdown 1A", "Cobertura",
        "Fuente", "Actualización"
    ]
    market_rows_x = [[
        r.get("ticker"), r.get("market_symbol"), r.get("benchmark"),
        r.get("price"), r.get("var_1d"), r.get("ret_1m"), r.get("ret_3m"),
        r.get("ret_6m"), r.get("ret_12m"), r.get("rsi14"),
        r.get("vol_20d"), r.get("beta_6m"), r.get("max_drawdown_1y"),
        r.get("coverage"), r.get("source"), r.get("updated_at")
    ] for r in market_rows]

    fund_headers = [
        "Ticker", "Nombre", "Sector", "Industria", "Precio", "Market Cap",
        "P/E", "Fwd P/E", "P/B", "EV/EBITDA", "ROE", "ROA",
        "Debt/Equity", "Margen Neto", "Revenue Growth", "EPS Growth",
        "FCF Yield", "Fuente", "Actualización"
    ]
    fund_rows_x = [[
        r.get("ticker"), r.get("name"), r.get("sector"), r.get("industry"),
        r.get("price"), r.get("market_cap"), r.get("pe"), r.get("forward_pe"),
        r.get("price_book"), r.get("ev_ebitda"), r.get("roe"), r.get("roa"),
        r.get("debt_to_equity"), r.get("profit_margin"),
        r.get("revenue_growth"), r.get("eps_growth"), r.get("fcf_yield"),
        r.get("source"), r.get("updated_at")
    ] for r in fund_rows]

    forward_headers = [
        "Signal Date", "Ticker", "Target Weight", "Expected Active Total",
        "Expected Active / Session", "Effective Horizon Sessions",
        "Entry OK", "Model Intent"
    ]
    forward_rows = [[
        r.get("signal_date"), r.get("ticker"), r.get("target_weight"),
        r.get("expected_active_total"), r.get("expected_active_per_session"),
        r.get("effective_horizon_sessions"), r.get("entry_ok"),
        r.get("model_intent")
    ] for r in (v.get("targets") or [])]


    rec_headers = [
        "Signal Date", "Ticker", "Cambio Modelo", "Target Weight",
        "Target Previo", "Delta Target", "Entry OK", "Expected Active Total",
        "Horizonte Efectivo", "Acción Personal", "Cantidad Actual",
        "Cantidad Objetivo", "Delta Nominal", "Precio Ejecución", "Símbolo"
    ]
    try:
        rec = recommendations()
        rec_rows = [[
            r.get("signal_date"), r.get("ticker"), r.get("model_change"),
            r.get("model_target_weight"), r.get("previous_target_weight"),
            r.get("target_delta_weight"), r.get("entry_ok"),
            r.get("expected_active_total"), r.get("effective_horizon_sessions"),
            r.get("action"), r.get("current_quantity"), r.get("target_quantity"),
            r.get("delta_quantity"), r.get("local_price"), r.get("execution_symbol")
        ] for r in (rec.get("rows") or [])]
    except Exception as exc:
        rec_rows = [["ERROR", str(exc), "", "", "", "", "", "", "", "", "", "", "", "", ""]]

    sheets = [
        ("Operaciones", op_headers, op_rows),
        ("Posiciones", pos_headers, pos_rows),
        ("Resumen", summary_headers, summary_rows),
        ("Mercado", market_headers, market_rows_x),
        ("Fundamentales", fund_headers, fund_rows_x),
        ("Forward", forward_headers, forward_rows),
        ("Recomendaciones", rec_headers, rec_rows),
    ]

    tmp = LEDGER_XLSX.with_suffix(".xlsx.tmp")
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + overrides +
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    sheet_nodes = "".join(
        f'<sheet name="{xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, (name, _, _) in enumerate(sheets, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{sheet_nodes}</sheets></workbook>'
    )
    wb_rels_nodes = "".join(
        f'<Relationship Id="rId{i}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + wb_rels_nodes +
        f'<Relationship Id="rId{len(sheets)+1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Aptos"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF083B31"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
        '</styleSheet>'
    )

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", styles)
        for i, (_, headers, rows) in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(headers, rows))
    try:
        os.replace(tmp, LEDGER_XLSX)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("EXCEL_FILE_IS_OPEN_CLOSE_AND_RETRY")


def save_ledger(ledger: dict):
    with _lock:
        LEDGER_JSON.parent.mkdir(parents=True, exist_ok=True)
        ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_json(LEDGER_JSON, ledger)
        ops = []
        for raw in ledger.get("operations") or []:
            try:
                ops.append(normalize_operation(raw))
            except Exception:
                continue
        with LEDGER_CSV.open("w", encoding="utf-8-sig", newline="") as f:
            headers = ["id", "date", "type", "market", "ticker", "market_symbol", "quantity", "unit_price", "fees", "currency", "cash_amount", "note", "created_at"]
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            for op in ops:
                w.writerow({h: op.get(h) for h in headers})
        book = compute_book(ops)
        try:
            write_xlsx(book["operations"], book["positions"])
            ledger["excel_status"] = "PASS"
        except Exception as exc:
            ledger["excel_status"] = "WARN"
            ledger["excel_error"] = str(exc)
        # Persist Excel status without recursion.
        atomic_json(LEDGER_JSON, ledger)


def add_operation(payload: dict) -> dict:
    op = normalize_operation(payload)
    ledger = load_ledger()
    ledger["operations"].append(op)
    save_ledger(ledger)
    return {"status": "PASS", "operation": op, "portfolio": live_portfolio()}


def delete_operation(op_id: str) -> dict:
    ledger = load_ledger()
    before = len(ledger.get("operations") or [])
    ledger["operations"] = [o for o in ledger.get("operations") or [] if str(o.get("id")) != op_id]
    if len(ledger["operations"]) == before:
        raise ValueError("OPERATION_NOT_FOUND")
    save_ledger(ledger)
    return {"status": "PASS", "deleted_id": op_id, "portfolio": live_portfolio()}


def portfolio_history() -> dict:
    ledger = load_ledger()
    ops = []
    for raw in ledger.get("operations") or []:
        try:
            ops.append(normalize_operation(raw))
        except Exception:
            pass
    if not ops:
        return {"status": "PASS", "series": {}, "note": "Cargá una operación para iniciar el P&L histórico."}
    ops.sort(key=lambda o: o["date"])
    earliest = ops[0]["date"][:10]
    years = max(1.0, (date.today() - date.fromisoformat(earliest)).days / 365.25)
    range_ = "10y" if years > 5 else "5y" if years > 2 else "2y" if years > 1 else "1y"
    symbols = sorted({o["market_symbol"] for o in ops if o.get("market_symbol") and o["type"] in {"BUY", "SELL"}})
    price_maps: dict[str, dict[str, float]] = {}
    all_dates: set[str] = set()
    errors = {}
    for symbol in symbols:
        try:
            rows = history_for(symbol, range_)
            pm = {r["date"]: r["close"] for r in rows if r["date"] >= earliest}
            price_maps[symbol] = pm
            all_dates.update(pm)
        except Exception as exc:
            errors[symbol] = str(exc)
    for o in ops:
        all_dates.add(o["date"][:10])
    dates = sorted(d for d in all_dates if d >= earliest)
    state_by_key = {}
    realized_by_cur = {}
    series = {}
    op_index = 0
    sorted_ops = ops
    last_prices: dict[str, float] = {}
    for d in dates:
        while op_index < len(sorted_ops) and sorted_ops[op_index]["date"][:10] <= d:
            o = sorted_ops[op_index]
            cur = o["currency"]
            realized_by_cur.setdefault(cur, 0.0)
            if o["type"] == "DIVIDEND":
                realized_by_cur[cur] += o["cash_amount"]
            elif o["type"] in {"BUY", "SELL"}:
                key = (o["market"], o["ticker"])
                st = state_by_key.setdefault(key, {"quantity": 0.0, "book": 0.0, "currency": cur, "symbol": o["market_symbol"]})
                if o["type"] == "BUY":
                    st["quantity"] += o["quantity"]
                    st["book"] += o["quantity"] * o["unit_price"] + o["fees"]
                else:
                    sell_qty = min(o["quantity"], st["quantity"])
                    if sell_qty > 0:
                        avg = st["book"] / st["quantity"] if st["quantity"] else 0.0
                        proceeds = sell_qty * o["unit_price"] - o["fees"]
                        basis = avg * sell_qty
                        realized_by_cur[cur] += proceeds - basis
                        st["quantity"] -= sell_qty
                        st["book"] -= basis
            op_index += 1
        for symbol, pm in price_maps.items():
            if d in pm:
                last_prices[symbol] = pm[d]
        by_cur = {}
        for st in state_by_key.values():
            cur = st["currency"]
            row = by_cur.setdefault(cur, {"market_value": 0.0, "cost_basis": 0.0, "unrealized": 0.0})
            px = last_prices.get(st["symbol"])
            if st["quantity"] > 0 and px is not None:
                mv = st["quantity"] * px
                row["market_value"] += mv
                row["cost_basis"] += st["book"]
                row["unrealized"] += mv - st["book"]
        for cur in set(realized_by_cur) | set(by_cur):
            r = by_cur.get(cur, {"market_value": 0.0, "cost_basis": 0.0, "unrealized": 0.0})
            pnl = realized_by_cur.get(cur, 0.0) + r["unrealized"]
            series.setdefault(cur, []).append({
                "date": d,
                "pnl": pnl,
                "realized": realized_by_cur.get(cur, 0.0),
                "unrealized": r["unrealized"],
                "market_value": r["market_value"],
                "cost_basis": r["cost_basis"],
            })
    return clean({"status": "PASS", "series": series, "errors": errors, "earliest_operation": earliest, "regular_session_only": True})


def safe_run(cmd: list[str], cwd: Path, timeout: int) -> dict:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, shell=False)
    return {"returncode": proc.returncode, "stdout": proc.stdout[-20000:], "stderr": proc.stderr[-12000:]}


def discover_forward_runner() -> tuple[str, list[str]] | None:
    candidates = [
        V13 / "RUN_V13_PHASE5B_LIVE_SHADOW.ps1",
        V13 / "scripts" / "run_v13_phase5b.py",
    ]
    for p in candidates:
        if p.exists():
            if p.suffix.lower() == ".ps1":
                return str(p), ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)]
            return str(p), [os.sys.executable, str(p)]
    for p in sorted(V13.glob("RUN_V13_PHASE5B*.ps1")):
        return str(p), ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)]
    for p in sorted((V13 / "scripts").glob("*phase5b*.py")) if (V13 / "scripts").exists() else []:
        return str(p), [os.sys.executable, str(p)]
    return None


def _set_forward_job(**changes):
    with _forward_job_lock:
        _forward_job.update(changes)
        return dict(_forward_job)


def forward_job_status() -> dict:
    with _forward_job_lock:
        j = dict(_forward_job)
    try:
        current = v13_status().get("latest_completed_session")
    except Exception:
        current = None
    try:
        target = latest_completed_us_session()
    except Exception as exc:
        target = None
        j["market_session_error"] = str(exc)
    j["current_model_session"] = current
    j["latest_completed_market_session"] = target
    j["stale"] = bool(target and (not current or str(current) < str(target)))
    return clean(j)


def _forward_worker(path: str, cmd: list[str]):
    _set_forward_job(
        status="RUNNING",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        runner=path,
        error=None,
        returncode=None,
        stdout_tail="",
        stderr_tail="",
    )
    try:
        before = v13_status()
        result = safe_run(cmd, V13, 1200)
        after = v13_status()
        status = (
            "PASS"
            if result["returncode"] == 0 and after.get("status") == "PASS"
            else "FAIL"
        )
        err = None
        if status != "PASS":
            err = (
                f"FORWARD_RUNNER_FAILED returncode={result['returncode']} "
                f"stderr={result.get('stderr','')[-3000:]}"
            )
        nav_result = None
        if status == "PASS":
            try:
                nav_result = build_forward_nav()
                if nav_result.get("status") != "PASS":
                    status = "FAIL"
                    err = "FORWARD_NAV_BUILD_FAILED: " + str(nav_result.get("console"))[-2500:]
            except Exception as exc:
                status = "FAIL"
                err = f"FORWARD_NAV_BUILD_EXCEPTION: {exc}"
        _set_forward_job(
            status=status,
            finished_at=datetime.now(timezone.utc).isoformat(),
            returncode=result["returncode"],
            stdout_tail=result.get("stdout", "")[-12000:],
            stderr_tail=result.get("stderr", "")[-6000:],
            error=err,
            before_session=before.get("latest_completed_session"),
            after_session=after.get("latest_completed_session"),
            forward_nav_status=(nav_result or {}).get("status"),
        )
        try:
            save_ledger(load_ledger())
        except Exception:
            pass
    except Exception as exc:
        _set_forward_job(
            status="FAIL",
            finished_at=datetime.now(timezone.utc).isoformat(),
            error=str(exc),
        )
    finally:
        try:
            _forward_lock.release()
        except RuntimeError:
            pass


def start_forward_refresh(force: bool = False) -> dict:
    status = forward_job_status()
    if status.get("status") == "RUNNING":
        return {"status": "BUSY", "job": status}
    if not force and status.get("stale") is False:
        return {"status": "UP_TO_DATE", "job": status}
    found = discover_forward_runner()
    if not found:
        return {
            "status": "NOT_AVAILABLE",
            "message": "No se encontró el runner sellado Phase 5B.",
            "job": status,
        }
    if not _forward_lock.acquire(blocking=False):
        return {"status": "BUSY", "job": forward_job_status()}
    path, cmd = found
    t = threading.Thread(
        target=_forward_worker,
        args=(path, cmd),
        daemon=True,
        name="alpha-forward-refresh",
    )
    t.start()
    time.sleep(0.05)
    return {"status": "ACCEPTED", "job": forward_job_status()}


def _forward_scheduler():
    # Daily model: keep Phase 5B caught up to the latest COMPLETED US session.
    # This does not tune/retrain the sealed V13 core and never sends real orders.
    while True:
        try:
            j = forward_job_status()
            if j.get("stale") and j.get("status") != "RUNNING":
                start_forward_refresh(force=False)
        except Exception:
            pass
        time.sleep(300)


def _set_market_job(**changes):
    with _market_job_lock:
        _market_job.update(changes)
        return dict(_market_job)


def market_job_status() -> dict:
    with _market_job_lock:
        j = dict(_market_job)
    try:
        q = current_quote("SPY")
        j["market_state"] = q.get("market_state")
        j["spy_market_time"] = q.get("market_time")
        j["latest_completed_session"] = latest_completed_us_session()
    except Exception as exc:
        j["market_probe_error"] = str(exc)
    j["refresh_every_seconds"] = 300
    j["regular_session_only"] = True
    return clean(j)


def build_forward_nav() -> dict:
    if not FORWARD_NAV_BUILDER.exists():
        return {"status": "NOT_AVAILABLE", "message": str(FORWARD_NAV_BUILDER)}
    result = safe_run([os.sys.executable, str(FORWARD_NAV_BUILDER)], ROOT, 900)
    payload = load_json(FORWARD_NAV_JSON, {}) or {}
    status = "PASS" if result["returncode"] == 0 and payload.get("status") == "PASS" else "FAIL"
    return {
        "status": status,
        "payload": payload if status == "PASS" else None,
        "console": result,
    }


def _market_scheduler():
    # Full 200-name DR1 refresh every 5 minutes only during REGULAR US session.
    # Outside regular hours, perform one catch-up if the stored market date is
    # older than the latest completed US session.
    while True:
        try:
            q = current_quote("SPY")
            state_ = str(q.get("market_state") or "").upper()
            latest = latest_completed_us_session()
            rows = latest_market_rows()
            asof = market_asof(rows)
            data_date = str(asof)[:10] if asof else None
            now = time.time()
            with _market_job_lock:
                last_pass = _market_job.get("_last_pass_epoch") or 0.0

            should = False
            if state_ == "REGULAR":
                should = (now - float(last_pass)) >= 300
            elif latest and (not data_date or data_date < latest):
                should = True

            if should:
                _set_market_job(
                    status="RUNNING",
                    started_at=datetime.now(timezone.utc).isoformat(),
                    error=None,
                )
                result = refresh_market()
                if result.get("status") == "PASS":
                    _set_market_job(
                        status="PASS",
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        last_pass_at=datetime.now(timezone.utc).isoformat(),
                        _last_pass_epoch=time.time(),
                        rows=result.get("rows"),
                        critical_rows=result.get("critical_rows"),
                        asof=result.get("asof"),
                        error=None,
                    )
                elif result.get("status") != "BUSY":
                    _set_market_job(
                        status="FAIL",
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        error=(result.get("message") or str(result.get("console"))[-2000:]),
                    )
        except Exception as exc:
            _set_market_job(
                status="WARN",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error=str(exc),
            )
        time.sleep(60)


def refresh_market() -> dict:
    if not _market_refresh_lock.acquire(blocking=False):
        return {"status": "BUSY"}
    try:
        script = REC / "scripts" / "run_dr1f_market_refresh.py"
        if not script.exists():
            return {"status": "NOT_AVAILABLE", "message": str(script)}
        result = safe_run([os.sys.executable, str(script), "--market-workers", "6"], ROOT, 600)
        rows = latest_market_rows()
        good = sum(
            1 for r in rows
            if r.get("ticker") and finite(r.get("price")) is not None
            and finite(r.get("var_1d")) is not None
        )
        status = "PASS" if result["returncode"] == 0 and len(rows) == 200 and good >= 190 else "FAIL"
        if status == "PASS":
            try:
                save_ledger(load_ledger())
            except Exception:
                pass
        sample = next((r for r in rows if r.get("ticker") == "NKE"), None)
        return {
            "status": status,
            "rows": len(rows),
            "critical_rows": good,
            "asof": market_asof(rows),
            "sample_nke": sample,
            "console": result,
        }
    finally:
        _market_refresh_lock.release()


def summary() -> dict:
    s = state()
    v = v13_status()
    m = latest_market_rows()
    f = fundamentals_rows()
    personal = live_portfolio()
    return clean({
        "status": "PASS",
        "version": "ALPHA_ENGINE_WEB_V4_2_AUTOMATED",
        "llm": {"status": "PAUSED", "reason": "Core product is deterministic; manual ledger is authoritative."},
        "system": s.get("system") or {},
        "v13": {k: v.get(k) for k in ["status", "seal_id", "holdout_verdict", "oos_last_date", "latest_completed_session", "entry_eligible", "positive_targets", "universe", "shadow_only", "real_orders_sent", "tuning_performed"]},
        "market": {"rows": len(m), "asof": market_asof(m), "source": "ALPHA_ENGINE_DATA_RECOVERY_V1", "prepost": False, "auto_refresh": market_job_status()},
        "fundamentals": {"rows": len(f), "asof": (s.get("fundamentals") or {}).get("asof"), "source": "Data Recovery V1"},
        "portfolio": {"operations": personal.get("operations_count"), "positions": len(personal.get("positions") or []), "excel_file": str(LEDGER_XLSX), "legacy_positions": (personal.get("legacy_snapshot") or {}).get("position_rows")},
        "forward_nav": {k: forward_nav_status().get(k) for k in ["status","start_date","latest_date","metrics","holdout_parity"]},
    })


def ensure_storage():
    PRODUCT.mkdir(parents=True, exist_ok=True)
    PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not LEDGER_JSON.exists():
        save_ledger(empty_ledger())
    else:
        ledger = load_json(LEDGER_JSON, {}) or {}
        if ledger.get("schema") == "ALPHA_ENGINE_PERSONAL_LEDGER_V4":
            save_ledger(ledger)


class Handler(BaseHTTPRequestHandler):
    server_version = "AlphaEngineV4/1.2"

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().isoformat(timespec='seconds')}] {self.client_address[0]} {fmt % args}", flush=True)

    def send_bytes(self, data: bytes, mime: str, status=200, cache="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj, status=200):
        data = json.dumps(clean(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_bytes(data, "application/json; charset=utf-8", status)

    def body_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0 or n > 2_000_000:
            raise ValueError("INVALID_BODY_SIZE")
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def serve_static(self, path: str):
        rel = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
        target = (WEB / rel).resolve()
        if WEB.resolve() not in target.parents and target != WEB.resolve():
            self.send_error(403); return
        if not target.exists() or not target.is_file():
            self.send_error(404); return
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_bytes(target.read_bytes(), mime + ("; charset=utf-8" if mime.startswith("text/") or mime in {"application/javascript", "application/json"} else ""), cache="no-cache")

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(p.query)
        try:
            if p.path == "/api/v4/health":
                return self.send_json({"status": "PASS", "version": "V4.2", "llm": "PAUSED", "time": datetime.now(timezone.utc).isoformat()})
            if p.path == "/api/v4/summary":
                return self.send_json(summary())
            if p.path == "/api/v4/v13":
                return self.send_json(v13_status())
            if p.path == "/api/v4/performance":
                return self.send_json(nav_history())
            if p.path == "/api/v4/pulse":
                return self.send_json(market_pulse())
            if p.path == "/api/v4/market/job":
                return self.send_json(market_job_status())
            if p.path == "/api/v4/recommendations":
                return self.send_json(recommendations())
            if p.path == "/api/v4/forward/nav":
                return self.send_json(forward_nav_status())
            if p.path == "/api/v4/forward/job":
                return self.send_json(forward_job_status())
            if p.path == "/api/v4/market":
                rows = latest_market_rows()
                q = (qs.get("q", [""])[0] or "").strip().upper()
                if q:
                    rows = [r for r in rows if q in str(r.get("ticker") or "").upper() or q in str(r.get("market_symbol") or "").upper()]
                return self.send_json({"status": "PASS", "rows": rows, "count": len(rows), "prepost": False})
            if p.path == "/api/v4/fundamentals":
                rows = [fundamental_compact(r) for r in fundamentals_rows()]
                q = (qs.get("q", [""])[0] or "").strip().lower()
                sector = (qs.get("sector", [""])[0] or "").strip().lower()
                if q:
                    rows = [r for r in rows if q in " ".join(str(r.get(k) or "") for k in ["ticker", "name", "sector", "industry"]).lower()]
                if sector:
                    rows = [r for r in rows if str(r.get("sector") or "").lower() == sector]
                sectors = sorted({str(r.get("sector")) for r in rows if r.get("sector")})
                return self.send_json({"status": "PASS", "rows": rows, "count": len(rows), "sectors": sectors})
            if p.path == "/api/v4/portfolio":
                return self.send_json(live_portfolio())
            if p.path == "/api/v4/portfolio/history":
                return self.send_json(portfolio_history())
            if p.path == "/api/v4/quote":
                market = (qs.get("market", ["US"])[0] or "US").upper()
                ticker = (qs.get("ticker", [""])[0] or "").upper().strip()
                symbol = (qs.get("symbol", [""])[0] or "").upper().strip()
                if not symbol:
                    symbol = ticker if market == "US" else (ticker if ticker.endswith(".BA") else ticker + ".BA")
                if not symbol:
                    raise ValueError("SYMBOL_REQUIRED")
                return self.send_json(current_quote(symbol))
            return self.serve_static(p.path)
        except Exception as exc:
            return self.send_json({"status": "FAIL", "error": str(exc)}, 500)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path)
        try:
            payload = self.body_json() if int(self.headers.get("Content-Length", "0") or 0) > 0 else {}
            if p.path == "/api/v4/portfolio/operation":
                return self.send_json(add_operation(payload))
            if p.path == "/api/v4/portfolio/delete":
                return self.send_json(delete_operation(str(payload.get("id") or "")))
            if p.path == "/api/v4/forward/refresh":
                return self.send_json(start_forward_refresh(force=bool(payload.get("force"))))
            if p.path == "/api/v4/market/refresh":
                return self.send_json(refresh_market())
            self.send_error(404)
        except ValueError as exc:
            return self.send_json({"status": "FAIL", "error": str(exc)}, 400)
        except Exception as exc:
            return self.send_json({"status": "FAIL", "error": str(exc)}, 500)


def main():
    ensure_storage()
    s = summary()
    if s.get("status") != "PASS":
        raise SystemExit("PREFLIGHT_NOT_PASS")
    print("=" * 72)
    print("ALPHA ENGINE V4 - FINAL CONTROL CENTER")
    print("=" * 72)
    print(f"WEB:            http://{HOST}:{PORT}/")
    print(f"V13:            {s['v13'].get('status')} / {s['v13'].get('holdout_verdict')}")
    print(f"MARKET:         {s['market']['rows']} rows / regular session only")
    print(f"FUNDAMENTALS:   {s['fundamentals']['rows']} rows")
    print("LLM:            PAUSED")
    print(f"LEDGER:         {LEDGER_JSON}")
    print(f"EXCEL MIRROR:   {LEDGER_XLSX}")
    print("V13 MUTATION:   NO")
    print("=" * 72, flush=True)
    threading.Thread(
        target=_forward_scheduler,
        daemon=True,
        name="alpha-forward-scheduler",
    ).start()
    threading.Thread(
        target=_market_scheduler,
        daemon=True,
        name="alpha-market-scheduler",
    ).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
