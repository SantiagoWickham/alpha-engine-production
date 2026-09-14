from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen
import json
import math
import re
import sys
import warnings
from io import StringIO

import numpy as np
import pandas as pd

ROOT = Path.cwd()
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

warnings.filterwarnings("ignore", message="Downcasting object dtype arrays")

print("=" * 120)
print("ALPHA ENGINE V13 - PHASE 5H V4")
print("EXECUTABLE V13 - COMPLETE CURRENT BYMA GEOMETRY INTEGER REPLAY + CAPITAL CAPACITY")
print("IDEAL V13 FROZEN / CEDEARS + LOCAL BYMA / INTEGER NOMINALS ONLY")
print("NO TOP-N / NO MANUAL STOCK SELECTION / NO TARGET REDISTRIBUTION")
print("CURRENT 2026 BYMA GEOMETRY REPLAYED OVER FROZEN V13 HISTORY")
print("=" * 120)

from alpha_engine_v13 import active_alpha_persistent_portfolio as p3y
from alpha_engine_v13 import roundtrip_resize_hysteresis as p3z
from alpha_engine_v13 import economic_portfolio_closure as p3v
from alpha_engine_v13 import final_holdout as p4

BUILD = "V13_P5H_V4_COMPLETE_BYMA_DUAL_ISSUER_INTEGER_REPLAY_2026-09-13"
BASE_COST_BPS = 20.0
STRESS_COSTS_BPS = [40.0, 60.0]

# Frozen acceptance gates. No tuning after results.
MIN_CAGR_RETENTION = 0.95
MAX_CAGR_SHORTFALL_PP = 0.02
MAX_DD_DETERIORATION_PP = 0.02
MAX_TURNOVER_MULTIPLE = 1.25
MAX_P95_EXECUTION_L1 = 0.10
MAX_CURRENT_L1 = 0.10
MAX_CURRENT_P95_ABS_WEIGHT_ERROR = 0.02
MAX_CURRENT_OVERWEIGHT = 0.025

BASE_CAPITAL_GRID = [
    500.0, 750.0, 1000.0, 1500.0, 2000.0, 3000.0, 5000.0,
    7500.0, 10000.0, 15000.0, 20000.0, 30000.0, 50000.0,
    75000.0, 100000.0, 150000.0, 250000.0, 500000.0,
    750000.0, 1000000.0, 2000000.0,
]

OUT = ROOT / "outputs" / "phase5h_executable_v4"
OUT.mkdir(parents=True, exist_ok=True)
CACHE = ROOT / "research" / "phase5h_cache"
CACHE.mkdir(parents=True, exist_ok=True)

SIZING_PATH = ROOT / "outputs" / "portfolio_sizing_shadow" / "v13_total_nav_shadow_sizing_latest.csv"
HOLDOUT_ADVISOR_PATH = ROOT / "outputs" / "v13_phase4_holdout_advisor.parquet"
OFFICIAL_PRE_NAV = ROOT / "outputs" / "v13_phase3z_nav_20bps.csv"
OFFICIAL_HOLD_NAV = ROOT / "outputs" / "v13_phase4_holdout_nav_20bps.csv"

for path in [SIZING_PATH, HOLDOUT_ADVISOR_PATH, OFFICIAL_PRE_NAV, OFFICIAL_HOLD_NAV]:
    if not path.exists():
        raise FileNotFoundError(path)

COMAFI_URL = "https://www.comafi.com.ar/Programas-CEDEARs-2483.note.aspx"
CAJA_URL = "https://cajadevalores.com.ar/Servicios/Cedears"
COMAFI_CACHE = CACHE / "comafi_cedear_master_2026-09-13.csv"
CAJA_CACHE = CACHE / "caja_cedear_master_2026-09-13.csv"

DETAIL_COLUMNS = [
    "ticker", "target_weight", "current_weight", "execution_present",
    "vehicle_available", "vehicle", "byma_ticker", "ratio", "unit_usd",
    "target_usd", "q_star", "quantity", "actual_usd", "actual_weight",
    "weight_error", "abs_weight_error", "reason",
]


def norm_ticker(x) -> str:
    return str(x).strip().upper().replace("*", "")


def norm_dates(x):
    return pd.to_datetime(x, errors="coerce").dt.normalize()


def ratio_tuple(x):
    m = re.search(r"(\d+)\s*:\s*(\d+)", str(x))
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a <= 0 or b <= 0:
        return None
    return a, b


def ratio_text(r):
    return "" if r is None else f"{int(r[0])}:{int(r[1])}"


def underlying_per_cedear(r):
    a, b = r
    return float(b / a)


def max_drawdown(nav):
    x = pd.to_numeric(nav, errors="coerce").dropna()
    if x.empty:
        return np.nan
    return float((x / x.cummax() - 1.0).min())


CORE_SIM_COLUMNS = [
    "nav", "turnover", "holdings", "cash_weight", "max_name_weight"
]


def _numeric_column(sim, name, default=0.0):
    """Return a numeric Series with fixed length. Optional execution-only
    diagnostics default to zero for the continuous ideal V13 simulation."""
    if name in sim.columns:
        return pd.to_numeric(sim[name], errors="coerce").fillna(default)
    return pd.Series(np.full(len(sim), float(default)), index=sim.index, dtype=float)


def metrics(sim):
    if sim.empty:
        raise RuntimeError("Empty simulation")

    missing = [c for c in CORE_SIM_COLUMNS if c not in sim.columns]
    if missing:
        raise RuntimeError(f"Simulation schema missing required columns: {missing}")

    nav = _numeric_column(sim, "nav", np.nan)
    if nav.isna().any() or not np.isfinite(nav.to_numpy(float)).all():
        raise RuntimeError("Simulation NAV contains non-finite values")

    years = len(sim) / 252.0
    final_nav = float(nav.iloc[-1])
    cagr = final_nav ** (1.0 / years) - 1.0 if final_nav > 0 and years > 0 else np.nan
    turn = float(_numeric_column(sim, "turnover", 0.0).sum()) / years

    holdings = _numeric_column(sim, "holdings", 0.0)
    cash = _numeric_column(sim, "cash_weight", 0.0)
    max_name = _numeric_column(sim, "max_name_weight", 0.0)

    # These columns exist only in the executable simulator. For ideal V13
    # they are definitionally zero because no integer projection occurs.
    exec_l1 = _numeric_column(sim, "execution_l1_error", 0.0)
    inaccessible = _numeric_column(sim, "inaccessible_target_weight", 0.0)

    return {
        "days": int(len(sim)),
        "final_nav": final_nav,
        "total_return": final_nav - 1.0,
        "cagr": float(cagr),
        "max_drawdown": max_drawdown(nav),
        "annual_turnover": float(turn),
        "median_holdings": float(holdings.median()),
        "max_holdings": int(holdings.max()),
        "mean_cash": float(cash.mean()),
        "p95_max_name": float(max_name.quantile(0.95)),
        "max_name": float(max_name.max()),
        "p95_execution_l1": float(exec_l1.quantile(0.95)),
        "mean_execution_l1": float(exec_l1.mean()),
        "mean_inaccessible_target_weight": float(inaccessible.mean()),
        "p95_inaccessible_target_weight": float(inaccessible.quantile(0.95)),
    }


