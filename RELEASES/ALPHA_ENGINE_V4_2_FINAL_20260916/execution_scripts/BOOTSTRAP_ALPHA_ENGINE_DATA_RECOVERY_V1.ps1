$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-A"
Write-Host "MARKET DATA / OHLCV / VAR 1D / AUDIT CONTRACT"
Write-Host "NO V13 MUTATION / NO SHEETS MUTATION / NO WEB MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $ROOT)) { throw "No existe ROOT: $ROOT" }
if (-not (Test-Path $V13))  { throw "No existe V13 productivo: $V13" }

Set-Location $ROOT

# Guardrail: V13 is checked, never written by this bootstrap.
$before = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"

New-Item -ItemType Directory -Force -Path $REC | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $REC "src\alpha_data_recovery") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $REC "scripts") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $REC "tests") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $REC "outputs\data_recovery_v1\ohlcv") | Out-Null


@'
"""ALPHA ENGINE - DATA RECOVERY V1.

Independent recovery layer. It must not mutate sealed V13 model/policy artifacts.
"""
__version__ = "0.1.0"
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\__init__.py") -Encoding UTF8

@'
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AuditValue:
    value: Any
    source: str
    asof: str | None
    status: str
    fallback: str = "none"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketSnapshot:
    ticker: str
    market_symbol: str
    retrieved_at: str
    currency: str | None = None
    exchange: str | None = None
    market_state: str | None = None
    fields: dict[str, AuditValue] = field(default_factory=dict)
    metrics: dict[str, AuditValue] = field(default_factory=dict)
    coverage: float = 0.0
    overall_status: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "market_symbol": self.market_symbol,
            "retrieved_at": self.retrieved_at,
            "currency": self.currency,
            "exchange": self.exchange,
            "market_state": self.market_state,
            "coverage": self.coverage,
            "overall_status": self.overall_status,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
        }
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\contracts.py") -Encoding UTF8

@'
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
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\market_metrics.py") -Encoding UTF8

@'
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
    raw_closes = [r["close"] for r in rows if r["close"] is not None]
    adj_closes = [r["adj_close"] for r in rows if r["adj_close"] is not None]
    volumes = [r["volume"] for r in rows if r["volume"] is not None]

    price = _finite(meta.get("regularMarketPrice"))
    if price is None and raw_closes:
        price = raw_closes[-1]

    prev_close = _finite(meta.get("regularMarketPreviousClose"))
    if prev_close is None:
        prev_close = _finite(meta.get("chartPreviousClose"))
    if prev_close is None and len(raw_closes) >= 2:
        prev_close = raw_closes[-2]

    var_1d = (
        price / prev_close - 1.0
        if price is not None and prev_close is not None and prev_close > 0
        else None
    )

    market_asof = _iso_epoch(meta.get("regularMarketTime"))
    age_hours = None
    if market_asof:
        dt = datetime.fromisoformat(market_asof)
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0

    status = "OK"
    detail = ""
    if price is None or prev_close is None:
        status = "MISSING"
        detail = "price or previous close unavailable"
    elif price <= 0 or prev_close <= 0:
        status = "INVALID"
        detail = "non-positive price"
    elif abs(var_1d or 0.0) > 0.40:
        status = "WARN"
        detail = "absolute live 1D move exceeds 40%; review split/mapping"
    elif age_hours is not None and age_hours > 120:
        status = "STALE"
        detail = f"regular market timestamp age={age_hours:.1f}h"

    audit_fallback = fallback
    fields = {
        "price": AuditValue(price, SOURCE, market_asof, status, audit_fallback, detail),
        "previous_close": AuditValue(prev_close, SOURCE, market_asof, status, audit_fallback, detail),
        "var_1d": AuditValue(var_1d, SOURCE, market_asof, status, audit_fallback, detail),
        "market_data_age_hours": AuditValue(
            age_hours, SOURCE, market_asof, "OK" if age_hours is not None else "MISSING",
            audit_fallback,
        ),
    }

    raw_metrics = compute_market_metrics(adj_closes, raw_closes, volumes)
    metrics: dict[str, AuditValue] = {}
    history_asof = rows[-1]["timestamp"] if rows else None
    for name, value in raw_metrics.items():
        metric_status = "OK" if value is not None else "MISSING"
        metrics[name] = AuditValue(
            value=value,
            source=f"{SOURCE} OHLCV 2Y",
            asof=history_asof,
            status=metric_status,
            fallback=audit_fallback,
        )

    required = list(fields.values()) + [
        metrics["ret_1m"],
        metrics["vol_60d"],
        metrics["max_drawdown_1y"],
    ]
    coverage = sum(x.value is not None for x in required) / len(required)

    overall = "OK"
    if any(x.status in {"INVALID", "MISSING"} for x in fields.values()):
        overall = "ERROR"
    elif any(x.status in {"WARN", "STALE"} for x in fields.values()):
        overall = "WARN"

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
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\yahoo_chart.py") -Encoding UTF8

