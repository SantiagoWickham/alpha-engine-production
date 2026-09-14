import json
import os
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

STATE_PATH = (
    ROOT
    / "public"
    / "data"
    / "alpha_product_state.json"
)

URL = os.environ.get(
    "ALPHA_SHEET_WEBAPP_URL",
    "",
).strip()

TOKEN = os.environ.get(
    "ALPHA_SHEET_TOKEN",
    "",
).strip()


if not URL:
    raise SystemExit(
        "MISSING ALPHA_SHEET_WEBAPP_URL"
    )

if not TOKEN:
    raise SystemExit(
        "MISSING ALPHA_SHEET_TOKEN"
    )

if not STATE_PATH.exists():
    raise SystemExit(
        f"MISSING PRODUCT STATE: {STATE_PATH}"
    )


product_state = json.loads(
    STATE_PATH.read_text(
        encoding="utf-8"
    )
)


if (
    product_state.get("schema")
    !=
    "ALPHA_ENGINE_PRODUCT_STATE_V1"
):
    raise SystemExit(
        "INVALID PRODUCT STATE SCHEMA"
    )


if (
    product_state
    .get("system", {})
    .get("status")
    !=
    "PASS"
):
    raise SystemExit(
        "PRODUCT STATE SYSTEM NOT PASS"
    )


payload = {
    "schema":
        "ALPHA_ENGINE_PRODUCT_STATE_SYNC_V1",

    "token":
        TOKEN,

    "product_state":
        product_state,
}


body = json.dumps(
    payload,
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")


request = urllib.request.Request(
    URL,
    data=body,
    headers={
        "Content-Type":
            "application/json",

        "User-Agent":
            "AlphaEngineProductState/1.0",
    },
    method="POST",
)


with urllib.request.urlopen(
    request,
    timeout=180,
) as response:

    raw = response.read().decode(
        "utf-8"
    )


try:

    result = json.loads(
        raw
    )

except Exception:

    print()
    print("RAW RESPONSE:")
    print(raw)

    raise SystemExit(
        "INVALID JSON RESPONSE FROM SHEETS"
    )


print()
print(
    json.dumps(
        result,
        indent=2,
        ensure_ascii=False,
    )
)


if (
    result.get("status")
    !=
    "PASS"
):

    raise SystemExit(
        "PRODUCT STATE SHEETS SYNC FAILED"
    )


print()
print(
    "============================================================"
)
print(
    "ALPHA PRODUCT STATE -> SHEETS: PASS"
)
print(
    "============================================================"
)
