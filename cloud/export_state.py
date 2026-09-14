from pathlib import Path
import json
import pandas as pd
from datetime import datetime, timezone

ROOT = Path(r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_V12_RETURN_FIRST")
V13 = ROOT / "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"

OUT = Path("public/data/latest.json")

EXPECTED_SEAL = "46bbbf853561e26625ee3ecbccb6037051556f2f3ca26dcb4e311c165c08d8e9"

def read_json(path, required=True):
    path = Path(path)
    if not path.exists():
        if required:
            raise RuntimeError(f"Falta archivo: {path}")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return json.loads(
        df.to_json(
            orient="records",
            date_format="iso"
        )
    )

live_summary = read_json(
    V13 / "outputs/live_shadow/v13_live_shadow_summary.json"
)

if live_summary.get("status") != "PASS":
    raise RuntimeError(
        f"V13 NO PASS: {live_summary.get('status')}"
    )

if live_summary.get("seal_id") != EXPECTED_SEAL:
    raise RuntimeError("SEAL INCORRECTO")

if live_summary.get("real_orders_sent") is not False:
    raise RuntimeError("SAFETY: real_orders_sent != false")

if live_summary.get("tuning_performed") is not False:
    raise RuntimeError("SAFETY: tuning_performed != false")

v13_targets = read_csv(
    V13 /
    "outputs/live_shadow/v13_live_shadow_contract_latest.csv"
)

byma_summary = read_json(
    V13 /
    "outputs/phase5h_executable_v4/v13_phase5h_v4_summary.json",
    required=False
)

byma_portfolio = read_csv(
    V13 /
    "outputs/phase5h_executable_v4/v13_phase5h_v4_current_integer_portfolio.csv"
)

state = {
    "schema": "ALPHA_ENGINE_PRODUCTION_V1",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "status": "PASS",

    "model": {
        "authority": "V13_IDEAL",
        "local_implementation": "BYMA_TRANSFER",
        "seal_id": EXPECTED_SEAL,
        "holdout_verdict": live_summary.get("holdout_verdict"),
        "asof": live_summary.get("latest_completed_session")
    },

    "market": {
        "last_observed": live_summary.get("last_observed"),
        "latest_completed_session": live_summary.get("latest_completed_session"),
        "new_sessions": live_summary.get("new_sessions"),
        "coverage": live_summary.get("market_coverage_latest"),
        "sec": live_summary.get("sec")
    },

    "v13": {
        "summary": live_summary,
        "targets": v13_targets
    },

    "byma_transfer": {
        "summary": byma_summary,
        "portfolio": byma_portfolio
    },

    "safety": {
        "real_orders_sent": False,
        "tuning_performed": False,
        "personal_portfolio_included": False
    }
}

OUT.parent.mkdir(parents=True, exist_ok=True)

OUT.write_text(
    json.dumps(
        state,
        ensure_ascii=False,
        indent=2,
        default=str
    ),
    encoding="utf-8"
)

print("============================================")
print("PRODUCTION STATE: PASS")
print("V13 TARGETS:", len(v13_targets))
print("BYMA ROWS:", len(byma_portfolio))
print("ASOF:", live_summary.get("latest_completed_session"))
print("============================================")
