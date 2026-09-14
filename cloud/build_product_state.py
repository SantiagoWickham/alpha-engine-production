import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

LATEST_PATH = ROOT / "public" / "data" / "latest.json"
PERFORMANCE_PATH = ROOT / "PRODUCT" / "performance_summary.json"
NAV_PATH = ROOT / "PRODUCT" / "nav_history.csv"

PERSONAL_SUMMARY_PATH = ROOT / "PRODUCT" / "personal_portfolio.json"
PERSONAL_POSITIONS_PATH = ROOT / "PRODUCT" / "personal_portfolio_positions.json"
PERSONAL_CASH_PATH = ROOT / "PRODUCT" / "personal_portfolio_cash.json"
PERSONAL_LEDGER_PATH = ROOT / "PRODUCT" / "personal_portfolio_ledger.json"

OUTPUT_PATH = ROOT / "public" / "data" / "alpha_product_state.json"


def read_json(path: Path, required: bool = False, default=None):
    if not path.exists():
        if required:
            raise FileNotFoundError(f"MISSING_REQUIRED_FILE: {path}")
        return default

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def nested_get(obj: dict, *keys, default=None):
    current = obj

    for key in keys:
        if not isinstance(current, dict):
            return default

        if key not in current:
            return default

        current = current[key]

    return current


def clean_number(value: Any):
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    text = str(value).strip()

    if text == "":
        return None

    try:
        number = float(text)

        if not math.isfinite(number):
            return None

        return number

    except ValueError:
        return value


def read_nav_history():
    if not NAV_PATH.exists():
        return []

    rows = []

    with NAV_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        reader = csv.DictReader(f)

        for raw in reader:
            row = {}

            for key, value in raw.items():
                if key in {"date", "segment"}:
                    row[key] = value
                else:
                    row[key] = clean_number(value)

            rows.append(row)

    return rows


latest = read_json(
    LATEST_PATH,
    required=True,
)

performance = read_json(
    PERFORMANCE_PATH,
    required=True,
)

personal_summary = read_json(
    PERSONAL_SUMMARY_PATH,
    default={},
) or {}

personal_positions = read_json(
    PERSONAL_POSITIONS_PATH,
    default={},
) or {}

personal_cash = read_json(
    PERSONAL_CASH_PATH,
    default={},
) or {}

personal_ledger = read_json(
    PERSONAL_LEDGER_PATH,
    default={},
) or {}

nav_history = read_nav_history()


# ============================================================
# SAFETY / AUTHORITY VALIDATION
# ============================================================

if latest.get("status") != "PASS":
    raise RuntimeError(
        f"LATEST_STATE_NOT_PASS: {latest.get('status')}"
    )


authority = nested_get(
    latest,
    "model",
    "authority",
)

if authority != "V13_IDEAL":
    raise RuntimeError(
        f"INVALID_MODEL_AUTHORITY: {authority}"
    )


methodology = performance.get(
    "methodology",
    {}
)


byma_methodology = methodology.get(
    "byma_model"
)

if (
    byma_methodology is not None
    and byma_methodology != "ACCEPTED_BYMA_TRANSFER"
):
    raise RuntimeError(
        "PERFORMANCE_SUMMARY_IS_NOT_ACCEPTED_BYMA_TRANSFER"
    )


phase5h_primary = methodology.get(
    "phase5h_current_geometry_used_as_primary_curve"
)

if phase5h_primary is True:
    raise RuntimeError(
        "PHASE5H_CANNOT_BE_PRIMARY_BYMA_PERFORMANCE_CURVE"
    )


# ============================================================
# V13
# ============================================================

v13_targets = nested_get(
    latest,
    "v13",
    "targets",
    default=[],
) or []

v13_summary = nested_get(
    latest,
    "v13",
    "summary",
    default={},
) or []


v13_recommendations = []

for row in v13_targets:
    if not isinstance(row, dict):
        continue

    v13_recommendations.append({
        "signal_date": row.get("signal_date"),
        "ticker": row.get("ticker"),
        "target_weight": row.get("model_target_weight"),
        "expected_active_total": row.get("expected_active_total"),
        "entry_ok": row.get("entry_ok"),
        "model_intent": row.get("model_intent"),
    })


v13_recommendations.sort(
    key=lambda x: (
        x.get("target_weight") is None,
        -(x.get("target_weight") or 0),
        x.get("ticker") or "",
    )
)


# ============================================================
# BYMA CURRENT IMPLEMENTATION SNAPSHOT
# ============================================================

byma_portfolio = nested_get(
    latest,
    "byma_transfer",
    "portfolio",
    default=[],
) or []


byma_map = {}

for row in byma_portfolio:
    if not isinstance(row, dict):
        continue

    ticker = row.get("ticker")

    if ticker:
        byma_map[ticker] = row


byma_recommendations = []

for v13 in v13_recommendations:
    ticker = v13.get("ticker")
    byma = byma_map.get(ticker, {})

    byma_recommendations.append({
        "ticker": ticker,
        "v13_target_weight": v13.get("target_weight"),
        "v13_model_intent": v13.get("model_intent"),
        "v13_entry_ok": v13.get("entry_ok"),
        "vehicle_available": byma.get("vehicle_available"),
        "vehicle": byma.get("vehicle"),
        "byma_ticker": byma.get("byma_ticker"),
        "ratio": byma.get("ratio"),
        "unit_usd": byma.get("unit_usd"),
        "quantity": byma.get("quantity"),
        "actual_weight": byma.get("actual_weight"),
        "weight_error": byma.get("weight_error"),
        "reason": byma.get("reason"),
    })


# ============================================================
# UNIVERSE
# ============================================================

universe = []

