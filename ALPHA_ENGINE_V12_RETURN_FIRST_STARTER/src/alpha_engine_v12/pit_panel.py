from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import json
import tomllib

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Phase2Config:
    name: str
    objective: str
    sources: dict[str, str]
    policies: dict[str, object]


def load_phase2_config(path: Path) -> Phase2Config:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))["phase2"]
    return Phase2Config(
        name=raw["name"],
        objective=raw["objective"],
        sources=dict(raw["sources"]),
        policies=dict(raw["policies"]),
    )


def _norm_ticker(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.upper()


def _as_date(s: pd.Series) -> pd.Series:
    """Normalize date-like values and force nanosecond precision.

    Parquet/Arrow sources can arrive as datetime64[us] while pandas-created
    dates are commonly datetime64[ns]. merge_asof requires exact dtype
    equality, so all internal date keys are canonicalized to datetime64[ns].
    """
    out = pd.to_datetime(s, errors="coerce").dt.normalize()
    return out.astype("datetime64[ns]")


def _require_columns(df: pd.DataFrame, required: Iterable[str], source: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{source}: missing required columns {missing}")


def _next_session_strict(dates: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    cal = calendar.values.astype("datetime64[ns]")
    vals = pd.to_datetime(dates, errors="coerce").values.astype("datetime64[ns]")
    out = np.full(len(vals), np.datetime64("NaT"), dtype="datetime64[ns]")
    valid = ~pd.isna(vals)
    idx = np.searchsorted(cal, vals[valid], side="right")
    ok = idx < len(cal)
    target = np.full(valid.sum(), np.datetime64("NaT"), dtype="datetime64[ns]")
    target[ok] = cal[idx[ok]]
    out[np.where(valid)[0]] = target
    return pd.Series(pd.to_datetime(out), index=dates.index)


def load_trading_calendar(root: Path, cfg: Phase2Config) -> tuple[pd.DatetimeIndex, pd.DataFrame]:
    path = root / cfg.sources["benchmark_daily"]
    df = pd.read_parquet(path)
    _require_columns(df, ["date", "close"], str(path))
    df = df.copy()
    df["date"] = _as_date(df["date"])
    df = df.dropna(subset=["date", "close"]).sort_values("date")
    df = df.drop_duplicates("date", keep="last")
    cal = pd.DatetimeIndex(df["date"].unique()).sort_values()
    if len(cal) < 2:
        raise ValueError("Trading calendar has fewer than two sessions")
    return cal, df


def _load_market_file(path: Path, source: str, priority: int) -> pd.DataFrame:
    df = pd.read_parquet(path)
    _require_columns(df, ["date", "ticker", "close"], str(path))
    keep = [c for c in ["date", "ticker", "close", "volume", "adj_close", "provider_symbol"] if c in df.columns]
    out = df[keep].copy()
    out["date"] = _as_date(out["date"])
    out["ticker"] = _norm_ticker(out["ticker"])
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    if "volume" in out.columns:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
    else:
        out["volume"] = np.nan
    if "adj_close" in out.columns:
        out["adj_close"] = pd.to_numeric(out["adj_close"], errors="coerce")
    else:
        out["adj_close"] = np.nan
    if "provider_symbol" not in out.columns:
        out["provider_symbol"] = pd.NA
    out["market_source"] = source
    out["market_priority"] = priority
    return out[["date", "ticker", "close", "volume", "adj_close", "provider_symbol", "market_source", "market_priority"]]


def load_market_panel(root: Path, cfg: Phase2Config) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    sources: list[pd.DataFrame] = []
    src_audit: list[dict] = []
    primary = root / cfg.sources["market_primary"]
    secondary = root / cfg.sources["market_secondary"]

    for priority, (name, path) in enumerate((("PRIMARY", primary), ("SECONDARY", secondary))):
        if not path.exists():
            raise FileNotFoundError(path)
        df = _load_market_file(path, name, priority)
        sources.append(df)
        src_audit.append({"source": name, "path": path.relative_to(root).as_posix(), "rows": len(df)})

    ddir = root / cfg.sources["delisted_market_dir"]
    delisted_frames: list[pd.DataFrame] = []
    parquet_files = sorted(ddir.glob("*.parquet")) if ddir.exists() else []
    for p in parquet_files:
        try:
            delisted_frames.append(_load_market_file(p, "DELISTED", 2))
        except Exception:
            # A broken supplemental file is audited by count but does not override core market sources.
            continue
    if delisted_frames:
        ddf = pd.concat(delisted_frames, ignore_index=True)
        sources.append(ddf)
        src_audit.append({"source": "DELISTED", "path": cfg.sources["delisted_market_dir"], "rows": len(ddf)})
    else:
        src_audit.append({"source": "DELISTED", "path": cfg.sources["delisted_market_dir"], "rows": 0})

    allm = pd.concat(sources, ignore_index=True)
    allm = allm.dropna(subset=["date", "ticker", "close"])
    allm = allm[allm["ticker"].ne("") & np.isfinite(allm["close"]) & (allm["close"] > 0)]

    dup = (
        allm.groupby(["ticker", "date"], observed=True)
        .agg(source_count=("market_source", "nunique"), close_min=("close", "min"), close_max=("close", "max"))
        .reset_index()
    )
    dup = dup[dup["source_count"] > 1].copy()
    if len(dup):
        denom = dup[["close_min", "close_max"]].abs().max(axis=1).replace(0, np.nan)
        dup["relative_spread"] = (dup["close_max"] - dup["close_min"]).abs() / denom
    else:
        dup["relative_spread"] = pd.Series(dtype=float)

    allm = allm.sort_values(["ticker", "date", "market_priority"])
    panel = allm.drop_duplicates(["ticker", "date"], keep="first").copy()
    panel = panel.sort_values(["date", "ticker"]).reset_index(drop=True)
    meta = {"market_source_rows": src_audit, "supplemental_delisted_parquet_files": len(parquet_files)}
    return panel, dup, meta


def attach_universe(root: Path, market: pd.DataFrame, cfg: Phase2Config) -> tuple[pd.DataFrame, dict]:
    upath = root / cfg.sources["universe_monthly"]
    uni = pd.read_parquet(upath)
    _require_columns(uni, ["asof", "symbol", "ipo_date", "delisting_date"], str(upath))
    uni = uni.copy()
    uni["asof"] = _as_date(uni["asof"])
    uni["symbol"] = _norm_ticker(uni["symbol"])
    uni["ipo_date"] = _as_date(uni["ipo_date"])
    uni["delisting_date"] = _as_date(uni["delisting_date"])
    uni = uni.dropna(subset=["asof", "symbol"])
    uni = uni.sort_values(["asof", "symbol"]).drop_duplicates(["asof", "symbol"], keep="last")

    snapshot_dates = pd.DataFrame({"universe_asof": sorted(uni["asof"].unique())})
    market_dates = pd.DataFrame({"date": sorted(market["date"].unique())})
    date_map = pd.merge_asof(
        market_dates.sort_values("date"),
        snapshot_dates.sort_values("universe_asof"),
        left_on="date",
        right_on="universe_asof",
        direction="backward",
    )

    out = market.merge(date_map, on="date", how="left")
    uni_meta_cols = [c for c in ["asof", "symbol", "name", "exchange", "asset_type", "ipo_date", "delisting_date", "source_state"] if c in uni.columns]
    u = uni[uni_meta_cols].rename(columns={"asof": "universe_asof", "symbol": "ticker"})
    out = out.merge(u, on=["universe_asof", "ticker"], how="left", validate="many_to_one")
    out["universe_snapshot_eligible"] = out["name"].notna() if "name" in out.columns else out["ipo_date"].notna()
    out["lifecycle_eligible"] = (
        out["ipo_date"].notna()
        & (out["date"] >= out["ipo_date"])
        & (out["delisting_date"].isna() | (out["date"] <= out["delisting_date"]))
    )
    out["universe_snapshot_age_days"] = (out["date"] - out["universe_asof"]).dt.days
    out["research_eligible"] = out["universe_snapshot_eligible"] & out["lifecycle_eligible"]
    stats = {
        "universe_rows": len(uni),
        "universe_snapshots": int(uni["asof"].nunique()),
        "market_rows_with_snapshot": int(out["universe_asof"].notna().sum()),
        "research_eligible_rows": int(out["research_eligible"].sum()),
    }
    return out, stats


def load_fundamental_events(root: Path, calendar: pd.DatetimeIndex, cfg: Phase2Config) -> tuple[pd.DataFrame, dict]:
    fpath = root / cfg.sources["sec_facts_long"]
    facts = pd.read_parquet(fpath)
    required = ["ticker", "canonical_metric", "value", "end", "filed", "form", "accn"]
    _require_columns(facts, required, str(fpath))
    facts = facts.copy()
    facts["ticker"] = _norm_ticker(facts["ticker"])
    facts["canonical_metric"] = facts["canonical_metric"].astype("string").str.strip()
    facts["filed"] = _as_date(facts["filed"])
    facts["period_end"] = _as_date(facts["end"])
    facts["value"] = pd.to_numeric(facts["value"], errors="coerce")
    facts = facts.dropna(subset=["ticker", "canonical_metric", "filed", "value"])
    facts = facts[np.isfinite(facts["value"])]
    facts["available_date"] = _next_session_strict(facts["filed"], calendar)
    facts = facts.dropna(subset=["available_date"])

    # Deterministic event de-duplication. Later period-end within the same filing wins.
    # Amendments filed later remain separate events and can update the known value later.
    facts = facts.sort_values(
        ["ticker", "canonical_metric", "available_date", "period_end", "filed", "accn"],
        na_position="first",
    )
    facts = facts.drop_duplicates(["ticker", "canonical_metric", "available_date"], keep="last")
    facts["filing_lag_days"] = (facts["filed"] - facts["period_end"]).dt.days
    keep = [
        "ticker", "canonical_metric", "value", "period_end", "filed", "available_date",
        "form", "fy", "fp", "frame", "accn", "unit", "taxonomy", "concept", "filing_lag_days"
    ]
    keep = [c for c in keep if c in facts.columns]
    events = facts[keep].sort_values(["available_date", "ticker", "canonical_metric"]).reset_index(drop=True)
    stats = {
        "fundamental_events": len(events),
        "tickers": int(events["ticker"].nunique()),
        "metrics": int(events["canonical_metric"].nunique()),
        "first_filed": str(events["filed"].min().date()) if len(events) else None,
        "last_filed": str(events["filed"].max().date()) if len(events) else None,
    }
    return events, stats


def attach_fundamentals(panel: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    base = panel.sort_values(["ticker", "date"]).reset_index(drop=True).copy()
    metrics = sorted(str(x) for x in events["canonical_metric"].dropna().unique())
    for metric in metrics:
        ev = events[events["canonical_metric"].eq(metric)].copy()
        if ev.empty:
            continue
        ev = ev.sort_values(["ticker", "available_date"])
        cols = ["ticker", "available_date", "value", "filed", "period_end", "form", "accn"]
        ev = ev[[c for c in cols if c in ev.columns]]
        rename = {
            "value": metric,
            "available_date": f"{metric}__available_date",
            "filed": f"{metric}__filed",
            "period_end": f"{metric}__period_end",
            "form": f"{metric}__form",
            "accn": f"{metric}__accn",
        }
        ev = ev.rename(columns=rename)
        available_col = f"{metric}__available_date"

        # merge_asof is strict about both dtype identity and global ordering
        # of the as-of keys.  Arrow-backed parquet data can expose dates at
        # microsecond precision, while derived dates use nanoseconds.
        # Canonicalize both sides and sort primarily by the as-of key; `by`
        # still prevents values from crossing ticker boundaries.
        base["date"] = _as_date(base["date"])
        ev[available_col] = _as_date(ev[available_col])
        base = pd.merge_asof(
            base.sort_values(["date", "ticker"]),
            ev.sort_values([available_col, "ticker"]),
            left_on="date",
            right_on=available_col,
            by="ticker",
            direction="backward",
            allow_exact_matches=True,
        )
    return base.sort_values(["date", "ticker"]).reset_index(drop=True), metrics


def add_execution_dates(panel: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    out = panel.copy()
    out["signal_date"] = out["date"]
    out["earliest_execution_date"] = _next_session_strict(out["signal_date"], calendar)
    return out


def build_event_calendar(panel: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    market_events = panel[["date", "ticker"]].drop_duplicates().rename(columns={"date": "event_date"})
    market_events["event_type"] = "SESSION_CLOSE"
    market_events["metric"] = pd.NA
    market_events["source_date"] = market_events["event_date"]

    fund_events = events[["available_date", "ticker", "canonical_metric", "filed"]].copy()
    fund_events = fund_events.rename(
        columns={"available_date": "event_date", "canonical_metric": "metric", "filed": "source_date"}
    )
    fund_events["event_type"] = "FUNDAMENTAL_AVAILABLE"
    cols = ["event_date", "ticker", "event_type", "metric", "source_date"]
    out = pd.concat([market_events[cols], fund_events[cols]], ignore_index=True)
    return out.sort_values(["event_date", "ticker", "event_type", "metric"], na_position="last").reset_index(drop=True)


def pit_audit(panel: pd.DataFrame, events: pd.DataFrame, conflicts: pd.DataFrame, cfg: Phase2Config) -> pd.DataFrame:
    rows: list[dict] = []

    def add(test: str, passed: bool, value: object, rule: str) -> None:
        rows.append({"test": test, "status": "PASS" if passed else "FAIL", "value": value, "rule": rule})

    add("UNIQUE_TICKER_DATE", not panel.duplicated(["ticker", "date"]).any(), int(panel.duplicated(["ticker", "date"]).sum()), "0 duplicates")
    add("POSITIVE_CLOSE", bool((panel["close"] > 0).all()), int((panel["close"] <= 0).sum()), "all close > 0")
    add(
        "UNIVERSE_ASOF_CAUSAL",
        bool((panel.loc[panel["universe_asof"].notna(), "universe_asof"] <= panel.loc[panel["universe_asof"].notna(), "date"]).all()),
        int((panel["universe_asof"] > panel["date"]).fillna(False).sum()),
        "universe_asof <= date",
    )
    add(
        "FUNDAMENTAL_NEXT_SESSION_STRICT",
        bool((events["available_date"] > events["filed"]).all()) if len(events) else True,
        int((events["available_date"] <= events["filed"]).sum()) if len(events) else 0,
        "available_date > filed",
    )
    avail_cols = [c for c in panel.columns if c.endswith("__available_date")]
    future_uses = 0
    for c in avail_cols:
        future_uses += int((panel[c] > panel["date"]).fillna(False).sum())
    add("NO_FUTURE_FUNDAMENTALS_IN_PANEL", future_uses == 0, future_uses, "all metric available dates <= panel date")
    exec_bad = int((panel["earliest_execution_date"] <= panel["signal_date"]).fillna(False).sum())
    add("EXECUTION_AFTER_SIGNAL", exec_bad == 0, exec_bad, "earliest_execution_date > signal_date")
    max_age = int(cfg.policies.get("max_universe_snapshot_age_days", 45))
    age_bad = int((panel["universe_snapshot_age_days"] > max_age).fillna(False).sum())
    add("UNIVERSE_SNAPSHOT_AGE", age_bad == 0, age_bad, f"snapshot age <= {max_age} days")
    tol = float(cfg.policies.get("price_conflict_relative_tolerance", 1e-6))
    conflict_bad = int((conflicts["relative_spread"] > tol).sum()) if len(conflicts) else 0
    # Conflicts are a diagnostic, not a failure, because source precedence is deterministic.
    rows.append({"test": "MARKET_SOURCE_CONFLICTS", "status": "WARN" if conflict_bad else "PASS", "value": conflict_bad, "rule": f"relative spread <= {tol}; precedence resolves conflicts"})
    return pd.DataFrame(rows)


def _source_audit(root: Path, cfg: Phase2Config, market_meta: dict, universe_stats: dict, fundamental_stats: dict) -> pd.DataFrame:
    rows: list[dict] = []
    for key, rel in cfg.sources.items():
        p = root / rel
        if key == "delisted_market_dir":
            exists = p.is_dir()
            size = sum(x.stat().st_size for x in p.glob("*.parquet")) if exists else 0
        else:
            exists = p.exists()
            size = p.stat().st_size if exists and p.is_file() else 0
        rows.append({"source_key": key, "path": rel, "exists": exists, "size_bytes": int(size)})
    return pd.DataFrame(rows)


def build_phase2(root: Path) -> dict:
    cfg = load_phase2_config(root / "config" / "phase2.toml")
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    calendar, benchmark = load_trading_calendar(root, cfg)
    market, conflicts, market_meta = load_market_panel(root, cfg)
    # Keep only actual benchmark trading sessions. This removes stray provider dates.
    market = market[market["date"].isin(calendar)].copy()

    panel, universe_stats = attach_universe(root, market, cfg)
    events, fundamental_stats = load_fundamental_events(root, calendar, cfg)
    panel, metrics = attach_fundamentals(panel, events)
    panel = add_execution_dates(panel, calendar)
    event_calendar = build_event_calendar(panel, events)
    audit = pit_audit(panel, events, conflicts, cfg)
    source_audit = _source_audit(root, cfg, market_meta, universe_stats, fundamental_stats)

    panel.to_parquet(outputs / "phase2_canonical_pit_panel.parquet", index=False)
    events.to_parquet(outputs / "phase2_fundamental_events.parquet", index=False)
    event_calendar.to_parquet(outputs / "phase2_event_calendar.parquet", index=False)
    conflicts.to_csv(outputs / "phase2_market_conflicts.csv", index=False)
    audit.to_csv(outputs / "phase2_pit_audit.csv", index=False)
    source_audit.to_csv(outputs / "phase2_source_audit.csv", index=False)

    schema = {
        "panel_columns": list(panel.columns),
        "fundamental_metrics": metrics,
        "policies": cfg.policies,
        "meaning": {
            "date": "information snapshot at session close",
            "signal_date": "decision timestamp represented at session-close date granularity",
            "earliest_execution_date": "first session strictly after signal_date",
            "metric__available_date": "first trading session on which the filing may be used under strict next-session policy",
            "research_eligible": "historical universe snapshot membership AND lifecycle eligibility; no alpha rule applied",
        },
    }
    (outputs / "phase2_panel_schema.json").write_text(json.dumps(schema, indent=2, default=str), encoding="utf-8")

    hard_fail = bool((audit["status"] == "FAIL").any()) or not bool(source_audit["exists"].all())
    summary = {
        "status": "FAIL" if hard_fail else "PASS",
        "phase": 2,
        "name": cfg.name,
        "objective": cfg.objective,
        "calendar": {
            "sessions": len(calendar),
            "first": str(calendar.min().date()),
            "last": str(calendar.max().date()),
        },
        "market": {
            "rows": len(market),
            "tickers": int(market["ticker"].nunique()),
            "first": str(market["date"].min().date()) if len(market) else None,
            "last": str(market["date"].max().date()) if len(market) else None,
            **market_meta,
        },
        "universe": universe_stats,
        "fundamentals": fundamental_stats,
        "panel": {
            "rows": len(panel),
            "tickers": int(panel["ticker"].nunique()),
            "research_eligible_rows": int(panel["research_eligible"].sum()),
            "fundamental_metrics": metrics,
        },
        "event_calendar": {
            "rows": len(event_calendar),
            "fundamental_events": int((event_calendar["event_type"] == "FUNDAMENTAL_AVAILABLE").sum()),
            "session_close_events": int((event_calendar["event_type"] == "SESSION_CLOSE").sum()),
        },
        "pit_gate": audit.to_dict(orient="records"),
        "next_gate": "Do not create return targets or alpha features unless Phase 2 status is PASS and price semantics/corporate-action handling are reviewed.",
    }
    (outputs / "phase2_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
