import csv
import json
import os
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

STATE_PATH = ROOT / "public" / "data" / "latest.json"
NAV_PATH = ROOT / "PRODUCT" / "nav_history.csv"
PERFORMANCE_PATH = ROOT / "PRODUCT" / "performance_summary.json"

URL = os.environ.get(
    "ALPHA_SHEET_WEBAPP_URL",
    ""
).strip()

TOKEN = os.environ.get(
    "ALPHA_SHEET_TOKEN",
    ""
).strip()


def require_file(path):
    if not path.exists():
        raise SystemExit(
            f"MISSING FILE: {path}"
        )


def coerce(value):
    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        return value


if not URL:
    raise SystemExit(
        "MISSING ALPHA_SHEET_WEBAPP_URL"
    )

if not TOKEN:
    raise SystemExit(
        "MISSING ALPHA_SHEET_TOKEN"
    )

require_file(STATE_PATH)
require_file(NAV_PATH)
require_file(PERFORMANCE_PATH)


# ============================================================
# PRODUCTION STATE
# ============================================================

state = json.loads(
    STATE_PATH.read_text(
        encoding="utf-8"
    )
)

if state.get("status") != "PASS":
    raise SystemExit(
        f"STATE IS NOT PASS: "
        f"{state.get('status')}"
    )


# ============================================================
# NAV HISTORY
# ============================================================

nav_history = []

with NAV_PATH.open(
    "r",
    encoding="utf-8-sig",
    newline=""
) as f:

    reader = csv.DictReader(f)

    for row in reader:

        converted = {}

        for key, value in row.items():

            if key in {
                "date",
                "segment",
            }:
                converted[key] = value
            else:
                converted[key] = coerce(value)

        nav_history.append(converted)


if not nav_history:
    raise SystemExit(
        "NAV HISTORY IS EMPTY"
    )


# ============================================================
# PERFORMANCE SUMMARY
# ============================================================

performance_summary = json.loads(
    PERFORMANCE_PATH.read_text(
        encoding="utf-8"
    )
)


# ============================================================
# PAYLOAD
# ============================================================

payload = {
    "schema": "ALPHA_ENGINE_SHEETS_SYNC_V1",
    "token": TOKEN,
    "state": state,
    "nav_history": nav_history,
    "performance_summary": performance_summary,
}

body = json.dumps(
    payload,
    allow_nan=False,
).encode("utf-8")


request = urllib.request.Request(
    URL,
    data=body,
    headers={
        "Content-Type": "application/json",
        "User-Agent":
            "AlphaEngineProduction/2.0",
    },
    method="POST",
)


with urllib.request.urlopen(
    request,
    timeout=120
) as response:

    raw = response.read().decode(
        "utf-8"
    )


try:
    result = json.loads(raw)

except Exception:

    print("RAW RESPONSE:")
    print(raw)

    raise SystemExit(
        "INVALID JSON RESPONSE FROM SHEETS"
    )


print(
    json.dumps(
        result,
        indent=2
    )
)

if result.get("status") != "PASS":
    raise SystemExit(
        f"SHEETS SYNC FAILED: {result}"
    )


print()
print(
    f"NAV ROWS SENT: "
    f"{len(nav_history)}"
)

print(
    "PERFORMANCE SUMMARY SENT: PASS"
)

print()
print(
    "ALPHA ENGINE SHEETS SYNC: PASS"
)
