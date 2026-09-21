from __future__ import annotations

import math
from statistics import mean
from typing import Any


def _finite(x: Any) -> float | None:
    try:
        y = float(x)
    except (TypeError, ValueError):
        return None
    return y if math.isfinite(y) else None


def _series(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [
        float(v)
        for r in rows
        if (v := _finite(r.get(key))) is not None
    ]


def _ret_n(values: list[float], n: int) -> float | None:
    if len(values) <= n or values[-n - 1] == 0:
        return None
    return values[-1] / values[-n - 1] - 1.0


def _sma(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return mean(values[-n:])


def _daily_return_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    clean: list[tuple[str, float]] = []
    for r in rows:
        ts = str(r.get("timestamp") or "")
        px = _finite(r.get("adj_close"))
        if not ts or px is None or px <= 0:
            continue
        clean.append((ts[:10], px))

    out: dict[str, float] = {}
    for i in range(1, len(clean)):
        d, px = clean[i]
        prev = clean[i - 1][1]
        if prev > 0:
            out[d] = px / prev - 1.0
    return out


def _beta_corr(
    asset_rows: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]] | None,
    n: int = 126,
) -> tuple[float | None, float | None]:
    if not benchmark_rows:
        return None, None

    a = _daily_return_map(asset_rows)
    b = _daily_return_map(benchmark_rows)
    dates = sorted(set(a).intersection(b))
    if len(dates) < 30:
        return None, None
    dates = dates[-n:]

    av = [a[d] for d in dates]
    bv = [b[d] for d in dates]
    ma, mb = mean(av), mean(bv)

    cov = sum((x - ma) * (y - mb) for x, y in zip(av, bv))
    vb = sum((y - mb) ** 2 for y in bv)
    va = sum((x - ma) ** 2 for x in av)

    beta = cov / vb if vb > 0 else None
    corr = cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None
    return beta, corr


def compute_sheet_market_metrics(
    asset_rows: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]] | None = None,
) -> dict[str, float | None]:
    adj = _series(asset_rows, "adj_close")
    raw = _series(asset_rows, "close")
    vols = _series(asset_rows, "volume")

    last = raw[-1] if raw else (adj[-1] if adj else None)
    sma20 = _sma(adj, 20)
    sma50 = _sma(adj, 50)
    sma200 = _sma(adj, 200)

    avg_vol20 = mean(vols[-20:]) if len(vols) >= 20 else None
    avg_vol60 = mean(vols[-60:]) if len(vols) >= 60 else None

    b_adj = _series(benchmark_rows or [], "adj_close")
    ret3 = _ret_n(adj, 63)
    ret6 = _ret_n(adj, 126)
    bret3 = _ret_n(b_adj, 63)
    bret6 = _ret_n(b_adj, 126)
    beta, corr = _beta_corr(asset_rows, benchmark_rows, 126)

    high_1y = max(adj[-252:]) if len(adj) >= 2 else None

    return {
        "dist_sma20": (last / sma20 - 1.0) if last is not None and sma20 not in (None, 0) else None,
        "dist_sma50": (last / sma50 - 1.0) if last is not None and sma50 not in (None, 0) else None,
        "dist_sma200": (last / sma200 - 1.0) if last is not None and sma200 not in (None, 0) else None,
        "avg_vol_20d": avg_vol20,
        "dollar_volume_20d_aligned": (
            avg_vol20 * last
            if avg_vol20 is not None and last is not None
            else None
        ),
        "relative_volume_20v60_aligned": (
            avg_vol20 / avg_vol60
            if avg_vol20 is not None and avg_vol60 not in (None, 0)
            else None
        ),
        "rs_3m": (
            ret3 - bret3
            if ret3 is not None and bret3 is not None
            else None
        ),
        "rs_6m": (
            ret6 - bret6
            if ret6 is not None and bret6 is not None
            else None
        ),
        "beta_6m": beta,
        "corr_6m": corr,
        "dist_52w_high": (
            last / high_1y - 1.0
            if last is not None and high_1y not in (None, 0)
            else None
        ),
    }
