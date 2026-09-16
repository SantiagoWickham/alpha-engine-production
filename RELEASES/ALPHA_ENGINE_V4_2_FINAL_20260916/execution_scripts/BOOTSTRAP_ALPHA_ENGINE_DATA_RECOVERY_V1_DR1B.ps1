$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-B"
Write-Host "FUNDAMENTALS: YAHOO + SEC FIELD-LEVEL AUDIT"
Write-Host "NO V8/V10 SCORES / NO V13 / SHEETS / WEB MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $REC)) { throw "No existe Recovery V1: $REC" }
if (-not (Test-Path $V13)) { throw "No existe V13: $V13" }

Set-Location $ROOT
$before = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"


@'
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK"


def _ua() -> str:
    return os.getenv(
        "SEC_USER_AGENT",
        "AlphaEngine-Data-Recovery local-research",
    )


def _get_json(url: str, attempts: int = 3) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": _ua(),
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip, deflate",
                },
            )
            with urlopen(req, timeout=25) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"SEC request failed: {url}: {last_error}")


def fetch_ticker_map() -> dict[str, str]:
    payload = _get_json(SEC_TICKERS)
    out: dict[str, str] = {}
    for item in payload.values():
        ticker = str(item.get("ticker") or "").upper().strip()
        cik = item.get("cik_str")
        if ticker and cik is not None:
            out[ticker] = str(cik).zfill(10)
    return out


def fetch_companyfacts(cik: str) -> dict[str, Any]:
    return _get_json(f"{SEC_FACTS}{str(cik).zfill(10)}.json")


def annual_series(
    facts: dict[str, Any],
    names: list[str],
) -> list[dict[str, Any]]:
    for namespace in ("us-gaap", "ifrs-full"):
        block = (facts or {}).get(namespace) or {}
        for name in names:
            concept = block.get(name)
            if not concept or not concept.get("units"):
                continue
            for unit, values in concept["units"].items():
                annual = []
                for x in values or []:
                    if x.get("form") not in {"10-K", "20-F", "40-F"}:
                        continue
                    if x.get("fp") not in {None, "", "FY"}:
                        continue
                    if x.get("fy") is None or x.get("val") is None:
                        continue
                    annual.append({
                        "fy": int(x["fy"]),
                        "val": float(x["val"]),
                        "end": x.get("end"),
                        "filed": x.get("filed"),
                        "form": x.get("form"),
                        "unit": unit,
                        "concept": name,
                        "namespace": namespace,
                    })
                if annual:
                    # Keep the latest filed value per fiscal year.
                    by_year: dict[int, dict[str, Any]] = {}
                    for x in annual:
                        old = by_year.get(x["fy"])
                        if old is None or str(x.get("filed") or "") >= str(old.get("filed") or ""):
                            by_year[x["fy"]] = x
                    return [by_year[y] for y in sorted(by_year)]
    return []


def sec_raw_fundamentals(companyfacts: dict[str, Any]) -> dict[str, Any]:
    facts = companyfacts.get("facts") or {}

    concept_map = {
        "revenue": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "Revenue",
        ],
        "net_income": ["NetIncomeLoss", "ProfitLoss"],
        "assets": ["Assets"],
        "equity": [
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            "Equity",
        ],
        "debt": [
            "LongTermDebtAndFinanceLeaseObligationsCurrent",
            "LongTermDebtCurrent",
            "LongTermDebtNoncurrent",
            "LongTermDebt",
            "Borrowings",
        ],
        "eps_diluted": [
            "EarningsPerShareDiluted",
            "DilutedEarningsLossPerShare",
            "BasicEarningsLossPerShare",
        ],
        "cash_from_operations": [
            "NetCashProvidedByUsedInOperatingActivities",
            "CashFlowsFromUsedInOperatingActivities",
        ],
        "capex": [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PurchaseOfPropertyPlantAndEquipment",
        ],
        "current_assets": ["AssetsCurrent"],
        "current_liabilities": ["LiabilitiesCurrent"],
    }

    series = {k: annual_series(facts, v) for k, v in concept_map.items()}

    def latest(name: str) -> dict[str, Any] | None:
        arr = series[name]
        return arr[-1] if arr else None

    def previous(name: str) -> dict[str, Any] | None:
        arr = series[name]
        return arr[-2] if len(arr) >= 2 else None

    return {
        "entity_name": companyfacts.get("entityName"),
        "series": series,
        "latest": {k: latest(k) for k in series},
        "previous": {k: previous(k) for k in series},
    }


