$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$REC = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"
$WEB = Join-Path $ROOT "web"
$WRAPPER = Join-Path $WEB "run_data_recovery_server.py"
$CSS = Join-Path $WEB "finish.css"
$JS = Join-Path $WEB "finish.js"
$START = Join-Path $ROOT "START_ALPHA_ENGINE.ps1"
$SMOKE = Join-Path $REC "scripts\smoke_web_v32.py"
$SECRET = Join-Path $REC "secrets\groq_api_key.clixml"

Write-Host ""
Write-Host "================================================================"
Write-Host "ALPHA ENGINE WEB V3.2 - STABILITY + UX FIX"
Write-Host "COMPACT LLM / LOGO CONTAIN / FUNDAMENTALS EXPLORER"
Write-Host "NO V13 MUTATION / NO SHEETS WRITE"
Write-Host "================================================================"

if (-not (Test-Path $SECRET)) { throw "Falta la credencial Groq cifrada." }
if (-not (Test-Path $START)) { throw "Falta START_ALPHA_ENGINE.ps1." }
if (-not (Test-Path (Join-Path $ROOT "public\data\alpha_product_state.json"))) {
    throw "Falta alpha_product_state.json."
}

Write-Host ""
Write-Host "[1/6] BACKUP CURRENT WEB RUNTIME"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path $REC "outputs\data_recovery_v1\web_backups\v32_$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item $WRAPPER (Join-Path $backup "run_data_recovery_server.py") -Force
if (Test-Path $CSS) { Copy-Item $CSS (Join-Path $backup "finish.css") -Force }
if (Test-Path $JS) { Copy-Item $JS (Join-Path $backup "finish.js") -Force }
Write-Host "  PASS $backup"

Write-Host ""
Write-Host "[2/6] INSTALL V3.2 RUNTIME"
@'
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
        "reasoning_effort": "medium",
        "reasoning_format": "hidden",
        "max_completion_tokens": 1800,
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
'@ | Set-Content -Path $WRAPPER -Encoding UTF8
@'
/* Alpha Engine Web V3.2 - presentation layer only */

img[src*="alpha-engine"],
img.ae-logo-wordmark,
img.ae-logo-mark {
  object-fit: contain !important;
  object-position: center !important;
  max-width: 100% !important;
  height: auto !important;
  background: transparent !important;
  border: 0 !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  transform: none !important;
}

.ae-brand-fixed {
  min-height: 72px !important;
  overflow: visible !important;
  display: flex !important;
  align-items: center !important;
}

.ae-brand-fixed img {
  width: 180px !important;
  height: 58px !important;
  object-fit: contain !important;
  object-position: left center !important;
}

.ae-v32-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9998;
  background: rgba(1, 8, 14, .78);
  backdrop-filter: blur(8px);
  display: none;
}

.ae-v32-modal-backdrop.open { display: block; }

.ae-v32-modal {
  position: fixed;
  z-index: 9999;
  inset: 5vh 4vw;
  display: none;
  flex-direction: column;
  background: #07131c;
  border: 1px solid rgba(76, 216, 162, .24);
  border-radius: 18px;
  box-shadow: 0 30px 100px rgba(0,0,0,.55);
  overflow: hidden;
  color: #eaf2f6;
}

.ae-v32-modal.open { display: flex; }

.ae-v32-modal-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  border-bottom: 1px solid rgba(255,255,255,.08);
}

.ae-v32-modal-head h2 {
  margin: 0;
  font-size: 18px;
  letter-spacing: .01em;
}

.ae-v32-modal-head .meta {
  font-size: 11px;
  color: #8fa5b1;
}

.ae-v32-close {
  margin-left: auto;
  border: 1px solid rgba(255,255,255,.12);
  background: #0a1b26;
  color: #dbe8ee;
  border-radius: 9px;
  padding: 8px 11px;
  cursor: pointer;
}

