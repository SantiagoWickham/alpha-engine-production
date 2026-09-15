from __future__ import annotations

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

OPENAI_API_KEY = os.environ.get(
    "OPENAI_API_KEY",
    "",
).strip()

OPENAI_MODEL = os.environ.get(
    "ALPHA_OPENAI_MODEL",
    "gpt-5.6-sol",
).strip()

CACHE_SECONDS = 30

_cache = None
_cache_time = 0.0
_lock = threading.Lock()


def sanitize(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, int):
        return value

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


def latest_state():
    subprocess.run(
        ["git", "fetch", "origin", "main"],
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
        result.stdout.decode("utf-8")
    )


def local_state():
    return json.loads(
        STATE_FILE.read_text(
            encoding="utf-8"
        )
    )


def load_state(force=False):
    global _cache
    global _cache_time

    with _lock:
        now = time.time()

        if (
            not force
            and _cache is not None
            and now - _cache_time < CACHE_SECONDS
        ):
            return _cache

        source = "GITHUB_ORIGIN_MAIN"

        try:
            state = latest_state()

        except Exception:
            source = "LOCAL_FALLBACK"
            state = local_state()

        state = sanitize(state)

        if (
            state.get("schema")
            != "ALPHA_ENGINE_PRODUCT_STATE_V1"
        ):
            raise RuntimeError(
                "INVALID_PRODUCT_STATE_SCHEMA"
            )

        state["_web"] = {
            "source": source,
            "version": "WEB_V2",
            "alpha_configured": bool(
                OPENAI_API_KEY
            ),
            "alpha_model": OPENAI_MODEL,
        }

        _cache = state
        _cache_time = now

        return state


def ticker_of(row):
    if not isinstance(row, dict):
        return None

    for key in (
        "ticker",
        "Ticker",
        "symbol",
        "Symbol",
    ):
        value = row.get(key)

        if value:
            return str(value).upper()

    return None


