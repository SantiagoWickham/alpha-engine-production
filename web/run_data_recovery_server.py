from __future__ import annotations

import csv
import importlib.util
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION")
REC = ROOT / "ALPHA_ENGINE_DATA_RECOVERY_V1"
V13 = ROOT / "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
STATE = ROOT / "public" / "data" / "alpha_product_state.json"
MARKET = REC / "outputs" / "data_recovery_v1" / "live" / "mercado_riesgo_live_latest.csv"
MARKET_SUMMARY = REC / "outputs" / "data_recovery_v1" / "live" / "market_refresh_summary_latest.json"
LIVE_SHADOW_SUMMARY = V13 / "outputs" / "live_shadow" / "v13_live_shadow_summary.json"
WEB = ROOT / "web"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

CONTEXT_CHAR_BUDGET = 12_000
HISTORY_TURNS = 4
HISTORY_CHAR_LIMIT = 800

spec = importlib.util.spec_from_file_location(
    "alpha_web_base",
    ROOT / "web" / "server.py",
)
if spec is None or spec.loader is None:
    raise RuntimeError("CANNOT_LOAD_BASE_WEB_SERVER")

base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

sys.path.insert(0, str(REC / "src"))
from alpha_data_recovery.yahoo_chart import recover_market


def read_json_optional(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def num(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


_market_cache_mtime = None
_market_lookup = {}


def load_market_lookup():
    global _market_cache_mtime, _market_lookup
    mtime = MARKET.stat().st_mtime
    if _market_cache_mtime == mtime and _market_lookup:
        return _market_lookup

    with MARKET.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    lookup = {}
    for row in rows:
        canonical = str(row.get("Ticker") or "").strip().upper()
        symbol = str(row.get("Yahoo Symbol") or "").strip().upper()
        if canonical:
            lookup[canonical] = row
        if symbol:
            lookup[symbol] = row

    _market_cache_mtime = mtime
    _market_lookup = lookup
    return lookup


def row_snapshot(requested: str, row: dict) -> dict:
    price = num(row.get("Precio"))
    var = num(row.get("Var 1D"))
    previous = None
    if price is not None and var is not None and (1.0 + var) != 0:
        previous = price / (1.0 + var)

    return base.sanitize({
        "status": "PASS",
        "ticker": requested,
        "symbol": row.get("Yahoo Symbol") or requested,
        "regular_market_price": price,
        "previous_close": previous,
        "change": (
            price - previous
            if price is not None and previous is not None
            else None
        ),
        "change_pct": var,
        "regular_market_time": row.get("Actualización"),
        "source": row.get("Fuente") or "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "data_authority": "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "var_1d_contract": "price / previous_session_daily_close - 1",
        "include_prepost": False,
        "sparkline": [],
    })


def recovery_snapshot(requested: str) -> dict:
    snap, history = recover_market(requested, requested)
    f = snap.fields
    price = f["price"].value
    previous = f["previous_close"].value
    var = f["var_1d"].value

    if snap.overall_status in {"INVALID", "MISSING", "QUARANTINE"}:
        return base.sanitize({
            "status": snap.overall_status,
            "ticker": requested,
            "symbol": requested,
            "regular_market_price": price,
            "previous_close": previous,
            "change_pct": var,
            "source": f["price"].source,
            "data_authority": "ALPHA_ENGINE_DATA_RECOVERY_V1",
            "include_prepost": False,
            "error": f["price"].detail,
        })

    return base.sanitize({
        "status": "PASS",
        "ticker": requested,
        "symbol": snap.market_symbol,
        "regular_market_price": price,
        "previous_close": previous,
        "change": (
            price - previous
            if price is not None and previous is not None
            else None
        ),
        "change_pct": var,
        "regular_market_time": f["price"].asof,
        "source": f["price"].source,
        "data_authority": "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "var_1d_contract": "price / previous_session_daily_close - 1",
        "include_prepost": False,
        "sparkline": [
            {"time": r.get("timestamp"), "close": r.get("close")}
            for r in history[-60:]
            if r.get("close") is not None
        ],
    })


def audited_market_snapshot(ticker, force=False):
    requested = str(ticker or "").strip().upper()
    if not requested:
        raise ValueError("EMPTY_TICKER")
    row = load_market_lookup().get(requested)
    if row is not None:
        return row_snapshot(requested, row)
    return recovery_snapshot(requested)


def model_dates(state: dict) -> dict:
    live = read_json_optional(LIVE_SHADOW_SUMMARY)
    market = read_json_optional(MARKET_SUMMARY)
    return {
        "historical_oos_last_score_date": "2026-09-04",
        "historical_oos_status": "SEALED_OBSERVED_VALIDATION",
        "live_shadow_last_observed": live.get("last_observed"),
        "live_shadow_latest_completed_session": live.get("latest_completed_session"),
        "live_shadow_new_sessions": live.get("new_sessions"),
        "live_shadow_status": live.get("status"),
        "market_data_asof": market.get("asof"),
        "product_state_model_asof": (state.get("system") or {}).get("asof"),
        "note": (
            "Historical OOS, live-shadow model state, and current market data "
            "are separate clocks. Current market refresh does not itself rerun "
            "the sealed V13 scorer."
        ),
    }


def local_only_state(force=False):
    if not STATE.exists():
        raise FileNotFoundError(f"MISSING_PRODUCT_STATE: {STATE}")

    state = json.loads(STATE.read_text(encoding="utf-8"))
    state = base.sanitize(state)

    if state.get("schema") != "ALPHA_ENGINE_PRODUCT_STATE_V1":
        raise RuntimeError("INVALID_PRODUCT_STATE_SCHEMA")
    if (state.get("system") or {}).get("status") != "PASS":
        raise RuntimeError("PRODUCT_STATE_NOT_PASS")

    personal = dict(state.get("personal") or {})
    positions = personal.get("positions") or []
    overview = dict(state.get("overview") or {})

    overview["personal_positions_count"] = int(
        personal.get("positions_count")
        or personal.get("position_rows")
        or len(positions)
        or 0
    )
    # Do not misrepresent an unconnected source as zero activity.
    overview["personal_operations_count"] = None
    overview["personal_operations_status"] = "NOT_CONNECTED"

    personal["operations_status"] = "NOT_CONNECTED"
    personal["operations_source"] = "PRODUCT/personal_portfolio_ledger.json"
    personal["operations_note"] = (
        "The local operations ledger is an empty placeholder. "
        "Recent executed operations are not connected to the recovered runtime."
    )
    personal["operations_count"] = None
    state["personal"] = personal
    state["overview"] = overview

    state["_web"] = {
        "source": "LOCAL_DATA_RECOVERY_V1",
        "version": "ALPHA_WEB_V3_2",
        "alpha_configured": bool(GROQ_API_KEY),
        "alpha_provider": "GROQ",
        "alpha_model": GROQ_MODEL,
        "market_source": "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "market_prepost": False,
        "model_dates": model_dates(state),
    }
    return state


def ticker_of(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(
        row.get("ticker")
        or row.get("Ticker")
        or row.get("symbol")
        or ""
    ).strip().upper()


def detected_tickers(state: dict, message: str) -> list[str]:
    words = {
        w.strip(".,;:()[]{}!?$\"'").upper()
        for w in re.split(r"\s+", message or "")
        if w.strip()
    }

    known = set()
    for section in (
        state.get("universe") or [],
        (state.get("v13") or {}).get("recommendations") or [],
        (state.get("byma") or {}).get("recommendations") or [],
        (state.get("personal") or {}).get("positions") or [],
        (state.get("fundamentals") or {}).get("companies") or [],
        (state.get("market") or {}).get("assets") or [],
    ):
        for row in section:
            t = ticker_of(row)
            if t:
                known.add(t)

    return sorted(words.intersection(known))[:6]


def top_v13(state: dict, limit: int = 10) -> list[dict]:
    rows = [
        r for r in ((state.get("v13") or {}).get("recommendations") or [])
        if isinstance(r, dict)
    ]
    rows.sort(
        key=lambda r: float(r.get("target_weight") or 0),
        reverse=True,
    )
    out = []
    for r in rows[:limit]:
        out.append({
            "ticker": r.get("ticker"),
            "target_weight": r.get("target_weight"),
            "expected_active_total": r.get("expected_active_total"),
            "entry_ok": r.get("entry_ok"),
            "model_intent": r.get("model_intent"),
        })
    return out


def byma_for_tickers(state: dict, tickers: set[str]) -> list[dict]:
    out = []
    for r in ((state.get("byma") or {}).get("recommendations") or []):
        if not isinstance(r, dict):
            continue
        t = ticker_of(r)
        if t in tickers:
            out.append({
                "ticker": t,
                "vehicle_available": r.get("vehicle_available"),
                "vehicle": r.get("vehicle"),
                "byma_ticker": r.get("byma_ticker"),
                "ratio": r.get("ratio"),
                "actual_weight": r.get("actual_weight"),
                "weight_error": r.get("weight_error"),
                "reason": r.get("reason"),
            })
    return out


def relevant_rows(rows: list, tickers: set[str], fields: list[str]) -> list[dict]:
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if ticker_of(r) not in tickers:
            continue
        out.append({k: r.get(k) for k in fields if k in r})
    return out


def compact_personal(state: dict) -> dict:
    p = state.get("personal") or {}
    return {
        "status": p.get("status"),
        "valuation_mode": p.get("valuation_mode"),
        "position_rows": p.get("position_rows") or p.get("positions_count"),
        "positions": [
            {
                "ticker": x.get("ticker"),
                "quantity": x.get("quantity"),
                "market_value_usd": x.get("market_value_usd"),
                "current_weight": x.get("current_weight"),
                "unrealized_pnl_usd": x.get("unrealized_pnl_usd"),
            }
            for x in (p.get("positions") or [])[:10]
            if isinstance(x, dict)
        ],
        "cash_by_currency": p.get("cash_by_currency"),
        "operations_status": p.get("operations_status"),
        "operations_note": p.get("operations_note"),
    }


def compact_context(state: dict, message: str) -> dict:
    requested = detected_tickers(state, message)
    requested_set = set(requested)
    tops = top_v13(state, 10)
    top_set = {str(x.get("ticker") or "").upper() for x in tops}
    focus = requested_set or top_set

    fund_rows = relevant_rows(
        (state.get("fundamentals") or {}).get("companies") or [],
        requested_set,
        [
            "ticker", "name", "sector", "price_usd", "market_cap",
            "pe", "forward_pe", "peg", "roe", "roa",
            "debt_to_equity", "net_margin", "eps_growth",
            "revenue_growth", "fcf", "fcf_yield", "ev_ebitda",
            "current_ratio", "quick_ratio", "dividend_yield",
            "target_price", "upside", "analyst_recommendation",
            "price_to_book", "source",
        ],
    )

    market_rows = relevant_rows(
        (state.get("market") or {}).get("assets") or [],
        requested_set,
        [
            "ticker", "market_symbol", "price", "var_1d",
            "ret_1m", "ret_3m", "ret_6m", "ret_12m",
            "rsi14", "vol_20d", "vol_60d", "max_drawdown_1y",
            "beta_6m", "corr_6m", "dist_52w_high",
            "coverage", "source", "updated_at",
        ],
    )

    v13_specific = relevant_rows(
        (state.get("v13") or {}).get("recommendations") or [],
        requested_set,
        [
            "ticker", "target_weight", "expected_active_total",
            "entry_ok", "model_intent",
        ],
    )

    context = {
        "system": {
            "status": (state.get("system") or {}).get("status"),
            "authority": (state.get("system") or {}).get("authority"),
            "local_implementation": (state.get("system") or {}).get("local_implementation"),
            "seal_id": (state.get("system") or {}).get("seal_id"),
            "holdout_verdict": (state.get("system") or {}).get("holdout_verdict"),
            "model_asof": (state.get("system") or {}).get("asof"),
        },
        "dates": model_dates(state),
        "overview": state.get("overview") or {},
        "v13": {
            "performance": (state.get("v13") or {}).get("performance") or {},
            "top_exposures": tops,
            "requested_tickers": v13_specific,
        },
        "byma": {
            "performance": (state.get("byma") or {}).get("performance") or {},
            "requested_or_top": byma_for_tickers(state, focus),
        },
        "personal": compact_personal(state),
        "data_coverage": {
            "market_rows": (state.get("market") or {}).get("rows"),
            "market_asof": (state.get("market") or {}).get("asof"),
            "fundamental_rows": (state.get("fundamentals") or {}).get("rows"),
            "fundamentals_asof": (state.get("fundamentals") or {}).get("asof"),
            "fundamental_exceptions": (state.get("fundamentals") or {}).get("exceptions"),
        },
        "requested": {
            "tickers": requested,
            "fundamentals": fund_rows,
            "market": market_rows,
        },
    }

    raw = json.dumps(
        base.sanitize(context),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    if len(raw) > CONTEXT_CHAR_BUDGET:
        # Defensive fallback: preserve authority, dates, top exposures,
        # personal state and requested ticker data.
        context = {
            "system": context["system"],
            "dates": context["dates"],
            "overview": context["overview"],
            "v13": {
                "top_exposures": context["v13"]["top_exposures"][:8],
                "requested_tickers": context["v13"]["requested_tickers"],
            },
            "personal": context["personal"],
            "data_coverage": context["data_coverage"],
            "requested": context["requested"],
            "context_trimmed": True,
        }

    return base.sanitize(context)


def recent_history(history):
    out = []
    for item in (history or [])[-HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        content = content.strip()
        if content:
            out.append({
                "role": role,
                "content": content[:HISTORY_CHAR_LIMIT],
            })
    return out


def ask_alpha_groq(state, message, history):
    if not GROQ_API_KEY:
        return {
            "status": "NOT_CONFIGURED",
            "answer": "Alpha Decision Desk necesita GROQ_API_KEY.",
            "model": GROQ_MODEL,
            "provider": "GROQ",
        }

    context = compact_context(state, message)
    context_json = json.dumps(
        context,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(context_json) > CONTEXT_CHAR_BUDGET + 1000:
        raise RuntimeError(
            f"CONTEXT_BUDGET_BREACH chars={len(context_json)}"
        )

    instructions = """
Sos Alpha, el Decision Desk de Alpha Engine.
Respondé en español claro, institucional y directo.

AUTORIDAD
- V13 IDEAL es la autoridad cuantitativa sellada.
- BYMA es una traducción local separada.
- Mercado y fundamentales vienen de Data Recovery V1.
- La cartera personal es independiente del modelo.
- No existen órdenes automáticas.

REGLAS
- Nunca inventes datos.
- Diferenciá: OOS histórico sellado, live shadow, mercado actual y snapshot personal.
- Si operations_status es NOT_CONNECTED, no digas que hubo cero operaciones: decí que el ledger no está conectado.
- La cartera personal está en AUDITED_SNAPSHOT_NOT_LIVE hasta validar BYMA+MEP live.
- No reutilices scores V8/V10.
- Si el dato pedido no está en el contexto, decilo.
- El LLM interpreta; no reemplaza cálculos del motor.
- Para exposiciones, usá target_weight del bloque v13.top_exposures.
- Cuando sea útil: SEÑAL / EVIDENCIA / RIESGOS / LECTURA.
""".strip()

    messages = [{"role": "system", "content": instructions}]
    messages.extend(recent_history(history))
    messages.append({
        "role": "user",
        "content": (
            "CONTEXTO AUDITADO:\n"
            + context_json
            + "\n\nCONSULTA:\n"
            + str(message).strip()
        ),
    })

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "reasoning_effort": "low",
        "reasoning_format": "hidden",
        "max_completion_tokens": 640,
    }

    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + GROQ_API_KEY,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "AlphaEngineDecisionDesk/3.2",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=75) as resp:
            raw = resp.read()
            result = json.loads(raw.decode("utf-8", errors="strict"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        body = raw.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GROQ_HTTP_{exc.code}: {body[:1200]}"
        ) from exc

    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("GROQ_EMPTY_CHOICES")

    answer = str(
        ((choices[0] or {}).get("message") or {}).get("content")
        or ""
    ).strip()
    if not answer:
        raise RuntimeError("GROQ_EMPTY_ANSWER")

    return {
        "status": "PASS",
        "answer": answer,
        "model": result.get("model") or GROQ_MODEL,
        "provider": "GROQ",
        "context_chars": len(context_json),
        "context_budget_chars": CONTEXT_CHAR_BUDGET,
    }


base.load_state = local_only_state
base.yahoo_market_snapshot = audited_market_snapshot
base.ask_alpha = ask_alpha_groq

# Compatibility with original health banner.
base.OPENAI_API_KEY = GROQ_API_KEY
base.OPENAI_MODEL = GROQ_MODEL

_original_do_get = base.Handler.do_GET


def serve_index_v32(self):
    html = (WEB / "index.html").read_text(encoding="utf-8")

    if "/v3.css" not in html:
        html = html.replace(
            "</head>",
            '<link rel="stylesheet" href="/v3.css?v=3">\n</head>',
        )
    html = html.replace(
        "</head>",
        '<link rel="stylesheet" href="/finish.css?v=32">\n</head>',
    )

    if "/v3.js" not in html:
        html = html.replace(
            "</body>",
            '<script src="/v3.js?v=3"></script>\n</body>',
        )
    html = html.replace(
        "</body>",
        '<script src="/finish.js?v=32"></script>\n</body>',
    )

    self.send_bytes(
        html.encode("utf-8"),
        "text/html; charset=utf-8",
    )


def do_get_v32(self):
    path = urllib.parse.urlparse(self.path).path
    extra = {
        "/finish.css": (WEB / "finish.css", "text/css; charset=utf-8"),
        "/finish.js": (WEB / "finish.js", "application/javascript; charset=utf-8"),
        "/assets/alpha-engine-wordmark.png": (
            WEB / "assets" / "alpha-engine-wordmark.png",
            "image/png",
        ),
    }
    if path in extra:
        target, mime = extra[path]
        if not target.exists():
            self.send_error(404)
            return
        self.send_bytes(target.read_bytes(), mime)
        return

    return _original_do_get(self)


def do_post_v32(self):
    parsed = urllib.parse.urlparse(self.path)
    if parsed.path != "/api/alpha":
        self.send_error(404)
        return

    try:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 500_000:
            raise RuntimeError("INVALID_BODY_SIZE")

        raw = self.rfile.read(length)

        # Browsers use UTF-8. cp1252 fallback makes Windows PowerShell
        # diagnostic calls non-fatal without changing browser behavior.
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")

        payload = json.loads(text)
        message = str(payload.get("message") or "").strip()
        if not message:
            raise RuntimeError("EMPTY_MESSAGE")

        result = ask_alpha_groq(
            local_only_state(),
            message,
            payload.get("history") or [],
        )
        self.send_json(result)
    except Exception as exc:
        self.send_json(
            {
                "status": "FAIL",
                "error": str(exc),
            },
            500,
        )


base.Handler.serve_index = serve_index_v32
base.Handler.do_GET = do_get_v32
base.Handler.do_POST = do_post_v32

if __name__ == "__main__":
    base.main()