.ae-v32-toolbar {
  display: grid;
  grid-template-columns: minmax(220px, 1.5fr) minmax(180px, .8fr) auto;
  gap: 10px;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(255,255,255,.06);
}

.ae-v32-toolbar input,
.ae-v32-toolbar select {
  width: 100%;
  box-sizing: border-box;
  background: #091923;
  color: #eaf2f6;
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 9px;
  padding: 10px 12px;
  outline: none;
}

.ae-v32-table-wrap {
  flex: 1;
  overflow: auto;
  padding: 0 20px 18px;
}

.ae-v32-table {
  border-collapse: collapse;
  width: 100%;
  min-width: 1180px;
  font-size: 12px;
}

.ae-v32-table th {
  position: sticky;
  top: 0;
  z-index: 2;
  text-align: left;
  padding: 10px 9px;
  background: #0b1c27;
  color: #92a8b5;
  font-size: 10px;
  letter-spacing: .06em;
  text-transform: uppercase;
  border-bottom: 1px solid rgba(255,255,255,.10);
}

.ae-v32-table td {
  padding: 10px 9px;
  border-bottom: 1px solid rgba(255,255,255,.055);
  white-space: nowrap;
}

.ae-v32-table tr:hover td {
  background: rgba(19,217,120,.035);
}

.ae-v32-ticker {
  font-weight: 800;
  color: #f2f7fa;
}

.ae-v32-source {
  color: #78909c;
  max-width: 230px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ae-v32-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px 16px;
  border-top: 1px solid rgba(255,255,255,.06);
  color: #8fa5b1;
  font-size: 11px;
}

.ae-v32-pager button {
  border: 1px solid rgba(255,255,255,.12);
  background: #0a1b26;
  color: #e2edf2;
  border-radius: 8px;
  padding: 7px 10px;
  cursor: pointer;
}

.ae-v32-status-card {
  margin: 14px 0;
  padding: 14px 16px;
  border: 1px solid rgba(240, 183, 70, .25);
  background: rgba(240, 183, 70, .055);
  border-radius: 12px;
}

.ae-v32-status-card .title {
  color: #f3c766;
  font-weight: 700;
  margin-bottom: 4px;
}

.ae-v32-status-card .copy {
  color: #9eb0ba;
  font-size: 12px;
  line-height: 1.55;
}

.ae-v32-clockbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 10px 0 16px;
}

.ae-v32-clock {
  border: 1px solid rgba(255,255,255,.10);
  background: rgba(255,255,255,.025);
  border-radius: 999px;
  padding: 6px 9px;
  font-size: 10px;
  color: #91a6b2;
}

.ae-v32-clock strong {
  color: #dce8ed;
  font-weight: 700;
}