@'
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    ticker: str
    quantity: float
    avg_cost_usd: float = 0.0


@dataclass(frozen=True)
class ValuedPosition:
    ticker: str
    quantity: float
    price_usd: float
    market_value_usd: float
    avg_cost_usd: float
    cost_basis_usd: float
    unrealized_pnl_usd: float
    weight: float


def value_portfolio(
    positions: list[Position],
    prices_usd: dict[str, float],
) -> list[ValuedPosition]:
    prelim = []
    total = 0.0
    for p in positions:
        price = float(prices_usd[p.ticker.upper()])
        mv = float(p.quantity) * price
        cost = float(p.quantity) * float(p.avg_cost_usd)
        prelim.append((p, price, mv, cost))
        total += mv

    out = []
    for p, price, mv, cost in prelim:
        out.append(
            ValuedPosition(
                ticker=p.ticker.upper(),
                quantity=float(p.quantity),
                price_usd=price,
                market_value_usd=mv,
                avg_cost_usd=float(p.avg_cost_usd),
                cost_basis_usd=cost,
                unrealized_pnl_usd=mv - cost,
                weight=(mv / total) if total else 0.0,
            )
        )
    return sorted(out, key=lambda x: x.market_value_usd, reverse=True)
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\portfolio.py") -Encoding UTF8