def _self_test_metrics():
    # Continuous ideal schema: no executable-only columns.
    ideal = pd.DataFrame({
        "nav": [1.0, 1.01],
        "turnover": [0.0, 0.1],
        "holdings": [0, 2],
        "cash_weight": [1.0, 0.1],
        "max_name_weight": [0.0, 0.45],
    })
    m = metrics(ideal)
    if m["p95_execution_l1"] != 0.0 or m["mean_inaccessible_target_weight"] != 0.0:
        raise RuntimeError("Internal metrics self-test failed")


_self_test_metrics()


def recursive_nav(obj):
    keys = {"total_nav_usd", "nav_total_usd", "portfolio_nav_usd", "nav_usd"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in keys:
                try:
                    z = float(v)
                    if np.isfinite(z) and z > 0:
                        return z
                except Exception:
                    pass
        for v in obj.values():
            z = recursive_nav(v)
            if z is not None:
                return z
    elif isinstance(obj, list):
        for v in obj:
            z = recursive_nav(v)
            if z is not None:
                return z
    return None


# =============================================================================
# COMPLETE CURRENT OFFICIAL BYMA CEDEAR MASTER
# COMAFI + CAJA DE VALORES
# =============================================================================


def _clean_table_columns(df):
    x = df.copy()
    if isinstance(x.columns, pd.MultiIndex):
        x.columns = [
            " ".join(str(v) for v in tup if str(v).lower() != "nan").strip()
            for tup in x.columns.to_flat_index()
        ]
    else:
        x.columns = [str(c).strip() for c in x.columns]
    x.columns = [
        re.sub(r"\s+", " ", str(c).replace("\xa0", " ")).strip()
        for c in x.columns
    ]
    return x


def _fetch_text(url, agent):
    req = Request(url, headers={"User-Agent": agent})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def fetch_comafi_master():
    """
    Official Banco Comafi current CEDEAR programs.
    Cache is accepted only if structurally valid.
    """
    if COMAFI_CACHE.exists():
        x = pd.read_csv(COMAFI_CACHE)
        needed = {"market_id", "origin_ticker", "ratio_a", "ratio_b"}
        if len(x) >= 250 and needed.issubset(x.columns):
            x["issuer"] = x.get("issuer", "BANCO_COMAFI")
            return x, "CACHE"

    html = _fetch_text(COMAFI_URL, "Mozilla/5.0 AlphaEngineV13/4.0")
    rows = []

    for block in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.I | re.S):
        cells_raw = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", block, flags=re.I | re.S)
        cells = []
        for c in cells_raw:
            c = re.sub(r"<br\s*/?>", " ", c, flags=re.I)
            c = re.sub(r"<[^>]+>", " ", c)
            c = re.sub(r"\s+", " ", c.replace("\xa0", " ")).strip()
            cells.append(c)

        if len(cells) < 7:
            continue

        ridx = next(
            (i for i, c in enumerate(cells) if re.fullmatch(r"\d+\s*:\s*\d+", c)),
            None,
        )
        if ridx is None or ridx + 4 >= len(cells) or ridx < 2:
            continue

        rr = ratio_tuple(cells[ridx])
        if rr is None:
            continue

        market_id = norm_ticker(str(cells[ridx + 3]).split()[0])
        origin = norm_ticker(str(cells[ridx + 4]).split()[0])
        if not market_id:
            continue

        rows.append({
            "program_name": cells[ridx - 2],
            "current_ratio": ratio_text(rr),
            "ratio_a": int(rr[0]),
            "ratio_b": int(rr[1]),
            "caja_code": str(cells[ridx + 2]).strip(),
            "market_id": market_id,
            "origin_ticker": origin,
            "issuer": "BANCO_COMAFI",
        })

    x = pd.DataFrame(rows).drop_duplicates(
        ["issuer", "market_id", "origin_ticker"]
    ).reset_index(drop=True)

    if len(x) < 250:
        raise RuntimeError(
            f"FAIL CLOSED: Comafi parser returned only {len(x)} programs"
        )

    x.to_csv(COMAFI_CACHE, index=False)
    return x, "LIVE"


def fetch_caja_master():
    """
    Official Caja de Valores current CEDEAR programs.

    Important: Caja de Valores is itself a CEDEAR issuer. V3 omitted it,
    which incorrectly classified active BYMA instruments such as MU, OXY
    and KEEL as unavailable.
    """
    if CAJA_CACHE.exists():
        x = pd.read_csv(CAJA_CACHE)
        needed = {"market_id", "origin_ticker", "ratio_a", "ratio_b"}
        if len(x) >= 10 and needed.issubset(x.columns):
            x["issuer"] = x.get("issuer", "CAJA_DE_VALORES")
            return x, "CACHE"

    html = _fetch_text(CAJA_URL, "Mozilla/5.0 AlphaEngineV13/4.0")

    try:
        tables = pd.read_html(StringIO(html))
    except Exception as e:
        raise RuntimeError(
            f"FAIL CLOSED: could not parse Caja de Valores CEDEAR tables: {e}"
        ) from e

    rows = []

    for raw in tables:
        df = _clean_table_columns(raw)

        cols_norm = {
            c: re.sub(r"\s+", " ", c.lower().replace("\xa0", " ")).strip()
            for c in df.columns
        }

        def find_col(*needles):
            for original, low in cols_norm.items():
                if all(n.lower() in low for n in needles):
                    return original
            return None

        sym_col = (
            find_col("símbolo", "byma")
            or find_col("simbolo", "byma")
        )
        origin_col = (
            find_col("ticker", "origen")
            or find_col("ticker", "mercado")
        )
        ratio_col = (
            find_col("ratio", "cedear")
            or find_col("ratio", "subyacente")
        )
        code_col = (
            find_col("código", "caja", "cedear")
            or find_col("codigo", "caja", "cedear")
        )

        if sym_col is None or origin_col is None or ratio_col is None:
            continue

        name_col = df.columns[0]

        for r in df.itertuples(index=False, name=None):
            rec = dict(zip(df.columns, r))

            market_id = norm_ticker(rec.get(sym_col, ""))
            origin = norm_ticker(rec.get(origin_col, ""))
            rr = ratio_tuple(rec.get(ratio_col))

            if not market_id or market_id in {"NAN", "NONE"} or rr is None:
                continue

            # Exclude section labels / malformed rows.
            if len(market_id) > 16 or "CEDEAR" in market_id:
                continue

            code = ""
            if code_col is not None:
                code = str(rec.get(code_col, "")).strip()

            rows.append({
                "program_name": str(rec.get(name_col, "")).strip(),
                "current_ratio": ratio_text(rr),
                "ratio_a": int(rr[0]),
                "ratio_b": int(rr[1]),
                "caja_code": code,
                "market_id": market_id,
                "origin_ticker": origin,
                "issuer": "CAJA_DE_VALORES",
            })

    x = pd.DataFrame(rows).drop_duplicates(
        ["issuer", "market_id", "origin_ticker"]
    ).reset_index(drop=True)

    # Current official Caja catalogue contains materially more than a
    # trivial handful of programs. Fail closed if the parser clearly broke.
    if len(x) < 10:
        raise RuntimeError(
            f"FAIL CLOSED: Caja de Valores parser returned only {len(x)} programs"
        )

    # Critical sanity names known to be current Caja-issued CEDEARs.
    for required in ["MU", "OXY", "KEEL"]:
        if not (
            (x["market_id"] == required)
            | (x["origin_ticker"] == required)
        ).any():
            raise RuntimeError(
                f"FAIL CLOSED: official Caja master missing sanity ticker {required}"
            )

    x.to_csv(CAJA_CACHE, index=False)
    return x, "LIVE"


