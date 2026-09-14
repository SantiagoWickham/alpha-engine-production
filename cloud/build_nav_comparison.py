import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

V13_ROOT = ROOT / "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
BYMA_ROOT = ROOT / "ALPHA_ENGINE_BYMA"

V13_PRE = (
    V13_ROOT
    / "outputs"
    / "v13_phase3z_nav_20bps.csv"
)

V13_HOLD = (
    V13_ROOT
    / "outputs"
    / "v13_phase4_holdout_nav_20bps.csv"
)

BYMA_PRE = (
    BYMA_ROOT
    / "outputs"
    / "byma_pre2025_nav_20bps.csv"
)

BYMA_HOLD = (
    BYMA_ROOT
    / "outputs"
    / "byma_holdout_nav_20bps.csv"
)

OUT_NAV = ROOT / "PRODUCT" / "nav_history.csv"
OUT_SUMMARY = ROOT / "PRODUCT" / "performance_summary.json"

DISPLAY_NOTIONAL_USD = 1000.0
TRADING_DAYS = 252.0


def read_nav(path):
    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(path)

    required = {"date", "nav"}

    if not required.issubset(df.columns):
        raise ValueError(
            f"{path.name}: missing columns "
            f"{required - set(df.columns)}"
        )

    df["date"] = pd.to_datetime(df["date"])
    df["nav"] = pd.to_numeric(df["nav"], errors="raise")

    df = (
        df.sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )

    if len(df) == 0:
        raise ValueError(f"{path.name}: empty")

    return df


def cagr_252(df):
    """
    Same annualization convention used by the validated model:
    252 trading sessions / number of NAV observations.
    """
    final_nav = float(df["nav"].iloc[-1])

    if final_nav <= 0:
        return None

    return float(
        final_nav ** (TRADING_DAYS / len(df)) - 1.0
    )


def max_drawdown(nav):
    s = pd.Series(nav, dtype=float)

    peak = s.cummax()
    dd = s / peak - 1.0

    return float(dd.min())


def chain(pre, hold):
    pre = pre.copy()
    hold = hold.copy()

    pre_final = float(pre["nav"].iloc[-1])

    pre["nav_chained"] = pre["nav"]

    hold["nav_chained"] = (
        hold["nav"] * pre_final
    )

    pre["segment"] = "PRE2025"
    hold["segment"] = "HOLDOUT"

    combined = pd.concat(
        [
            pre[["date", "nav_chained", "segment"]],
            hold[["date", "nav_chained", "segment"]],
        ],
        ignore_index=True,
    )

    combined = (
        combined
        .sort_values("date")
        .reset_index(drop=True)
    )

    return combined


# ============================================================
# LOAD CANONICAL SERIES
# ============================================================

v13_pre = read_nav(V13_PRE)
v13_hold = read_nav(V13_HOLD)

byma_pre = read_nav(BYMA_PRE)
byma_hold = read_nav(BYMA_HOLD)


# ============================================================
# VALIDATION AGAINST KNOWN MODEL RESULTS
# ============================================================

v13_pre_cagr = cagr_252(v13_pre)
v13_hold_cagr = cagr_252(v13_hold)

byma_pre_cagr = cagr_252(byma_pre)
byma_hold_cagr = cagr_252(byma_hold)

expected = {
    "v13_pre": 0.32230531748574753,
    "v13_hold": 0.30234103682729474,
    "byma_pre": 0.29592399007115877,
    "byma_hold": 0.2305155662746161,
}

actual = {
    "v13_pre": v13_pre_cagr,
    "v13_hold": v13_hold_cagr,
    "byma_pre": byma_pre_cagr,
    "byma_hold": byma_hold_cagr,
}

for key, target in expected.items():
    value = actual[key]

    if abs(value - target) > 1e-10:
        raise RuntimeError(
            f"CAGR VALIDATION FAILED {key}: "
            f"{value} != {target}"
        )


# ============================================================
# CHAIN PRE + HOLDOUT
# ============================================================

v13 = chain(v13_pre, v13_hold)
byma = chain(byma_pre, byma_hold)

v13 = v13.rename(
    columns={
        "nav_chained": "v13_ideal_nav",
        "segment": "v13_segment",
    }
)

byma = byma.rename(
    columns={
        "nav_chained": "byma_model_nav",
        "segment": "byma_segment",
    }
)

history = pd.merge(
    v13,
    byma,
    on="date",
    how="outer",
)

history = history.sort_values("date").reset_index(drop=True)

history["segment"] = np.where(
    history["date"] < pd.Timestamp("2025-01-01"),
    "PRE2025",
    "HOLDOUT",
)

history["v13_ideal_index_100"] = (
    history["v13_ideal_nav"] * 100.0
)

history["byma_model_index_100"] = (
    history["byma_model_nav"] * 100.0
)

history["v13_ideal_value_usd"] = (
    history["v13_ideal_nav"]
    * DISPLAY_NOTIONAL_USD
)

history["byma_model_value_usd"] = (
    history["byma_model_nav"]
    * DISPLAY_NOTIONAL_USD
)

