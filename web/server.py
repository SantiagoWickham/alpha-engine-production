from __future__ import annotations

import json
import mimetypes
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"

LOCAL_STATE = (
    ROOT
    / "public"
    / "data"
    / "alpha_product_state.json"
)

HOST = "127.0.0.1"
PORT = 8765

CACHE_SECONDS = 30

_state_cache = None
_state_cache_time = 0.0
_state_lock = threading.Lock()


def git_latest_state() -> dict:
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
        result.stdout.decode("utf-8")
    )


def local_state() -> dict:
    if not LOCAL_STATE.exists():
        raise FileNotFoundError(
            f"State file not found: {LOCAL_STATE}"
        )

    return json.loads(
        LOCAL_STATE.read_text(
            encoding="utf-8"
        )
    )


def load_state(force=False) -> dict:
    global _state_cache
    global _state_cache_time

    with _state_lock:

        now = time.time()

        if (
            not force
            and _state_cache is not None
            and (
                now - _state_cache_time
                < CACHE_SECONDS
            )
        ):
            return _state_cache

        source = "GITHUB_ORIGIN_MAIN"

        try:
            state = git_latest_state()

        except Exception as exc:
            source = "LOCAL_FALLBACK"

            try:
                state = local_state()

            except Exception:
                raise RuntimeError(
                    "Could not load Alpha Product State "
                    f"from GitHub or local file. Git error: {exc}"
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
            "source": source,
            "served_at_unix": now,
        }

        _state_cache = state
        _state_cache_time = now

        return state


class AlphaHandler(BaseHTTPRequestHandler):

    server_version = "AlphaEngineWeb/1.0"

    def log_message(
        self,
        format,
        *args,
    ):
        return

    def send_json(
        self,
        payload,
        status=200,
    ):
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
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

    def serve_static(
        self,
        relative_path: str,
    ):
        target = (
            WEB_ROOT
            / relative_path
        ).resolve()

        if (
            WEB_ROOT.resolve()
            not in target.parents
            and target
            != WEB_ROOT.resolve()
        ):
            self.send_error(403)
            return

        if not target.exists():
            self.send_error(404)
            return

        mime, _ = mimetypes.guess_type(
            str(target)
        )

        if not mime:
            mime = "application/octet-stream"

        raw = target.read_bytes()

        self.send_response(200)
        self.send_header(
            "Content-Type",
            mime,
        )
        self.send_header(
            "Content-Length",
            str(len(raw)),
        )
        self.send_header(
            "Cache-Control",
            "no-cache",
        )
        self.end_headers()

        self.wfile.write(raw)

    def do_GET(self):
        parsed = urllib.parse.urlparse(
            self.path
        )

        path = parsed.path

        query = urllib.parse.parse_qs(
            parsed.query
        )

        if path == "/api/health":

            self.send_json({
                "status": "PASS",
                "service": "ALPHA_ENGINE_WEB",
                "binding": f"{HOST}:{PORT}",
                "private_local_only": True,
            })

            return

        if path == "/api/state":

            try:
                force = (
                    query.get("refresh", ["0"])[0]
                    == "1"
                )

                state = load_state(
                    force=force
                )

                self.send_json(
                    state
                )

            except Exception as exc:

                self.send_json(
                    {
                        "status": "FAIL",
                        "error": str(exc),
                    },
                    status=500,
                )

            return

        if path in {
            "/",
            "/index.html",
        }:
            self.serve_static(
                "index.html"
            )
            return

        static_map = {
            "/styles.css": "styles.css",
            "/app.js": "app.js",
        }

        if path in static_map:
            self.serve_static(
                static_map[path]
            )
            return

        self.send_error(404)


def main():

    # Validate state before opening browser.
    try:
        state = load_state(
            force=True
        )

        status = (
            state
            .get("system", {})
            .get("status")
        )

        if status != "PASS":
            raise RuntimeError(
                f"PRODUCT_STATE_NOT_PASS: {status}"
            )

    except Exception as exc:

        print()
        print("=" * 60)
        print("ALPHA ENGINE WEB: FAIL")
        print("=" * 60)
        print()
        print(exc)
        print()

        raise SystemExit(1)


    server = ThreadingHTTPServer(
        (HOST, PORT),
        AlphaHandler,
    )

    url = (
        f"http://{HOST}:{PORT}"
    )

    print()
    print("=" * 60)
    print("ALPHA ENGINE WEB")
    print("=" * 60)
    print()
    print("STATUS:             PASS")
    print("MODE:               PRIVATE LOCAL")
    print("PRODUCT STATE:      PASS")
    print(f"URL:                {url}")
    print()
    print("CTRL+C para cerrar.")
    print("=" * 60)
    print()

    threading.Timer(
        0.7,
        lambda: webbrowser.open(url),
    ).start()

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        pass

    finally:
        server.server_close()

        print()
        print("ALPHA ENGINE WEB: STOPPED")


if __name__ == "__main__":
    main()
