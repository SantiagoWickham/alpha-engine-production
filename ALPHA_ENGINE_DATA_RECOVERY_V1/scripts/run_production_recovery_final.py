from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION")
REC = ROOT / "ALPHA_ENGINE_DATA_RECOVERY_V1"
BUILDER = REC / "scripts" / "build_runtime_product_state.py"
SERVER = ROOT / "web" / "run_data_recovery_server.py"
LOG = REC / "outputs" / "data_recovery_v1" / "web_runtime.log"


def get_json(url: str, timeout: float = 8.0):
    with urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def run_builder(*args: str) -> int:
    proc = subprocess.run(
        [sys.executable, str(BUILDER), *args],
        cwd=ROOT,
    )
    return proc.returncode


def main() -> int:
    print("")
    print("================================================================")
    print("ALPHA ENGINE - PRODUCTION RECOVERY FINAL")
    print("NO SHEETS / NO V13 MUTATION / LOCAL-FIRST")
    print("================================================================")
    print("")

    # Never let stale Sheet credentials affect this runtime.
    for name in (
        "ALPHA_SHEETS_API_URL",
        "ALPHA_SHEETS_API_TOKEN",
        "MMM_API_TOKEN_V8",
        "MMM_SHEET_API_URL",
        "MMM_SHEET_API_TOKEN",
    ):
        os.environ.pop(name, None)

    print("[A] Build audited local product state", flush=True)
    rc = run_builder()
    if rc != 0:
        print("")
        print("RECOVERY ABORTED BEFORE SERVER START.", flush=True)
        return rc

    print("")
    print("[B] Port 8765 gate", flush=True)
    if port_open(8765):
        print(
            "  FAIL port 8765 is already occupied. "
            "No process was killed.",
            flush=True,
        )
        run_builder("--rollback")
        return 21

    print("  PASS port is free", flush=True)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    log_handle = LOG.open("a", encoding="utf-8")

    flags = 0
    if os.name == "nt":
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)

    print("")
    print("[C] Start local DR1 web server", flush=True)
    server_proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        cwd=ROOT,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    print(f"  PID={server_proc.pid}", flush=True)

    last_error = None
    health = state = nke = None

    print("")
    print("[D] HTTP smoke gates", flush=True)

    for _ in range(20):
        try:
            time.sleep(0.75)
            health = get_json("http://127.0.0.1:8765/api/health", 5)
            state = get_json("http://127.0.0.1:8765/api/state?refresh=1", 8)
            nke = get_json("http://127.0.0.1:8765/api/market?ticker=NKE", 10)

            assert health.get("status") == "PASS", "health != PASS"
            assert state.get("schema") == "ALPHA_ENGINE_PRODUCT_STATE_V1", "schema invalid"
            assert (state.get("system") or {}).get("status") == "PASS", "system.status != PASS"
            assert (state.get("_web") or {}).get("source") == "LOCAL_DATA_RECOVERY_V1", "web not local-first"
            assert int(state["data_recovery"]["market"]["rows"]) == 200, "market rows != 200"
            assert int(state["data_recovery"]["fundamentals"]["rows"]) == 187, "fundamental rows != 187"
            assert int(state["personal"]["position_rows"]) == 3, "personal positions != 3"
            assert state["personal"]["valuation_mode"] == "AUDITED_SNAPSHOT_NOT_LIVE", "portfolio valuation mode invalid"

            actual = sorted(
                str(p.get("ticker") or "")
                for p in state["personal"]["positions"]
            )
            assert actual == ["AVGO", "GOOGL", "NVDA"], f"portfolio tickers invalid: {actual}"

            assert nke.get("status") == "PASS", "NKE market status != PASS"
            nke_var = float(nke["change_pct"])
            assert abs(nke_var) <= 0.35, "NKE Var1D quarantine"

            last_error = None
            break
        except Exception as exc:
            last_error = str(exc)

    if last_error is not None:
        print(f"  FAIL {last_error}", flush=True)
        try:
            server_proc.terminate()
        except Exception:
            pass
        run_builder("--rollback")
        print("  Product state rolled back.", flush=True)
        return 22

    print("  PASS health/state/NKE", flush=True)

    print("")
    print("================================================================")
    print("ALPHA ENGINE PRODUCTION RECOVERY: PASS")
    print("================================================================")
    print("WEB                 : http://127.0.0.1:8765/")
    print(f"STATE SOURCE        : {state['_web']['source']}")
    print(f"V13 SEAL            : {state['data_recovery']['v13_seal_id']}")
    print(f"MARKET              : {state['data_recovery']['market']['rows']}/200")
    print(f"PROVIDER COVERAGE   : {state['data_recovery']['market']['provider_coverage']}")
    print(f"FUNDAMENTALS        : {state['data_recovery']['fundamentals']['rows']}/187")
    print(f"PERSONAL POSITIONS  : {state['personal']['position_rows']}")
    print(
        "PORTFOLIO TICKERS   : "
        + " | ".join(
            f"{p['ticker']}={p['quantity']}"
            for p in state["personal"]["positions"]
        )
    )
    print("PERSONAL VALUATION  : AUDITED SNAPSHOT / NOT LIVE")
    print(f"NKE PRICE           : {nke['regular_market_price']}")
    print(f"NKE VAR 1D          : {float(nke['change_pct']):.4%}")
    print(f"MARKET SOURCE       : {nke['data_authority']}")
    print("PRE / POST MARKET   : DISABLED")
    print("SHEETS REQUIRED     : NO")
    print("OLD V8/V10 SCORES   : NOT IMPORTED")
    print("OLD OPENAI LLM PATH : DISABLED")
    print("V13 MUTATED          : NO")
    print("================================================================")
    print("")
    print(f"Server log: {LOG}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