def ticker_rows(rows, ticker):
    return [
        sanitize(row)
        for row in (rows or [])
        if ticker_of(row) == ticker
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

    if isinstance(obj, dict):
        if ticker_of(obj) == ticker:
            found.append({
                "path": path or "root",
                "data": sanitize(obj),
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

    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            recursive_matches(
                value,
                ticker,
                f"{path}[{index}]",
                found,
            )

            if len(found) >= 20:
                break

    return found


def ticker_view(state, ticker):
    ticker = ticker.strip().upper()

    v13 = ticker_rows(
        state.get("v13", {})
        .get("recommendations", []),
        ticker,
    )

    byma = []

    for row in (
        state.get("byma", {})
        .get("recommendations", [])
    ):
        if not isinstance(row, dict):
            continue

        source = str(
            row.get("ticker") or ""
        ).upper()

        local = str(
            row.get("byma_ticker") or ""
        ).upper()

        if ticker in {source, local}:
            byma.append(
                sanitize(row)
            )

    personal = ticker_rows(
        state.get("personal", {})
        .get("positions", []),
        ticker,
    )

    universe = ticker_rows(
        state.get("universe", []),
        ticker,
    )

    fundamentals = (
        state.get("fundamentals", {})
        or {}
    )

    companies = fundamentals.get(
        "companies",
        [],
    )

    fundamental = ticker_rows(
        companies,
        ticker,
    )

    fundamental_matches = recursive_matches(
        fundamentals,
        ticker,
        "fundamentals",
    )

    market_matches = recursive_matches(
        state.get("market", {}),
        ticker,
        "market",
    )

    return sanitize({
        "status": "PASS",

        "ticker": ticker,

        "coverage": {
            "v13": bool(v13),
            "byma": bool(byma),
            "personal": bool(personal),
            "fundamentals": bool(
                fundamental
                or fundamental_matches
            ),
            "market": bool(
                market_matches
            ),
        },

        "v13":
            v13[0] if v13 else None,

        "byma":
            byma,

        "personal":
            personal[0]
            if personal
            else None,

        "universe":
            universe[0]
            if universe
            else None,

        "fundamentals":
            fundamental[0]
            if fundamental
            else None,

        "fundamental_matches":
            fundamental_matches,

        "market_matches":
            market_matches,
    })


def top_recommendations(state):
    rows = (
        state.get("v13", {})
        .get("recommendations", [])
    )

    positive = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        weight = row.get(
            "target_weight"
        )

        if (
            isinstance(weight, (int, float))
            and weight > 0
        ):
            positive.append(row)

    return sorted(
        positive,
        key=lambda row:
            row.get("target_weight") or 0,
        reverse=True,
    )[:40]


def detect_tickers(state, message):
    words = {
        word.strip(
            ".,;:()[]{}!?$"
        ).upper()
        for word in message.split()
    }

    available = {
        ticker_of(row)
        for row in state.get(
            "universe",
            [],
        )
        if ticker_of(row)
    }

    return [
        ticker
        for ticker in available
        if ticker in words
    ][:5]


def alpha_context(state, message):
    requested = {
        ticker: ticker_view(
            state,
            ticker,
        )
        for ticker in detect_tickers(
            state,
            message,
        )
    }

    return sanitize({
        "system":
            state.get("system", {}),

        "overview":
            state.get("overview", {}),

        "v13": {
            "performance":
                state.get("v13", {})
                .get("performance", {}),

            "top_recommendations":
                top_recommendations(state),
        },

        "byma": {
            "performance":
                state.get("byma", {})
                .get("performance", {}),

            "retention":
                state.get("byma", {})
                .get("retention", {}),

            "recommendations":
                state.get("byma", {})
                .get(
                    "recommendations",
                    [],
                )[:80],
        },

        "personal":
            state.get("personal", {}),

        "market":
            state.get("market", {}),

        "risk":
            state.get("risk", {}),

        "fundamentals":
            state.get(
                "fundamentals",
                {},
            ),

        "ticker_views":
            requested,
    })


def response_text(result):
    text = result.get(
        "output_text"
    )

    if isinstance(text, str):
        return text.strip()

    parts = []

    for output in result.get(
        "output",
        [],
    ):
        if not isinstance(output, dict):
            continue

        for content in output.get(
            "content",
            [],
        ):
            if not isinstance(content, dict):
                continue

            text = content.get("text")

            if isinstance(text, str):
                parts.append(text)

    return "\n".join(parts).strip()


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
                    "Alpha AI está instalada. "
                    "Falta configurar OPENAI_API_KEY "
                    "en esta PC."
                ),

            "model":
                OPENAI_MODEL,
        }

    recent = []

    for item in (history or [])[-8:]:
        if not isinstance(item, dict):
            continue

        if (
            item.get("role")
            in {"user", "assistant"}
            and isinstance(
                item.get("content"),
                str,
            )
        ):
            recent.append(item)

    context = alpha_context(
        state,
        message,
    )

    instructions = """
Sos Alpha AI, la capa conversacional de Alpha Engine.

Respondé en español.

Reglas:
- V13 IDEAL es la autoridad teórica.
- BYMA MODEL es una traducción local separada.
- La cartera personal no modifica V13.
- No inventes precios, ratios ni fundamentales.
- Si falta información, decilo.
- Diferenciá modelo, mercado, BYMA y cartera.
- No enviás órdenes a brokers.
- No afirmes que una operación fue ejecutada o registrada.
- Una escritura de cartera requiere confirmación humana explícita.
- Usá solamente los datos de Alpha Engine suministrados.
"""

    history_text = "\n".join(
        (
            f"{x['role'].upper()}: "
            f"{x['content']}"
        )
        for x in recent
    )

    input_text = (
        "ALPHA ENGINE PRODUCT STATE:\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n\nHISTORIAL:\n"
        + history_text
        + "\n\nUSUARIO:\n"
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
            2200,
    }

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",

        data=json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8"),

        headers={
            "Authorization":
                (
                    "Bearer "
                    + OPENAI_API_KEY
                ),

            "Content-Type":
                "application/json",
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
                .decode("utf-8")
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
                + body[:1000]
            )
        )

    answer = response_text(
        result
    )

    if not answer:
        raise RuntimeError(
            "OPENAI_EMPTY_RESPONSE"
        )

    return {
        "status": "PASS",
        "answer": answer,
        "model": OPENAI_MODEL,
    }


