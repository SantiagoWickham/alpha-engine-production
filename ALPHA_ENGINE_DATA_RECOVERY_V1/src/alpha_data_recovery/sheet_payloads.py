from __future__ import annotations

from typing import Any

from .market_sheet_metrics import compute_sheet_market_metrics


FUND_HEADERS = [
    "Ticker","Nombre","Sector","Precio USD","Market Cap","P/E","Fwd P/E","PEG",
    "ROE","ROA","Debt/Eq","Margen Neto","EPS Growth","Revenue Growth","FCF",
    "FCF Yield","EV/EBITDA","Current Ratio","Quick Ratio","Dividend Yield",
    "Beta Yahoo","Target Price","Upside","Recom. Analistas",
    "Score Calidad (Shrink)","Score Crecimiento (Shrink)","Score Valuación (Shrink)",
    "Fuente","Price / Book",
]

MKT_HEADERS = [
    "Ticker","Yahoo Symbol","Benchmark","Precio","Var 1D","Ret 1M","Ret 3M",
    "Ret 6M","Ret 12M","SMA20","SMA50","SMA200","Dist SMA20","Dist SMA50",
    "Dist SMA200","RSI14","Vol 20D","Vol 60D","Vol 1A","Downside Dev 60D",
    "Max Drawdown 1A","Avg Vol 20D","Dollar Vol 20D","Vol 20/60","RS 3M",
    "RS 6M","Beta 6M","Corr 6M","Dist 52W High","Score Tendencia","Score RS",
    "Score Participación","Score Mercado","Score Volatilidad","Score Tail Risk",
    "Score Liquidez","Beta/Corr Info Score","RISK SCORE","Cobertura Mercado",
    "Fuente","Actualización",
]

FUND_SCORE_COLUMNS = {
    "Score Calidad (Shrink)",
    "Score Crecimiento (Shrink)",
    "Score Valuación (Shrink)",
}

MKT_SCORE_COLUMNS = {
    "Score Tendencia","Score RS","Score Participación","Score Mercado",
    "Score Volatilidad","Score Tail Risk","Score Liquidez",
    "Beta/Corr Info Score","RISK SCORE",
}


def _field(record: dict[str, Any], name: str) -> Any:
    return ((record.get("fields") or {}).get(name) or {}).get("value")


def _sources(record: dict[str, Any]) -> str:
    names = [
        "pe","roe","debt_equity","net_margin","revenue_growth","free_cash_flow"
    ]
    sources = {
        ((record.get("fields") or {}).get(n) or {}).get("source")
        for n in names
        if ((record.get("fields") or {}).get(n) or {}).get("value") is not None
    }
    sources.discard(None)
    if any("SEC" in str(s) for s in sources) and any("Yahoo" in str(s) for s in sources):
        return "Yahoo + SEC"
    if sources:
        return " | ".join(sorted(str(s) for s in sources))
    return ""


def fundamental_payload_row(
    universe,
    record: dict[str, Any],
) -> dict[str, Any]:
    currency = _field(record, "currency")
    provider_price = _field(record, "price")
    price_usd = provider_price if str(currency or "").upper() == "USD" else None

    return dict(zip(FUND_HEADERS, [
        universe.canonical_ticker,
        _field(record, "company_name"),
        universe.sector,
        price_usd,
        _field(record, "market_cap"),
        _field(record, "pe"),
        _field(record, "fwd_pe"),
        _field(record, "peg"),
        _field(record, "roe"),
        _field(record, "roa"),
        _field(record, "debt_equity"),
        _field(record, "net_margin"),
        _field(record, "eps_growth"),
        _field(record, "revenue_growth"),
        _field(record, "free_cash_flow"),
        _field(record, "fcf_yield"),
        _field(record, "ev_ebitda"),
        _field(record, "current_ratio"),
        _field(record, "quick_ratio"),
        _field(record, "dividend_yield"),
        _field(record, "beta"),
        _field(record, "target_mean_price"),
        _field(record, "target_upside"),
        _field(record, "recommendation_mean"),
        None,
        None,
        None,
        _sources(record),
        _field(record, "price_book"),
    ]))


def market_payload_row(
    universe,
    snapshot: dict[str, Any] | None,
    asset_rows: list[dict[str, Any]] | None,
    benchmark_rows: list[dict[str, Any]] | None,
    error: str | None = None,
) -> dict[str, Any]:
    if not snapshot or not asset_rows:
        row = {h: None for h in MKT_HEADERS}
        row["Ticker"] = universe.canonical_ticker
        row["Yahoo Symbol"] = universe.market_symbol
        row["Benchmark"] = universe.benchmark
        row["Cobertura Mercado"] = 0.0
        row["Fuente"] = f"ERROR: {error}" if error else "MISSING"
        return row

    f = snapshot["fields"]
    m = snapshot["metrics"]
    extra = compute_sheet_market_metrics(asset_rows, benchmark_rows)

    def fv(name):
        return (f.get(name) or {}).get("value")

    def mv(name):
        return (m.get(name) or {}).get("value")

    return dict(zip(MKT_HEADERS, [
        universe.canonical_ticker,
        universe.market_symbol,
        universe.benchmark,
        fv("price"),
        fv("var_1d"),
        mv("ret_1m"),
        mv("ret_3m"),
        mv("ret_6m"),
        mv("ret_12m"),
        mv("sma_20"),
        mv("sma_50"),
        mv("sma_200"),
        extra["dist_sma20"],
        extra["dist_sma50"],
        extra["dist_sma200"],
        mv("rsi_14"),
        mv("vol_20d"),
        mv("vol_60d"),
        mv("vol_1y"),
        mv("downside_vol_60d"),
        mv("max_drawdown_1y"),
        extra["avg_vol_20d"],
        extra["dollar_volume_20d_aligned"],
        extra["relative_volume_20v60_aligned"],
        extra["rs_3m"],
        extra["rs_6m"],
        extra["beta_6m"],
        extra["corr_6m"],
        extra["dist_52w_high"],
        None,None,None,None,None,None,None,None,None,
        snapshot.get("coverage"),
        (f.get("price") or {}).get("source"),
        (f.get("price") or {}).get("asof"),
    ]))
