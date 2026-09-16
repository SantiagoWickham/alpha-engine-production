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
