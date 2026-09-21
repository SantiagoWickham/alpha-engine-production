from __future__ import annotations

import math
import statistics
from typing import Iterable


def _valid(values: Iterable[float | None]) -> list[float]:
    out = []
    for value in values:
        if value is None:
            continue
        try:
            x = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):
            out.append(x)
    return out


def returns(prices: list[float]) -> list[float]:
    out: list[float] = []
    for a, b in zip(prices[:-1], prices[1:]):
        if a > 0:
            out.append(b / a - 1.0)
    return out


def ret_n(prices: list[float], n: int) -> float | None:
    if len(prices) <= n or prices[-1] <= 0 or prices[-1 - n] <= 0:
        return None
    return prices[-1] / prices[-1 - n] - 1.0


def stdev(values: list[float]) -> float | None:
    return statistics.stdev(values) if len(values) >= 2 else None


def annualized_vol(rets: list[float], n: int) -> float | None:
    x = rets[-n:]
    s = stdev(x)
    return s * math.sqrt(252.0) if s is not None else None


def downside_vol(rets: list[float], n: int) -> float | None:
    x = [r for r in rets[-n:] if r < 0]
    if len(x) < 2:
        return None
    return statistics.stdev(x) * math.sqrt(252.0)


def max_drawdown(prices: list[float], n: int = 252) -> float | None:
    x = prices[-n:]
    if not x:
        return None
    peak = x[0]
    worst = 0.0
    for p in x:
        peak = max(peak, p)
        if peak > 0:
            worst = min(worst, p / peak - 1.0)
    return worst


def sma(prices: list[float], n: int) -> float | None:
    if len(prices) < n:
        return None
    return sum(prices[-n:]) / n


def rsi(prices: list[float], n: int = 14) -> float | None:
    if len(prices) <= n:
        return None
    d = [b - a for a, b in zip(prices[-n-1:-1], prices[-n:])]
    gains = [max(x, 0.0) for x in d]
    losses = [max(-x, 0.0) for x in d]
    avg_gain = sum(gains) / n
    avg_loss = sum(losses) / n
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def compute_market_metrics(
    adjusted_closes: list[float],
    raw_closes: list[float],
    volumes: list[float],
) -> dict[str, float | None]:
    p = _valid(adjusted_closes)
    raw = _valid(raw_closes)
    v = _valid(volumes)
    rets = returns(p)

    last_raw = raw[-1] if raw else None
    prev_raw = raw[-2] if len(raw) >= 2 else None
    close_to_close = (
        last_raw / prev_raw - 1.0
        if last_raw is not None and prev_raw is not None and prev_raw > 0
        else None
    )

    dv20 = None
    if raw and v:
        pairs = list(zip(raw[-20:], v[-20:]))
        if pairs:
            dv20 = sum(px * vol for px, vol in pairs) / len(pairs)

    vol20 = sum(v[-20:]) / min(20, len(v)) if v else None
    vol60 = sum(v[-60:]) / min(60, len(v)) if v else None
    relvol = (vol20 / vol60) if vol20 is not None and vol60 not in (None, 0) else None

    return {
        "close_to_close_1d": close_to_close,
        "ret_1m": ret_n(p, 21),
        "ret_3m": ret_n(p, 63),
        "ret_6m": ret_n(p, 126),
        "ret_12m": ret_n(p, 252),
        "sma_20": sma(p, 20),
        "sma_50": sma(p, 50),
        "sma_200": sma(p, 200),
        "rsi_14": rsi(p, 14),
        "vol_20d": annualized_vol(rets, 20),
        "vol_60d": annualized_vol(rets, 60),
        "vol_1y": annualized_vol(rets, 252),
        "downside_vol_60d": downside_vol(rets, 60),
        "max_drawdown_1y": max_drawdown(p, 252),
        "dollar_volume_20d": dv20,
        "relative_volume_20v60": relvol,
    }