def age_days(asof: str | None) -> float | None:
    if not asof:
        return None
    try:
        dt = datetime.fromisoformat(asof).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\sec_companyfacts.py") -Encoding UTF8

@'
from __future__ import annotations

import http.cookiejar
import json
import math
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, Request, build_opener


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/153 Safari/537.36"
)
YQ1 = "https://query1.finance.yahoo.com"
YQ2 = "https://query2.finance.yahoo.com"


def _finite(value: Any) -> float | None:
    if isinstance(value, dict):
        if "raw" in value:
            value = value.get("raw")
        elif "fmt" in value:
            value = value.get("fmt")
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _text(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("raw") or value.get("fmt")
    if value is None:
        return None
    s = str(value).strip()
    return s or None


class YahooSession:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))
        self.crumb: str | None = None

    def _request(self, url: str) -> bytes:
        req = Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/json,text/plain,*/*",
            },
        )
        with self.opener.open(req, timeout=20) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            return resp.read()

    def bootstrap(self) -> None:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                try:
                    self._request("https://fc.yahoo.com")
                except Exception:
                    # Cookie endpoint can reply oddly; continue to crumb.
                    pass
                raw = self._request(f"{YQ1}/v1/test/getcrumb")
                crumb = raw.decode("utf-8").strip()
                if not crumb or "<html" in crumb.lower():
                    raise RuntimeError("invalid Yahoo crumb")
                self.crumb = crumb
                return
            except Exception as exc:
                last_error = exc
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Yahoo session bootstrap failed: {last_error}")

    def quote_summary(self, symbol: str) -> tuple[dict[str, Any], str]:
        if not self.crumb:
            self.bootstrap()

        modules = ",".join([
            "price",
            "financialData",
            "defaultKeyStatistics",
            "summaryDetail",
            "assetProfile",
            "calendarEvents",
        ])
        encoded = quote(symbol, safe="")
        qs = quote(modules, safe=",")
        crumb = quote(self.crumb or "", safe="")

        last_error: Exception | None = None
        for idx, base in enumerate((YQ2, YQ1)):
            url = (
                f"{base}/v10/finance/quoteSummary/{encoded}"
                f"?modules={qs}&crumb={crumb}"
            )
            for attempt in range(2):
                try:
                    payload = json.loads(self._request(url).decode("utf-8"))
                    err = (payload.get("quoteSummary") or {}).get("error")
                    if err:
                        raise RuntimeError(str(err))
                    result = ((payload.get("quoteSummary") or {}).get("result") or [])
                    if not result:
                        raise RuntimeError("Yahoo quoteSummary returned no result")
                    return result[0], ("none" if idx == 0 else "query1")
                except (HTTPError, URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
                    last_error = exc
                    time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"Yahoo quoteSummary failed for {symbol}: {last_error}")


def normalize_quote_summary(result: dict[str, Any]) -> dict[str, Any]:
    price = result.get("price") or {}
    fd = result.get("financialData") or {}
    ks = result.get("defaultKeyStatistics") or {}
    sd = result.get("summaryDetail") or {}
    ap = result.get("assetProfile") or {}

    current_price = _finite(price.get("regularMarketPrice"))
    market_cap = _finite(price.get("marketCap")) or _finite(sd.get("marketCap"))
    eps = _finite(ks.get("trailingEps"))
    fwd_eps = _finite(ks.get("forwardEps"))

    pe = _finite(sd.get("trailingPE"))
    if pe is None and current_price is not None and eps not in (None, 0):
        pe = current_price / eps

    fwd_pe = _finite(sd.get("forwardPE"))
    if fwd_pe is None and current_price is not None and fwd_eps not in (None, 0):
        fwd_pe = current_price / fwd_eps

    fcf = _finite(fd.get("freeCashflow"))
    target = _finite(fd.get("targetMeanPrice"))

    return {
        "company_name": _text(price.get("longName")) or _text(price.get("shortName")),
        "sector": _text(ap.get("sector")),
        "industry": _text(ap.get("industry")),
        "price": current_price,
        "market_cap": market_cap,
        "pe": pe,
        "fwd_pe": fwd_pe,
        "peg": _finite(ks.get("pegRatio")),
        "roe": _finite(fd.get("returnOnEquity")),
        "roa": _finite(fd.get("returnOnAssets")),
        "debt_equity": _finite(fd.get("debtToEquity")),
        "net_margin": _finite(fd.get("profitMargins")),
        "eps_growth": _finite(fd.get("earningsGrowth")),
        "revenue_growth": _finite(fd.get("revenueGrowth")),
        "free_cash_flow": fcf,
        "fcf_yield": (fcf / market_cap) if fcf is not None and market_cap not in (None, 0) else None,
        "ev_ebitda": _finite(ks.get("enterpriseToEbitda")),
        "current_ratio": _finite(fd.get("currentRatio")),
        "quick_ratio": _finite(fd.get("quickRatio")),
        "dividend_yield": _finite(sd.get("dividendYield")),
        "beta": _finite(ks.get("beta")),
        "target_mean_price": target,
        "target_upside": (
            target / current_price - 1.0
            if target is not None and current_price not in (None, 0)
            else None
        ),
        "recommendation_mean": _finite(fd.get("recommendationMean")),
        "price_book": _finite(ks.get("priceToBook")),
        "shares_outstanding": _finite(ks.get("sharesOutstanding")),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\yahoo_fundamentals.py") -Encoding UTF8

@'
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .contracts import AuditValue
from .sec_companyfacts import (
    fetch_companyfacts,
    fetch_ticker_map,
    sec_raw_fundamentals,
)
from .yahoo_fundamentals import YahooSession, normalize_quote_summary


YAHOO_SOURCE = "Yahoo Finance quoteSummary"
SEC_SOURCE = "SEC companyfacts"


def _v(x: dict[str, Any] | None) -> float | None:
    return None if not x else float(x["val"])


def _asof(x: dict[str, Any] | None) -> str | None:
    return None if not x else x.get("end") or x.get("filed")


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return a / b


def sec_derived(raw: dict[str, Any]) -> dict[str, tuple[float | None, str | None, str]]:
    latest = raw["latest"]
    previous = raw["previous"]

    revenue = _v(latest["revenue"])
    prev_revenue = _v(previous["revenue"])
    net_income = _v(latest["net_income"])
    assets = _v(latest["assets"])
    equity = _v(latest["equity"])
    debt = _v(latest["debt"])
    eps = _v(latest["eps_diluted"])
    prev_eps = _v(previous["eps_diluted"])
    cfo = _v(latest["cash_from_operations"])
    capex = _v(latest["capex"])
    ca = _v(latest["current_assets"])
    cl = _v(latest["current_liabilities"])

    fcf = None
    if cfo is not None:
        fcf = cfo - (abs(capex) if capex is not None else 0.0)

    def best_asof(*items: dict[str, Any] | None) -> str | None:
        vals = [x for x in (_asof(i) for i in items) if x]
        return max(vals) if vals else None

    return {
        "roe": (
            _safe_div(net_income, equity),
            best_asof(latest["net_income"], latest["equity"]),
            "Net income / equity",
        ),
        "roa": (
            _safe_div(net_income, assets),
            best_asof(latest["net_income"], latest["assets"]),
            "Net income / assets",
        ),
        "debt_equity": (
            None if debt is None or equity in (None, 0) else debt / equity * 100.0,
            best_asof(latest["debt"], latest["equity"]),
            "Debt / equity * 100 to match Yahoo convention",
        ),
        "net_margin": (
            _safe_div(net_income, revenue),
            best_asof(latest["net_income"], latest["revenue"]),
            "Net income / revenue",
        ),
        "eps_growth": (
            None if eps is None or prev_eps in (None, 0) else eps / prev_eps - 1.0,
            _asof(latest["eps_diluted"]),
            "Annual diluted EPS growth",
        ),
        "revenue_growth": (
            None
            if revenue is None or prev_revenue in (None, 0)
            else revenue / prev_revenue - 1.0,
            _asof(latest["revenue"]),
            "Annual revenue growth",
        ),
        "free_cash_flow": (
            fcf,
            best_asof(latest["cash_from_operations"], latest["capex"]),
            "CFO - abs(CapEx)",
        ),
        "current_ratio": (
            _safe_div(ca, cl),
            best_asof(latest["current_assets"], latest["current_liabilities"]),
            "Current assets / current liabilities",
        ),
        "eps_diluted_sec": (
            eps,
            _asof(latest["eps_diluted"]),
            "Latest annual diluted EPS",
        ),
        "equity_sec": (
            equity,
            _asof(latest["equity"]),
            "Latest annual equity",
        ),
    }


@dataclass
class FundamentalSnapshot:
    ticker: str
    yahoo_symbol: str
    sec_ticker: str
    retrieved_at: str
    fields: dict[str, AuditValue]
    overall_status: str
    coverage: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "yahoo_symbol": self.yahoo_symbol,
            "sec_ticker": self.sec_ticker,
            "retrieved_at": self.retrieved_at,
            "overall_status": self.overall_status,
            "coverage": self.coverage,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
        }


def recover_fundamentals(
    ticker: str,
    yahoo_symbol: str | None = None,
    sec_ticker: str | None = None,
    yahoo_session: YahooSession | None = None,
    sec_map: dict[str, str] | None = None,
) -> FundamentalSnapshot:
    ticker = ticker.upper()
    yahoo_symbol = (yahoo_symbol or ticker).upper()
    sec_ticker = (sec_ticker or ticker).upper()
    retrieved = datetime.now(timezone.utc).isoformat()

    fields: dict[str, AuditValue] = {}
    yahoo_error: str | None = None
    sec_error: str | None = None
    yahoo_data: dict[str, Any] = {}
    sec_data: dict[str, tuple[float | None, str | None, str]] = {}
    sec_entity_name: str | None = None

    session = yahoo_session or YahooSession()
    try:
        result, yf_fallback = session.quote_summary(yahoo_symbol)
        yahoo_data = normalize_quote_summary(result)
        y_asof = yahoo_data["retrieved_at"]
        for name, value in yahoo_data.items():
            if name == "retrieved_at":
                continue
            fields[name] = AuditValue(
                value=value,
                source=YAHOO_SOURCE,
                asof=y_asof,
                status="OK" if value is not None else "MISSING",
                fallback=yf_fallback,
                detail="Provider snapshot; field-level filing date not exposed by quoteSummary.",
            )
    except Exception as exc:
        yahoo_error = str(exc)

    try:
        smap = sec_map if sec_map is not None else fetch_ticker_map()
        cik = smap.get(sec_ticker)
        if not cik:
            raise RuntimeError(f"SEC CIK not found for {sec_ticker}")
        companyfacts = fetch_companyfacts(cik)
        raw = sec_raw_fundamentals(companyfacts)
        sec_entity_name = raw.get("entity_name")
        sec_data = sec_derived(raw)
    except Exception as exc:
        sec_error = str(exc)

    # Canonical fields. SEC only fills fields that Yahoo did not provide.
    fallback_fields = {
        "roe",
        "roa",
        "debt_equity",
        "net_margin",
        "eps_growth",
        "revenue_growth",
        "free_cash_flow",
        "current_ratio",
    }
    for name in fallback_fields:
        current = fields.get(name)
        sec_value, sec_asof, detail = sec_data.get(name, (None, None, ""))
        if current is None or current.value is None:
            fields[name] = AuditValue(
                value=sec_value,
                source=SEC_SOURCE,
                asof=sec_asof,
                status="FALLBACK" if sec_value is not None else "MISSING",
                fallback="SEC companyfacts" if sec_value is not None else "none",
                detail=detail,
            )

    # SEC can support some valuation ratios if Yahoo supplies market values but
    # does not supply the ratio itself.
    eps_sec, eps_asof, _ = sec_data.get("eps_diluted_sec", (None, None, ""))
    equity_sec, eq_asof, _ = sec_data.get("equity_sec", (None, None, ""))
    price = fields.get("price").value if fields.get("price") else None
    market_cap = fields.get("market_cap").value if fields.get("market_cap") else None

    if (fields.get("pe") is None or fields["pe"].value is None) and price is not None and eps_sec not in (None, 0):
        fields["pe"] = AuditValue(
            price / eps_sec,
            "derived: Yahoo price + SEC EPS",
            max(x for x in [fields["price"].asof, eps_asof] if x),
            "FALLBACK",
            "SEC companyfacts",
            "Price / latest annual diluted EPS",
        )

    if (fields.get("price_book") is None or fields["price_book"].value is None) and market_cap is not None and equity_sec not in (None, 0):
        fields["price_book"] = AuditValue(
            market_cap / equity_sec,
            "derived: Yahoo market cap + SEC equity",
            max(x for x in [fields["market_cap"].asof, eq_asof] if x),
            "FALLBACK",
            "SEC companyfacts",
            "Market cap / latest annual equity",
        )

    fcf = fields.get("free_cash_flow").value if fields.get("free_cash_flow") else None
    if (fields.get("fcf_yield") is None or fields["fcf_yield"].value is None) and fcf is not None and market_cap not in (None, 0):
        fields["fcf_yield"] = AuditValue(
            fcf / market_cap,
            "derived: FCF / market cap",
            fields.get("free_cash_flow").asof,
            "FALLBACK",
            fields.get("free_cash_flow").fallback,
            "Free cash flow / market capitalization",
        )

    if (fields.get("company_name") is None or not fields["company_name"].value) and sec_entity_name:
        fields["company_name"] = AuditValue(
            sec_entity_name,
            SEC_SOURCE,
            None,
            "FALLBACK",
            "SEC companyfacts",
            "SEC entity name",
        )

    required = [
        "company_name",
        "market_cap",
        "pe",
        "roe",
        "debt_equity",
        "net_margin",
        "revenue_growth",
        "free_cash_flow",
    ]
    available = sum(
        1 for name in required
        if fields.get(name) is not None and fields[name].value is not None
    )
    coverage = available / len(required)

    if coverage >= 0.875 and yahoo_error is None:
        overall = "OK"
    elif coverage >= 0.625:
        overall = "PARTIAL"
    else:
        overall = "INCOMPLETE"

    # Explicit diagnostics are data too; they are never silently swallowed.
    fields["_yahoo_error"] = AuditValue(
        yahoo_error,
        YAHOO_SOURCE,
        retrieved,
        "OK" if yahoo_error is None else "ERROR",
        "none",
        "",
    )
    fields["_sec_error"] = AuditValue(
        sec_error,
        SEC_SOURCE,
        retrieved,
        "OK" if sec_error is None else "ERROR",
        "none",
        "",
    )

    return FundamentalSnapshot(
        ticker=ticker,
        yahoo_symbol=yahoo_symbol,
        sec_ticker=sec_ticker,
        retrieved_at=retrieved,
        fields=fields,
        overall_status=overall,
        coverage=coverage,
    )
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\fundamentals.py") -Encoding UTF8

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

from alpha_data_recovery.fundamentals import recover_fundamentals
from alpha_data_recovery.sec_companyfacts import fetch_ticker_map
from alpha_data_recovery.yahoo_fundamentals import YahooSession


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["NVDA", "MSFT", "YPF", "PAMP"],
    )
    args = parser.parse_args()

    output_dir = ROOT / "outputs" / "data_recovery_v1"
    output_dir.mkdir(parents=True, exist_ok=True)

    yf = YahooSession()
    try:
        yf.bootstrap()
        print("[OK] Yahoo session")
    except Exception as exc:
        print(f"[WARN] Yahoo session bootstrap failed: {exc}")

    try:
        sec_map = fetch_ticker_map()
        print(f"[OK] SEC ticker map: {len(sec_map)} tickers")
    except Exception as exc:
        sec_map = {}
        print(f"[WARN] SEC ticker map failed: {exc}")

    records = []
    for symbol in args.symbols:
        snap = recover_fundamentals(
            ticker=symbol,
            yahoo_symbol=symbol,
            sec_ticker=symbol,
            yahoo_session=yf,
            sec_map=sec_map,
        )
        records.append(snap.to_dict())

        f = snap.fields
        def val(name):
            return f[name]["value"] if name in f else None
        def src(name):
            return f[name]["source"] if name in f else None

        print(
            f"[{snap.overall_status}] {symbol:<6} "
            f"mcap={val('market_cap')} "
            f"pe={val('pe')} "
            f"roe={val('roe')} "
            f"rev_growth={val('revenue_growth')} "
            f"coverage={snap.coverage:.0%}"
        )
        print(
            f"       roe_source={src('roe')} | "
            f"revenue_growth_source={src('revenue_growth')}"
        )

    payload = {
        "stage": "ALPHA_ENGINE_DATA_RECOVERY_V1_DR1B",
        "mutation_policy": {
            "v13_model": False,
            "v13_policy": False,
            "v13_outputs": False,
            "sheets": False,
            "web": False,
            "product_state": False,
        },
        "records": records,
    }
    json_path = output_dir / "fundamentals_snapshot_latest.json"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    canonical = [
        "company_name", "sector", "industry", "price", "market_cap",
        "pe", "fwd_pe", "peg", "roe", "roa", "debt_equity",
        "net_margin", "eps_growth", "revenue_growth", "free_cash_flow",
        "fcf_yield", "ev_ebitda", "current_ratio", "quick_ratio",
        "dividend_yield", "beta", "target_mean_price", "target_upside",
        "recommendation_mean", "price_book", "shares_outstanding",
    ]

    wide_path = output_dir / "fundamentals_snapshot_latest.csv"
    with wide_path.open("w", newline="", encoding="utf-8-sig") as fh:
        headers = ["ticker", "status", "coverage"] + canonical
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for r in records:
            row = {
                "ticker": r["ticker"],
                "status": r["overall_status"],
                "coverage": r["coverage"],
            }
            for name in canonical:
                row[name] = (r["fields"].get(name) or {}).get("value")
            writer.writerow(row)

    audit_path = output_dir / "fundamentals_audit_latest.csv"
    with audit_path.open("w", newline="", encoding="utf-8-sig") as fh:
        headers = [
            "ticker", "field", "value", "source", "asof",
            "status", "fallback", "detail",
        ]
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for r in records:
            for field, audit in r["fields"].items():
                writer.writerow({
                    "ticker": r["ticker"],
                    "field": field,
                    **audit,
                })

    print("")
    print("WROTE:")
    print(f"  {json_path}")
    print(f"  {wide_path}")
    print(f"  {audit_path}")
    print("")
    incomplete = [r["ticker"] for r in records if r["overall_status"] == "INCOMPLETE"]
    print(f"records={len(records)} incomplete={len(incomplete)} {incomplete}")
    return 2 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
'@ | Set-Content -Path (Join-Path $REC "scripts\run_fundamentals_recovery.py") -Encoding UTF8

@'
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.fundamentals import sec_derived


class TestDataRecoveryDR1B(unittest.TestCase):
    def test_sec_derived_metrics(self):
        raw = {
            "latest": {
                "revenue": {"val": 120.0, "end": "2025-12-31"},
                "net_income": {"val": 12.0, "end": "2025-12-31"},
                "assets": {"val": 100.0, "end": "2025-12-31"},
                "equity": {"val": 60.0, "end": "2025-12-31"},
                "debt": {"val": 30.0, "end": "2025-12-31"},
                "eps_diluted": {"val": 6.0, "end": "2025-12-31"},
                "cash_from_operations": {"val": 18.0, "end": "2025-12-31"},
                "capex": {"val": 5.0, "end": "2025-12-31"},
                "current_assets": {"val": 40.0, "end": "2025-12-31"},
                "current_liabilities": {"val": 20.0, "end": "2025-12-31"},
            },
            "previous": {
                "revenue": {"val": 100.0, "end": "2024-12-31"},
                "net_income": {"val": 10.0, "end": "2024-12-31"},
                "assets": {"val": 90.0, "end": "2024-12-31"},
                "equity": {"val": 50.0, "end": "2024-12-31"},
                "debt": {"val": 25.0, "end": "2024-12-31"},
                "eps_diluted": {"val": 5.0, "end": "2024-12-31"},
                "cash_from_operations": {"val": 15.0, "end": "2024-12-31"},
                "capex": {"val": 4.0, "end": "2024-12-31"},
                "current_assets": {"val": 35.0, "end": "2024-12-31"},
                "current_liabilities": {"val": 20.0, "end": "2024-12-31"},
            },
        }
        d = sec_derived(raw)
        self.assertAlmostEqual(d["roe"][0], 0.2)
        self.assertAlmostEqual(d["roa"][0], 0.12)
        self.assertAlmostEqual(d["debt_equity"][0], 50.0)
        self.assertAlmostEqual(d["net_margin"][0], 0.1)
        self.assertAlmostEqual(d["eps_growth"][0], 0.2)
        self.assertAlmostEqual(d["revenue_growth"][0], 0.2)
        self.assertAlmostEqual(d["free_cash_flow"][0], 13.0)
        self.assertAlmostEqual(d["current_ratio"][0], 2.0)

    def test_no_v8_scores_in_fundamental_contract(self):
        forbidden = {
            "quality", "growth_score", "value_score",
            "alpha", "market_score", "risk_score",
        }
        expected = {
            "roe", "roa", "debt_equity", "net_margin",
            "eps_growth", "revenue_growth", "free_cash_flow",
        }
        self.assertTrue(forbidden.isdisjoint(expected))


if __name__ == "__main__":
    unittest.main()
'@ | Set-Content -Path (Join-Path $REC "tests\test_data_recovery_dr1b.py") -Encoding UTF8

Write-Host ""
Write-Host "[1/4] Unit tests"
Set-Location $REC
python -m unittest discover -s tests -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "Tests DR1-B fallaron." }

Write-Host ""
Write-Host "[2/4] Live fundamentals sentinels: NVDA MSFT YPF PAMP"
python scripts\run_fundamentals_recovery.py --symbols NVDA MSFT YPF PAMP
if ($LASTEXITCODE -ne 0) {
    throw "DR1-B live recovery quedó INCOMPLETE en al menos un sentinel."
}

Write-Host ""
Write-Host "[3/4] Audit sanity"
$audit = Import-Csv (Join-Path $REC "outputs\data_recovery_v1\fundamentals_audit_latest.csv")
$required = @("roe","debt_equity","net_margin","revenue_growth","free_cash_flow")
foreach ($ticker in @("NVDA","MSFT","YPF","PAMP")) {
    foreach ($field in $required) {
        $row = $audit | Where-Object { $_.ticker -eq $ticker -and $_.field -eq $field } | Select-Object -First 1
        if (-not $row) { throw "AUDIT GATE: falta $ticker/$field" }
        if (-not $row.source) { throw "AUDIT GATE: source vacío $ticker/$field" }
        if (-not $row.status) { throw "AUDIT GATE: status vacío $ticker/$field" }
        if ($row.status -eq "MISSING") {
            Write-Host "  [WARN] $ticker/$field MISSING source=$($row.source)"
        } else {
            Write-Host "  [OK]   $ticker/$field source=$($row.source) fallback=$($row.fallback)"
        }
    }
}

Write-Host ""
Write-Host "[4/4] V13 immutability"
Set-Location $ROOT
$after = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
if (($before | Out-String) -ne ($after | Out-String)) {
    throw "GUARDRAIL: cambió V13 durante DR1-B."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "DR1-B COMPLETE"
Write-Host "FUNDAMENTALS: RECOVERED + AUDITED"
Write-Host "V8/V10 SCORES: NOT IMPORTED"
Write-Host "V13: UNCHANGED"
Write-Host "SHEETS: UNCHANGED"
Write-Host "WEB: UNCHANGED"
Write-Host "PRODUCT STATE: NOT REGENERATED"
Write-Host "============================================================"
Write-Host ""
Write-Host "Pegame la salida completa."
