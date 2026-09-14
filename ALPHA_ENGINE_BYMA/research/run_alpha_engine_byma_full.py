from __future__ import annotations

from pathlib import Path
from urllib.request import Request, urlopen
import io
import json
import math
import re
import sys
import warnings

import numpy as np
import pandas as pd

# =============================================================================
# IDENTITY / CONTRACT
# =============================================================================

BUILD = "ALPHA_ENGINE_BYMA_1_0_1_2026-09-13"
NAME = "ALPHA_ENGINE_BYMA"
VERSION = "1.0.1"

PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "outputs"
CACHE = PROJECT / "cache"
OUT.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)

V13_ROOT = Path(
    r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_V12_RETURN_FIRST"
    r"\ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
)
V13_SRC = V13_ROOT / "src"

if not V13_ROOT.exists():
    raise FileNotFoundError(f"Frozen V13 root not found: {V13_ROOT}")

if str(V13_SRC) not in sys.path:
    sys.path.insert(0, str(V13_SRC))

warnings.filterwarnings("ignore", message="Downcasting object dtype arrays")

from alpha_engine_v13 import active_alpha_persistent_portfolio as p3y
from alpha_engine_v13 import roundtrip_resize_hysteresis as p3z
from alpha_engine_v13 import economic_portfolio_closure as p3v
from alpha_engine_v13 import final_holdout as p4

# =============================================================================
# FROZEN ACCEPTANCE GATES
# =============================================================================

BASE_COST_BPS = 20.0
STRESS_COSTS = [40.0, 60.0]

MIN_CAGR_RETENTION = 0.95
MAX_CAGR_SHORTFALL = 0.02
MAX_DD_DETERIORATION = 0.02
MAX_TURNOVER_MULTIPLE = 1.25

CAPITAL_GRID = [
    320.42, 500, 750, 1000, 1500, 2000, 3000, 5000, 7500, 10000,
    15000, 20000, 30000, 50000, 75000, 100000, 150000, 250000,
    500000
]

COMAFI_URL = "https://www.comafi.com.ar/Programas-CEDEARs-2483.note.aspx"
CAJA_URL = "https://cajadevalores.com.ar/Servicios/Cedears"

# Local share alternatives for same economic exposure.
# Only relationships we want to certify explicitly here.
LOCAL = {
    "CEPU": {"byma_ticker": "CEPU", "local_per_adr": 10.0},
    "YPF":  {"byma_ticker": "YPFD", "local_per_adr": 10.0},
}

# =============================================================================
# HELPERS
# =============================================================================

def tk(x):
    return str(x).strip().upper().replace("*", "")

def dt(x):
    return pd.to_datetime(x, errors="coerce").dt.normalize()

def flat_col(c):
    if isinstance(c, tuple):
        c = " ".join(str(x) for x in c if str(x) != "nan")
    s = str(c).strip().lower()
    s = (
        s.replace("í","i").replace("ó","o").replace("á","a")
         .replace("é","e").replace("ú","u").replace("\n"," ")
    )
    return re.sub(r"\s+", " ", s)

def ratio_tuple(x):
    m = re.search(r"(\d+)\s*:\s*(\d+)", str(x))
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a,b) if a > 0 and b > 0 else None