# Personal portfolio deliberately empty until ledger exists.
history["personal_portfolio_nav"] = np.nan

history["date"] = history["date"].dt.strftime("%Y-%m-%d")

history = history[
    [
        "date",
        "segment",
        "v13_ideal_nav",
        "byma_model_nav",
        "personal_portfolio_nav",
        "v13_ideal_index_100",
        "byma_model_index_100",
        "v13_ideal_value_usd",
        "byma_model_value_usd",
    ]
]

history.to_csv(
    OUT_NAV,
    index=False,
    float_format="%.10f",
)


# ============================================================
# FULL-SERIES METRICS
# ============================================================

v13_final = float(
    pd.to_numeric(
        history["v13_ideal_nav"],
        errors="coerce",
    ).dropna().iloc[-1]
)

byma_final = float(
    pd.to_numeric(
        history["byma_model_nav"],
        errors="coerce",
    ).dropna().iloc[-1]
)

v13_full_nav = pd.to_numeric(
    history["v13_ideal_nav"],
    errors="coerce",
).dropna()

byma_full_nav = pd.to_numeric(
    history["byma_model_nav"],
    errors="coerce",
).dropna()

v13_full_cagr = float(
    v13_final
    ** (TRADING_DAYS / len(v13_full_nav))
    - 1.0
)

byma_full_cagr = float(
    byma_final
    ** (TRADING_DAYS / len(byma_full_nav))
    - 1.0
)

summary = {
    "schema": "ALPHA_ENGINE_PERFORMANCE_V1",
    "generated_at_utc": datetime.now(
        timezone.utc
    ).isoformat(),

    "display_notional_usd": DISPLAY_NOTIONAL_USD,

    "methodology": {
        "annualization_sessions": 252,
        "transaction_cost_case": "20bps",
        "v13_authority": "V13_IDEAL",
        "byma_model": "ACCEPTED_BYMA_TRANSFER",
        "phase5h_current_geometry_used_as_primary_curve": False,
        "personal_portfolio_separate": True,
    },

    "V13_IDEAL": {
        "status": "PASS",
        "start_date": str(
            v13_pre["date"].iloc[0].date()
        ),
        "end_date": str(
            v13_hold["date"].iloc[-1].date()
        ),
        "pre2025_cagr": v13_pre_cagr,
        "holdout_cagr": v13_hold_cagr,
        "full_period_cagr": v13_full_cagr,
        "final_nav_multiple": v13_final,
        "total_return": v13_final - 1.0,
        "max_drawdown_full": max_drawdown(
            v13_full_nav
        ),
        "sources": [
            str(V13_PRE.relative_to(ROOT)),
            str(V13_HOLD.relative_to(ROOT)),
        ],
    },

    "BYMA_MODEL": {
        "status": "PASS",
        "label": "BYMA_TRANSFER",
        "start_date": str(
            byma_pre["date"].iloc[0].date()
        ),
        "end_date": str(
            byma_hold["date"].iloc[-1].date()
        ),
        "pre2025_cagr": byma_pre_cagr,
        "holdout_cagr": byma_hold_cagr,
        "full_period_cagr": byma_full_cagr,
        "final_nav_multiple": byma_final,
        "total_return": byma_final - 1.0,
        "max_drawdown_full": max_drawdown(
            byma_full_nav
        ),
        "sources": [
            str(BYMA_PRE.relative_to(ROOT)),
            str(BYMA_HOLD.relative_to(ROOT)),
        ],
    },

    "RETENTION": {
        "pre2025_cagr_ratio": (
            byma_pre_cagr / v13_pre_cagr
        ),
        "holdout_cagr_ratio": (
            byma_hold_cagr / v13_hold_cagr
        ),
    },

    "PERSONAL_PORTFOLIO": {
        "status": "PENDING_LEDGER",
        "nav": None,
        "cagr": None,
        "max_drawdown": None,
    },
}

OUT_SUMMARY.write_text(
    json.dumps(
        summary,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)


# ============================================================
# REPORT
# ============================================================

print()
print("============================================================")
print("ALPHA ENGINE - PERFORMANCE LAYER")
print("============================================================")
print()

print(
    f"V13 PRE CAGR:       "
    f"{v13_pre_cagr:.4%}"
)

print(
    f"BYMA PRE CAGR:      "
    f"{byma_pre_cagr:.4%}"
)

print(
    f"PRE RETENTION:      "
    f"{byma_pre_cagr / v13_pre_cagr:.2%}"
)

print()

print(
    f"V13 HOLD CAGR:      "
    f"{v13_hold_cagr:.4%}"
)

print(
    f"BYMA HOLD CAGR:     "
    f"{byma_hold_cagr:.4%}"
)

print(
    f"HOLD RETENTION:     "
    f"{byma_hold_cagr / v13_hold_cagr:.2%}"
)

print()

print(
    f"NAV HISTORY:        {OUT_NAV}"
)

print(
    f"SUMMARY:            {OUT_SUMMARY}"
)

print()
print("PERFORMANCE LAYER: PASS")
print("============================================================")