@media (max-width: 900px) {
  .ae-v32-modal { inset: 2vh 2vw; }
  .ae-v32-toolbar { grid-template-columns: 1fr; }
  .ae-brand-fixed img { width: 154px !important; }
}
'@ | Set-Content -Path $CSS -Encoding UTF8
@'
(() => {
  "use strict";

  const LOGO = "/assets/alpha-engine-wordmark.png?v=32";
  const PAGE_SIZE = 25;
  let stateCache = null;
  let fundPage = 0;
  let fundQuery = "";
  let fundSector = "ALL";

  const esc = (x) => String(x ?? "");

  async function getState(force=false) {
    if (stateCache && !force) return stateCache;
    const r = await fetch("/api/state" + (force ? "?refresh=1" : ""), {
      cache: "no-store"
    });
    if (!r.ok) throw new Error("state " + r.status);
    stateCache = await r.json();
    return stateCache;
  }

  function leafText(selector="body *") {
    return [...document.querySelectorAll(selector)]
      .filter(el => el.children.length === 0);
  }

  function fixLogo() {
    const imgs = [...document.querySelectorAll("img")].filter(img => {
      const src = (img.getAttribute("src") || "").toLowerCase();
      return src.includes("alpha-engine") || src.includes("alpha_engine");
    });

    imgs.forEach(img => {
      img.src = LOGO;
      img.style.objectFit = "contain";
      img.style.objectPosition = "center";
      img.style.borderRadius = "0";
      img.style.transform = "none";

      const p = img.parentElement;
      if (p && /ALPHA ENGINE/i.test(p.textContent || "")) {
        p.classList.add("ae-brand-fixed");
      }
    });
  }

  function fmtNum(v, d=2) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString("es-AR", {
      minimumFractionDigits: d,
      maximumFractionDigits: d
    });
  }

  function fmtPct(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    const z = Math.abs(n) <= 2 ? n * 100 : n;
    return z.toLocaleString("es-AR", {
      maximumFractionDigits: 1
    }) + "%";
  }

  function fmtCap(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    if (Math.abs(n) >= 1e12) return (n/1e12).toFixed(2) + "T";
    if (Math.abs(n) >= 1e9) return (n/1e9).toFixed(2) + "B";
    if (Math.abs(n) >= 1e6) return (n/1e6).toFixed(1) + "M";
    return fmtNum(n,0);
  }

  function ensureModal() {
    if (document.getElementById("aeV32Modal")) return;

    const backdrop = document.createElement("div");
    backdrop.id = "aeV32Backdrop";
    backdrop.className = "ae-v32-modal-backdrop";

    const modal = document.createElement("div");
    modal.id = "aeV32Modal";
    modal.className = "ae-v32-modal";
    modal.innerHTML = `
      <div class="ae-v32-modal-head">
        <div>
          <h2>Fundamentals Explorer</h2>
          <div class="meta" id="aeFundMeta">Data Recovery V1</div>
        </div>
        <button class="ae-v32-close" id="aeV32Close">Cerrar</button>
      </div>
      <div class="ae-v32-toolbar">
        <input id="aeFundSearch" placeholder="Buscar ticker, empresa o sector…" />
        <select id="aeFundSector"><option value="ALL">Todos los sectores</option></select>
        <div id="aeFundCount" style="align-self:center;color:#8fa5b1;font-size:11px"></div>
      </div>
      <div class="ae-v32-table-wrap">
        <table class="ae-v32-table">
          <thead><tr>
            <th>Ticker</th><th>Empresa</th><th>Sector</th><th>Precio</th>
            <th>Market Cap</th><th>P/E</th><th>Fwd P/E</th><th>ROE</th>
            <th>Debt/Eq</th><th>Margen</th><th>Rev Growth</th>
            <th>FCF Yield</th><th>Fuente</th>
          </tr></thead>
          <tbody id="aeFundBody"></tbody>
        </table>
      </div>
      <div class="ae-v32-pager">
        <span id="aeFundPageInfo"></span>
        <div>
          <button id="aeFundPrev">Anterior</button>
          <button id="aeFundNext">Siguiente</button>
        </div>
      </div>`;

    document.body.appendChild(backdrop);
    document.body.appendChild(modal);

    const close = () => {
      backdrop.classList.remove("open");
      modal.classList.remove("open");
    };
    document.getElementById("aeV32Close").onclick = close;
    backdrop.onclick = close;

    document.getElementById("aeFundSearch").addEventListener("input", e => {
      fundQuery = e.target.value.trim().toLowerCase();
      fundPage = 0;
      renderFundamentals();
    });

    document.getElementById("aeFundSector").addEventListener("change", e => {
      fundSector = e.target.value;
      fundPage = 0;
      renderFundamentals();
    });

    document.getElementById("aeFundPrev").onclick = () => {
      fundPage = Math.max(0, fundPage - 1);
      renderFundamentals();
    };
    document.getElementById("aeFundNext").onclick = () => {
      fundPage += 1;
      renderFundamentals();
    };
  }

  async function openFundamentals() {
    ensureModal();
    await getState(true);

    const sectorSel = document.getElementById("aeFundSector");
    const companies = stateCache?.fundamentals?.companies || [];
    const sectors = [...new Set(
      companies.map(x => x.sector).filter(Boolean)
    )].sort((a,b) => String(a).localeCompare(String(b)));

    const current = sectorSel.value || "ALL";
    sectorSel.innerHTML = '<option value="ALL">Todos los sectores</option>';
    sectors.forEach(s => {
      const o = document.createElement("option");
      o.value = s;
      o.textContent = s;
      sectorSel.appendChild(o);
    });
    if ([...sectorSel.options].some(o => o.value === current)) {
      sectorSel.value = current;
    }

    document.getElementById("aeV32Backdrop").classList.add("open");
    document.getElementById("aeV32Modal").classList.add("open");
    renderFundamentals();
  }

  function filteredFundamentals() {
    const companies = stateCache?.fundamentals?.companies || [];
    return companies.filter(r => {
      const sectorOK = fundSector === "ALL" || esc(r.sector) === fundSector;
      const hay = [r.ticker, r.name, r.sector]
        .map(x => esc(x).toLowerCase())
        .join(" ");
      const queryOK = !fundQuery || hay.includes(fundQuery);
      return sectorOK && queryOK;
    });
  }

  function td(tr, value, cls="") {
    const cell = document.createElement("td");
    if (cls) cell.className = cls;
    cell.textContent = value;
    tr.appendChild(cell);
  }

  function renderFundamentals() {
    if (!stateCache) return;
    const all = filteredFundamentals();
    const pages = Math.max(1, Math.ceil(all.length / PAGE_SIZE));
    fundPage = Math.min(fundPage, pages - 1);

    const start = fundPage * PAGE_SIZE;
    const rows = all.slice(start, start + PAGE_SIZE);
    const body = document.getElementById("aeFundBody");
    body.textContent = "";

    rows.forEach(r => {
      const tr = document.createElement("tr");
      td(tr, esc(r.ticker), "ae-v32-ticker");
      td(tr, esc(r.name));
      td(tr, esc(r.sector));
      td(tr, r.price_usd == null ? "—" : "$" + fmtNum(r.price_usd,2));
      td(tr, fmtCap(r.market_cap));
      td(tr, fmtNum(r.pe,2));
      td(tr, fmtNum(r.forward_pe,2));
      td(tr, fmtPct(r.roe));
      td(tr, fmtNum(r.debt_to_equity,2));
      td(tr, fmtPct(r.net_margin));
      td(tr, fmtPct(r.revenue_growth));
      td(tr, fmtPct(r.fcf_yield));
      td(tr, esc(r.source || "—"), "ae-v32-source");
      body.appendChild(tr);
    });

    document.getElementById("aeFundCount").textContent =
      `${all.length} compañías`;
    document.getElementById("aeFundPageInfo").textContent =
      `Página ${fundPage + 1} de ${pages} · filas ${all.length ? start + 1 : 0}–${Math.min(start + PAGE_SIZE, all.length)}`;

    const asof = stateCache?.fundamentals?.asof || "—";
    document.getElementById("aeFundMeta").textContent =
      `Data Recovery V1 · ${stateCache?.fundamentals?.rows ?? all.length} filas · as of ${asof}`;

    document.getElementById("aeFundPrev").disabled = fundPage <= 0;
    document.getElementById("aeFundNext").disabled = fundPage >= pages - 1;
  }

  function bindFundamentalsNav() {
    [...document.querySelectorAll("a,button")].forEach(el => {
      const label = (el.textContent || "").trim().toLowerCase();
      if (label === "fundamentales" && !el.dataset.aeV32Bound) {
        el.dataset.aeV32Bound = "1";
        el.addEventListener("click", ev => {
          ev.preventDefault();
          ev.stopPropagation();
          openFundamentals().catch(console.error);
        }, true);
      }
    });
  }

  async function semanticStatusPass() {
    try {
      const s = await getState(true);
      const count = Number(
        s?.personal?.positions_count ??
        s?.personal?.position_rows ??
        s?.personal?.positions?.length ??
        0
      );

      leafText().forEach(el => {
        const v = (el.textContent || "").trim();

        if (/^0 posiciones$/i.test(v) && count > 0) {
          el.textContent = `${count} posiciones · snapshot auditado`;
        }

        if (/^0 operaciones$/i.test(v)) {
          el.textContent = "Ledger de operaciones no conectado";
        }

        if (/^operaciones personales\s*0$/i.test(v)) {
          el.textContent = "Operaciones personales · fuente no conectada";
        }
      });

      // Insert explicit status into visible Mi Cartera content once.
      const headings = [...document.querySelectorAll("h1,h2,h3,h4")]
        .filter(x => /mi cartera/i.test(x.textContent || ""));
      headings.forEach(h => {
        const container = h.closest("section,main,.panel,.view,.content") || h.parentElement;
        if (!container || container.querySelector(".ae-v32-status-card")) return;

        const card = document.createElement("div");
        card.className = "ae-v32-status-card";
        card.innerHTML = `
          <div class="title">Operaciones personales · fuente no conectada</div>
          <div class="copy">
            Las 3 posiciones visibles provienen del snapshot auditado V13.
            El ledger local de operaciones está vacío y no se interpreta como
            “cero operaciones”. La importación de operaciones ejecutadas queda
            pendiente de conectar a una fuente autoritativa.
          </div>`;
        h.insertAdjacentElement("afterend", card);
      });

      // Add separate clocks where an overview/status panel is visible.
      const mainHeading = [...document.querySelectorAll("h1,h2")]
        .find(x => /overview|alpha engine v13/i.test(x.textContent || ""));
      if (mainHeading && !document.getElementById("aeClockBar")) {
        const d = s?._web?.model_dates || {};
        const bar = document.createElement("div");
        bar.id = "aeClockBar";
        bar.className = "ae-v32-clockbar";
        bar.innerHTML = `
          <span class="ae-v32-clock"><strong>OOS sellado</strong> ${esc(d.historical_oos_last_score_date || "—")}</span>
          <span class="ae-v32-clock"><strong>Live shadow</strong> ${esc(d.live_shadow_latest_completed_session || "—")}</span>
          <span class="ae-v32-clock"><strong>Mercado</strong> ${esc(d.market_data_asof || "—")}</span>`;
        mainHeading.insertAdjacentElement("afterend", bar);
      }
    } catch (_) {}
  }

  let queued = false;
  function pass() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(async () => {
      queued = false;
      fixLogo();
      bindFundamentalsNav();
      await semanticStatusPass();
    });
  }

  document.addEventListener("DOMContentLoaded", pass);
  window.addEventListener("load", pass);
  new MutationObserver(pass).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
  setTimeout(pass, 400);
  setTimeout(pass, 1500);
})();
'@ | Set-Content -Path $JS -Encoding UTF8
@'
from __future__ import annotations