for v13 in v13_recommendations:
    ticker = v13.get("ticker")
    byma = byma_map.get(ticker, {})

    universe.append({
        "ticker": ticker,
        "v13_target_weight": v13.get("target_weight"),
        "v13_entry_ok": v13.get("entry_ok"),
        "v13_model_intent": v13.get("model_intent"),
        "byma_vehicle_available": byma.get("vehicle_available"),
        "byma_vehicle": byma.get("vehicle"),
        "byma_ticker": byma.get("byma_ticker"),
    })


# ============================================================
# PERSONAL PORTFOLIO
# ============================================================

positions = personal_positions.get(
    "positions",
    [],
)

operations = personal_ledger.get(
    "operations",
    [],
)

personal = {
    "summary": personal_summary,
    "positions": positions,
    "cash": personal_cash,
    "operations": operations,
    "operations_count": len(operations),
    "positions_count": len(positions),
}


# ============================================================
# FUNDAMENTALS
# ============================================================

sec_summary = nested_get(
    latest,
    "market",
    "sec",
    default={},
) or {}

fundamentals = {
    "status": (
        "SUMMARY_AVAILABLE"
        if sec_summary
        else "NOT_CONNECTED"
    ),
    "sec_summary": sec_summary,
    "companies": [],
    "note": (
        "Per-company fundamentals will be attached "
        "to Product State when the company-level SEC export "
        "is connected."
    ),
}


# ============================================================
# MARKET / RISK
# ============================================================

market = nested_get(
    latest,
    "market",
    default={},
) or {}

risk = nested_get(
    latest,
    "risk",
    default={},
) or {}


# ============================================================
# COUNTS
# ============================================================

positive_targets = sum(
    1
    for row in v13_recommendations
    if (row.get("target_weight") or 0) > 0
)

entry_eligible = sum(
    1
    for row in v13_recommendations
    if row.get("entry_ok") is True
)

byma_available = sum(
    1
    for row in byma_recommendations
    if row.get("vehicle_available") is True
)


# ============================================================
# PRODUCT STATE
# ============================================================

product_state = {
    "schema": "ALPHA_ENGINE_PRODUCT_STATE_V1",

    "generated_at_utc": datetime.now(
        timezone.utc
    ).isoformat(),

    "system": {
        "status": latest.get("status"),
        "authority": authority,
        "local_implementation": nested_get(
            latest,
            "model",
            "local_implementation",
        ),
        "seal_id": nested_get(
            latest,
            "model",
            "seal_id",
        ),
        "holdout_verdict": nested_get(
            latest,
            "model",
            "holdout_verdict",
        ),
        "asof": nested_get(
            latest,
            "model",
            "asof",
        ),
        "shadow_only": nested_get(
            latest,
            "v13",
            "summary",
            "shadow_only",
        ),
        "real_orders_sent": nested_get(
            latest,
            "safety",
            "real_orders_sent",
        ),
        "tuning_performed": nested_get(
            latest,
            "safety",
            "tuning_performed",
        ),
        "personal_portfolio_included_in_model": nested_get(
            latest,
            "safety",
            "personal_portfolio_included",
        ),
    },

    "overview": {
        "universe_count": len(universe),
        "entry_eligible_count": entry_eligible,
        "positive_target_count": positive_targets,
        "byma_available_count": byma_available,
        "personal_operations_count": len(operations),
        "personal_positions_count": len(positions),
    },

    "v13": {
        "summary": v13_summary,
        "recommendations": v13_recommendations,
        "performance": performance.get(
            "V13_IDEAL",
            {},
        ),
    },

    "byma": {
        "model": "ACCEPTED_BYMA_TRANSFER",
        "performance": performance.get(
            "BYMA_MODEL",
            {},
        ),
        "retention": performance.get(
            "RETENTION",
            {},
        ),
        "current_implementation_snapshot": {
            "source": "LATEST_PRODUCTION_STATE",
            "note": (
                "Current BYMA implementation geometry is "
                "kept separate from the accepted BYMA "
                "historical performance curve."
            ),
            "portfolio": byma_portfolio,
        },
        "recommendations": byma_recommendations,
    },

    "personal": personal,

    "market": market,

    "risk": risk,

    "fundamentals": fundamentals,

    "universe": universe,

    "performance": {
        "methodology": methodology,
        "summary": performance,
        "nav_history": nav_history,
    },

    "data_sources": {
        "latest": "public/data/latest.json",
        "performance": "PRODUCT/performance_summary.json",
        "nav_history": "PRODUCT/nav_history.csv",
        "personal_summary": "PRODUCT/personal_portfolio.json",
        "personal_positions": "PRODUCT/personal_portfolio_positions.json",
        "personal_cash": "PRODUCT/personal_portfolio_cash.json",
        "personal_ledger": "PRODUCT/personal_portfolio_ledger.json",
    },
}


OUTPUT_PATH.write_text(
    json.dumps(
        product_state,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ),
    encoding="utf-8",
)


print()
print("============================================================")
print("ALPHA ENGINE - PRODUCT STATE")
print("============================================================")
print()

print(f"SYSTEM STATUS:        {product_state['system']['status']}")
print(f"AUTHORITY:            {product_state['system']['authority']}")
print(f"UNIVERSE:             {len(universe)}")
print(f"ENTRY ELIGIBLE:       {entry_eligible}")
print(f"POSITIVE TARGETS:     {positive_targets}")
print(f"BYMA AVAILABLE:       {byma_available}")
print(f"PERSONAL OPERATIONS:  {len(operations)}")
print(f"PERSONAL POSITIONS:   {len(positions)}")
print(f"NAV HISTORY ROWS:     {len(nav_history)}")

print()
print(f"OUTPUT: {OUTPUT_PATH}")

print()
print("ALPHA PRODUCT STATE: PASS")
print("============================================================")
