from __future__ import annotations

import concurrent.futures
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
import webbrowser

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

STATE_FILE = (
    ROOT
    / "public"
    / "data"
    / "alpha_product_state.json"
)

HOST = "127.0.0.1"
PORT = 8765

STATE_CACHE_SECONDS = 30
MARKET_CACHE_SECONDS = 60

OPENAI_API_KEY = os.environ.get(
    "OPENAI_API_KEY",
    "",
).strip()

OPENAI_MODEL = os.environ.get(
    "ALPHA_OPENAI_MODEL",
    "gpt-5.6-sol",
).strip()

OPENAI_URL = (
    "https://api.openai.com/v1/responses"
)

_state_cache = None
_state_cache_time = 0.0
_state_lock = threading.Lock()

_market_cache = {}
_market_lock = threading.Lock()


# ============================================================
# GENERIC
# ============================================================

def sanitize(value):

    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return (
            value
            if math.isfinite(value)
            else None
        )

    if isinstance(value, str):

        if value.strip().lower() in {
            "nan",
            "+nan",
            "-nan",
            "none",
            "null",
            "<na>",
        }:
            return None

        return value

    if isinstance(value, list):
        return [
            sanitize(v)
            for v in value
        ]

    if isinstance(value, dict):
        return {
            str(k): sanitize(v)
            for k, v in value.items()
        }

    return str(value)


def safe_number(value):

    if isinstance(value, bool):
        return None

    try:
        number = float(value)

        if math.isfinite(number):
            return number

    except Exception:
        pass

    return None


def utc_iso(timestamp):

    if not timestamp:
        return None

    try:
        return (
            datetime
            .fromtimestamp(
                timestamp,
                tz=timezone.utc,
            )
            .isoformat()
        )

    except Exception:
        return None


# ============================================================
# PRODUCT STATE
# ============================================================