def request_bytes(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 AlphaEngineBYMA/1.0"})
    with urlopen(req, timeout=45) as r:
        return r.read()

def read_html_official(url):
    raw = request_bytes(url)
    return pd.read_html(io.BytesIO(raw))

def find_col(cols, needles):
    for c in cols:
        lc = flat_col(c)
        if all(n in lc for n in needles):
            return c
    return None

def normalize_alias(x):
    s = tk(x)
    if s in {"", "NAN", "NONE"}:
        return ""
    # Origin tickers may appear as "VIST US". The market id remains VIST.
    return s.split()[0]

def parse_issuer(url, issuer):
    rows = []
    tables = read_html_official(url)

    for tab in tables:
        if tab.empty:
            continue

        # Flatten potentially multi-level headers.
        tab = tab.copy()
        tab.columns = [flat_col(c) for c in tab.columns]
        cols = list(tab.columns)

        # Current Comafi master:
        # "ratio cedear / valor sub-yacente"
        # "id de mercado"
        # "ticker en mercado de origen"
        ratio_col = None
        byma_col = None
        origin_col = None

        for c in cols:
            lc = flat_col(c)
            if ratio_col is None and "ratio" in lc and ("cedear" in lc or "subyacente" in lc):
                ratio_col = c
            if byma_col is None and (
                ("id" in lc and "mercado" in lc)
                or ("identificacion" in lc and "mercado" in lc)
                or ("simbolo" in lc and "byma" in lc)
            ):
                byma_col = c
            if origin_col is None and "ticker" in lc and ("origen" in lc or "mercado" in lc):
                origin_col = c

        if ratio_col is None or origin_col is None:
            continue
        if byma_col is None:
            byma_col = origin_col

        for _, r in tab.iterrows():
            rr = ratio_tuple(r.get(ratio_col))
            origin_raw = r.get(origin_col, "")
            byma_raw = r.get(byma_col, "")

            origin = normalize_alias(origin_raw)
            byma = normalize_alias(byma_raw)

            if not origin or rr is None:
                continue
            if not byma:
                byma = origin

            rows.append({
                "issuer": issuer,
                "origin_ticker": origin,
                "byma_ticker": byma,
                "ratio_a": rr[0],
                "ratio_b": rr[1],
                "ratio": f"{rr[0]}:{rr[1]}",
                "source_url": url,
            })

    return pd.DataFrame(rows)

def load_master():
    cache = CACHE / "byma_master_current_v101.csv"
    frames = []
    errors = []

    for url, issuer in [
        (COMAFI_URL, "BANCO_COMAFI"),
        (CAJA_URL, "CAJA_DE_VALORES"),
    ]:
        try:
            q = parse_issuer(url, issuer)
            if q.empty:
                raise RuntimeError("parsed zero programs")
            frames.append(q)
            print(f"  {issuer}: {len(q):,} rows LIVE")
        except Exception as e:
            errors.append(f"{issuer}: {e}")

    # For this release we fail closed rather than use the old 1.0.0 cache,
    # because that cache came from the obsolete Comafi page.
    if len(frames) < 2:
        raise RuntimeError(
            "OFFICIAL MASTER LOAD FAILED CLOSED: "
            + " | ".join(errors)
        )

    m = pd.concat(frames, ignore_index=True)
    m["origin_ticker"] = m["origin_ticker"].map(normalize_alias)
    m["byma_ticker"] = m["byma_ticker"].map(normalize_alias)
    m = (
        m.drop_duplicates(["issuer","origin_ticker","byma_ticker","ratio"])
         .sort_values(["origin_ticker","issuer","byma_ticker"])
         .reset_index(drop=True)
    )

    if len(m) < 300:
        raise RuntimeError(
            f"OFFICIAL MASTER LOOKS INCOMPLETE: only {len(m)} combined rows"
        )

    m.to_csv(cache, index=False)
    return m, errors

def certified_ratio(master, ticker, issuer="BANCO_COMAFI"):
    t = tk(ticker)
    q = master[
        master["issuer"].eq(issuer)
        & (
            master["origin_ticker"].eq(t)
            | master["byma_ticker"].eq(t)
        )
    ]
    if q.empty:
        return None
    # If aliases duplicate the same current program, use the modal ratio.
    vc = q["ratio"].astype(str).value_counts()
    return str(vc.index[0]) if len(vc) else None

def assert_current_master_ratios(master):
    # Hard checks against the official current Comafi program master
    # as of 2026-09-13. This prevents silently replaying legacy ratios.
    expected = {
        "AMD": "10:1",
        "NKE": "12:1",
        "NUE": "16:1",
        "CAT": "20:1",
        "VIST": "3:1",
        "AMAT": "5:1",
        "GOOGL": "58:1",
        "FDX": "10:1",
    }

    bad = []
    for t, exp in expected.items():
        got = certified_ratio(master, t)
        if got != exp:
            bad.append((t, exp, got))

    if bad:
        msg = "; ".join(
            f"{t} expected {exp}, got {got}"
            for t, exp, got in bad
        )
        raise RuntimeError(
            "CURRENT COMAFI RATIO CERTIFICATION FAILED: " + msg
        )

    print("  current Comafi ratio certification: PASS")
    for t, exp in expected.items():
        print(f"    {t}: {exp}")

def maxdd(nav):
    x = pd.to_numeric(nav, errors="coerce").dropna()
    return float((x / x.cummax() - 1).min())

def metrics(sim):
    n = len(sim)
    yrs = n / 252.0
    nav = pd.to_numeric(sim["nav"], errors="coerce")
    final = float(nav.iloc[-1])
    return {
        "final_nav": final,
        "cagr": float(final ** (1 / yrs) - 1) if final > 0 and yrs > 0 else np.nan,
        "max_drawdown": maxdd(nav),
        "annual_turnover": float(pd.to_numeric(sim["turnover"], errors="coerce").fillna(0).sum() / yrs),
        "median_holdings": float(pd.to_numeric(sim["holdings"], errors="coerce").median()),
        "mean_cash": float(pd.to_numeric(sim["cash_weight"], errors="coerce").mean()),
        "p95_max_name": float(pd.to_numeric(sim["max_name_weight"], errors="coerce").quantile(.95)),
    }

def gate(candidate, ideal):
    retention = candidate["cagr"] / ideal["cagr"] if ideal["cagr"] > 0 else np.nan
    shortfall = ideal["cagr"] - candidate["cagr"]
    dd_det = max(0.0, ideal["max_drawdown"] - candidate["max_drawdown"])
    turn_mult = candidate["annual_turnover"] / ideal["annual_turnover"]
    tests = {
        "cagr_retention": bool(np.isfinite(retention) and retention >= MIN_CAGR_RETENTION),
        "cagr_shortfall": bool(shortfall <= MAX_CAGR_SHORTFALL),
        "drawdown": bool(dd_det <= MAX_DD_DETERIORATION),
        "turnover": bool(turn_mult <= MAX_TURNOVER_MULTIPLE),
    }
    return {
        "pass": all(tests.values()),
        "retention": float(retention),
        "shortfall": float(shortfall),
        "dd_deterioration": float(dd_det),
        "turnover_multiple": float(turn_mult),
        "tests": tests,
    }

def parity(rebuilt, official_path, label):
    b = pd.read_csv(official_path)
    a = rebuilt.copy()
    a["date"] = dt(a["date"])
    b["date"] = dt(b["date"])
    z = a.merge(b, on="date", how="outer", suffixes=("_new","_official"), indicator=True)
    if not z["_merge"].eq("both").all():
        raise RuntimeError(f"{label}: date parity failed")
    worst = 0.0
    for c in ["nav","net_return","turnover","holdings","cash_weight","max_name_weight"]:
        g = (
            pd.to_numeric(z[f"{c}_new"], errors="coerce")
            - pd.to_numeric(z[f"{c}_official"], errors="coerce")
        ).abs()
        worst = max(worst, float(g.max()))
    print(f"  {label}: parity max gap {worst:.3e}")
    if worst > 1e-9:
        raise RuntimeError(f"{label}: V13 parity failed")

# =============================================================================
# BYMA UNIVERSE
# =============================================================================

print("=" * 118)
print("ALPHA ENGINE BYMA 1.0.1")
print("BYMA-NATIVE PORTFOLIO BUILD FROM FROZEN V13 FORECAST SURFACE")
print("UNIVERSE FILTER OCCURS BEFORE PORTFOLIO ALLOCATION")
print("NO TOP-N / NO MANUAL REPLACEMENTS / NO POST-HOC DELETION OF TARGETS")
print("=" * 118)

print("\n[1/10] OFFICIAL CURRENT BYMA UNIVERSE")
master, master_errors = load_master()
assert_current_master_ratios(master)
master.to_csv(OUT / "byma_master.csv", index=False)

origin_set = set(master["origin_ticker"].map(tk))
byma_set = set(master["byma_ticker"].map(tk))
accessible = origin_set | byma_set | set(LOCAL)

print(f"  combined CEDEAR rows: {len(master):,}")
print(f"  accessible ticker aliases: {len(accessible):,}")
if master_errors:
    print("  source warnings:", " | ".join(master_errors))

# =============================================================================
# FROZEN V13 RECONSTRUCTION
# =============================================================================

print("\n[2/10] LOAD FROZEN V13")
cfg = p3z.load_cfg(V13_ROOT)
_, _, source, scores, targets = p3y.load_inputs(V13_ROOT, cfg)
advisor_pre, _, _ = p3y.build_active_advisor(scores, targets, cfg)

hold = pd.Timestamp(cfg.p["holdout_start"])
start = pd.Timestamp(cfg.p["portfolio_start"])
pcfg = p3v.load_cfg(V13_ROOT)
terminals = p3v.load_terminals(source, pcfg)

# Official pre market, exact.
needed_all = set(advisor_pre.ticker.map(tk).unique())
surface = p3v.load_market(V13_ROOT, source, pcfg, needed_all)
spy = p3v._load_benchmark(source, pcfg.p["source_spy_benchmark"], "SPY", hold)
qqq = p3v._load_benchmark(source, pcfg.p["source_qqq_benchmark"], "QQQ", hold)
market_pre = p3v.prepare_market(surface, spy, start, hold, int(cfg.p["risk_lookback_sessions"]))
benches_pre = p3v.benchmark_returns(source, pcfg, market_pre, spy, qqq)

# Attach raw execution close only for integer unit geometry.
if "execution_close" not in market_pre:
    market_pre["execution_close"] = (
        surface.pivot_table(index="date", columns="ticker", values="execution_close", aggfunc="last")
               .reindex(market_pre["calendar"])
    )

plans_ideal_pre = p3z.build_plans(advisor_pre, market_pre, cfg)
ideal_pre_20 = p3y.simulate_persistent(plans_ideal_pre, market_pre, terminals, start, hold, BASE_COST_BPS)
parity(ideal_pre_20, V13_ROOT / "outputs" / "v13_phase3z_nav_20bps.csv", "PRE2025")
ideal_pre_m = metrics(ideal_pre_20)

# Exact holdout environment.
advisor_hold = pd.read_parquet(V13_ROOT / "outputs" / "v13_phase4_holdout_advisor.parquet")
advisor_hold["signal_date"] = dt(advisor_hold["signal_date"])
advisor_hold["ticker"] = advisor_hold["ticker"].map(tk)

cfg1 = p4.p1.load_cfg(V13_ROOT)
cfg1full = p4.p1.Cfg({**cfg1.p, "holdout_start": "2100-01-01"})
market_full, _ = p4._load_full_market(source, cfg1full)
end = pd.Timestamp(market_full.date.max())
bench_full = p4._load_full_bench(source, cfg1full, market_full)

c = pd.read_parquet(
    source / "outputs" / "phase2_canonical_pit_panel.parquet",
    columns=["date","ticker","close","research_eligible"]
)
r = pd.read_parquet(
    source / "outputs" / "phase2c_return_price_layer.parquet",
    columns=["date","ticker","target_total_return_price"]
)
c["date"] = dt(c["date"]); c["ticker"] = c["ticker"].map(tk)
r["date"] = dt(r["date"]); r["ticker"] = r["ticker"].map(tk)
surf_hold = c.merge(r, on=["date","ticker"], how="left")
surf_hold["execution_close"] = pd.to_numeric(surf_hold["close"], errors="coerce")
surf_hold["mark_price"] = pd.to_numeric(surf_hold["target_total_return_price"], errors="coerce")
surf_hold["research_eligible"] = surf_hold["research_eligible"].fillna(False).astype(bool)
surf_hold = surf_hold[["date","ticker","execution_close","mark_price","research_eligible"]]

spy_h = bench_full.dropna(subset=["SPY"]).drop_duplicates("date").set_index("date")["SPY"]
qqq_h = bench_full.dropna(subset=["QQQ"]).drop_duplicates("date").set_index("date")["QQQ"]
end_excl = end + pd.Timedelta(days=1)
market_hold = p3v.prepare_market(surf_hold, spy_h, hold, end_excl, int(cfg.p["risk_lookback_sessions"]))
benches_hold = p3v.benchmark_returns(source, pcfg, market_hold, spy_h, qqq_h)

if "execution_close" not in market_hold:
    market_hold["execution_close"] = (
        surf_hold.pivot_table(index="date", columns="ticker", values="execution_close", aggfunc="last")
                 .reindex(market_hold["calendar"])
    )

plans_ideal_hold = p3z.build_plans(advisor_hold, market_hold, cfg)
ideal_hold_20 = p3y.simulate_persistent(plans_ideal_hold, market_hold, terminals, hold, end_excl, BASE_COST_BPS)
parity(ideal_hold_20, V13_ROOT / "outputs" / "v13_phase4_holdout_nav_20bps.csv", "HOLDOUT")
ideal_hold_m = metrics(ideal_hold_20)

print(f"  V13 IDEAL PRE CAGR: {ideal_pre_m['cagr']:.2%}")
print(f"  V13 IDEAL HOLD CAGR: {ideal_hold_m['cagr']:.2%}")

# =============================================================================
# FILTER BEFORE ALLOCATION
# =============================================================================

print("\n[3/10] BYMA-NATIVE ADVISOR SURFACE")
advisor_pre["ticker"] = advisor_pre["ticker"].map(tk)
pre_byma = advisor_pre[advisor_pre["ticker"].isin(accessible)].copy()
hold_byma = advisor_hold[advisor_hold["ticker"].isin(accessible)].copy()

pre_cov = pre_byma["ticker"].nunique() / max(1, advisor_pre["ticker"].nunique())
hold_cov = hold_byma["ticker"].nunique() / max(1, advisor_hold["ticker"].nunique())

print(f"  PRE unique tickers: {advisor_pre.ticker.nunique()} -> {pre_byma.ticker.nunique()} ({pre_cov:.1%})")
print(f"  HOLD unique tickers: {advisor_hold.ticker.nunique()} -> {hold_byma.ticker.nunique()} ({hold_cov:.1%})")

if pre_byma.empty or hold_byma.empty:
    raise RuntimeError("BYMA filtered advisor is empty")

# IMPORTANT: rebuild p3z AFTER filtering. This reallocates risk/capital using the
# same V13 economics among names that are actually executable.
plans_pre = p3z.build_plans(pre_byma, market_pre, cfg)
plans_hold = p3z.build_plans(hold_byma, market_hold, cfg)

continuous_rows = []
continuous_sims = {}

print("\n[4/10] CONTINUOUS BYMA-NATIVE ECONOMICS")
for cost in [20.0, 40.0, 60.0]:
    sp = p3y.simulate_persistent(plans_pre, market_pre, terminals, start, hold, cost)
    sh = p3y.simulate_persistent(plans_hold, market_hold, terminals, hold, end_excl, cost)
    continuous_sims[("PRE",cost)] = sp
    continuous_sims[("HOLD",cost)] = sh

    ip = ideal_pre_20 if cost == 20 else p3y.simulate_persistent(plans_ideal_pre, market_pre, terminals, start, hold, cost)
    ih = ideal_hold_20 if cost == 20 else p3y.simulate_persistent(plans_ideal_hold, market_hold, terminals, hold, end_excl, cost)

    mp, mh = metrics(sp), metrics(sh)
    mip, mih = metrics(ip), metrics(ih)

    continuous_rows.append({
        "cost_bps": cost,
        "pre_ideal_cagr": mip["cagr"],
        "pre_byma_cagr": mp["cagr"],
        "pre_retention": mp["cagr"]/mip["cagr"] if mip["cagr"]>0 else np.nan,
        "pre_ideal_dd": mip["max_drawdown"],
        "pre_byma_dd": mp["max_drawdown"],
        "pre_ideal_turnover": mip["annual_turnover"],
        "pre_byma_turnover": mp["annual_turnover"],
        "hold_ideal_cagr": mih["cagr"],
        "hold_byma_cagr": mh["cagr"],
        "hold_retention": mh["cagr"]/mih["cagr"] if mih["cagr"]>0 else np.nan,
        "hold_ideal_dd": mih["max_drawdown"],
        "hold_byma_dd": mh["max_drawdown"],
        "hold_ideal_turnover": mih["annual_turnover"],
        "hold_byma_turnover": mh["annual_turnover"],
    })
    print(
        f"  {int(cost):>2}bps | PRE {mip['cagr']:.2%} -> {mp['cagr']:.2%} "
        f"| HOLD {mih['cagr']:.2%} -> {mh['cagr']:.2%}"
    )

continuous = pd.DataFrame(continuous_rows)
continuous.to_csv(OUT / "byma_continuous_comparison.csv", index=False)

pre20 = metrics(continuous_sims[("PRE",20.0)])
hold20 = metrics(continuous_sims[("HOLD",20.0)])
g_pre = gate(pre20, ideal_pre_m)
g_hold = gate(hold20, ideal_hold_m)

print(f"  PRE strict non-inferiority: {g_pre['pass']} ({g_pre['retention']:.1%} CAGR retention)")
print(f"  HOLD strict non-inferiority: {g_hold['pass']} ({g_hold['retention']:.1%} CAGR retention)")

# =============================================================================
# EXECUTION GEOMETRY
# =============================================================================

# Prefer the smallest valid unit for a model ticker.
by_origin = {}
for rr in master.itertuples():
    by_origin.setdefault(tk(rr.origin_ticker), []).append(rr)
    by_origin.setdefault(tk(rr.byma_ticker), []).append(rr)

def unit_info(ticker, underlying_price):
    t = tk(ticker)
    px = float(underlying_price) if np.isfinite(underlying_price) else np.nan
    if not np.isfinite(px) or px <= 0:
        return None

    candidates = []

    for rr in by_origin.get(t, []):
        a, b = int(rr.ratio_a), int(rr.ratio_b)
        u = px * (b / a)
        if np.isfinite(u) and u > 0:
            candidates.append({
                "vehicle": f"CEDEAR_{rr.issuer}",
                "byma_ticker": tk(rr.byma_ticker),
                "ratio": f"{a}:{b}",
                "unit_usd": float(u),
            })

    if t in LOCAL:
        n = float(LOCAL[t]["local_per_adr"])
        u = px / n
        candidates.append({
            "vehicle": "LOCAL_BYMA_SHARE",
            "byma_ticker": LOCAL[t]["byma_ticker"],
            "ratio": f"1 ADR:{n:g} LOCAL",
            "unit_usd": float(u),
        })

    if not candidates:
        return None

    return min(candidates, key=lambda z: z["unit_usd"])

DETAIL_COLUMNS = [
    "ticker","target_weight","vehicle","byma_ticker","ratio","unit_usd",
    "q_star","quantity","actual_weight","weight_error"
]

def integer_projection(target, nav_usd, date, prices, presence=None, current=None):
    current = {} if current is None else {tk(k):float(v) for k,v in current.items()}
    rows = []
    actual = {}

    for t, tw0 in target.items():
        t = tk(t)
        tw = max(0.0, float(tw0))
        if tw <= 1e-14:
            continue

        if presence is not None and not bool(presence.get(t, False)):
            cw = max(0.0, current.get(t,0.0))
            if cw > 0:
                actual[t] = cw
            rows.append({
                "ticker":t,"target_weight":tw,"vehicle":"BLOCKED","byma_ticker":"",
                "ratio":"","unit_usd":np.nan,"q_star":np.nan,"quantity":np.nan,
                "actual_weight":cw,"weight_error":cw-tw
            })
            continue

        info = unit_info(t, prices.get(t, np.nan))
        if info is None:
            # This should be rare after filtering. Fail closed rather than silently delete.
            raise RuntimeError(f"Accessible BYMA ticker has no execution unit on {date.date()}: {t}")

        unit = info["unit_usd"]
        qstar = tw * nav_usd / unit
        qfloor = math.floor(qstar)
        frac = qstar - qfloor
        q = int(qfloor + 1 if frac > 0.5 else qfloor)
        aw = q * unit / nav_usd

        rows.append({
            "ticker":t,"target_weight":tw,**info,"q_star":qstar,
            "quantity":q,"actual_weight":aw,"weight_error":aw-tw
        })

    detail = pd.DataFrame(rows, columns=DETAIL_COLUMNS)

    # Budget repair: nearest integer independently, then undo the least costly
    # round-ups until invested weight <= 1. No redistribution of leftover cash.
    if not detail.empty:
        for r in detail.itertuples():
            if np.isfinite(r.actual_weight) and r.actual_weight > 1e-14:
                actual[tk(r.ticker)] = float(r.actual_weight)

    invested = sum(actual.values())

    if invested > 1.0 + 1e-10:
        # Rebuild candidate list from rounded-up rows.
        candidates = []
        for i, r in detail.iterrows():
            if not np.isfinite(r["q_star"]) or not np.isfinite(r["unit_usd"]):
                continue
            floorq = int(math.floor(float(r["q_star"])))
            q = int(r["quantity"])
            if q > floorq:
                f = float(r["q_star"]) - floorq
                candidates.append((2*f-1, -float(r["unit_usd"]), i, floorq))
        candidates.sort()

        for _, _, i, floorq in candidates:
            if invested <= 1.0 + 1e-10:
                break
            t = tk(detail.loc[i,"ticker"])
            unit = float(detail.loc[i,"unit_usd"])
            oldw = float(detail.loc[i,"actual_weight"])
            neww = floorq * unit / nav_usd
            detail.loc[i,"quantity"] = floorq
            detail.loc[i,"actual_weight"] = neww
            detail.loc[i,"weight_error"] = neww - float(detail.loc[i,"target_weight"])
            if neww > 1e-14:
                actual[t] = neww
            else:
                actual.pop(t, None)
            invested += neww - oldw

    if invested > 1.000001:
        raise RuntimeError("Integer projection exceeds NAV after budget repair")

    cash = max(0.0, 1.0-invested)
    ideal_cash = max(0.0, 1.0-sum(float(x) for x in target.values()))
    names = set(actual) | set(target)
    l1 = sum(abs(actual.get(t,0)-float(target.get(t,0))) for t in names) + abs(cash-ideal_cash)
    return actual, cash, detail, float(l1)

def simulate_integer(plans, market, start_date, end_date, initial_capital, cost_bps):
    cal = market["calendar"][(market["calendar"]>=start_date)&(market["calendar"]<end_date)]
    ret = market["returns"]
    pres = market["execution_presence"]
    raw = market["execution_close"]

    w = {}
    cash = 1.0
    nav = 1.0
    pending = None
    one = float(cost_bps)/2/10000
    rows = []

    for d in cal:
        d = pd.Timestamp(d)
        prev = nav

        if w:
            rr = ret.loc[d] if d in ret.index else pd.Series(dtype=float)
            vals = {}
            for t,v in w.items():
                rv = rr.get(t,np.nan)
                rv = float(rv) if np.isfinite(rv) else 0.0
                vals[t] = v*(1+rv)
            total = cash + sum(vals.values())
            if total > 0:
                w = {t:v/total for t,v in vals.items() if v>1e-14}
                cash /= total
                nav *= total

        turnover = cost = l1 = 0.0

        if pending is not None:
            old = dict(w)
            econ = p3y._economic_target(old, pending)
            rp = raw.loc[d] if d in raw.index else pd.Series(dtype=float)
            pr = pres.loc[d] if d in pres.index else pd.Series(dtype=bool)
            actual, newcash, _, l1 = integer_projection(
                econ, initial_capital*nav, d, rp, pr, old
            )
            executed = sum(abs(actual.get(t,0)-old.get(t,0)) for t in set(actual)|set(old))
            turnover = .5*(executed + abs(newcash-cash))
            cost = one*executed
            nav *= max(0.0, 1.0-cost)
            w, cash = actual, newcash
            pending = None

        for t in [t for t in list(w) if terminals.get(t)==d]:
            cash += w.pop(t)

        if d in plans:
            pending = plans[d]

        rows.append({
            "date":d,"nav":nav,"net_return":nav/prev-1 if prev>0 else -1,
            "turnover":turnover,"cost_fraction":cost,"holdings":len(w),
            "cash_weight":cash,"max_name_weight":max(w.values()) if w else 0.0,
            "execution_l1_error":l1,
        })

    return pd.DataFrame(rows)

# =============================================================================
# INTEGER CAPACITY
# =============================================================================

print("\n[5/10] INTEGER BYMA CAPITAL CAPACITY")
capacity_rows = []
integer_sims = {}

for cap in CAPITAL_GRID:
    sp = simulate_integer(plans_pre, market_pre, start, hold, cap, 20.0)
    sh = simulate_integer(plans_hold, market_hold, hold, end_excl, cap, 20.0)
    integer_sims[(cap,"PRE")] = sp
    integer_sims[(cap,"HOLD")] = sh
    mp, mh = metrics(sp), metrics(sh)
    gp, gh = gate(mp, ideal_pre_m), gate(mh, ideal_hold_m)
    passed = bool(gp["pass"] and gh["pass"])
    capacity_rows.append({
        "capital_usd":cap,"pass":passed,
        "pre_cagr":mp["cagr"],"pre_retention":gp["retention"],
        "pre_dd":mp["max_drawdown"],"pre_turnover":mp["annual_turnover"],
        "hold_cagr":mh["cagr"],"hold_retention":gh["retention"],
        "hold_dd":mh["max_drawdown"],"hold_turnover":mh["annual_turnover"],
        "pre_median_holdings":mp["median_holdings"],
        "hold_median_holdings":mh["median_holdings"],
        "pre_mean_cash":mp["mean_cash"],"hold_mean_cash":mh["mean_cash"],
    })
    print(
        f"  USD {cap:>10,.2f} | PRE {mp['cagr']:.2%} ({gp['retention']:.1%}) "
        f"| HOLD {mh['cagr']:.2%} ({gh['retention']:.1%}) | PASS={passed}"
    )

capacity = pd.DataFrame(capacity_rows)
capacity.to_csv(OUT / "byma_integer_capacity.csv", index=False)

# =============================================================================
# CURRENT TARGET
# =============================================================================

print("\n[6/10] CURRENT BYMA TARGET")
last_plan_date = max(plans_hold)
last_plan = plans_hold[last_plan_date]

# For a clean "from cash" current target, use all desired weights whose entry is valid.
target_now = {
    t: float(p["desired"])
    for t,p in last_plan.items()
    if float(p.get("desired",0.0)) > 0 and bool(p.get("entry_ok",False))
}

price_dates = market_hold["execution_close"].index[
    market_hold["execution_close"].index <= last_plan_date
]
if len(price_dates)==0:
    raise RuntimeError("No current execution prices")
price_date = pd.Timestamp(price_dates.max())
prices_now = market_hold["execution_close"].loc[price_date]
pres_now = market_hold["execution_presence"].loc[price_date]

CURRENT_NAV = 320.42
actual_now, cash_now, detail_now, l1_now = integer_projection(
    target_now, CURRENT_NAV, price_date, prices_now, pres_now, {}
)
detail_now["signal_date"] = last_plan_date
detail_now["price_date"] = price_date
detail_now.to_csv(OUT / "byma_current_target.csv", index=False)

print(f"  signal date: {last_plan_date.date()}")
print(f"  price date:  {price_date.date()}")
print(f"  continuous target names: {len(target_now)}")
print(f"  integer holdings @ USD {CURRENT_NAV:.2f}: {len(actual_now)}")
print(f"  cash: {cash_now:.2%}")
print(f"  L1 tracking error: {l1_now:.2%}")

if not detail_now.empty:
    print(detail_now.sort_values("target_weight",ascending=False).to_string(index=False))

# =============================================================================
# FINAL VERDICT
# =============================================================================

print("\n[7/10] FINAL VERDICT")

continuous_pass = bool(g_pre["pass"] and g_hold["pass"])
cap_current = min(CAPITAL_GRID, key=lambda x: abs(x-CURRENT_NAV))
row_current = capacity.loc[capacity.capital_usd.eq(cap_current)].iloc[0]
current_pass = bool(row_current["pass"])

passing = capacity[capacity["pass"]]
min_pass = float(passing.capital_usd.min()) if len(passing) else None

if not continuous_pass:
    verdict = "REJECT_ALPHA_PORTABILITY"
elif current_pass:
    verdict = "PRODUCTION_CANDIDATE"
elif min_pass is not None:
    verdict = "CAPITAL_INSUFFICIENT"
else:
    verdict = "REJECT_INTEGER_IMPLEMENTATION"

print(f"  continuous BYMA PRE pass:  {g_pre['pass']}")
print(f"  continuous BYMA HOLD pass: {g_hold['pass']}")
print(f"  current NAV integer pass:  {current_pass}")
print(f"  minimum tested pass NAV:    {min_pass}")
print(f"  VERDICT: {verdict}")

# =============================================================================
# SAVE NAVS / ALPHA ATTRIBUTION
# =============================================================================

print("\n[8/10] SAVE RESEARCH ARTIFACTS")
continuous_sims[("PRE",20.0)].to_csv(OUT / "byma_pre2025_nav_20bps.csv", index=False)
continuous_sims[("HOLD",20.0)].to_csv(OUT / "byma_holdout_nav_20bps.csv", index=False)

alpha_rows = []
for sample,sim,benches in [
    ("PRE2025",continuous_sims[("PRE",20.0)],benches_pre),
    ("HOLDOUT_POSTHOC",continuous_sims[("HOLD",20.0)],benches_hold),
]:
    sr = sim.set_index("date").net_return
    for k,b in benches.items():
        alpha_rows.append({"sample":sample,"benchmark":k,**p3y._ols(sr,b.reindex(sr.index))})
pd.DataFrame(alpha_rows).to_csv(OUT / "byma_active_alpha.csv", index=False)

summary = {
    "status":"COMPLETE",
    "name":NAME,
    "version":VERSION,
    "build":BUILD,
    "v13_ideal_preserved":True,
    "v13_root":str(V13_ROOT),
    "design":{
        "forecast_surface":"frozen V13",
        "universe":"current official BYMA CEDEAR union + certified local alternatives",
        "filter_timing":"BEFORE portfolio allocation",
        "allocator":"frozen V13 Phase3Z economics rebuilt on accessible universe",
        "top_n":False,
        "manual_replacements":False,
        "integer_execution":True,
        "cash_allowed":True,
    },
    "gates":{
        "minimum_cagr_retention":MIN_CAGR_RETENTION,
        "maximum_cagr_shortfall":MAX_CAGR_SHORTFALL,
        "maximum_dd_deterioration":MAX_DD_DETERIORATION,
        "maximum_turnover_multiple":MAX_TURNOVER_MULTIPLE,
    },
    "ideal":{
        "pre2025":ideal_pre_m,
        "holdout":ideal_hold_m,
    },
    "continuous_byma":{
        "pre2025":pre20,
        "holdout":hold20,
        "pre_gate":g_pre,
        "hold_gate":g_hold,
    },
    "current":{
        "nav_usd":CURRENT_NAV,
        "signal_date":str(last_plan_date.date()),
        "price_date":str(price_date.date()),
        "target_names":len(target_now),
        "integer_holdings":len(actual_now),
        "cash":cash_now,
        "l1_tracking_error":l1_now,
    },
    "minimum_tested_pass_nav_usd":min_pass,
    "verdict":verdict,
    "holdout_interpretation":"2025+ is secondary/post-hoc because V13 holdout has already been inspected.",
}
(OUT / "byma_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")

print("\n[9/10] WEBSITE TRACK CONTRACT")
website = {
    "ideal_track":{
        "name":"V13 IDEAL",
        "description":"Frictionless/reference model; no BYMA accessibility or integer-lot constraint.",
        "nav_source":str(V13_ROOT / "outputs" / "v13_phase4_holdout_nav_20bps.csv"),
    },
    "executable_track":{
        "name":"ALPHA ENGINE BYMA",
        "description":"Current-BYMA accessible portfolio built before allocation; integer execution.",
        "nav_source":str(OUT / "byma_holdout_nav_20bps.csv"),
        "current_target":str(OUT / "byma_current_target.csv"),
    }
}
(OUT / "website_track_contract.json").write_text(json.dumps(website,indent=2),encoding="utf-8")
print("  V13 IDEAL and ALPHA ENGINE BYMA are preserved as separate tracks.")

print("\n[10/10] FINAL CARD")
print("="*118)
print("V13_IDEAL: FROZEN_AND_PRESERVED")
print(f"V13_IDEAL_PRE_CAGR: {ideal_pre_m['cagr']:.2%}")
print(f"V13_IDEAL_HOLD_CAGR: {ideal_hold_m['cagr']:.2%}")
print(f"BYMA_CONTINUOUS_PRE_CAGR: {pre20['cagr']:.2%}")
print(f"BYMA_CONTINUOUS_HOLD_CAGR: {hold20['cagr']:.2%}")
print(f"BYMA_CONTINUOUS_PRE_RETENTION: {g_pre['retention']:.2%}")
print(f"BYMA_CONTINUOUS_HOLD_RETENTION: {g_hold['retention']:.2%}")
print(f"CURRENT_NAV_USD: {CURRENT_NAV:.2f}")
print(f"CURRENT_INTEGER_HOLDINGS: {len(actual_now)}")
print(f"CURRENT_INTEGER_CASH: {cash_now:.2%}")
print(f"MINIMUM_TESTED_PASS_NAV_USD: {min_pass}")
print(f"FINAL_VERDICT: {verdict}")
print("NO REAL ORDERS / NO SHEETS MUTATION / V13 UNCHANGED")
print("="*118)