@'
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.yahoo_chart import recover_market


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["NVDA", "MSFT", "SPY"],
        help="Yahoo market symbols for smoke recovery",
    )
    args = parser.parse_args()

    output_dir = ROOT / "outputs" / "data_recovery_v1"
    ohlcv_dir = output_dir / "ohlcv"
    output_dir.mkdir(parents=True, exist_ok=True)
    ohlcv_dir.mkdir(parents=True, exist_ok=True)

    records = []
    failures = []

    for symbol in args.symbols:
        ticker = symbol.upper()
        try:
            snap, rows = recover_market(ticker=ticker, market_symbol=ticker)
            records.append(snap.to_dict())
            with (ohlcv_dir / f"{ticker.replace('^', '_')}.jsonl").open(
                "w", encoding="utf-8"
            ) as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(
                f"[OK] {ticker:<8} "
                f"price={snap.fields['price'].value} "
                f"var_1d={snap.fields['var_1d'].value} "
                f"status={snap.overall_status} "
                f"fallback={snap.fields['price'].fallback}"
            )
        except Exception as exc:
            failures.append({"ticker": ticker, "error": str(exc)})
            print(f"[ERROR] {ticker}: {exc}")

    payload = {
        "stage": "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "mutation_policy": {
            "v13_model": False,
            "v13_policy": False,
            "v13_outputs": False,
            "sheets": False,
            "web": False,
        },
        "records": records,
        "failures": failures,
    }
    (output_dir / "market_snapshot_latest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    csv_path = output_dir / "market_snapshot_latest.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        headers = [
            "ticker", "market_symbol", "price", "previous_close", "var_1d",
            "close_to_close_1d", "ret_1m", "ret_3m", "ret_6m", "ret_12m",
            "vol_20d", "vol_60d", "vol_1y", "max_drawdown_1y",
            "dollar_volume_20d", "relative_volume_20v60",
            "source", "asof", "status", "fallback", "coverage",
        ]
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for r in records:
            f = r["fields"]
            m = r["metrics"]
            writer.writerow({
                "ticker": r["ticker"],
                "market_symbol": r["market_symbol"],
                "price": f["price"]["value"],
                "previous_close": f["previous_close"]["value"],
                "var_1d": f["var_1d"]["value"],
                "close_to_close_1d": m["close_to_close_1d"]["value"],
                "ret_1m": m["ret_1m"]["value"],
                "ret_3m": m["ret_3m"]["value"],
                "ret_6m": m["ret_6m"]["value"],
                "ret_12m": m["ret_12m"]["value"],
                "vol_20d": m["vol_20d"]["value"],
                "vol_60d": m["vol_60d"]["value"],
                "vol_1y": m["vol_1y"]["value"],
                "max_drawdown_1y": m["max_drawdown_1y"]["value"],
                "dollar_volume_20d": m["dollar_volume_20d"]["value"],
                "relative_volume_20v60": m["relative_volume_20v60"]["value"],
                "source": f["price"]["source"],
                "asof": f["price"]["asof"],
                "status": r["overall_status"],
                "fallback": f["price"]["fallback"],
                "coverage": r["coverage"],
            })

    print("")
    print("WROTE:")
    print(f"  {output_dir / 'market_snapshot_latest.json'}")
    print(f"  {csv_path}")
    print(f"  {ohlcv_dir}")
    print("")
    print(f"records={len(records)} failures={len(failures)}")
    return 0 if records and not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
'@ | Set-Content -Path (Join-Path $REC "scripts\run_market_recovery.py") -Encoding UTF8

@'
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.contracts import AuditValue
from alpha_data_recovery.market_metrics import compute_market_metrics
from alpha_data_recovery.portfolio import Position, value_portfolio


class TestDataRecoveryV1(unittest.TestCase):
    def test_audit_contract_has_required_fields(self):
        x = AuditValue(
            value=100.0,
            source="test",
            asof="2026-09-15T12:00:00+00:00",
            status="OK",
            fallback="none",
        ).to_dict()
        self.assertEqual(
            set(x),
            {"value", "source", "asof", "status", "fallback", "detail"},
        )

    def test_close_to_close_var_is_deterministic(self):
        raw = [100.0, 105.0, 103.0]
        adj = raw[:]
        vol = [10.0, 11.0, 12.0]
        m = compute_market_metrics(adj, raw, vol)
        self.assertAlmostEqual(m["close_to_close_1d"], 103.0 / 105.0 - 1.0)

    def test_portfolio_valuation(self):
        p = [
            Position("AAA", 2, 10),
            Position("BBB", 1, 30),
        ]
        valued = value_portfolio(p, {"AAA": 20, "BBB": 40})
        total = sum(x.market_value_usd for x in valued)
        self.assertAlmostEqual(total, 80.0)
        self.assertAlmostEqual(sum(x.weight for x in valued), 1.0)

    def test_market_metrics_do_not_emit_scores(self):
        raw = [100.0 + i for i in range(300)]
        vol = [1000.0 + i for i in range(300)]
        m = compute_market_metrics(raw, raw, vol)
        forbidden = {"alpha", "quality", "growth", "value_score", "market_score", "risk_score"}
        self.assertTrue(forbidden.isdisjoint(m.keys()))


if __name__ == "__main__":
    unittest.main()
'@ | Set-Content -Path (Join-Path $REC "tests\test_data_recovery_v1.py") -Encoding UTF8

@'
# ALPHA ENGINE - DATA RECOVERY V1

Purpose: recover the proven data layer independently from the sealed V13 decision engine.

## Hard rules

- Do not mutate `ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON`.
- Do not generate `alpha_product_state.json` yet.
- Do not write to Google Sheets yet.
- Do not import V8/V10 Alpha scores, portfolio actions, thresholds or model weights.
- Every recovered datum must carry `source`, `asof`, `status`, and `fallback`.

## Stage DR1-A

This bootstrap recovers and audits:
- regular-session price
- previous close
- current `var_1d`
- 2Y daily OHLCV
- 1M/3M/6M/12M returns
- SMA 20/50/200
- RSI 14
- 20D/60D/1Y realized vol
- 60D downside vol
- 1Y max drawdown
- 20D dollar volume
- relative volume 20D vs 60D

No scores are computed.

Next stages:
- DR1-B: SEC/Yahoo fundamentals + field-level fallback contract
- DR1-C: workbook/Google Sheet adapter
- DR1-D: portfolio valuation and CEDEAR/FX mapping
- DR1-E: product-state regeneration gate
'@ | Set-Content -Path (Join-Path $REC "README.md") -Encoding UTF8

Write-Host ""
Write-Host "[1/4] Python"
python --version

Write-Host ""
Write-Host "[2/4] Unit tests"
Set-Location $REC
python -m unittest discover -s tests -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "Tests DR1-A fallaron." }

Write-Host ""
Write-Host "[3/4] Live market recovery smoke: NVDA MSFT SPY"
python scripts\run_market_recovery.py --symbols NVDA MSFT SPY
if ($LASTEXITCODE -ne 0) { throw "Smoke de mercado DR1-A falló." }

Write-Host ""
Write-Host "[4/4] V13 immutability check"
Set-Location $ROOT
$after = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
if (($before | Out-String) -ne ($after | Out-String)) {
    throw "GUARDRAIL: cambió el estado de V13 durante DR1-A."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "DR1-A COMPLETE"
Write-Host "V13: UNCHANGED"
Write-Host "SHEETS: UNCHANGED"
Write-Host "WEB: UNCHANGED"
Write-Host "PRODUCT STATE: NOT REGENERATED"
Write-Host "============================================================"
Write-Host ""
Write-Host "Pegame la salida completa de esta consola."
Write-Host "También quedan:"
Write-Host "  $REC\outputs\data_recovery_v1\market_snapshot_latest.json"
Write-Host "  $REC\outputs\data_recovery_v1\market_snapshot_latest.csv"