print()
print("[1/11] COMPLETE CURRENT BYMA EXECUTION GEOMETRY")

comafi, comafi_source = fetch_comafi_master()
caja, caja_source = fetch_caja_master()

programs = pd.concat([comafi, caja], ignore_index=True)

# If two issuers expose the same economic underlying, keep both rows in
# the audit master. PROGRAM_CHOICES below will choose the smallest
# executable unit; it does NOT choose based on alpha or realized returns.
programs["market_id"] = programs["market_id"].map(norm_ticker)
programs["origin_ticker"] = programs["origin_ticker"].map(norm_ticker)
programs["ratio_a"] = pd.to_numeric(programs["ratio_a"], errors="coerce")
programs["ratio_b"] = pd.to_numeric(programs["ratio_b"], errors="coerce")
programs = programs.dropna(subset=["ratio_a", "ratio_b"]).copy()
programs = programs[
    programs["ratio_a"].gt(0)
    & programs["ratio_b"].gt(0)
].reset_index(drop=True)

print(f"  Comafi programs: {len(comafi):,} ({comafi_source})")
print(f"  Caja de Valores programs: {len(caja):,} ({caja_source})")
print(f"  Combined official program rows: {len(programs):,}")

# Sanity checks across the COMBINED official universe.
for required in ["AAPL", "MSFT", "GOOGL", "AMD", "MELI", "NKE", "MU", "OXY", "KEEL"]:
    if not (
        (programs["market_id"] == required)
        | (programs["origin_ticker"] == required)
    ).any():
        raise RuntimeError(
            f"FAIL CLOSED: complete current official CEDEAR universe missing {required}"
        )

PROGRAM_CHOICES = {}

for r in programs.itertuples():
    aliases = {
        norm_ticker(r.market_id),
        norm_ticker(r.origin_ticker),
    }
    for alias in aliases:
        if not alias:
            continue
        PROGRAM_CHOICES.setdefault(alias, []).append(r)


# Current production geometry for Argentine ADRs with fungible local BYMA shares.
# Ratios are economic local shares represented by one US ADS/ADR.
LOCAL_CURRENT = {
    "GGAL": {"byma": "GGAL", "shares_per_adr": 10.0},
    "BMA":  {"byma": "BMA",  "shares_per_adr": 10.0},
    "BBAR": {"byma": "BBAR", "shares_per_adr": 3.0},
    "SUPV": {"byma": "SUPV", "shares_per_adr": 5.0},
    "LOMA": {"byma": "LOMA", "shares_per_adr": 5.0},
    "PAM":  {"byma": "PAMP", "shares_per_adr": 25.0},
    "TGS":  {"byma": "TGSU2", "shares_per_adr": 5.0},
    "EDN":  {"byma": "EDN",  "shares_per_adr": 20.0},
    "CRESY":{"byma": "CRES", "shares_per_adr": 10.0},
    "IRS":  {"byma": "IRSA", "shares_per_adr": 10.0},
    "TEO":  {"byma": "TECO2","shares_per_adr": 5.0},
    "CEPU": {"byma": "CEPU", "shares_per_adr": 10.0},
    "YPF":  {"byma": "YPFD", "shares_per_adr": 10.0},
}


def execution_unit(model_ticker, underlying_price):
    """
    Return the smallest CURRENT integer BYMA unit representing the same
    economic underlying. Candidate vehicles come only from the official
    Comafi/Caja catalogues plus explicitly mapped fungible local shares.

    No realized return or alpha ranking enters this choice.
    """
    t = norm_ticker(model_ticker)

    try:
        px = float(underlying_price)
    except Exception:
        px = np.nan

    if not np.isfinite(px) or px <= 0:
        return None

    choices = []

    for p in PROGRAM_CHOICES.get(t, []):
        rr = (int(p.ratio_a), int(p.ratio_b))
        unit = px * underlying_per_cedear(rr)

        if np.isfinite(unit) and unit > 0:
            choices.append({
                "vehicle": f"CEDEAR_{str(p.issuer)}",
                "byma_ticker": norm_ticker(p.market_id),
                "ratio": ratio_text(rr),
                "unit_usd": float(unit),
            })

    loc = LOCAL_CURRENT.get(t)
    if loc is not None:
        unit = px / float(loc["shares_per_adr"])
        if np.isfinite(unit) and unit > 0:
            choices.append({
                "vehicle": "LOCAL_BYMA_SHARE",
                "byma_ticker": loc["byma"],
                "ratio": f"1 ADR:{loc['shares_per_adr']:g} LOCAL",
                "unit_usd": float(unit),
            })

    if not choices:
        return None

    # For the same exposure, the smallest unit is mechanically the most
    # precise integer representation. This is an execution rule, not a
    # stock-selection rule.
    return min(
        choices,
        key=lambda z: (
            z["unit_usd"],
            z["byma_ticker"],
            z["vehicle"],
        ),
    )


# =============================================================================
# LOAD FROZEN IDEAL V13 AND EXACT OFFICIAL MARKETS
# =============================================================================

print()
print("[2/11] REBUILD FROZEN IDEAL V13")
cfg3z = p3z.load_cfg(ROOT)
if int(cfg3z.p["risk_lookback_sessions"]) != 60:
    raise RuntimeError("FAIL CLOSED: V13 risk lookback changed from frozen 60")

_, _, source, scores, targets = p3y.load_inputs(ROOT, cfg3z)
hold = pd.Timestamp(cfg3z.p["holdout_start"])
start = pd.Timestamp(cfg3z.p["portfolio_start"])
pcfg = p3v.load_cfg(ROOT)

advisor_pre, _, _ = p3y.build_active_advisor(scores, targets, cfg3z)
advisor_pre["signal_date"] = norm_dates(advisor_pre["signal_date"])
advisor_pre["ticker"] = advisor_pre["ticker"].map(norm_ticker)

needed_pre = set(advisor_pre["ticker"].unique())
surface_pre = p3v.load_market(ROOT, source, pcfg, needed_pre)
spy_pre = p3v._load_benchmark(source, pcfg.p["source_spy_benchmark"], "SPY", hold)
qqq_pre = p3v._load_benchmark(source, pcfg.p["source_qqq_benchmark"], "QQQ", hold)
market_pre = p3v.prepare_market(surface_pre, spy_pre, start, hold, 60)

