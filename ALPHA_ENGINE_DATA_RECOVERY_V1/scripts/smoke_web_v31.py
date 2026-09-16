from __future__ import annotations

import json
import time
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8765"


def get(path, timeout=8):
    with urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path, payload, timeout=90):
    req = Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


last = None
for _ in range(25):
    try:
        h = get("/api/health", 5)
        s = get("/api/state?refresh=1", 8)
        n = get("/api/market?ticker=NKE", 10)
        assert h["status"] == "PASS"
        assert s["_web"]["source"] == "LOCAL_DATA_RECOVERY_V1"
        assert s["_web"]["version"] == "ALPHA_WEB_V3_1"
        assert s["_web"]["alpha_configured"] is True
        assert s["_web"]["alpha_provider"] == "GROQ"
        assert s["overview"]["personal_positions_count"] == 3
        assert n["status"] == "PASS"
        last = None
        break
    except Exception as exc:
        last = exc
        time.sleep(0.75)

if last:
    raise SystemExit(f"HTTP_BOOT_SMOKE_FAILED: {last}")

a = post(
    "/api/alpha",
    {
        "message": (
            "Smoke de sistema. Respondé en una sola línea indicando que "
            "Alpha Decision Desk está operativo y mencioná el proveedor Groq."
        ),
        "history": [],
    },
    90,
)

if a.get("status") != "PASS":
    raise SystemExit(f"ALPHA_LLM_SMOKE_FAILED: {a}")

answer = str(a.get("answer") or "").strip()
if not answer:
    raise SystemExit("ALPHA_LLM_EMPTY_ANSWER")

print("HEALTH=PASS")
print("STATE=PASS")
print("MARKET=PASS")
print("PORTFOLIO_COUNT=3")
print("ALPHA_LLM=PASS")
print("PROVIDER=" + str(a.get("provider")))
print("MODEL=" + str(a.get("model")))
print("ANSWER=" + answer.replace("\n", " ")[:500])
