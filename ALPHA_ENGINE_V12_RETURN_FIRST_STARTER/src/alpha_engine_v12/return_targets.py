from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

PHASE3_BUILD = "V3_TERMINAL_OVERLAY_2026-09-12"


@dataclass(frozen=True)
class Phase3Config:
    name: str
    objective: str
    panel_path: str
    return_price_layer_path: str
    phase2c_summary_path: str
    phase3c_summary_path: str
    terminal_overlay_path: str
    research_exclusions_path: str
    output_targets_path: str
    horizons: tuple[int, ...]
    entry_anchor: str
    policies: dict[str, object]


def _as_date(s: pd.Series) -> pd.Series:
    out = pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize()
    return out.astype("datetime64[ns]")


def _require_columns(df: pd.DataFrame, cols: Iterable[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")


def load_config(root: Path) -> Phase3Config:
    path = root / "config" / "phase3.toml"
    with path.open("rb") as f:
        raw = tomllib.load(f)
    p = raw["phase3"]
    policies = dict(p["policies"])
    horizons = tuple(int(x) for x in p["horizons"])
    if not horizons or any(h <= 0 for h in horizons):
        raise ValueError("Phase 3 horizons must be positive trading-session counts")
    if len(set(horizons)) != len(horizons):
        raise ValueError("Phase 3 horizons must be unique")
    return Phase3Config(
        name=str(p["name"]),
        objective=str(p["objective"]),
        panel_path=str(p["panel_path"]),
        return_price_layer_path=str(p["return_price_layer_path"]),
        phase2c_summary_path=str(p["phase2c_summary_path"]),
        phase3c_summary_path=str(p["phase3c_summary_path"]),
        terminal_overlay_path=str(p["terminal_overlay_path"]),
        research_exclusions_path=str(p["research_exclusions_path"]),
        output_targets_path=str(p["output_targets_path"]),
        horizons=horizons,
        entry_anchor=str(p["entry_anchor"]),
        policies=policies,
    )


def validate_phase2c_input(summary: dict) -> None:
    if summary.get("status") != "PASS":
        raise RuntimeError("Phase 2C must PASS before Phase 3 target construction")
    policy = summary.get("target_price_policy") or {}
    if policy.get("feature_allowed") is not False:
        raise RuntimeError("Phase 2C target price must remain feature-forbidden")
    if policy.get("column") != "target_total_return_price":
        raise RuntimeError("Unexpected Phase 2C target-price column")




def validate_phase3c_input(summary: dict) -> None:
    if summary.get("status") != "PASS":
        raise RuntimeError("Phase 3C must PASS before rebuilding Phase 3 targets")
    if summary.get("feature_allowed") is not False:
        raise RuntimeError("Phase 3C terminal overlay must remain feature-forbidden")


def _bool_series(s: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(s):
        return s.fillna(False).astype(bool)
    return s.fillna("").astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _prepare_terminal_overlay(overlay: pd.DataFrame | None) -> dict[str, dict[str, object]]:
    if overlay is None or overlay.empty:
        return {}
    required = [
        "ticker", "terminal_price_date", "consensus_delisting_date", "evidence_count",
        "overlay_validated", "target_only", "feature_allowed",
    ]
    _require_columns(overlay, required, "Phase 3C terminal overlay")
    x = overlay.copy()
    x["ticker"] = x["ticker"].astype(str).str.upper().str.replace(".", "-", regex=False).str.strip()
    x["terminal_price_date"] = _as_date(x["terminal_price_date"])
    x["consensus_delisting_date"] = _as_date(x["consensus_delisting_date"])
    if x.duplicated("ticker").any():
        raise ValueError("Phase 3C terminal overlay has duplicate tickers")
    x["overlay_validated"] = _bool_series(x["overlay_validated"])
    x["target_only"] = _bool_series(x["target_only"])
    x["feature_allowed"] = _bool_series(x["feature_allowed"])
    if not x["overlay_validated"].all():
        raise ValueError("Phase 3C terminal overlay contains unvalidated rows")
    if not x["target_only"].all():
        raise ValueError("Phase 3C terminal overlay must be target-only")
    if x["feature_allowed"].any():
        raise ValueError("Phase 3C terminal overlay cannot be feature-allowed")
    out: dict[str, dict[str, object]] = {}
    for _, r in x.iterrows():
        out[str(r["ticker"])] = r.to_dict()
    return out


def _future_extrema(price: np.ndarray, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    """Extrema over the next horizon ticker-observed sessions, including entry."""
    s = pd.Series(price[::-1])
    mx = s.rolling(window=horizon + 1, min_periods=1).max().to_numpy()[::-1]
    mn = s.rolling(window=horizon + 1, min_periods=1).min().to_numpy()[::-1]
    return mx, mn


def _ticker_delisting_date(panel_t: pd.DataFrame) -> pd.Timestamp | pd.NaT:
    vals = panel_t["delisting_date"].dropna()
    if vals.empty:
        return pd.NaT
    return pd.Timestamp(vals.iloc[0]).normalize()


def _actual_entry_positions(
    trade_dates: np.ndarray,
    signal_dates: np.ndarray,
    requested_dates: np.ndarray,
    max_entry_delay_calendar_days: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map requested next-session dates to the first actually observed tradable ticker date."""
    n = len(signal_dates)
    pos = np.full(n, -1, dtype=int)
    actual = np.full(n, np.datetime64("NaT"), dtype="datetime64[ns]")
    delay_days = np.full(n, np.nan, dtype=float)
    if len(trade_dates) == 0:
        return pos, actual, delay_days

    td = trade_dates.astype("datetime64[ns]")
    valid_req = ~pd.isna(requested_dates)
    for i in np.flatnonzero(valid_req):
        req = requested_dates[i].astype("datetime64[ns]")
        j = int(np.searchsorted(td, req, side="left"))
        if j >= len(td):
            continue
        act = td[j]
        if act <= signal_dates[i]:
            j = int(np.searchsorted(td, signal_dates[i], side="right"))
            if j >= len(td):
                continue
            act = td[j]
        delay = int((act - req) / np.timedelta64(1, "D"))
        if delay < 0 or delay > int(max_entry_delay_calendar_days):
            continue
        pos[i] = j
        actual[i] = act
        delay_days[i] = float(delay)
    return pos, actual, delay_days


def _apply_research_exclusions(eligible: pd.DataFrame, exclusions: pd.DataFrame | None) -> tuple[pd.DataFrame, int]:
    if exclusions is None or exclusions.empty:
        return eligible, 0
    required = ["ticker", "effective_start_date", "effective_end_date", "research_eligible", "feature_allowed"]
    _require_columns(exclusions, required, "Phase 3C research exclusions")
    x = exclusions.copy()
    x["ticker"] = x["ticker"].astype(str).str.upper().str.replace(".", "-", regex=False).str.strip()
    x["effective_start_date"] = _as_date(x["effective_start_date"])
    x["effective_end_date"] = _as_date(x["effective_end_date"])
    x["research_eligible"] = _bool_series(x["research_eligible"])
    x["feature_allowed"] = _bool_series(x["feature_allowed"])
    if x["research_eligible"].any():
        raise ValueError("Phase 3C exclusion rows must have research_eligible=False")
    if x["feature_allowed"].any():
        raise ValueError("Phase 3C exclusion rows must be feature-forbidden")
    keep = pd.Series(True, index=eligible.index)
    for _, r in x.iterrows():
        m = (eligible["ticker"].astype(str).str.upper().str.replace(".", "-", regex=False) == r["ticker"])
        m &= eligible["date"].between(r["effective_start_date"], r["effective_end_date"], inclusive="both")
        keep &= ~m
    removed = int((~keep).sum())
    return eligible.loc[keep].copy(), removed


def build_return_targets(
    panel: pd.DataFrame,
    layer: pd.DataFrame,
    horizons: tuple[int, ...],
    minimum_cross_section_size: int = 20,
    winner_top_decile_cutoff: float = 0.90,
    winner_top_quintile_cutoff: float = 0.80,
    max_entry_delay_calendar_days: int = 7,
    sample_end_grace_global_sessions: int = 5,
    terminal_overlay: pd.DataFrame | None = None,
    research_exclusions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    _require_columns(
        panel,
        ["date", "ticker", "close", "research_eligible", "earliest_execution_date", "delisting_date"],
        "canonical PIT panel",
    )
    _require_columns(
        layer,
        ["date", "ticker", "target_total_return_price", "target_price_source", "target_price_feature_allowed"],
        "Phase 2C return-price layer",
    )

    p = panel.copy()
    r = layer.copy()
    for df in (p, r):
        df["date"] = _as_date(df["date"])
        df["ticker"] = df["ticker"].astype(str)
    p["earliest_execution_date"] = _as_date(p["earliest_execution_date"])
    p["delisting_date"] = _as_date(p["delisting_date"])

    if r["target_price_feature_allowed"].fillna(False).astype(bool).any():
        raise ValueError("target_total_return_price is target-only and cannot be feature-allowed")

    global_sessions = pd.DatetimeIndex(sorted(p["date"].dropna().unique())).astype("datetime64[ns]")
    if len(global_sessions) < 3:
        raise ValueError("Not enough trading sessions for Phase 3")
    global_session_to_idx = {pd.Timestamp(d): i for i, d in enumerate(global_sessions)}
    last_global_idx = len(global_sessions) - 1

    eligible = p[p["research_eligible"].fillna(False).astype(bool)].copy()
    eligible, excluded_signal_rows = _apply_research_exclusions(eligible, research_exclusions)
    eligible = eligible.sort_values(["ticker", "date"]).reset_index(drop=True)
    if eligible.duplicated(["date", "ticker"]).any():
        raise ValueError("Canonical PIT panel contains duplicate eligible ticker-date rows")

    layer_groups = {t: g.sort_values("date") for t, g in r.groupby("ticker", sort=False)}
    panel_groups = {t: g.sort_values("date") for t, g in p.groupby("ticker", sort=False)}
    overlay_map = _prepare_terminal_overlay(terminal_overlay)

    out_frames: list[pd.DataFrame] = []
    for ticker, sig in eligible.groupby("ticker", sort=False):
        sig = sig.sort_values("date").copy()
        panel_t = panel_groups.get(ticker)
        layer_t = layer_groups.get(ticker)
        if panel_t is None or layer_t is None:
            continue

        lt = layer_t[["date", "target_total_return_price", "target_price_source"]].copy()
        lt["target_total_return_price"] = pd.to_numeric(lt["target_total_return_price"], errors="coerce")
        lt = lt[lt["target_total_return_price"].notna() & (lt["target_total_return_price"] > 0)].copy()
        lt = lt.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
        if lt.empty:
            continue

        trade_dates = lt["date"].to_numpy(dtype="datetime64[ns]")
        prices = lt["target_total_return_price"].to_numpy(dtype=float)
        sources = lt["target_price_source"].astype(object).to_numpy()
        raw_map = panel_t.drop_duplicates("date", keep="last").set_index("date")["close"]
        raw_close = pd.to_numeric(raw_map.reindex(pd.DatetimeIndex(trade_dates)), errors="coerce").to_numpy(dtype=float)

        signal_dates = sig["date"].to_numpy(dtype="datetime64[ns]")
        requested_dates = sig["earliest_execution_date"].to_numpy(dtype="datetime64[ns]")
        entry_pos, actual_entry_dates, entry_delay_days = _actual_entry_positions(
            trade_dates,
            signal_dates,
            requested_dates,
            max_entry_delay_calendar_days=max_entry_delay_calendar_days,
        )
        entry_ok = entry_pos >= 0
        entry_total = np.full(len(sig), np.nan, dtype=float)
        entry_close = np.full(len(sig), np.nan, dtype=float)
        entry_source = np.empty(len(sig), dtype=object)
        entry_source[:] = None
        if entry_ok.any():
            e = entry_pos[entry_ok]
            entry_total[entry_ok] = prices[e]
            entry_close[entry_ok] = raw_close[e]
            entry_source[entry_ok] = sources[e]

        base = pd.DataFrame({
            "signal_date": sig["date"].to_numpy(),
            "ticker": ticker,
            "requested_entry_date": sig["earliest_execution_date"].to_numpy(),
            "entry_date": actual_entry_dates,
            "entry_delay_calendar_days": entry_delay_days,
            "entry_execution_close": entry_close,
            "entry_total_return_price": entry_total,
            "entry_target_price_source": entry_source,
            "entry_anchor": "NEXT_TRADABLE_SESSION_CLOSE",
            "target_feature_allowed": False,
            "phase3c_research_exclusion_applied_to_row": False,
        })

        terminal_pos = len(trade_dates) - 1
        terminal_date = pd.Timestamp(trade_dates[terminal_pos]).normalize()
        terminal_global_idx = global_session_to_idx.get(terminal_date, -1)
        near_sample_end = terminal_global_idx >= (last_global_idx - int(sample_end_grace_global_sessions))
        delist_date = _ticker_delisting_date(panel_t)
        panel_known_delisting = bool(pd.notna(delist_date) and terminal_date <= pd.Timestamp(delist_date))
        overlay_row = overlay_map.get(str(ticker).upper().replace(".", "-"))
        overlay_terminal = False
        overlay_consensus_date = pd.NaT
        overlay_evidence_count = 0
        if overlay_row is not None:
            overlay_terminal_date = pd.Timestamp(overlay_row["terminal_price_date"]).normalize()
            overlay_consensus_date = pd.Timestamp(overlay_row["consensus_delisting_date"]).normalize() if pd.notna(overlay_row["consensus_delisting_date"]) else pd.NaT
            overlay_evidence_count = int(overlay_row.get("evidence_count", 0))
            overlay_terminal = bool(overlay_row.get("overlay_validated", False) and terminal_date == overlay_terminal_date)
        known_delisting = bool(panel_known_delisting or overlay_terminal)
        terminal_resolution_source = (
            "PHASE3C_VALIDATED_DELISTING_OVERLAY" if overlay_terminal
            else ("PANEL_DELISTING_DATE" if panel_known_delisting else "NONE")
        )
        base["terminal_resolution_source"] = terminal_resolution_source
        base["terminal_overlay_consensus_delisting_date"] = overlay_consensus_date
        base["terminal_overlay_evidence_count"] = overlay_evidence_count

        for h in horizons:
            h = int(h)
            desired_pos = entry_pos + h
            full = entry_ok & (desired_pos >= 0) & (desired_pos < len(trade_dates))
            terminal = entry_ok & ~full & known_delisting & (entry_pos <= terminal_pos)
            right_censored = entry_ok & ~full & ~terminal & near_sample_end
            unresolved = entry_ok & ~full & ~terminal & ~right_censored
            no_entry = ~entry_ok

            exit_price = np.full(len(sig), np.nan, dtype=float)
            final_pos = np.full(len(sig), -1, dtype=int)
            if full.any():
                final_pos[full] = desired_pos[full]
                exit_price[full] = prices[desired_pos[full]]
            if terminal.any():
                final_pos[terminal] = terminal_pos
                exit_price[terminal] = prices[terminal_pos]

            status = np.full(len(sig), "UNRESOLVED_TERMINATION", dtype=object)
            status[no_entry] = "NO_ENTRY"
            status[right_censored] = "RIGHT_CENSORED_SAMPLE_END"
            if terminal.any():
                status[terminal] = "TERMINAL_DELISTING_REPAIRED" if overlay_terminal else "TERMINAL_DELISTING"
            status[full] = "FULL_HORIZON"

            end_dates = np.full(len(sig), np.datetime64("NaT"), dtype="datetime64[ns]")
            valid_final = final_pos >= 0
            if valid_final.any():
                end_dates[valid_final] = trade_dates[final_pos[valid_final]]

            label_ok = full | terminal
            ret = np.full(len(sig), np.nan, dtype=float)
            logret = np.full(len(sig), np.nan, dtype=float)
            ret[label_ok] = exit_price[label_ok] / entry_total[label_ok] - 1.0
            logret[label_ok] = np.log(exit_price[label_ok] / entry_total[label_ok])

            fmax, fmin = _future_extrema(prices, h)
            path_max = np.full(len(sig), np.nan, dtype=float)
            path_min = np.full(len(sig), np.nan, dtype=float)
            if entry_ok.any():
                ep = entry_pos[entry_ok]
                path_max[entry_ok] = fmax[ep]
                path_min[entry_ok] = fmin[ep]
            mfe = np.full(len(sig), np.nan, dtype=float)
            mae = np.full(len(sig), np.nan, dtype=float)
            mfe[label_ok] = path_max[label_ok] / entry_total[label_ok] - 1.0
            mae[label_ok] = path_min[label_ok] / entry_total[label_ok] - 1.0

            suffix = f"{h}d"
            base[f"target_end_date_{suffix}"] = end_dates
            base[f"target_status_{suffix}"] = status
            base[f"target_resolved_{suffix}"] = label_ok
            base[f"fwd_return_{suffix}"] = ret
            base[f"fwd_log_return_{suffix}"] = logret
            base[f"mfe_{suffix}"] = mfe
            base[f"mae_{suffix}"] = mae

        out_frames.append(base)

    if not out_frames:
        raise RuntimeError("Phase 3 produced no target rows")
    out = pd.concat(out_frames, ignore_index=True)
    out["signal_date"] = _as_date(out["signal_date"])
    out["requested_entry_date"] = _as_date(out["requested_entry_date"])
    out["entry_date"] = _as_date(out["entry_date"])
    out = out.sort_values(["signal_date", "ticker"]).reset_index(drop=True)
    out.attrs["phase3c_excluded_signal_rows"] = int(excluded_signal_rows)

    for h in horizons:
        suffix = f"{int(h)}d"
        ret_col = f"fwd_return_{suffix}"
        count = out.groupby("signal_date", observed=True)[ret_col].transform("count")
        rank = out.groupby("signal_date", observed=True)[ret_col].rank(method="average", pct=True)
        rank = rank.where(count >= int(minimum_cross_section_size))
        out[f"cs_rank_pct_{suffix}"] = rank
        top10 = pd.Series(pd.NA, index=out.index, dtype="boolean")
        top20 = pd.Series(pd.NA, index=out.index, dtype="boolean")
        valid_rank = rank.notna()
        top10.loc[valid_rank] = rank.loc[valid_rank] >= float(winner_top_decile_cutoff)
        top20.loc[valid_rank] = rank.loc[valid_rank] >= float(winner_top_quintile_cutoff)
        out[f"winner_top_decile_{suffix}"] = top10
        out[f"winner_top_quintile_{suffix}"] = top20

    return out


def horizon_diagnostics(targets: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    rows: list[dict] = []
    for h in horizons:
        suffix = f"{int(h)}d"
        ret = pd.to_numeric(targets[f"fwd_return_{suffix}"], errors="coerce")
        available = ret.notna()
        resolved = targets[f"target_resolved_{suffix}"].fillna(False).astype(bool)
        status = targets[f"target_status_{suffix}"].astype(str)
        vals = ret.dropna()
        resolved_count = int(resolved.sum())
        rows.append({
            "horizon_sessions": int(h),
            "rows": int(len(targets)),
            "resolved_rows": resolved_count,
            "label_rows": int(available.sum()),
            "resolved_label_coverage": float((available & resolved).sum() / resolved_count) if resolved_count else math.nan,
            "full_horizon_rows": int(status.eq("FULL_HORIZON").sum()),
            "terminal_delisting_rows": int(status.isin(["TERMINAL_DELISTING", "TERMINAL_DELISTING_REPAIRED"]).sum()),
            "repaired_terminal_delisting_rows": int(status.eq("TERMINAL_DELISTING_REPAIRED").sum()),
            "right_censored_rows": int(status.eq("RIGHT_CENSORED_SAMPLE_END").sum()),
            "unresolved_termination_rows": int(status.eq("UNRESOLVED_TERMINATION").sum()),
            "no_entry_rows": int(status.eq("NO_ENTRY").sum()),
            "mean_return": float(vals.mean()) if len(vals) else math.nan,
            "median_return": float(vals.median()) if len(vals) else math.nan,
            "std_return": float(vals.std(ddof=1)) if len(vals) > 1 else math.nan,
            "q01": float(vals.quantile(0.01)) if len(vals) else math.nan,
            "q05": float(vals.quantile(0.05)) if len(vals) else math.nan,
            "q95": float(vals.quantile(0.95)) if len(vals) else math.nan,
            "q99": float(vals.quantile(0.99)) if len(vals) else math.nan,
            "min_return": float(vals.min()) if len(vals) else math.nan,
            "max_return": float(vals.max()) if len(vals) else math.nan,
        })
    return pd.DataFrame(rows)


def evaluate_gate(
    targets: pd.DataFrame,
    diagnostics: pd.DataFrame,
    phase2c_summary: dict,
    phase3c_summary: dict,
    cfg: Phase3Config,
    terminal_overlay: pd.DataFrame | None = None,
    research_exclusions: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, str]:
    rows: list[dict] = []

    def add(test: str, status: str, value: object, rule: str, blocking: bool = True) -> None:
        rows.append({"test": test, "status": status, "blocking": blocking, "value": value, "rule": rule})

    add("PHASE2C_INPUT_PASS", "PASS" if phase2c_summary.get("status") == "PASS" else "FAIL",
        phase2c_summary.get("status"), "Phase 2C status must be PASS")
    add("PHASE3C_INPUT_PASS", "PASS" if phase3c_summary.get("status") == "PASS" else "FAIL",
        phase3c_summary.get("status"), "Phase 3C terminal repair must be PASS")
    overlay_feature_forbidden = phase3c_summary.get("feature_allowed") is False
    add("TERMINAL_OVERLAY_FEATURE_FORBIDDEN", "PASS" if overlay_feature_forbidden else "FAIL", overlay_feature_forbidden,
        "Phase 3C delisting overlay must remain target-only and feature-forbidden")

    if terminal_overlay is not None and not terminal_overlay.empty:
        expected_overlay_tickers = set(terminal_overlay["ticker"].astype(str).str.upper().str.replace(".", "-", regex=False))
        used_overlay_tickers = set(targets.loc[targets["terminal_resolution_source"].astype(str).eq("PHASE3C_VALIDATED_DELISTING_OVERLAY"), "ticker"].astype(str).str.upper().str.replace(".", "-", regex=False))
        missing_overlay_tickers = expected_overlay_tickers - used_overlay_tickers
        add("TERMINAL_OVERLAY_TICKER_COVERAGE", "PASS" if not missing_overlay_tickers else "FAIL", len(missing_overlay_tickers),
            "0 validated Phase 3C terminal-overlay tickers unused in rebuilt targets")

    if research_exclusions is not None and not research_exclusions.empty:
        ex = research_exclusions.copy()
        ex["ticker"] = ex["ticker"].astype(str).str.upper().str.replace(".", "-", regex=False)
        ex["effective_start_date"] = _as_date(ex["effective_start_date"])
        ex["effective_end_date"] = _as_date(ex["effective_end_date"])
        leakage = 0
        for _, r in ex.iterrows():
            m = targets["ticker"].astype(str).str.upper().str.replace(".", "-", regex=False).eq(r["ticker"])
            m &= targets["signal_date"].between(r["effective_start_date"], r["effective_end_date"], inclusive="both")
            leakage += int(m.sum())
        add("RESEARCH_EXCLUSION_LEAKAGE", "PASS" if leakage == 0 else "FAIL", leakage,
            "0 target rows may remain inside Phase 3C non-equity exclusion windows")
        applied_rows = int(targets.attrs.get("phase3c_excluded_signal_rows", 0))
        add("RESEARCH_EXCLUSION_ROWS_APPLIED", "PASS" if applied_rows > 0 else "FAIL", applied_rows,
            "at least one signal row must be removed when Phase 3C declares research exclusions")

    feature_forbidden = (phase2c_summary.get("target_price_policy") or {}).get("feature_allowed") is False
    add("TARGET_PRICE_FEATURE_FORBIDDEN", "PASS" if feature_forbidden else "FAIL", feature_forbidden,
        "target_total_return_price must remain TARGET_CONSTRUCTION_ONLY")

    dups = int(targets.duplicated(["signal_date", "ticker"]).sum())
    add("UNIQUE_SIGNAL_TICKER", "PASS" if dups == 0 else "FAIL", dups, "0 duplicate signal_date,ticker rows")

    entry_mask = targets["entry_date"].notna()
    temporal_violations = int((targets.loc[entry_mask, "entry_date"] <= targets.loc[entry_mask, "signal_date"]).sum())
    add("ENTRY_AFTER_SIGNAL", "PASS" if temporal_violations == 0 else "FAIL", temporal_violations,
        "actual entry_date must be strictly after signal_date")

    requested_mask = targets["requested_entry_date"].notna()
    entry_price = pd.to_numeric(targets["entry_total_return_price"], errors="coerce")
    entry_ok = entry_mask & entry_price.notna() & np.isfinite(entry_price) & (entry_price > 0)
    entry_den = int(requested_mask.sum())
    entry_cov = float((entry_ok & requested_mask).sum() / entry_den) if entry_den else math.nan
    req = float(cfg.policies["entry_price_coverage_required"])
    add("ENTRY_PRICE_COVERAGE", "PASS" if np.isfinite(entry_cov) and entry_cov >= req else "FAIL", entry_cov,
        f">= {req:.3f} among signals with a requested execution date")

    max_delay = float(cfg.policies["max_entry_delay_calendar_days"])
    delays = pd.to_numeric(targets.loc[entry_mask, "entry_delay_calendar_days"], errors="coerce")
    delay_viol = int((delays > max_delay).sum())
    add("ENTRY_DELAY_LIMIT", "PASS" if delay_viol == 0 else "FAIL", delay_viol,
        f"0 actual entries delayed by more than {max_delay:g} calendar days")

    resolved_req = float(cfg.policies["resolved_label_coverage_required"])
    unresolved_rate_max = float(cfg.policies["unresolved_termination_rate_max"])
    for row in diagnostics.to_dict(orient="records"):
        h = int(row["horizon_sessions"])
        cov = row["resolved_label_coverage"]
        add(f"RESOLVED_LABEL_COVERAGE_{h}D", "PASS" if np.isfinite(cov) and float(cov) >= resolved_req else "FAIL", cov,
            f">= {resolved_req:.3f} among resolved {h}-session outcomes")
        eligible_entry_rows = int(len(targets) - row["no_entry_rows"])
        unresolved = int(row["unresolved_termination_rows"])
        unresolved_rate = float(unresolved / eligible_entry_rows) if eligible_entry_rows else 0.0
        add(f"UNRESOLVED_TERMINATION_{h}D", "PASS" if unresolved_rate <= unresolved_rate_max else "FAIL", unresolved_rate,
            f"<= {unresolved_rate_max:.6f}; unknown early history termination is not silently censored")

        status = targets[f"target_status_{h}d"].astype(str)
        ret = pd.to_numeric(targets[f"fwd_return_{h}d"], errors="coerce")
        censor_with_label = int((status.eq("RIGHT_CENSORED_SAMPLE_END") & ret.notna()).sum())
        add(f"CENSORED_HAS_NO_LABEL_{h}D", "PASS" if censor_with_label == 0 else "FAIL", censor_with_label,
            "0 right-censored rows may carry a future-return label")
        unresolved_with_label = int((status.eq("UNRESOLVED_TERMINATION") & ret.notna()).sum())
        add(f"UNRESOLVED_HAS_NO_LABEL_{h}D", "PASS" if unresolved_with_label == 0 else "FAIL", unresolved_with_label,
            "0 unresolved terminations may carry a future-return label")

    end_viol = 0
    for h in cfg.horizons:
        end = pd.to_datetime(targets[f"target_end_date_{int(h)}d"], errors="coerce")
        mask = end.notna() & targets["entry_date"].notna()
        end_viol += int((end.loc[mask] < targets.loc[mask, "entry_date"]).sum())
    add("TARGET_END_NOT_BEFORE_ENTRY", "PASS" if end_viol == 0 else "FAIL", end_viol,
        "0 target end dates before actual entry")

    return_cols = [c for c in targets.columns if c.startswith("fwd_return_")]
    min_return = math.nan
    if return_cols:
        stacked = pd.concat([pd.to_numeric(targets[c], errors="coerce") for c in return_cols], ignore_index=True).dropna()
        min_return = float(stacked.min()) if len(stacked) else math.nan
    floor = float(cfg.policies["return_floor_tolerance"])
    floor_ok = (not np.isfinite(min_return)) or min_return >= floor
    add("SIMPLE_RETURN_FLOOR", "PASS" if floor_ok else "FAIL", min_return,
        f"all simple-return labels >= {floor}")

    target_feature_flags = targets["target_feature_allowed"].fillna(True).astype(bool)
    feature_viol = int(target_feature_flags.sum())
    add("TARGET_OUTPUT_FEATURE_FORBIDDEN", "PASS" if feature_viol == 0 else "FAIL", feature_viol,
        "0 target rows may be feature-allowed")

    gate = pd.DataFrame(rows)
    blocking_fail = gate["blocking"].astype(bool) & gate["status"].eq("FAIL")
    status = "PASS" if not blocking_fail.any() else "FAIL"
    return gate, status


def target_schema(targets: pd.DataFrame, cfg: Phase3Config) -> dict:
    target_cols = [c for c in targets.columns if c not in {"signal_date", "ticker"}]
    return {
        "build": PHASE3_BUILD,
        "keys": ["signal_date", "ticker"],
        "entry_anchor": cfg.entry_anchor,
        "horizons_trading_sessions": list(cfg.horizons),
        "columns": list(targets.columns),
        "target_columns_feature_allowed": False,
        "semantics": {
            "signal_date": "session-close information timestamp from canonical PIT panel",
            "requested_entry_date": "earliest global-market execution date from the PIT panel",
            "entry_date": "first actually observed tradable ticker session on/after requested_entry_date, always strictly after signal_date",
            "entry_total_return_price": "target-only adjusted price at actual entry; never a feature or execution price",
            "entry_execution_close": "raw observable close on actual entry session; future relative to signal and therefore not a feature",
            "fwd_return_Hd": "simple total return from actual entry to H subsequent observed ticker trading sessions, or validated terminal delisting price",
            "mfe_Hd": "maximum favorable excursion in target-price space over the resolved observed-session path",
            "mae_Hd": "maximum adverse excursion in target-price space over the resolved observed-session path",
            "FULL_HORIZON": "H subsequent ticker-observed sessions exist",
            "TERMINAL_DELISTING": "known panel delisting ends the investment path before H ticker sessions",
            "TERMINAL_DELISTING_REPAIRED": "high-confidence Phase 3C target-only delisting overlay validates the terminal investment outcome before H ticker sessions",
            "terminal_resolution_source": "target-only provenance of terminal delisting resolution; never a live feature",
            "RIGHT_CENSORED_SAMPLE_END": "insufficient future ticker sessions because the observed history reaches the sample boundary",
            "UNRESOLVED_TERMINATION": "ticker history ends away from the sample boundary without a validated delisting; blocking data-quality state",
            "cs_rank_pct_Hd": "cross-sectional percentile rank of realized future return on the signal date; target-only",
            "winner_top_decile_Hd": "future-return top-decile label when the contemporaneous labeled cross-section is large enough",
            "winner_top_quintile_Hd": "future-return top-quintile label when the contemporaneous labeled cross-section is large enough",
        },
        "feature_firewall": {
            "feature_allowed": False,
            "rule": "Phase 3 outputs are labels/diagnostics only and must never be joined into live feature generation by date without explicit target isolation.",
        },
        "target_columns": target_cols,
    }


def build_phase3(root: Path) -> dict:
    cfg = load_config(root)
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    phase2c_summary_path = root / cfg.phase2c_summary_path
    phase3c_summary_path = root / cfg.phase3c_summary_path
    overlay_path = root / cfg.terminal_overlay_path
    exclusions_path = root / cfg.research_exclusions_path
    panel_path = root / cfg.panel_path
    layer_path = root / cfg.return_price_layer_path
    for pth in (phase2c_summary_path, phase3c_summary_path, overlay_path, exclusions_path, panel_path, layer_path):
        if not pth.exists():
            raise FileNotFoundError(str(pth))

    with phase2c_summary_path.open("r", encoding="utf-8") as f:
        phase2c_summary = json.load(f)
    validate_phase2c_input(phase2c_summary)
    with phase3c_summary_path.open("r", encoding="utf-8") as f:
        phase3c_summary = json.load(f)
    validate_phase3c_input(phase3c_summary)

    panel = pd.read_parquet(panel_path)
    layer = pd.read_parquet(layer_path)
    terminal_overlay = pd.read_csv(overlay_path, low_memory=False)
    research_exclusions = pd.read_csv(exclusions_path, low_memory=False)
    targets = build_return_targets(
        panel=panel,
        layer=layer,
        horizons=cfg.horizons,
        minimum_cross_section_size=int(cfg.policies["minimum_cross_section_size"]),
        winner_top_decile_cutoff=float(cfg.policies["winner_top_decile_cutoff"]),
        winner_top_quintile_cutoff=float(cfg.policies["winner_top_quintile_cutoff"]),
        max_entry_delay_calendar_days=int(cfg.policies["max_entry_delay_calendar_days"]),
        sample_end_grace_global_sessions=int(cfg.policies["sample_end_grace_global_sessions"]),
        terminal_overlay=terminal_overlay,
        research_exclusions=research_exclusions,
    )
    diag = horizon_diagnostics(targets, cfg.horizons)
    gate, status = evaluate_gate(
        targets, diag, phase2c_summary, phase3c_summary, cfg,
        terminal_overlay=terminal_overlay, research_exclusions=research_exclusions,
    )
    schema = target_schema(targets, cfg)

    output_target = root / cfg.output_targets_path
    output_target.parent.mkdir(parents=True, exist_ok=True)
    targets.to_parquet(output_target, index=False)
    diag.to_csv(outputs / "phase3_horizon_diagnostics.csv", index=False)
    gate.to_csv(outputs / "phase3_gate.csv", index=False)
    with (outputs / "phase3_target_schema.json").open("w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, default=str)

    horizon_summary = {}
    for row in diag.to_dict(orient="records"):
        h = str(int(row["horizon_sessions"]))
        horizon_summary[h] = {
            "resolved_rows": int(row["resolved_rows"]),
            "label_rows": int(row["label_rows"]),
            "resolved_label_coverage": row["resolved_label_coverage"],
            "full_horizon_rows": int(row["full_horizon_rows"]),
            "terminal_delisting_rows": int(row["terminal_delisting_rows"]),
            "repaired_terminal_delisting_rows": int(row["repaired_terminal_delisting_rows"]),
            "right_censored_rows": int(row["right_censored_rows"]),
            "unresolved_termination_rows": int(row["unresolved_termination_rows"]),
            "no_entry_rows": int(row["no_entry_rows"]),
            "mean_return": row["mean_return"],
            "median_return": row["median_return"],
            "q95": row["q95"],
            "q99": row["q99"],
        }

    summary = {
        "status": status,
        "phase": 3,
        "build": PHASE3_BUILD,
        "name": cfg.name,
        "objective": cfg.objective,
        "entry_anchor": cfg.entry_anchor,
        "horizon_semantics": "TICKER_OBSERVED_TRADING_SESSIONS",
        "horizons_trading_sessions": list(cfg.horizons),
        "targets": {
            "rows": int(len(targets)),
            "tickers": int(targets["ticker"].nunique()),
            "first_signal_date": targets["signal_date"].min().strftime("%Y-%m-%d") if len(targets) else None,
            "last_signal_date": targets["signal_date"].max().strftime("%Y-%m-%d") if len(targets) else None,
            "rows_with_requested_execution_date": int(targets["requested_entry_date"].notna().sum()),
            "rows_with_actual_entry_date": int(targets["entry_date"].notna().sum()),
            "rows_with_entry_target_price": int(targets["entry_total_return_price"].notna().sum()),
            "phase3c_excluded_signal_rows": int(targets.attrs.get("phase3c_excluded_signal_rows", 0)),
        },
        "horizon_diagnostics": horizon_summary,
        "gate": gate.to_dict(orient="records"),
        "terminal_repair": {
            "phase3c_status": phase3c_summary.get("status"),
            "overlay_path": cfg.terminal_overlay_path,
            "validated_terminal_overlays": phase3c_summary.get("validated_terminal_overlays"),
            "research_exclusions": phase3c_summary.get("research_exclusions"),
            "research_exclusions_path": cfg.research_exclusions_path,
            "feature_allowed": False,
        },
        "target_firewall": {
            "feature_allowed": False,
            "target_price_column": "target_total_return_price",
            "targets_file": cfg.output_targets_path,
            "principle": "Future labels and terminal-outcome metadata remain physically separate from the PIT feature panel.",
        },
        "next_gate": "If PASS: analyze target stability/distributions and build a leakage-free feature library before fitting any alpha model.",
    }
    with (outputs / "phase3_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    return summary