# Attach raw execution price panel ONLY as an auxiliary input to integer sizing.
# It does not alter returns, vol, plans or V13 economics.
if "execution_close" not in surface_pre.columns:
    raise RuntimeError("FAIL CLOSED: official pre-2025 execution surface lacks execution_close")
market_pre["execution_close"] = (
    surface_pre.pivot_table(index="date", columns="ticker", values="execution_close", aggfunc="last")
    .reindex(market_pre["calendar"])
)

terminals = p3v.load_terminals(source, pcfg)
plans_pre = p3z.build_plans(advisor_pre, market_pre, cfg3z)

advisor_hold = pd.read_parquet(HOLDOUT_ADVISOR_PATH)
advisor_hold["signal_date"] = norm_dates(advisor_hold["signal_date"])
advisor_hold["ticker"] = advisor_hold["ticker"].map(norm_ticker)

cfg1 = p4.p1.load_cfg(ROOT)
cfg1full = p4.p1.Cfg({**cfg1.p, "holdout_start": "2100-01-01"})
market_full, _ = p4._load_full_market(source, cfg1full)
end = pd.Timestamp(market_full["date"].max())
bench_full = p4._load_full_bench(source, cfg1full, market_full)

canonical = pd.read_parquet(
    source / "outputs" / "phase2_canonical_pit_panel.parquet",
    columns=["date", "ticker", "close", "research_eligible"],
)
ret_layer = pd.read_parquet(
    source / "outputs" / "phase2c_return_price_layer.parquet",
    columns=["date", "ticker", "target_total_return_price"],
)
canonical["date"] = norm_dates(canonical["date"])
canonical["ticker"] = canonical["ticker"].map(norm_ticker)
ret_layer["date"] = norm_dates(ret_layer["date"])
ret_layer["ticker"] = ret_layer["ticker"].map(norm_ticker)
surf_hold = canonical.merge(ret_layer, on=["date", "ticker"], how="left")
surf_hold["execution_close"] = pd.to_numeric(surf_hold["close"], errors="coerce")
surf_hold["mark_price"] = pd.to_numeric(surf_hold["target_total_return_price"], errors="coerce")
surf_hold["research_eligible"] = surf_hold["research_eligible"].fillna(False).astype(bool)
surf_hold = surf_hold[["date", "ticker", "execution_close", "mark_price", "research_eligible"]]

spy_hold = bench_full.dropna(subset=["SPY"]).drop_duplicates("date").set_index("date")["SPY"]
qqq_hold = bench_full.dropna(subset=["QQQ"]).drop_duplicates("date").set_index("date")["QQQ"]
end_excl = end + pd.Timedelta(days=1)
market_hold = p3v.prepare_market(surf_hold, spy_hold, hold, end_excl, 60)
market_hold["execution_close"] = (
    surf_hold.pivot_table(index="date", columns="ticker", values="execution_close", aggfunc="last")
    .reindex(market_hold["calendar"])
)
plans_hold = p3z.build_plans(advisor_hold, market_hold, cfg3z)


# =============================================================================
# EXACT IDEAL PARITY
# =============================================================================

print()
print("[3/11] AUTHORITATIVE IDEAL V13 PARITY")


def assert_parity(rebuilt, official_path, label):
    official = pd.read_csv(official_path)
    a = rebuilt.copy(); b = official.copy()
    a["date"] = norm_dates(a["date"]); b["date"] = norm_dates(b["date"])
    z = a.merge(b, on="date", how="outer", suffixes=("_new", "_official"), indicator=True)
    if not z["_merge"].eq("both").all():
        raise RuntimeError(f"{label}: date parity failed")
    cols = ["nav", "net_return", "turnover", "entry_exit_notional", "resize_notional", "cost_fraction", "holdings", "cash_weight", "max_name_weight", "requested", "executed", "blocked", "deviation"]
    worst = 0.0
    for c in cols:
        gap = (pd.to_numeric(z[f"{c}_new"], errors="coerce") - pd.to_numeric(z[f"{c}_official"], errors="coerce")).abs()
        worst = max(worst, float(gap.max()))
    print(f"  {label:<18} max gap={worst:.3e}")
    if worst > 1e-9:
        raise RuntimeError(f"{label}: official parity failed")


ideal_pre_20 = p3y.simulate_persistent(plans_pre, market_pre, terminals, start, hold, BASE_COST_BPS)
ideal_hold_20 = p3y.simulate_persistent(plans_hold, market_hold, terminals, hold, end_excl, BASE_COST_BPS)
assert_parity(ideal_pre_20, OFFICIAL_PRE_NAV, "PRE2025")
assert_parity(ideal_hold_20, OFFICIAL_HOLD_NAV, "FINAL_HOLDOUT")
IDEAL_PRE = metrics(ideal_pre_20)
IDEAL_HOLD = metrics(ideal_hold_20)
print(f"  IDEAL PRE2025 CAGR: {IDEAL_PRE['cagr']:.2%}")
print(f"  IDEAL HOLDOUT CAGR: {IDEAL_HOLD['cagr']:.2%}")


# =============================================================================
# CURRENT NAV
# =============================================================================

sizing = pd.read_csv(SIZING_PATH)
sizing["ticker"] = sizing["ticker"].map(norm_ticker)
for c in ["phase3z_target_weight_total_nav", "target_value_usd", "quantity_current", "current_market_value_usd"]:
    if c in sizing.columns:
        sizing[c] = pd.to_numeric(sizing[c], errors="coerce")

qnav = sizing[(sizing["phase3z_target_weight_total_nav"] > 0) & (sizing["target_value_usd"] > 0)].copy()
implied_nav = (qnav["target_value_usd"] / qnav["phase3z_target_weight_total_nav"]).replace([np.inf, -np.inf], np.nan).dropna()
if implied_nav.empty:
    raise RuntimeError("Cannot derive current NAV")
CURRENT_NAV = float(implied_nav.median())
ASOF = pd.to_datetime(sizing["asof"].iloc[0]).normalize()
print(f"  current NAV USD: {CURRENT_NAV:,.2f}")


# =============================================================================
# ROBUST INTEGER PROJECTION — PLAIN DICTS, FIXED SCHEMA
# =============================================================================


def _empty_detail_row(t, tw, cw, present):
    return {
        "ticker": t,
        "target_weight": float(tw),
        "current_weight": float(cw),
        "execution_present": bool(present),
        "vehicle_available": False,
        "vehicle": "",
        "byma_ticker": "",
        "ratio": "",
        "unit_usd": np.nan,
        "target_usd": np.nan,
        "q_star": np.nan,
        "quantity": 0,
        "actual_usd": 0.0,
        "actual_weight": 0.0,
        "weight_error": 0.0,
        "abs_weight_error": 0.0,
        "reason": "",
    }


