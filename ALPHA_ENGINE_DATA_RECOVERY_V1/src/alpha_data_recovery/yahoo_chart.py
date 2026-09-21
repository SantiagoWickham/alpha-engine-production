from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .contracts import AuditValue, MarketSnapshot
from .market_metrics import compute_market_metrics


BASES = (
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/153 Safari/537.36"
)
SOURCE = "Yahoo Finance chart v8"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finite(x: Any) -> float | None:
    try:
        y = float(x)
    except (TypeError, ValueError):
        return None
    return y if math.isfinite(y) else None


def _iso_epoch(x: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(x), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def fetch_chart(symbol: str, range_: str = "2y", interval: str = "1d") -> tuple[dict[str, Any], str]:
    last_error: Exception | None = None
    encoded = quote(symbol, safe="")
    query = (
        f"/v8/finance/chart/{encoded}"
        f"?range={range_}&interval={interval}"
        "&events=history&includeAdjustedClose=true&includePrePost=false"
    )

    for idx, base in enumerate(BASES):
        for attempt in range(3):
            try:
                req = Request(
                    base + query,
                    headers={
                        "User-Agent": UA,
                        "Accept": "application/json,text/plain,*/*",
                    },
                )
                with urlopen(req, timeout=20) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}")
                    payload = json.loads(resp.read().decode("utf-8"))
                error = ((payload.get("chart") or {}).get("error"))
                if error:
                    raise RuntimeError(str(error))
                result = (((payload.get("chart") or {}).get("result")) or [])
                if not result:
                    raise RuntimeError("Yahoo chart returned no result")
                fallback = "none" if idx == 0 else "query2"
                return result[0], fallback
            except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
                last_error = exc
                time.sleep(0.35 * (attempt + 1))
    raise RuntimeError(f"Yahoo chart failed for {symbol}: {last_error}")


def _extract_ohlcv(result: dict[str, Any]) -> list[dict[str, Any]]:
    ts = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote_block = ((indicators.get("quote") or [{}])[0]) or {}
    adj_block = ((indicators.get("adjclose") or [{}])[0]) or {}

    opens = quote_block.get("open") or []
    highs = quote_block.get("high") or []
    lows = quote_block.get("low") or []
    closes = quote_block.get("close") or []
    volumes = quote_block.get("volume") or []
    adjusted = adj_block.get("adjclose") or []

    rows: list[dict[str, Any]] = []
    for i, epoch in enumerate(ts):
        close = _finite(closes[i]) if i < len(closes) else None
        adj = _finite(adjusted[i]) if i < len(adjusted) else close
        if close is None and adj is None:
            continue
        rows.append(
            {
                "timestamp": _iso_epoch(epoch),
                "epoch": int(epoch),
                "open": _finite(opens[i]) if i < len(opens) else None,
                "high": _finite(highs[i]) if i < len(highs) else None,
                "low": _finite(lows[i]) if i < len(lows) else None,
                "close": close,
                "adj_close": adj,
                "volume": _finite(volumes[i]) if i < len(volumes) else None,
            }
        )
    return rows


def _previous_session_close(rows: list[dict[str, Any]]) -> tuple[float | None, str | None]:
    """Return the immediately preceding daily raw close.

    IMPORTANT:
    Yahoo `meta.chartPreviousClose` is deliberately NOT used here.
    With long chart ranges it may refer to the close preceding the beginning
    of the requested range, not the previous trading session.
    """
    closes = [
        (r.get("close"), r.get("timestamp"))
        for r in rows
        if _finite(r.get("close")) is not None
    ]
    if len(closes) < 2:
        return None, None
    return float(closes[-2][0]), closes[-2][1]


