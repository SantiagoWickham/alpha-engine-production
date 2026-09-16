$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-A FIX1"
Write-Host "CORRECT VAR 1D PREVIOUS-CLOSE SEMANTICS"
Write-Host "NO V13 / SHEETS / WEB / PRODUCT STATE MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $REC)) { throw "No existe Recovery V1: $REC" }
if (-not (Test-Path $V13)) { throw "No existe V13: $V13" }

Set-Location $ROOT
$before = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"


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
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\yahoo_chart.py") -Encoding UTF8

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

            f = snap.fields
            print(
                f"[{snap.overall_status}] {ticker:<8} "
                f"price={f['price'].value} "
                f"prev={f['previous_close'].value} "
                f"var_1d={f['var_1d'].value} "
                f"chartPrev_DIAG={f['meta_chart_previous_close'].value} "
                f"fallback={f['price'].fallback}"
            )
        except Exception as exc:
            failures.append({"ticker": ticker, "error": str(exc)})
            print(f"[ERROR] {ticker}: {exc}")

    payload = {
        "stage": "ALPHA_ENGINE_DATA_RECOVERY_V1_DR1A_FIX1",
        "var_1d_contract": "regular_market_price / immediately_preceding_raw_daily_close - 1",
        "forbidden_var_1d_input": "Yahoo meta.chartPreviousClose",
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
            "latest_daily_close", "close_to_close_1d",
            "ret_1m", "ret_3m", "ret_6m", "ret_12m",
            "vol_20d", "vol_60d", "vol_1y", "max_drawdown_1y",
            "dollar_volume_20d", "relative_volume_20v60",
            "source", "asof", "status", "fallback", "coverage",
            "meta_regular_previous_close_DIAGNOSTIC",
            "meta_chart_previous_close_DIAGNOSTIC",
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
                "latest_daily_close": f["latest_daily_close"]["value"],
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
                "meta_regular_previous_close_DIAGNOSTIC":
                    f["meta_regular_previous_close"]["value"],
                "meta_chart_previous_close_DIAGNOSTIC":
                    f["meta_chart_previous_close"]["value"],
            })

    print("")
    print("WROTE:")
    print(f"  {output_dir / 'market_snapshot_latest.json'}")
    print(f"  {csv_path}")
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
from alpha_data_recovery.yahoo_chart import _previous_session_close


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
        m = compute_market_metrics(raw, raw, [10.0, 11.0, 12.0])
        self.assertAlmostEqual(m["close_to_close_1d"], 103.0 / 105.0 - 1.0)

    def test_previous_session_close_uses_daily_bar_not_meta(self):
        rows = [
            {"close": 100.0, "timestamp": "2026-09-11T20:00:00+00:00"},
            {"close": 105.0, "timestamp": "2026-09-14T20:00:00+00:00"},
            {"close": 106.0, "timestamp": "2026-09-15T20:00:00+00:00"},
        ]
        px, asof = _previous_session_close(rows)
        self.assertEqual(px, 105.0)
        self.assertEqual(asof, "2026-09-14T20:00:00+00:00")

    def test_live_var_1d_formula(self):
        live = 106.0
        prev = 105.0
        self.assertAlmostEqual(live / prev - 1.0, 0.00952380952380949)

    def test_portfolio_valuation(self):
        p = [Position("AAA", 2, 10), Position("BBB", 1, 30)]
        valued = value_portfolio(p, {"AAA": 20, "BBB": 40})
        self.assertAlmostEqual(sum(x.market_value_usd for x in valued), 80.0)
        self.assertAlmostEqual(sum(x.weight for x in valued), 1.0)

    def test_market_metrics_do_not_emit_scores(self):
        raw = [100.0 + i for i in range(300)]
        vol = [1000.0 + i for i in range(300)]
        m = compute_market_metrics(raw, raw, vol)
        forbidden = {
            "alpha", "quality", "growth", "value_score", "market_score", "risk_score"
        }
        self.assertTrue(forbidden.isdisjoint(m.keys()))


if __name__ == "__main__":
    unittest.main()
'@ | Set-Content -Path (Join-Path $REC "tests\test_data_recovery_v1.py") -Encoding UTF8

Write-Host ""
Write-Host "[1/4] Tests"
Set-Location $REC
python -m unittest discover -s tests -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "Tests DR1-A FIX1 fallaron." }

Write-Host ""
Write-Host "[2/4] Re-run live sentinels"
python scripts\run_market_recovery.py --symbols NVDA MSFT SPY
if ($LASTEXITCODE -ne 0) { throw "Smoke DR1-A FIX1 falló." }

Write-Host ""
Write-Host "[3/4] Sanity gate"
$csv = Import-Csv (Join-Path $REC "outputs\data_recovery_v1\market_snapshot_latest.csv")
foreach ($r in $csv) {
    $v = [double]$r.var_1d
    if ([math]::Abs($v) -gt 0.35) {
        throw "SANITY GATE: $($r.ticker) Var 1D=$v quedó >35%. No avanzar."
    }
    Write-Host ("  {0,-6} price={1,-10} prev={2,-10} var1d={3,8:P2} status={4}" -f `
        $r.ticker, $r.price, $r.previous_close, $v, $r.status)
}

Write-Host ""
Write-Host "[4/4] V13 immutability"
Set-Location $ROOT
$after = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
if (($before | Out-String) -ne ($after | Out-String)) {
    throw "GUARDRAIL: cambió V13 durante DR1-A FIX1."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "DR1-A FIX1 COMPLETE"
Write-Host "VAR 1D: PRIOR DAILY CLOSE CONTRACT"
Write-Host "chartPreviousClose: DIAGNOSTIC ONLY"
Write-Host "V13: UNCHANGED"
Write-Host "SHEETS: UNCHANGED"
Write-Host "WEB: UNCHANGED"
Write-Host "PRODUCT STATE: NOT REGENERATED"
Write-Host "============================================================"
Write-Host ""
Write-Host "Pegame la salida completa."
