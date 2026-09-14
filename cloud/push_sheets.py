import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "public" / "data" / "latest.json"

URL = os.environ.get("ALPHA_SHEET_WEBAPP_URL", "").strip()
TOKEN = os.environ.get("ALPHA_SHEET_TOKEN", "").strip()

if not URL:
    raise SystemExit("MISSING ALPHA_SHEET_WEBAPP_URL")

if not TOKEN:
    raise SystemExit("MISSING ALPHA_SHEET_TOKEN")

if not STATE_PATH.exists():
    raise SystemExit(f"MISSING STATE: {STATE_PATH}")

state = json.loads(
    STATE_PATH.read_text(encoding="utf-8")
)

if state.get("status") != "PASS":
    raise SystemExit(
        f"STATE IS NOT PASS: {state.get('status')}"
    )

payload = {
    "schema": "ALPHA_ENGINE_SHEETS_SYNC_V1",
    "token": TOKEN,
    "state": state,
}

body = json.dumps(payload).encode("utf-8")

request = urllib.request.Request(
    URL,
    data=body,
    headers={
        "Content-Type": "application/json",
        "User-Agent": "AlphaEngineProduction/1.0",
    },
    method="POST",
)

with urllib.request.urlopen(
    request,
    timeout=60
) as response:
    raw = response.read().decode("utf-8")

try:
    result = json.loads(raw)
except Exception:
    print("RAW RESPONSE:")
    print(raw)
    raise SystemExit("INVALID JSON RESPONSE FROM SHEETS")

print(json.dumps(result, indent=2))

if result.get("status") != "PASS":
    raise SystemExit(
        f"SHEETS SYNC FAILED: {result}"
    )

print()
print("ALPHA ENGINE SHEETS SYNC: PASS")