def integer_projection(target_weights, nav_usd, price_row, presence_row=None, current_weights=None):
    nav_usd = float(nav_usd)
    if not np.isfinite(nav_usd) or nav_usd <= 0:
        raise RuntimeError("Invalid NAV in integer projection")

    tgt = {norm_ticker(k): max(0.0, float(v)) for k, v in target_weights.items() if np.isfinite(v) and float(v) > 1e-14}
    cur = {} if current_weights is None else {norm_ticker(k): max(0.0, float(v)) for k, v in current_weights.items() if np.isfinite(v) and float(v) > 1e-14}
    names = sorted(set(tgt) | set(cur))

    rows = []
    inaccessible_target_weight = 0.0

    for t in names:
        tw = float(tgt.get(t, 0.0))
        cw = float(cur.get(t, 0.0))
        present = True if presence_row is None else bool(presence_row.get(t, False))
        row = _empty_detail_row(t, tw, cw, present)
        row["target_usd"] = tw * nav_usd

        # Exit target. If underlying cannot execute today, retain current exposure.
        if tw <= 1e-14:
            if cw > 1e-14 and not present:
                row["actual_weight"] = cw
                row["actual_usd"] = cw * nav_usd
                row["reason"] = "BLOCKED_EXIT_RETAIN_CURRENT"
            else:
                row["reason"] = "TARGET_ZERO_EXIT"
            rows.append(row)
            continue

        # Positive target but underlying cannot execute today: preserve current if any.
        if not present:
            row["actual_weight"] = cw
            row["actual_usd"] = cw * nav_usd
            row["reason"] = "BLOCKED_TARGET_RETAIN_CURRENT"
            rows.append(row)
            continue

        px = price_row.get(t, np.nan)
        info = execution_unit(t, px)
        if info is None:
            inaccessible_target_weight += tw
            # If somehow already held, preserve it rather than fabricating an exit.
            row["actual_weight"] = cw
            row["actual_usd"] = cw * nav_usd
            row["reason"] = "NO_CURRENT_BYMA_VEHICLE"
            rows.append(row)
            continue

        unit = float(info["unit_usd"])
        q_star = row["target_usd"] / unit
        q_floor = int(math.floor(q_star))
        frac = q_star - q_floor
        # Nearest integer; exact tie rounds down to preserve cash / avoid forced exposure.
        qty = q_floor + 1 if frac > 0.5 else q_floor

        row.update({
            "vehicle_available": True,
            "vehicle": info["vehicle"],
            "byma_ticker": info["byma_ticker"],
            "ratio": info["ratio"],
            "unit_usd": unit,
            "q_star": float(q_star),
            "quantity": int(qty),
            "actual_usd": float(qty * unit),
            "actual_weight": float(qty * unit / nav_usd),
            "reason": "INTEGER_NEAREST",
        })
        rows.append(row)

    # Fixed schema even when zero rows or every row is unavailable.
    detail = pd.DataFrame(rows, columns=DETAIL_COLUMNS)

    # Budget repair: independent nearest rounding can overspend by small amounts,
    # especially when blocked current positions coexist with rounded targets.
    def total_weight(df):
        return float(pd.to_numeric(df["actual_weight"], errors="coerce").fillna(0).sum())

    guard = 0
    while total_weight(detail) > 1.0 + 1e-10:
        guard += 1
        if guard > 100000:
            raise RuntimeError("Budget repair did not converge")

        candidates = []
        for idx, r in detail.iterrows():
            try:
                qty = int(r["quantity"])
                unit = float(r["unit_usd"])
            except Exception:
                continue
            if qty <= 0 or not np.isfinite(unit) or unit <= 0 or not bool(r["vehicle_available"]):
                continue
            old_w = float(r["actual_weight"])
            new_w = (qty - 1) * unit / nav_usd
            tw = float(r["target_weight"])
            penalty = abs(new_w - tw) - abs(old_w - tw)
            candidates.append((penalty, -unit, str(r["ticker"]), idx))

        if not candidates:
            raise RuntimeError("FAIL CLOSED: integer portfolio exceeds NAV and cannot be repaired")

        _, _, _, idx = min(candidates)
        qty = int(detail.at[idx, "quantity"]) - 1
        unit = float(detail.at[idx, "unit_usd"])
        detail.at[idx, "quantity"] = qty
        detail.at[idx, "actual_usd"] = qty * unit
        detail.at[idx, "actual_weight"] = qty * unit / nav_usd
        detail.at[idx, "reason"] = "INTEGER_BUDGET_REPAIR"

    detail["weight_error"] = pd.to_numeric(detail["actual_weight"], errors="coerce").fillna(0) - pd.to_numeric(detail["target_weight"], errors="coerce").fillna(0)
    detail["abs_weight_error"] = detail["weight_error"].abs()

    actual = {
        str(r.ticker): float(r.actual_weight)
        for r in detail.itertuples()
        if np.isfinite(float(r.actual_weight)) and float(r.actual_weight) > 1e-14
    }
    invested = float(sum(actual.values()))
    if invested > 1.0000001:
        raise RuntimeError("FAIL CLOSED: repaired portfolio still exceeds NAV")

    cash = max(0.0, 1.0 - invested)
    ideal_cash = max(0.0, 1.0 - sum(tgt.values()))
    allnames = set(tgt) | set(actual)
    asset_l1 = sum(abs(actual.get(t, 0.0) - tgt.get(t, 0.0)) for t in allnames)
    l1 = asset_l1 + abs(cash - ideal_cash)
    max_over = max([actual.get(t, 0.0) - tgt.get(t, 0.0) for t in allnames] + [0.0])
    max_abs = max([abs(actual.get(t, 0.0) - tgt.get(t, 0.0)) for t in allnames] + [0.0])

    return {
        "weights": actual,
        "cash": float(cash),
        "detail": detail,
        "l1_error": float(l1),
        "max_abs_error": float(max_abs),
        "max_overweight": float(max_over),
        "inaccessible_target_weight": float(inaccessible_target_weight),
    }


# =============================================================================
# EXECUTABLE SIMULATOR
# =============================================================================