class Handler(
    BaseHTTPRequestHandler
):

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
        self.send_response(status)

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

        self.wfile.write(raw)

    def send_json(
        self,
        payload,
        status=200,
    ):
        raw = json.dumps(
            sanitize(payload),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

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
            and target != WEB.resolve()
        ):
            self.send_error(403)
            return

        if not target.exists():
            self.send_error(404)
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

    def serve_index(self):
        html = (
            WEB
            / "index.html"
        ).read_text(
            encoding="utf-8"
        )

        if "/v2.css" not in html:
            html = html.replace(
                "</head>",
                (
                    '<link rel="stylesheet" '
                    'href="/v2.css">'
                    "\n</head>"
                ),
            )

        if "/v2.js" not in html:
            html = html.replace(
                "</body>",
                (
                    '<script src="/v2.js"></script>'
                    "\n</body>"
                ),
            )

        self.send_bytes(
            html.encode("utf-8"),
            "text/html; charset=utf-8",
        )

    def do_GET(self):
        parsed = (
            urllib.parse
            .urlparse(
                self.path
            )
        )

        path = parsed.path

        query = (
            urllib.parse
            .parse_qs(
                parsed.query
            )
        )

        if path == "/api/health":
            self.send_json({
                "status": "PASS",
                "version": "WEB_V2",
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
                        "status": "FAIL",
                        "error": str(exc),
                    },
                    500,
                )

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
                        "status": "FAIL",
                        "error": str(exc),
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

        routes = {
            "/styles.css":
                "styles.css",

            "/app.js":
                "app.js",

            "/v2.css":
                "v2.css",

            "/v2.js":
                "v2.js",

            "/assets/alpha-engine-logo.jpg":
                "assets/alpha-engine-logo.jpg",
        }

        if path in routes:
            self.serve_file(
                routes[path]
            )
            return

        self.send_error(404)

    def do_POST(self):
        if self.path != "/api/alpha":
            self.send_error(404)
            return

        try:
            length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )

            payload = json.loads(
                self.rfile
                .read(length)
                .decode("utf-8")
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

            result = ask_alpha(
                load_state(),
                message,
                payload.get(
                    "history",
                    [],
                ),
            )

            self.send_json(
                result
            )

        except Exception as exc:
            self.send_json(
                {
                    "status": "FAIL",
                    "error": str(exc),
                },
                500,
            )


def main():
    state = load_state(
        force=True
    )

    if (
        state.get("system", {})
        .get("status")
        != "PASS"
    ):
        raise SystemExit(
            "PRODUCT_STATE_NOT_PASS"
        )

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler,
    )

    url = (
        f"http://{HOST}:{PORT}"
    )

    print()
    print("=" * 60)
    print("ALPHA ENGINE WEB V2")
    print("=" * 60)
    print("WEB:                PASS")
    print("PRODUCT STATE:      PASS")
    print(
        "ALPHA AI:           "
        + (
            "READY"
            if OPENAI_API_KEY
            else "API KEY NOT CONFIGURED"
        )
    )
    print(
        f"MODEL:              {OPENAI_MODEL}"
    )
    print(
        f"URL:                {url}"
    )
    print("=" * 60)
    print()

    threading.Timer(
        0.8,
        lambda:
            webbrowser.open(url),
    ).start()

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        server.server_close()


if __name__ == "__main__":
    main()