def recover_market(ticker: str, market_symbol: str | None = None) -> tuple[MarketSnapshot, list[dict[str, Any]]]:
    symbol = (market_symbol or ticker).strip().upper()
    retrieved = _now_iso()
    result, fallback = fetch_chart(symbol)
    meta = result.get("meta") or {}

    resolved_symbol = str(meta.get("symbol") or "").upper()
    if resolved_symbol and resolved_symbol != symbol:
        raise RuntimeError(
            f"Ticker mapping mismatch: requested={symbol} resolved={resolved_symbol}"
        )

    rows = _extract_ohlcv(result)
    raw_closes = [float(r["close"]) for r in rows if _finite(r.get("close")) is not None]
    adj_closes = [float(r["adj_close"]) for r in rows if _finite(r.get("adj_close")) is not None]
    volumes = [float(r["volume"]) for r in rows if _finite(r.get("volume")) is not None]

    price = _finite(meta.get("regularMarketPrice"))
    price_fallback = fallback
    if price is None and raw_closes:
        price = raw_closes[-1]
        price_fallback = "latest_daily_bar"

    previous_close, previous_close_asof = _previous_session_close(rows)

    # Yahoo diagnostic values are retained ONLY for audit; never for Var 1D.
    meta_regular_previous_close = _finite(meta.get("regularMarketPreviousClose"))
    meta_chart_previous_close = _finite(meta.get("chartPreviousClose"))

    var_1d = (
        price / previous_close - 1.0
        if price is not None and previous_close is not None and previous_close > 0
        else None
    )

    latest_daily_close = raw_closes[-1] if raw_closes else None
    latest_daily_asof = rows[-1]["timestamp"] if rows else None
    market_asof = _iso_epoch(meta.get("regularMarketTime")) or latest_daily_asof

    age_hours = None
    if market_asof:
        dt = datetime.fromisoformat(market_asof)
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0

    latest_bar_gap = (
        price / latest_daily_close - 1.0
        if price is not None and latest_daily_close not in (None, 0)
        else None
    )

    status = "OK"
    detail_parts: list[str] = []

    if price is None or previous_close is None:
        status = "MISSING"
        detail_parts.append("price or previous session close unavailable")
    elif price <= 0 or previous_close <= 0:
        status = "INVALID"
        detail_parts.append("non-positive price")
    else:
        # A huge move can be real, but it must be quarantined before publication.
        if abs(var_1d or 0.0) > 0.35:
            status = "QUARANTINE"
            detail_parts.append("absolute 1D move >35%; corporate action/mapping review required")
        elif abs(var_1d or 0.0) > 0.20:
            status = "WARN"
            detail_parts.append("absolute 1D move >20%; review required")

        if age_hours is not None and age_hours > 120:
            if status == "OK":
                status = "STALE"
            detail_parts.append(f"market timestamp age={age_hours:.1f}h")

    # Detect the exact bug fixed in DR1-A FIX1.
    if (
        meta_chart_previous_close is not None
        and previous_close is not None
        and previous_close > 0
        and abs(meta_chart_previous_close / previous_close - 1.0) > 0.05
    ):
        detail_parts.append(
            "Yahoo meta.chartPreviousClose rejected: not comparable with prior daily close"
        )

    detail = " | ".join(detail_parts)

    fields = {
        "price": AuditValue(
            price, SOURCE, market_asof, status, price_fallback, detail
        ),
        "previous_close": AuditValue(
            previous_close,
            f"{SOURCE} OHLCV daily bar",
            previous_close_asof,
            "OK" if previous_close is not None else "MISSING",
            fallback,
            "Immediately preceding raw daily close.",
        ),
        "var_1d": AuditValue(
            var_1d,
            "derived: price / previous_session_close - 1",
            market_asof,
            status,
            "none",
            detail,
        ),
        "latest_daily_close": AuditValue(
            latest_daily_close,
            f"{SOURCE} OHLCV daily bar",
            latest_daily_asof,
            "OK" if latest_daily_close is not None else "MISSING",
            fallback,
        ),
        "latest_bar_gap": AuditValue(
            latest_bar_gap,
            "derived: live price vs latest daily bar",
            market_asof,
            "OK" if latest_bar_gap is not None else "MISSING",
            "none",
        ),
        "meta_regular_previous_close": AuditValue(
            meta_regular_previous_close,
            f"{SOURCE} meta",
            market_asof,
            "DIAGNOSTIC_ONLY",
            "none",
            "Not trusted for Var 1D.",
        ),
        "meta_chart_previous_close": AuditValue(
            meta_chart_previous_close,
            f"{SOURCE} meta",
            market_asof,
            "DIAGNOSTIC_ONLY",
            "none",
            "Never used for Var 1D; range-dependent semantic.",
        ),
        "market_data_age_hours": AuditValue(
            age_hours,
            SOURCE,
            market_asof,
            "OK" if age_hours is not None else "MISSING",
            fallback,
        ),
    }

    raw_metrics = compute_market_metrics(adj_closes, raw_closes, volumes)
    metrics: dict[str, AuditValue] = {}
    history_asof = latest_daily_asof
    for name, value in raw_metrics.items():
        metric_status = "OK" if value is not None else "MISSING"
        metrics[name] = AuditValue(
            value=value,
            source=f"{SOURCE} OHLCV 2Y",
            asof=history_asof,
            status=metric_status,
            fallback=fallback,
        )

    required = [
        fields["price"],
        fields["previous_close"],
        fields["var_1d"],
        metrics["ret_1m"],
        metrics["vol_60d"],
        metrics["max_drawdown_1y"],
    ]
    coverage = sum(x.value is not None for x in required) / len(required)

    overall = status
    snapshot = MarketSnapshot(
        ticker=ticker.upper(),
        market_symbol=symbol,
        retrieved_at=retrieved,
        currency=meta.get("currency"),
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName"),
        market_state=meta.get("marketState"),
        fields=fields,
        metrics=metrics,
        coverage=coverage,
        overall_status=overall,
    )
    return snapshot, rows