def simulate_executable(plans, market, terminals, start_date, end_date, initial_capital_usd, round_trip_bps):
    cal = market["calendar"][(market["calendar"] >= start_date) & (market["calendar"] < end_date)]
    ret = market["returns"]
    raw = market["execution_close"]
    pres = market["execution_presence"]

    w = {}
    cash = 1.0
    nav = 1.0
    pending = None
    rows = []
    one = float(round_trip_bps) / 2.0 / 10000.0

    for d in cal:
        d = pd.Timestamp(d)
        prev = nav

        # mark existing positions exactly like V13
        if w:
            rr = ret.loc[d] if d in ret.index else pd.Series(dtype=float)
            vals = {}
            for t, v in w.items():
                r = rr.get(t, np.nan)
                r = float(r) if np.isfinite(r) else 0.0
                vals[t] = v * (1.0 + r)
            total = cash + sum(vals.values())
            if total > 0:
                w = {t: v / total for t, v in vals.items() if v > 1e-14}
                cash /= total
                nav *= total

        turnover = cost = requested = executed = blocked = 0.0
        entry_exit = resize = 0.0
        exec_l1 = max_abs = max_over = inaccessible = 0.0

        if pending is not None:
            old = dict(w)
            oldcash = cash
            econ = p3y._economic_target(old, pending)
            nav_usd = float(initial_capital_usd) * nav
            pr = raw.loc[d] if d in raw.index else pd.Series(dtype=float)
            er = pres.loc[d] if d in pres.index else pd.Series(dtype=bool)
            proj = integer_projection(econ, nav_usd, pr, presence_row=er, current_weights=old)
            actual = proj["weights"]
            newcash = proj["cash"]

            requested = float(sum(abs(econ.get(t, 0.0) - old.get(t, 0.0)) for t in set(econ) | set(old)))
            executed = float(sum(abs(actual.get(t, 0.0) - old.get(t, 0.0)) for t in set(actual) | set(old)))
            blocked = max(0.0, requested - executed)
            turnover = 0.5 * (executed + abs(newcash - oldcash))
            cost = one * executed
            nav *= max(0.0, 1.0 - cost)

            for t in set(old) | set(actual):
                a = float(old.get(t, 0.0)); b = float(actual.get(t, 0.0)); ch = abs(b - a)
                if (a <= 1e-14) != (b <= 1e-14):
                    entry_exit += ch
                else:
                    resize += ch

            w = {t: float(v) for t, v in actual.items() if v > 1e-14}
            cash = float(newcash)
            exec_l1 = proj["l1_error"]
            max_abs = proj["max_abs_error"]
            max_over = proj["max_overweight"]
            inaccessible = proj["inaccessible_target_weight"]
            pending = None

        for t in [t for t in list(w) if terminals.get(t) == d]:
            cash += w.pop(t)

        if d in plans:
            pending = plans[d]

        rows.append({
            "date": d,
            "nav": nav,
            "net_return": nav / prev - 1.0 if prev > 0 else -1.0,
            "turnover": turnover,
            "entry_exit_notional": entry_exit,
            "resize_notional": resize,
            "cost_fraction": cost,
            "holdings": len(w),
            "cash_weight": cash,
            "max_name_weight": max(w.values()) if w else 0.0,
            "requested": requested,
            "executed": executed,
            "blocked": blocked,
            "execution_l1_error": exec_l1,
            "max_abs_weight_error": max_abs,
            "max_overweight": max_over,
            "inaccessible_target_weight": inaccessible,
        })

    sim_columns = [
        "date", "nav", "net_return", "turnover", "entry_exit_notional",
        "resize_notional", "cost_fraction", "holdings", "cash_weight",
        "max_name_weight", "requested", "executed", "blocked",
        "execution_l1_error", "max_abs_weight_error", "max_overweight",
        "inaccessible_target_weight",
    ]
    return pd.DataFrame(rows, columns=sim_columns)


# =============================================================================
# CURRENT SNAPSHOT
# =============================================================================

print()
print("[4/11] CURRENT TARGET REPRESENTABILITY")
current_target = sizing[sizing["phase3z_target_weight_total_nav"] > 0].set_index("ticker")["phase3z_target_weight_total_nav"].to_dict()

# combine exact raw-price panels and take latest date <= asof
all_raw = pd.concat([market_pre["execution_close"], market_hold["execution_close"]]).sort_index()
all_raw = all_raw[~all_raw.index.duplicated(keep="last")]
raw_dates = all_raw.index[all_raw.index <= ASOF]
if len(raw_dates) == 0:
    raise RuntimeError("No execution prices <= current asof")
CURRENT_PRICE_DATE = pd.Timestamp(raw_dates.max())
current_prices = all_raw.loc[CURRENT_PRICE_DATE]

proj_cache = {}

def current_projection(cap):
    cap = float(cap)
    if cap not in proj_cache:
        proj_cache[cap] = integer_projection(current_target, cap, current_prices)
    return proj_cache[cap]

pnow = current_projection(CURRENT_NAV)
dnow = pnow["detail"].copy().sort_values(["target_weight", "ticker"], ascending=[False, True])
print(f"  target names: {len(current_target)}")
print(f"  executable names now: {len(pnow['weights'])}")
print(f"  inaccessible target weight: {pnow['inaccessible_target_weight']:.2%}")
print(f"  cash after exact nearest-integer projection: {pnow['cash']:.2%}")
print(f"  L1 tracking error: {pnow['l1_error']:.2%}")
print(f"  max abs name error: {pnow['max_abs_error']:.2%}")
print(f"  max overweight: {pnow['max_overweight']:.2%}")
print(f"  raw-price reference: {CURRENT_PRICE_DATE.date()}")

print()
print("  CURRENT INTEGER TARGET")
print(dnow[["ticker", "target_weight", "vehicle", "byma_ticker", "ratio", "unit_usd", "q_star", "quantity", "actual_weight", "weight_error", "reason"]].to_string(index=False))


# =============================================================================
# GATES
# =============================================================================


def noninferiority(candidate, ideal):
    retention = candidate["cagr"] / ideal["cagr"] if ideal["cagr"] > 0 else np.nan
    shortfall = ideal["cagr"] - candidate["cagr"]
    dd_deterioration = max(0.0, ideal["max_drawdown"] - candidate["max_drawdown"])
    turn_multiple = candidate["annual_turnover"] / ideal["annual_turnover"] if ideal["annual_turnover"] > 0 else np.nan
    gates = {
        "cagr_retention": bool(np.isfinite(retention) and retention >= MIN_CAGR_RETENTION),
        "cagr_shortfall": bool(shortfall <= MAX_CAGR_SHORTFALL_PP),
        "drawdown": bool(dd_deterioration <= MAX_DD_DETERIORATION_PP),
        "turnover": bool(np.isfinite(turn_multiple) and turn_multiple <= MAX_TURNOVER_MULTIPLE),
        "tracking": bool(candidate["p95_execution_l1"] <= MAX_P95_EXECUTION_L1),
    }
    return {
        "pass": all(gates.values()),
        "gates": gates,
        "retention": float(retention),
        "shortfall": float(shortfall),
        "dd_deterioration": float(dd_deterioration),
        "turnover_multiple": float(turn_multiple),
    }


def current_fit(cap):
    p = current_projection(cap)
    d = p["detail"]
    p95 = float(pd.to_numeric(d["abs_weight_error"], errors="coerce").fillna(0).quantile(0.95)) if len(d) else 1.0
    gates = {
        "l1": p["l1_error"] <= MAX_CURRENT_L1,
        "p95_abs_error": p95 <= MAX_CURRENT_P95_ABS_WEIGHT_ERROR,
        "max_overweight": p["max_overweight"] <= MAX_CURRENT_OVERWEIGHT,
    }
    return {
        "pass": all(gates.values()),
        "gates": gates,
        "l1": p["l1_error"],
        "p95_abs_error": p95,
        "max_overweight": p["max_overweight"],
        "inaccessible_target_weight": p["inaccessible_target_weight"],
        "holdings": len(p["weights"]),
        "cash": p["cash"],
    }


# =============================================================================
# PRE-GRID INTERNAL CONTRACT CHECKS
# =============================================================================

print()
print("[5/12] INTERNAL EXECUTION CONTRACT CHECKS")