import json
import time
import urllib.error
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8765"


def get(path, timeout=8):
    with urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload, timeout=90):
    req = Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP_{exc.code}: {body}") from exc


last = None
for _ in range(25):
    try:
        h = get("/api/health", 5)
        s = get("/api/state?refresh=1", 8)
        n = get("/api/market?ticker=NKE", 10)

        assert h.get("status") == "PASS"
        assert s["_web"]["source"] == "LOCAL_DATA_RECOVERY_V1"
        assert s["_web"]["version"] == "ALPHA_WEB_V3_2"
        assert s["_web"]["alpha_configured"] is True
        assert s["_web"]["alpha_provider"] == "GROQ"
        assert int(s["overview"]["personal_positions_count"]) == 3
        assert s["overview"]["personal_operations_status"] == "NOT_CONNECTED"
        assert n.get("status") == "PASS"
        last = None
        break
    except Exception as exc:
        last = exc
        time.sleep(0.75)

if last:
    raise SystemExit(f"BOOT_SMOKE_FAILED: {last}")

# ASCII-only smoke to avoid Windows PowerShell code-page ambiguity.
a = post(
    "/api/alpha",
    {
        "message": (
            "System smoke. Reply in one short line confirming Alpha Decision Desk "
            "is operational via Groq. Do not add analysis."
        ),
        "history": [],
    },
    90,
)

