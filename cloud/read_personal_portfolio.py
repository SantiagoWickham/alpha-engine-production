import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

OUT = ROOT / "PRODUCT" / "personal_portfolio_ledger.json"

URL = os.environ.get(
    "ALPHA_SHEET_WEBAPP_URL",
    ""
).strip()

TOKEN = os.environ.get(
    "ALPHA_SHEET_TOKEN",
    ""
).strip()


if not URL:
    raise SystemExit(
        "MISSING ALPHA_SHEET_WEBAPP_URL"
    )

if not TOKEN:
    raise SystemExit(
        "MISSING ALPHA_SHEET_TOKEN"
    )


payload = {
    "schema": "ALPHA_ENGINE_PORTFOLIO_READ_V1",
    "token": TOKEN,
}


request = urllib.request.Request(
    URL,
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "User-Agent": "AlphaEnginePersonalPortfolio/1.0",
    },
    method="POST",
)


with urllib.request.urlopen(
    request,
    timeout=120,
) as response:

    raw = response.read().decode("utf-8")


try:

    result = json.loads(raw)

except Exception:

    print("RAW RESPONSE:")
    print(raw)

    raise SystemExit(
        "INVALID JSON RESPONSE FROM SHEETS"
    )


if result.get("status") != "PASS":

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )

    raise SystemExit(
        "PORTFOLIO READ FAILED"
    )


ledger = {
    "schema": "ALPHA_ENGINE_PERSONAL_LEDGER_V1",

    "captured_at_utc": datetime.now(
        timezone.utc
    ).isoformat(),

    "source": "GOOGLE_SHEETS",

    "operations_count": result.get(
        "operations_count",
        0,
    ),

    "cash_rows_count": result.get(
        "cash_rows_count",
        0,
    ),

    "positions_count": result.get(
        "positions_count",
        0,
    ),

    "operations": result.get(
        "operations",
        [],
    ),

    "cash": result.get(
        "cash",
        [],
    ),

    "positions": result.get(
        "positions",
        [],
    ),
}


OUT.write_text(
    json.dumps(
        ledger,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)


print()
print("============================================================")
print("ALPHA ENGINE - PERSONAL PORTFOLIO READ")
print("============================================================")
print()

print(
    f"OPERATIONS: {ledger['operations_count']}"
)

print(
    f"CASH ROWS:  {ledger['cash_rows_count']}"
)

print(
    f"POSITIONS:  {ledger['positions_count']}"
)

print()
print(
    f"OUTPUT: {OUT}"
)

print()
print(
    "PERSONAL PORTFOLIO READ: PASS"
)

print(
    "============================================================"
)