def remote_state():

    subprocess.run(
        [
            "git",
            "fetch",
            "origin",
            "main",
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    result = subprocess.run(
        [
            "git",
            "show",
            "origin/main:public/data/alpha_product_state.json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )

    return json.loads(
        result.stdout.decode(
            "utf-8"
        )
    )


def local_state():

    if not STATE_FILE.exists():

        raise FileNotFoundError(
            f"MISSING PRODUCT STATE: {STATE_FILE}"
        )

    return json.loads(
        STATE_FILE.read_text(
            encoding="utf-8"
        )
    )


def load_state(force=False):

    global _state_cache
    global _state_cache_time

    with _state_lock:

        now = time.time()

        if (
            not force
            and _state_cache is not None
            and now - _state_cache_time
            < STATE_CACHE_SECONDS
        ):
            return _state_cache

        source = "GITHUB_ORIGIN_MAIN"

        try:
            state = remote_state()

        except Exception:
            source = "LOCAL_FALLBACK"
            state = local_state()

        state = sanitize(
            state
        )

        if (
            state.get("schema")
            !=
            "ALPHA_ENGINE_PRODUCT_STATE_V1"
        ):
            raise RuntimeError(
                "INVALID_PRODUCT_STATE_SCHEMA"
            )

        state["_web"] = {
            "source":
                source,

            "version":
                "ALPHA_WEB_V3",

            "alpha_configured":
                bool(
                    OPENAI_API_KEY
                ),

            "alpha_model":
                OPENAI_MODEL,

            "market_source":
                "Yahoo Finance Chart",

            "market_prepost":
                False,
        }

        _state_cache = state
        _state_cache_time = now

        return state


# ============================================================
# LIVE REGULAR MARKET DATA
# ============================================================

def yahoo_market_snapshot(
    ticker,
    force=False,
):

    ticker = (
        str(ticker)
        .strip()
        .upper()
    )

    if not ticker:
        raise ValueError(
            "EMPTY_TICKER"
        )

    now = time.time()

    with _market_lock:

        cached = _market_cache.get(
            ticker
        )

        if (
            not force
            and cached
            and now - cached["cached_at"]
            < MARKET_CACHE_SECONDS
        ):
            return cached["data"]

    encoded = urllib.parse.quote(
        ticker,
        safe="",
    )

    url = (
        "https://query1.finance.yahoo.com/"
        f"v8/finance/chart/{encoded}"
        "?range=1y"
        "&interval=1d"
        "&includePrePost=false"
        "&events=div%2Csplits"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/153 Safari/537.36",

            "Accept":
                "application/json,text/plain,*/*",
        },
        method="GET",
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=15,
        ) as response:

            raw = (
                response
                .read()
                .decode(
                    "utf-8"
                )
            )

    except Exception as exc:

        return {
            "status":
                "UNAVAILABLE",

            "ticker":
                ticker,

            "error":
                str(exc),

            "source":
                "Yahoo Finance Chart",

            "include_prepost":
                False,
        }

    payload = json.loads(
        raw
    )

    chart = payload.get(
        "chart",
        {}
    )

    error = chart.get(
        "error"
    )

    results = chart.get(
        "result"
    ) or []

    if error or not results:

        return {
            "status":
                "UNAVAILABLE",

            "ticker":
                ticker,

            "error":
                error,

            "source":
                "Yahoo Finance Chart",

            "include_prepost":
                False,
        }

    result = results[0]

    meta = (
        result.get(
            "meta",
            {}
        )
        or {}
    )

    timestamps = (
        result.get(
            "timestamp"
        )
        or []
    )

    indicators = (
        result.get(
            "indicators",
            {}
        )
        or {}
    )

    quotes = (
        indicators.get(
            "quote"
        )
        or [{}]
    )

    quote = quotes[0] or {}

    closes = (
        quote.get(
            "close"
        )
        or []
    )

    volumes = (
        quote.get(
            "volume"
        )
        or []
    )

    valid = []

    for index, value in enumerate(
        closes
    ):

        price = safe_number(
            value
        )

        if price is None:
            continue

        timestamp = (
            timestamps[index]
            if index < len(timestamps)
            else None
        )

        valid.append(
            (
                timestamp,
                price,
            )
        )

    regular_price = safe_number(
        meta.get(
            "regularMarketPrice"
        )
    )

    if (
        regular_price is None
        and valid
    ):
        regular_price = valid[-1][1]

    previous_close = safe_number(
        meta.get(
            "chartPreviousClose"
        )
    )

    if (
        previous_close is None
        and len(valid) >= 2
    ):
        previous_close = valid[-2][1]

    change = None
    change_pct = None

    if (
        regular_price is not None
        and previous_close not in {
            None,
            0,
        }
    ):

        change = (
            regular_price
            - previous_close
        )

        change_pct = (
            change
            / previous_close
        )

    one_year_values = [
        price
        for _, price in valid
    ]

    year_high = (
        max(one_year_values)
        if one_year_values
        else None
    )

    year_low = (
        min(one_year_values)
        if one_year_values
        else None
    )

    last_volume = None

    for volume in reversed(
        volumes
    ):

        volume_number = safe_number(
            volume
        )

        if volume_number is not None:

            last_volume = (
                volume_number
            )

            break

    sparkline = [
        {
            "time":
                utc_iso(timestamp),

            "close":
                price,
        }
        for timestamp, price
        in valid[-60:]
    ]

    data = sanitize({
        "status":
            "PASS",

        "ticker":
            ticker,

        "symbol":
            meta.get(
                "symbol"
            )
            or ticker,

        "name":
            meta.get(
                "shortName"
            )
            or meta.get(
                "longName"
            ),

        "currency":
            meta.get(
                "currency"
            ),

        "exchange":
            (
                meta.get(
                    "fullExchangeName"
                )
                or meta.get(
                    "exchangeName"
                )
            ),

        "instrument_type":
            meta.get(
                "instrumentType"
            ),

        "regular_market_price":
            regular_price,

        "previous_close":
            previous_close,

        "change":
            change,

        "change_pct":
            change_pct,

        "regular_market_time":
            utc_iso(
                meta.get(
                    "regularMarketTime"
                )
            ),

        "timezone":
            meta.get(
                "exchangeTimezoneName"
            ),

        "fifty_two_week_high":
            year_high,

        "fifty_two_week_low":
            year_low,

        "last_volume":
            last_volume,

        "source":
            "Yahoo Finance Chart",

        "include_prepost":
            False,

        "snapshot_generated_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "sparkline":
            sparkline,
    })

    with _market_lock:

        _market_cache[
            ticker
        ] = {
            "cached_at":
                now,

            "data":
                data,
        }

    return data


def market_batch(
    tickers,
):

    unique = []

    for ticker in tickers:

        ticker = (
            str(ticker)
            .strip()
            .upper()
        )

        if (
            ticker
            and ticker
            not in unique
        ):

            unique.append(
                ticker
            )

    unique = unique[:24]

    output = {}

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = {
            executor.submit(
                yahoo_market_snapshot,
                ticker,
            ):
                ticker

            for ticker in unique
        }

        for future in concurrent.futures.as_completed(
            futures
        ):

            ticker = futures[
                future
            ]

            try:

                output[ticker] = (
                    future.result()
                )

            except Exception as exc:

                output[ticker] = {
                    "status":
                        "UNAVAILABLE",

                    "ticker":
                        ticker,

                    "error":
                        str(exc),
                }

    return output


# ============================================================
# TICKER INTELLIGENCE
# ============================================================

def ticker_of(row):

    if not isinstance(
        row,
        dict,
    ):
        return None

    for key in (
        "ticker",
        "Ticker",
        "symbol",
        "Symbol",
    ):

        value = row.get(
            key
        )

        if value:

            return (
                str(value)
                .strip()
                .upper()
            )

    return None


def ticker_rows(
    rows,
    ticker,
):

    return [
        sanitize(row)

        for row in (
            rows
            or []
        )

        if ticker_of(row)
        == ticker
    ]


def recursive_matches(
    obj,
    ticker,
    path="",
    found=None,
):

    if found is None:
        found = []

    if len(found) >= 20:
        return found

    if isinstance(
        obj,
        dict,
    ):

        if ticker_of(
            obj
        ) == ticker:

            found.append({
                "path":
                    path or "root",

                "data":
                    sanitize(obj),
            })

        for key, value in obj.items():

            recursive_matches(
                value,
                ticker,
                (
                    f"{path}.{key}"
                    if path
                    else str(key)
                ),
                found,
            )

            if len(found) >= 20:
                break

    elif isinstance(
        obj,
        list,
    ):

        for index, value in enumerate(
            obj
        ):

            recursive_matches(
                value,
                ticker,
                f"{path}[{index}]",
                found,
            )

            if len(found) >= 20:
                break

    return found


def ticker_view(
    state,
    ticker,
):

    ticker = (
        ticker
        .strip()
        .upper()
    )

    v13 = ticker_rows(
        state
        .get(
            "v13",
            {}
        )
        .get(
            "recommendations",
            [],
        ),
        ticker,
    )

    byma = []

    for row in (
        state
        .get(
            "byma",
            {}
        )
        .get(
            "recommendations",
            [],
        )
    ):

        if not isinstance(
            row,
            dict,
        ):
            continue

        foreign = (
            str(
                row.get(
                    "ticker"
                )
                or ""
            )
            .upper()
        )

        local = (
            str(
                row.get(
                    "byma_ticker"
                )
                or ""
            )
            .upper()
        )

        if ticker in {
            foreign,
            local,
        }:

            byma.append(
                sanitize(row)
            )

    personal = ticker_rows(
        state
        .get(
            "personal",
            {}
        )
        .get(
            "positions",
            [],
        ),
        ticker,
    )

    universe = ticker_rows(
        state.get(
            "universe",
            [],
        ),
        ticker,
    )

    fundamentals = (
        state.get(
            "fundamentals",
            {}
        )
        or {}
    )

    companies = (
        fundamentals.get(
            "companies",
            [],
        )
        or []
    )

    fundamental = ticker_rows(
        companies,
        ticker,
    )

    fundamental_matches = (
        recursive_matches(
            fundamentals,
            ticker,
            "fundamentals",
        )
    )

    market_matches = (
        recursive_matches(
            state.get(
                "market",
                {},
            ),
            ticker,
            "product_state.market",
        )
    )

    live_market = (
        yahoo_market_snapshot(
            ticker
        )
    )

    return sanitize({
        "status":
            "PASS",

        "ticker":
            ticker,

        "market":
            live_market,

        "coverage": {
            "market":
                live_market.get(
                    "status"
                )
                == "PASS",

            "v13":
                bool(v13),

            "byma":
                bool(byma),

            "personal":
                bool(personal),

            "fundamentals":
                bool(
                    fundamental
                    or fundamental_matches
                ),
        },

        "v13":
            (
                v13[0]
                if v13
                else None
            ),

        "byma":
            byma,

        "personal":
            (
                personal[0]
                if personal
                else None
            ),

        "universe":
            (
                universe[0]
                if universe
                else None
            ),

        "fundamentals":
            (
                fundamental[0]
                if fundamental
                else None
            ),

        "fundamental_matches":
            fundamental_matches,

        "product_state_market_matches":
            market_matches,
    })


# ============================================================
# ALPHA DECISION DESK
# ============================================================

def top_recommendations(
    state,
    limit=40,
):

    rows = (
        state
        .get(
            "v13",
            {}
        )
        .get(
            "recommendations",
            [],
        )
        or []
    )

    positive = []

    for row in rows:

        if not isinstance(
            row,
            dict,
        ):
            continue

        weight = safe_number(
            row.get(
                "target_weight"
            )
        )

        if (
            weight is not None
            and weight > 0
        ):

            positive.append(
                row
            )

    positive.sort(
        key=lambda row:
            safe_number(
                row.get(
                    "target_weight"
                )
            )
            or 0,
        reverse=True,
    )

    return positive[:limit]


def detect_tickers(
    state,
    message,
):

    words = {
        word
        .strip(
            ".,;:()[]{}!?$"
        )
        .upper()

        for word in (
            message.split()
        )
    }

    universe = {
        ticker_of(row)

        for row in state.get(
            "universe",
            [],
        )

        if ticker_of(row)
    }

    return [
        ticker

        for ticker in universe

        if ticker in words
    ][:5]


def alpha_context(
    state,
    message,
):

    requested = (
        detect_tickers(
            state,
            message,
        )
    )

    ticker_views = {
        ticker:
            ticker_view(
                state,
                ticker,
            )

        for ticker in requested
    }

    benchmarks = market_batch(
        [
            "SPY",
            "QQQ",
            "IWM",
            "EEM",
            "^MERV",
            "ARS=X",
        ]
    )

    return sanitize({
        "system":
            state.get(
                "system",
                {},
            ),

        "overview":
            state.get(
                "overview",
                {},
            ),

        "v13": {
            "performance":
                state
                .get(
                    "v13",
                    {}
                )
                .get(
                    "performance",
                    {},
                ),

            "top_recommendations":
                top_recommendations(
                    state
                ),
        },

        "byma": {
            "performance":
                state
                .get(
                    "byma",
                    {}
                )
                .get(
                    "performance",
                    {},
                ),

            "retention":
                state
                .get(
                    "byma",
                    {}
                )
                .get(
                    "retention",
                    {},
                ),

            "recommendations":
                state
                .get(
                    "byma",
                    {}
                )
                .get(
                    "recommendations",
                    [],
                )[:80],
        },

        "personal":
            state.get(
                "personal",
                {},
            ),

        "risk":
            state.get(
                "risk",
                {},
            ),

        "fundamentals":
            state.get(
                "fundamentals",
                {},
            ),

        "live_market_benchmarks":
            benchmarks,

        "requested_tickers":
            ticker_views,
    })


def extract_response_text(
    result,
):

    output_text = result.get(
        "output_text"
    )

    if isinstance(
        output_text,
        str,
    ):

        return (
            output_text
            .strip()
        )

    parts = []

    for item in result.get(
        "output",
        [],
    ):

        if not isinstance(
            item,
            dict,
        ):
            continue

        for content in item.get(
            "content",
            [],
        ):

            if not isinstance(
                content,
                dict,
            ):
                continue

            text = content.get(
                "text"
            )

            if isinstance(
                text,
                str,
            ):

                parts.append(
                    text
                )

    return (
        "\n"
        .join(parts)
        .strip()
    )


def ask_alpha(
    state,
    message,
    history,
):

    if not OPENAI_API_KEY:

        return {
            "status":
                "NOT_CONFIGURED",

            "answer":
                (
                    "Alpha Decision Desk está instalado, "
                    "pero falta configurar OPENAI_API_KEY."
                ),

            "model":
                OPENAI_MODEL,
        }

    recent = []

    for item in (
        history
        or []
    )[-8:]:

        if not isinstance(
            item,
            dict,
        ):
            continue

        if (
            item.get(
                "role"
            )
            in {
                "user",
                "assistant",
            }
            and isinstance(
                item.get(
                    "content"
                ),
                str,
            )
        ):

            recent.append(
                item
            )

    context = alpha_context(
        state,
        message,
    )

    history_text = "\n".join(
        (
            f"{item['role'].upper()}: "
            f"{item['content']}"
        )

        for item in recent
    )

    instructions = """
IDENTIDAD
Sos Alpha, el Decision Desk de Alpha Engine.
No sos una interfaz genérica de chat y nunca te presentes como ChatGPT.
Tu voz es la de un analista cuantitativo institucional integrado al sistema.

ESTILO
- Español claro y profesional.
- Directo, preciso, sin frases vacías.
- Evitá emojis.
- Evitá disclaimers repetitivos.
- No uses lenguaje de asistente genérico.
- Cuando corresponda, estructurá en:
  SEÑAL
  EVIDENCIA
  RIESGOS
  ACCIÓN / LECTURA
- Si una pregunta simple no necesita esas cuatro secciones, respondé directamente.

JERARQUÍA DE INFORMACIÓN
1. V13 IDEAL = autoridad teórica del modelo.
2. BYMA MODEL = traducción local separada.
3. LIVE MARKET = snapshot regular de mercado.
4. PERSONAL PORTFOLIO = cartera del usuario, nunca contamina V13.
5. FUNDAMENTALS = sólo lo efectivamente disponible.

REGLAS
- No inventes precios, ratios, fundamentales ni métricas.
- Indicá cuando un dato no está disponible.
- Diferenciá claramente fecha del modelo y fecha del mercado.
- No confundas target weight con precio objetivo.
- No confundas BYMA Transfer con V13 Ideal.
- No afirmes que una operación fue registrada salvo confirmación del backend.
- No enviás órdenes a brokers.
- Si el usuario describe una compra o venta, podés preparar una propuesta,
  pero la escritura requiere confirmación humana explícita.
"""

    input_text = (
        "ALPHA ENGINE CONTEXT:\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
        )
        + "\n\nRECENT DESK HISTORY:\n"
        + history_text
        + "\n\nUSER REQUEST:\n"
        + message
    )

    payload = {
        "model":
            OPENAI_MODEL,

        "instructions":
            instructions,

        "input":
            input_text,

        "reasoning": {
            "effort":
                "medium"
        },

        "max_output_tokens":
            2400,
    }

    request = urllib.request.Request(
        OPENAI_URL,

        data=json.dumps(
            payload,
            ensure_ascii=False,
        ).encode(
            "utf-8"
        ),

        headers={
            "Authorization":
                (
                    "Bearer "
                    + OPENAI_API_KEY
                ),

            "Content-Type":
                "application/json",

            "User-Agent":
                "AlphaEngineDecisionDesk/3.0",
        },

        method="POST",
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=180,
        ) as response:

            result = json.loads(
                response
                .read()
                .decode(
                    "utf-8"
                )
            )

    except urllib.error.HTTPError as exc:

        body = (
            exc.read()
            .decode(
                "utf-8",
                errors="replace",
            )
        )

        raise RuntimeError(
            (
                f"OPENAI_HTTP_{exc.code}: "
                + body[:1200]
            )
        )

    answer = extract_response_text(
        result
    )

    if not answer:

        raise RuntimeError(
            "OPENAI_EMPTY_RESPONSE"
        )

    return {
        "status":
            "PASS",

        "answer":
            answer,

        "model":
            OPENAI_MODEL,
    }


# ============================================================
# HTTP
# ============================================================

class Handler(
    BaseHTTPRequestHandler
):

    server_version = (
        "AlphaEngineWeb/3.0"
    )

    def log_message(
        self,
        format,
        *args,
    ):
        return

    def send_bytes(
        self,
        raw,
        content_type,
        status=200,
    ):

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            content_type,
        )

        self.send_header(
            "Content-Length",
            str(len(raw)),
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

        self.end_headers()

        self.wfile.write(
            raw
        )

    def send_json(
        self,
        payload,
        status=200,
    ):

        raw = json.dumps(
            sanitize(payload),
            ensure_ascii=False,
            allow_nan=False,
        ).encode(
            "utf-8"
        )

        self.send_bytes(
            raw,
            "application/json; charset=utf-8",
            status,
        )

    def serve_file(
        self,
        relative,
    ):

        target = (
            WEB
            / relative
        ).resolve()

        if (
            WEB.resolve()
            not in target.parents
            and target
            != WEB.resolve()
        ):

            self.send_error(
                403
            )

            return

        if not target.exists():

            self.send_error(
                404
            )

            return

        mime, _ = (
            mimetypes
            .guess_type(
                str(target)
            )
        )

        self.send_bytes(
            target.read_bytes(),
            mime
            or "application/octet-stream",
        )

    def serve_index(
        self,
    ):

        html = (
            WEB
            / "index.html"
        ).read_text(
            encoding="utf-8"
        )

        html = html.replace(
            "</head>",
            (
                '<link rel="stylesheet" href="/v3.css?v=3">'
                "\n</head>"
            ),
        )

        html = html.replace(
            "</body>",
            (
                '<script src="/v3.js?v=3"></script>'
                "\n</body>"
            ),
        )

        self.send_bytes(
            html.encode(
                "utf-8"
            ),
            "text/html; charset=utf-8",
        )

    def do_GET(
        self,
    ):

        parsed = (
            urllib.parse
            .urlparse(
                self.path
            )
        )

        path = (
            parsed.path
        )

        query = (
            urllib.parse
            .parse_qs(
                parsed.query
            )
        )

        if path == "/api/health":

            self.send_json({
                "status":
                    "PASS",

                "service":
                    "ALPHA_ENGINE",

                "web_version":
                    "V3",

                "product_state":
                    "PASS",

                "market_source":
                    "Yahoo Finance Chart",

                "include_prepost":
                    False,

                "alpha_configured":
                    bool(
                        OPENAI_API_KEY
                    ),

                "alpha_model":
                    OPENAI_MODEL,
            })

            return

        if path == "/api/state":

            try:

                force = (
                    query.get(
                        "refresh",
                        ["0"],
                    )[0]
                    == "1"
                )

                self.send_json(
                    load_state(
                        force=force
                    )
                )

            except Exception as exc:

                self.send_json(
                    {
                        "status":
                            "FAIL",

                        "error":
                            str(exc),
                    },
                    500,
                )

            return

        if path == "/api/market":

            ticker = (
                query.get(
                    "ticker",
                    [""],
                )[0]
            )

            self.send_json(
                yahoo_market_snapshot(
                    ticker
                )
            )

            return

        if path == "/api/market-batch":

            raw = (
                query.get(
                    "tickers",
                    [""],
                )[0]
            )

            tickers = [
                ticker

                for ticker in raw.split(
                    ","
                )

                if ticker.strip()
            ]

            self.send_json({
                "status":
                    "PASS",

                "source":
                    "Yahoo Finance Chart",

                "include_prepost":
                    False,

                "data":
                    market_batch(
                        tickers
                    ),
            })

            return

        if path == "/api/ticker":

            try:

                ticker = (
                    query.get(
                        "ticker",
                        [""],
                    )[0]
                    .strip()
                    .upper()
                )

                if not ticker:

                    raise RuntimeError(
                        "MISSING_TICKER"
                    )

                self.send_json(
                    ticker_view(
                        load_state(),
                        ticker,
                    )
                )

            except Exception as exc:

                self.send_json(
                    {
                        "status":
                            "FAIL",

                        "error":
                            str(exc),
                    },
                    400,
                )

            return

        if path in {
            "/",
            "/index.html",
        }:

            self.serve_index()

            return

        files = {
            "/styles.css":
                "styles.css",

            "/app.js":
                "app.js",

            "/v3.css":
                "v3.css",

            "/v3.js":
                "v3.js",

            "/assets/alpha-engine-logo.jpg":
                "assets/alpha-engine-logo.jpg",
        }

        if path in files:

            self.serve_file(
                files[path]
            )

            return

        self.send_error(
            404
        )

    def do_POST(
        self,
    ):

        parsed = (
            urllib.parse
            .urlparse(
                self.path
            )
        )

        if (
            parsed.path
            != "/api/alpha"
        ):

            self.send_error(
                404
            )

            return

        try:

            length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )

            if (
                length <= 0
                or length
                > 2_000_000
            ):

                raise RuntimeError(
                    "INVALID_BODY_SIZE"
                )

            payload = json.loads(
                self.rfile
                .read(length)
                .decode(
                    "utf-8"
                )
            )

            message = str(
                payload.get(
                    "message",
                    "",
                )
            ).strip()

            if not message:

                raise RuntimeError(
                    "EMPTY_MESSAGE"
                )

            self.send_json(
                ask_alpha(
                    load_state(),
                    message,
                    payload.get(
                        "history",
                        [],
                    ),
                )
            )

        except Exception as exc:

            self.send_json(
                {
                    "status":
                        "FAIL",

                    "error":
                        str(exc),
                },
                500,
            )


# ============================================================
# MAIN
# ============================================================

def main():

    state = load_state(
        force=True
    )

    if (
        state.get(
            "system",
            {}
        ).get(
            "status"
        )
        != "PASS"
    ):

        raise SystemExit(
            "PRODUCT_STATE_NOT_PASS"
        )

    server = (
        ThreadingHTTPServer(
            (
                HOST,
                PORT,
            ),
            Handler,
        )
    )

    url = (
        f"http://{HOST}:{PORT}"
    )

    print()
    print("=" * 64)
    print("ALPHA ENGINE // MARKET INTELLIGENCE V3")
    print("=" * 64)
    print("WEB:                  PASS")
    print("PRODUCT STATE:        PASS")
    print("MARKET DATA:          READY - REGULAR SESSION ONLY")
    print("PRE / POST MARKET:    DISABLED")
    print(
        "ALPHA DECISION DESK: "
        + (
            "LIVE"
            if OPENAI_API_KEY
            else "API KEY NOT CONFIGURED"
        )
    )
    print(
        f"MODEL:                {OPENAI_MODEL}"
    )
    print(
        f"URL:                  {url}"
    )
    print("=" * 64)
    print()

    threading.Timer(
        0.7,
        lambda:
            webbrowser.open(
                url
            ),
    ).start()

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        pass

    finally:

        server.server_close()


if __name__ == "__main__":
    main()