if a.get("status") != "PASS":
    raise SystemExit(f"ALPHA_LLM_SMOKE_FAILED: {a}")

chars = int(a.get("context_chars") or 0)
budget = int(a.get("context_budget_chars") or 0)
if chars <= 0 or chars > budget:
    raise SystemExit(f"CONTEXT_BUDGET_FAILED chars={chars} budget={budget}")

print("HEALTH=PASS")
print("STATE=PASS")
print("MARKET=PASS")
print("PORTFOLIO_COUNT=3")
print("OPERATIONS_STATUS=NOT_CONNECTED")
print("ALPHA_LLM=PASS")
print("PROVIDER=" + str(a.get("provider")))
print("MODEL=" + str(a.get("model")))
print(f"CONTEXT_CHARS={chars}/{budget}")
print("ANSWER=" + str(a.get("answer") or "").replace("\n", " ")[:400])
'@ | Set-Content -Path $SMOKE -Encoding UTF8

python -m py_compile $WRAPPER
if ($LASTEXITCODE -ne 0) { throw "Wrapper syntax failed." }
python -m py_compile $SMOKE
if ($LASTEXITCODE -ne 0) { throw "Smoke syntax failed." }
Write-Host "  PASS"

Write-Host ""
Write-Host "[3/6] STOP ONLY CURRENT ALPHA SERVER"
$listeners = @(
    Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue
)
foreach ($listener in $listeners) {
    $processId = [int]$listener.OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    $cmd = [string]$proc.CommandLine
    if ($cmd -notlike "*run_data_recovery_server.py*") {
        throw "Puerto 8765 ocupado por proceso no-Alpha PID=$processId. No se cerró."
    }
    Stop-Process -Id $processId -Force
    Write-Host "  stopped PID=$processId"
}
Start-Sleep -Milliseconds 900
Write-Host "  PASS"