# 1) Empty target must be valid and remain 100% cash.
_empty_proj = integer_projection({}, 1000.0, current_prices)
if _empty_proj["weights"] or abs(_empty_proj["cash"] - 1.0) > 1e-12:
    raise RuntimeError("FAIL CLOSED: empty-target integer projection self-test failed")

# 2) Current projection must expose the full fixed detail schema.
_missing_detail = [c for c in DETAIL_COLUMNS if c not in pnow["detail"].columns]
if _missing_detail:
    raise RuntimeError(f"FAIL CLOSED: projection detail schema missing {_missing_detail}")

# 3) Ideal metrics must remain valid without executable-only columns.
if IDEAL_PRE["p95_execution_l1"] != 0.0 or IDEAL_HOLD["p95_execution_l1"] != 0.0:
    raise RuntimeError("FAIL CLOSED: ideal executable diagnostics are not zero")

print("  metrics optional-column contract: PASS")
print("  empty-target projection: PASS")
print("  fixed detail schema: PASS")


# =============================================================================
# CAPITAL GRID
# =============================================================================

print()
print("[6/12] COMPLETE CAPITAL CAPACITY GRID - 20 BPS")
grid = sorted(set([round(CURRENT_NAV, 2)] + BASE_CAPITAL_GRID))
rows = []
sim_cache = {}

for cap in grid:
    print(f"  USD {cap:,.2f}")
    pre_sim = simulate_executable(plans_pre, market_pre, terminals, start, hold, cap, BASE_COST_BPS)
    hold_sim = simulate_executable(plans_hold, market_hold, terminals, hold, end_excl, cap, BASE_COST_BPS)
    pm = metrics(pre_sim); hm = metrics(hold_sim)
    pg = noninferiority(pm, IDEAL_PRE); hg = noninferiority(hm, IDEAL_HOLD); cg = current_fit(cap)
    passed = bool(pg["pass"] and hg["pass"] and cg["pass"])

    rows.append({
        "capital_usd": cap,
        "pass": passed,
        "pre_exec_cagr": pm["cagr"],
        "pre_cagr_retention": pg["retention"],
        "pre_exec_dd": pm["max_drawdown"],
        "pre_exec_turnover": pm["annual_turnover"],
        "pre_median_holdings": pm["median_holdings"],
        "pre_p95_exec_l1": pm["p95_execution_l1"],
        "pre_mean_inaccessible": pm["mean_inaccessible_target_weight"],
        "hold_exec_cagr": hm["cagr"],
        "hold_cagr_retention": hg["retention"],
        "hold_exec_dd": hm["max_drawdown"],
        "hold_exec_turnover": hm["annual_turnover"],
        "hold_median_holdings": hm["median_holdings"],
        "hold_p95_exec_l1": hm["p95_execution_l1"],
        "hold_mean_inaccessible": hm["mean_inaccessible_target_weight"],
        "current_fit_pass": cg["pass"],
        "current_holdings": cg["holdings"],
        "current_cash": cg["cash"],
        "current_l1": cg["l1"],
        "current_p95_abs_error": cg["p95_abs_error"],
        "current_max_overweight": cg["max_overweight"],
        "current_inaccessible_target_weight": cg["inaccessible_target_weight"],
        "pre_gate_cagr_retention": pg["gates"]["cagr_retention"],
        "pre_gate_cagr_shortfall": pg["gates"]["cagr_shortfall"],
        "pre_gate_dd": pg["gates"]["drawdown"],
        "pre_gate_turnover": pg["gates"]["turnover"],
        "pre_gate_tracking": pg["gates"]["tracking"],
        "hold_gate_cagr_retention": hg["gates"]["cagr_retention"],
        "hold_gate_cagr_shortfall": hg["gates"]["cagr_shortfall"],
        "hold_gate_dd": hg["gates"]["drawdown"],
        "hold_gate_turnover": hg["gates"]["turnover"],
        "hold_gate_tracking": hg["gates"]["tracking"],
    })
    sim_cache[(float(cap), "PRE")] = pre_sim
    sim_cache[(float(cap), "HOLD")] = hold_sim

capacity = pd.DataFrame(rows).sort_values("capital_usd").reset_index(drop=True)
current_idx = (capacity["capital_usd"] - CURRENT_NAV).abs().idxmin()
current_row = capacity.loc[current_idx]
passing = capacity[capacity["pass"]]
min_pass = float(passing["capital_usd"].min()) if len(passing) else None

if bool(current_row["pass"]):
    verdict = "PASS_CURRENT_NAV"
elif min_pass is not None:
    verdict = "FAIL_CURRENT_NAV_CAPITAL_INSUFFICIENT"
else:
    verdict = "FAIL_CURRENT_BYMA_GEOMETRY_CANNOT_REPLICATE_V13"

print()
print("[7/12] PRIMARY VERDICT")
print(f"  current NAV: USD {CURRENT_NAV:,.2f}")
print(f"  current PASS: {bool(current_row['pass'])}")
print("  minimum tested PASS: " + (f"USD {min_pass:,.2f}" if min_pass is not None else "NONE"))
print(f"  verdict: {verdict}")


# =============================================================================
# STRESS ONLY CURRENT + MIN PASS
# =============================================================================

print()
print("[8/12] 40 / 60 BPS STRESS")
stress_caps = [CURRENT_NAV] + ([] if min_pass is None or abs(min_pass - CURRENT_NAV) < 1e-9 else [min_pass])
stress_rows = []
for cap in stress_caps:
    for cost in STRESS_COSTS_BPS:
        pre_i = metrics(p3y.simulate_persistent(plans_pre, market_pre, terminals, start, hold, cost))
        hold_i = metrics(p3y.simulate_persistent(plans_hold, market_hold, terminals, hold, end_excl, cost))
        pre_e = metrics(simulate_executable(plans_pre, market_pre, terminals, start, hold, cap, cost))
        hold_e = metrics(simulate_executable(plans_hold, market_hold, terminals, hold, end_excl, cap, cost))
        stress_rows.append({
            "capital_usd": cap,
            "cost_bps": cost,
            "pre_ideal_cagr": pre_i["cagr"],
            "pre_exec_cagr": pre_e["cagr"],
            "pre_retention": pre_e["cagr"] / pre_i["cagr"] if pre_i["cagr"] > 0 else np.nan,
            "hold_ideal_cagr": hold_i["cagr"],
            "hold_exec_cagr": hold_e["cagr"],
            "hold_retention": hold_e["cagr"] / hold_i["cagr"] if hold_i["cagr"] > 0 else np.nan,
            "pre_exec_dd": pre_e["max_drawdown"],
            "hold_exec_dd": hold_e["max_drawdown"],
            "pre_exec_turnover": pre_e["annual_turnover"],
            "hold_exec_turnover": hold_e["annual_turnover"],
        })
stress = pd.DataFrame(stress_rows)


# =============================================================================
# REPORTS
# =============================================================================

print()
print("[9/12] CURRENT INACCESSIBLE V13 TARGETS")
inacc = dnow[dnow["reason"].eq("NO_CURRENT_BYMA_VEHICLE")][["ticker", "target_weight"]].copy()
if inacc.empty:
    print("  none")