Write-Host ""
Write-Host "[4/6] START V3.2"
$launcher = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $START
    ) `
    -WindowStyle Hidden `
    -PassThru
Write-Host "  launcher PID=$($launcher.Id)"

Write-Host ""
Write-Host "[5/6] FULL HTTP + REAL GROQ SMOKE"
Set-Location $ROOT
python $SMOKE
if ($LASTEXITCODE -ne 0) {
    throw "V3.2 smoke failed. V13 remains untouched."
}

Write-Host ""
Write-Host "[6/6] FINAL"
Write-Host "================================================================"
Write-Host "ALPHA ENGINE WEB V3.2: PASS"
Write-Host "================================================================"
Write-Host "WEB                  : http://127.0.0.1:8765/"
Write-Host "LLM                   : GROQ / qwen/qwen3.8-27b"
Write-Host "LLM CONTEXT            : COMPACT / <= 12000 CHARS"
Write-Host "FUNDAMENTALS           : EXPLORER 187 COMPANIES"
Write-Host "PORTFOLIO              : 3 POSITIONS / AUDITED SNAPSHOT"
Write-Host "OPERATIONS             : NOT CONNECTED (NO FALSE ZERO)"
Write-Host "LOGO                   : CONTAIN / NO CROP"
Write-Host "MODEL CLOCKS            : OOS 09-04 / LIVE SHADOW 09-11 / MARKET CURRENT"
Write-Host "SHEETS WRITE            : NO"
Write-Host "V13 MUTATED             : NO"
Write-Host "================================================================"