else:
    print(inacc.to_string(index=False))
    print(f"  TOTAL INACCESSIBLE TARGET WEIGHT: {inacc['target_weight'].sum():.2%}")

print()
print("[10/12] CAPITAL CAPACITY TABLE")
show = capacity[[
    "capital_usd", "pass", "pre_exec_cagr", "pre_cagr_retention",
    "hold_exec_cagr", "hold_cagr_retention", "pre_exec_dd", "hold_exec_dd",
    "pre_exec_turnover", "hold_exec_turnover", "current_holdings", "current_cash",
    "current_l1", "current_inaccessible_target_weight",
]].copy()
print(show.to_string(index=False, formatters={
    "capital_usd": lambda x: f"{x:,.2f}",
    "pre_exec_cagr": lambda x: f"{x:.2%}",
    "pre_cagr_retention": lambda x: f"{x:.2%}",
    "hold_exec_cagr": lambda x: f"{x:.2%}",
    "hold_cagr_retention": lambda x: f"{x:.2%}",
    "pre_exec_dd": lambda x: f"{x:.2%}",
    "hold_exec_dd": lambda x: f"{x:.2%}",
    "current_cash": lambda x: f"{x:.2%}",
    "current_l1": lambda x: f"{x:.2%}",
    "current_inaccessible_target_weight": lambda x: f"{x:.2%}",
}))

print()
print("[11/12] SAVE")
paths = {
    "capacity": OUT / "v13_phase5h_v4_capital_capacity.csv",
    "current": OUT / "v13_phase5h_v4_current_integer_portfolio.csv",
    "programs": OUT / "v13_phase5h_v4_current_official_byma_master.csv",
    "stress": OUT / "v13_phase5h_v4_stress.csv",
    "pre_nav": OUT / "v13_phase5h_v4_current_nav_pre2025_20bps.csv",
    "hold_nav": OUT / "v13_phase5h_v4_current_nav_holdout_20bps.csv",
    "summary": OUT / "v13_phase5h_v4_summary.json",
}
capacity.to_csv(paths["capacity"], index=False)
dnow.to_csv(paths["current"], index=False)
programs.to_csv(paths["programs"], index=False)
stress.to_csv(paths["stress"], index=False)
sim_cache[(float(current_row["capital_usd"]), "PRE")].to_csv(paths["pre_nav"], index=False)
sim_cache[(float(current_row["capital_usd"]), "HOLD")].to_csv(paths["hold_nav"], index=False)

summary = {
    "status": "PASS_PHASE_EXECUTED",
    "phase": "V13-P5H-V4",
    "build": BUILD,
    "methodology": "COMPLETE_CURRENT_BYMA_DUAL_ISSUER_GEOMETRY_REPLAY_INTEGER_NEAREST_V4",
    "interpretation": (
        "Frozen V13 historical target path is replayed using the current 2026 BYMA vehicle set "
        "and current CEDEAR/local-share unit geometry. This is a prospective implementation-capacity "
        "test, not a claim that today's CEDEAR ratios/listings existed historically."
    ),
    "ideal_v13_frozen": True,
    "production_model_changed": False,
    "production_policy_changed": False,
    "top_n": False,
    "manual_stock_selection": False,
    "leftover_cash_redistributed": False,
    "integer_nominals_only": True,
    "universe": "Current official CEDEARs from Banco Comafi + Caja de Valores + current fungible local BYMA shares",
    "current_nav_usd": CURRENT_NAV,
    "current_nav_pass": bool(current_row["pass"]),
    "minimum_tested_pass_nav_usd": min_pass,
    "final_verdict": verdict,
    "current_inaccessible_target_weight": float(pnow["inaccessible_target_weight"]),
    "current_l1_error": float(pnow["l1_error"]),
    "gates": {
        "min_cagr_retention": MIN_CAGR_RETENTION,
        "max_cagr_shortfall_pp": MAX_CAGR_SHORTFALL_PP,
        "max_dd_deterioration_pp": MAX_DD_DETERIORATION_PP,
        "max_turnover_multiple": MAX_TURNOVER_MULTIPLE,
        "max_p95_execution_l1": MAX_P95_EXECUTION_L1,
        "max_current_l1": MAX_CURRENT_L1,
        "max_current_p95_abs_weight_error": MAX_CURRENT_P95_ABS_WEIGHT_ERROR,
        "max_current_overweight": MAX_CURRENT_OVERWEIGHT,
    },
    "ideal_reference": {
        "pre2025_cagr_20bps": IDEAL_PRE["cagr"],
        "pre2025_maxdd_20bps": IDEAL_PRE["max_drawdown"],
        "holdout_cagr_20bps": IDEAL_HOLD["cagr"],
        "holdout_maxdd_20bps": IDEAL_HOLD["max_drawdown"],
    },
    "current_result": current_row.to_dict(),
}
paths["summary"].write_text(json.dumps(summary, indent=2, sort_keys=True, default=str), encoding="utf-8")
for p in paths.values():
    print(f"  {p.relative_to(ROOT)}")

print()
print("[12/12] FINAL PHASE 5H V4 DECISION")
print("=" * 120)
print("IDEAL_V13: FROZEN")
print(f"IDEAL_PRE2025_CAGR_20BPS: {IDEAL_PRE['cagr']:.2%}")
print(f"IDEAL_HOLDOUT_CAGR_20BPS: {IDEAL_HOLD['cagr']:.2%}")
print(f"CURRENT_NAV_USD: {CURRENT_NAV:,.2f}")
print("EXECUTABLE_V13_CURRENT_NAV: " + ("PASS" if bool(current_row["pass"]) else "FAIL"))
print("MINIMUM_TESTED_NAV_FOR_NONINFERIORITY: " + (f"USD {min_pass:,.2f}" if min_pass is not None else "NONE IN TESTED GRID"))
print(f"CURRENT_EXECUTABLE_CAGR_PRE2025: {float(current_row['pre_exec_cagr']):.2%}")
print(f"CURRENT_EXECUTABLE_CAGR_HOLDOUT: {float(current_row['hold_exec_cagr']):.2%}")
print(f"CURRENT_PRE_CAGR_RETENTION: {float(current_row['pre_cagr_retention']):.2%}")
print(f"CURRENT_HOLDOUT_CAGR_RETENTION: {float(current_row['hold_cagr_retention']):.2%}")
print(f"CURRENT_INTEGER_HOLDINGS: {int(current_row['current_holdings'])}")
print(f"CURRENT_INTEGER_CASH: {float(current_row['current_cash']):.2%}")
print(f"CURRENT_L1_TRACKING_ERROR: {float(current_row['current_l1']):.2%}")
print(f"CURRENT_INACCESSIBLE_TARGET_WEIGHT: {float(current_row['current_inaccessible_target_weight']):.2%}")
print(f"FINAL_VERDICT: {verdict}")
print("PHASE 5G REMAINS PROPOSED / NOT CONFIRMED / NOT EXECUTABLE")
print("NO REAL ORDERS / NO SHEETS MUTATION / NO IDEAL V13 MUTATION")
print("=" * 120)
