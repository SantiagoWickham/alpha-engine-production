from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd

PHASE3B_BUILD = "V1_2026-09-12"


def _dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")


def _read_csv_if(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def _norm_symbol(s: pd.Series) -> pd.Series:
    return s.astype(str).str.upper().str.strip().str.replace(".", "-", regex=False)


def _prep_listing(df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["ticker", f"{source}_status", f"{source}_delisting_date", f"{source}_name"])
    sym = next((c for c in ["symbol", "ticker"] if c in df.columns), None)
    if sym is None:
        return pd.DataFrame(columns=["ticker", f"{source}_status", f"{source}_delisting_date", f"{source}_name"])
    out = pd.DataFrame({"ticker": _norm_symbol(df[sym])})
    status_col = next((c for c in ["status", "source_state"] if c in df.columns), None)
    delist_col = next((c for c in ["delisting_date", "delistingDate"] if c in df.columns), None)
    name_col = next((c for c in ["name", "companyName"] if c in df.columns), None)
    out[f"{source}_status"] = df[status_col].astype(str) if status_col else None
    out[f"{source}_delisting_date"] = _dt(df[delist_col]) if delist_col else pd.NaT
    out[f"{source}_name"] = df[name_col].astype(str) if name_col else None
    # Prefer records carrying an actual delisting date, then last record.
    out["_has_d"] = out[f"{source}_delisting_date"].notna().astype(int)
    out = out.sort_values(["ticker", "_has_d"]).drop_duplicates("ticker", keep="last").drop(columns="_has_d")
    return out


def _cache_delist_manifest(directory: Path) -> pd.DataFrame:
    rows = []
    if not directory.exists():
        return pd.DataFrame(columns=["ticker", "cache_filename_delisting_date", "cache_has_parquet", "cache_files"])
    pat = re.compile(r"^(?P<ticker>.+?)__(?P<start>\d{4}-\d{2}-\d{2})__(?P<end>\d{4}-\d{2}-\d{2})")
    for p in directory.iterdir():
        if not p.is_file():
            continue
        m = pat.match(p.name)
        if not m:
            continue
        rows.append({
            "ticker": m.group("ticker").upper().replace(".", "-"),
            "cache_filename_delisting_date": pd.Timestamp(m.group("end")),
            "cache_has_parquet": p.suffix.lower() == ".parquet",
            "cache_file": p.name,
        })
    if not rows:
        return pd.DataFrame(columns=["ticker", "cache_filename_delisting_date", "cache_has_parquet", "cache_files"])
    x = pd.DataFrame(rows)
    agg = x.groupby("ticker", as_index=False).agg(
        cache_filename_delisting_date=("cache_filename_delisting_date", "max"),
        cache_has_parquet=("cache_has_parquet", "max"),
        cache_files=("cache_file", lambda s: " | ".join(sorted(set(map(str, s)))[:5])),
    )
    return agg


def unresolved_counts(targets: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    rows = []
    for ticker, g in targets.groupby("ticker", sort=True):
        rec = {"ticker": str(ticker).upper().replace(".", "-")}
        any_unres = False
        first_dates = []
        last_dates = []
        total = 0
        for h in horizons:
            col = f"target_status_{h}d"
            if col not in g.columns:
                continue
            m = g[col].astype(str).eq("UNRESOLVED_TERMINATION")
            n = int(m.sum())
            rec[f"unresolved_{h}d"] = n
            total += n
            if n:
                any_unres = True
                d = pd.to_datetime(g.loc[m, "signal_date"], errors="coerce")
                if d.notna().any():
                    first_dates.append(d.min())
                    last_dates.append(d.max())
        if any_unres:
            rec["unresolved_total_across_horizons"] = total
            rec["first_unresolved_signal"] = min(first_dates) if first_dates else pd.NaT
            rec["last_unresolved_signal"] = max(last_dates) if last_dates else pd.NaT
            rows.append(rec)
    return pd.DataFrame(rows)


def classify(row: pd.Series, sample_end: pd.Timestamp, grace_days: int) -> tuple[str, str]:
    terminal = row.get("return_price_last_date")
    lifecycle_d = row.get("lifecycle_delisting_date")
    av_d = row.get("av_delisted_delisting_date")
    cache_d = row.get("cache_filename_delisting_date")
    av_active_status = str(row.get("av_active_status", "")).lower()
    lifecycle_status = str(row.get("lifecycle_status", "")).lower()

    delist_candidates = [x for x in [lifecycle_d, av_d, cache_d] if pd.notna(x)]
    best_delist = min(delist_candidates, key=lambda d: abs((pd.Timestamp(d) - pd.Timestamp(terminal)).days)) if delist_candidates and pd.notna(terminal) else (delist_candidates[0] if delist_candidates else pd.NaT)
    if pd.notna(best_delist):
        gap = abs((pd.Timestamp(best_delist) - pd.Timestamp(terminal)).days) if pd.notna(terminal) else 999999
        if gap <= 14:
            return "CONFIRMED_OR_NEAR_DELISTING_METADATA_GAP", f"delisting evidence within {gap} calendar days of terminal price"
        return "DELISTING_DATE_PRICE_GAP", f"delisting evidence exists but terminal price differs by {gap} calendar days"

    if pd.notna(terminal) and (sample_end - pd.Timestamp(terminal)).days <= grace_days:
        return "SAMPLE_END_CENSORING_CANDIDATE", "history reaches configured sample-end grace window"

    if "active" in av_active_status or "active" in lifecycle_status:
        return "ACTIVE_PRICE_HISTORY_GAP", "ticker appears active but adjusted-price history stops before sample end"

    if bool(row.get("cache_has_parquet", False)):
        return "DELISTED_CACHE_WITHOUT_LIFECYCLE_DATE", "delisted-price parquet exists but no authoritative lifecycle date was found"

    return "UNCLASSIFIED_EARLY_TERMINATION", "no active or delisting metadata explains the early price-history end"


def build_phase3b(root: Path) -> dict:
    cfg_path = root / "config" / "phase3b.toml"
    with cfg_path.open("rb") as f:
        cfg = tomllib.load(f)["phase3b"]
    horizons = [int(x) for x in cfg["horizons"]]
    pol = cfg["policies"]

    paths = {k: root / cfg[k] for k in [
        "phase3_targets_path", "phase3_summary_path", "canonical_panel_path", "return_price_layer_path",
        "listing_lifecycle_path", "alpha_vantage_active_path", "alpha_vantage_delisted_path", "delisted_price_dir",
    ]}
    for k in ["phase3_targets_path", "phase3_summary_path", "canonical_panel_path", "return_price_layer_path"]:
        if not paths[k].exists():
            raise FileNotFoundError(paths[k])

    phase3_summary = json.loads(paths["phase3_summary_path"].read_text(encoding="utf-8"))
    targets = pd.read_parquet(paths["phase3_targets_path"])
    panel = pd.read_parquet(paths["canonical_panel_path"])
    layer = pd.read_parquet(paths["return_price_layer_path"])

    targets["signal_date"] = _dt(targets["signal_date"])
    panel["date"] = _dt(panel["date"])
    layer["date"] = _dt(layer["date"])
    targets["ticker"] = _norm_symbol(targets["ticker"])
    panel["ticker"] = _norm_symbol(panel["ticker"])
    layer["ticker"] = _norm_symbol(layer["ticker"])

    u = unresolved_counts(targets, horizons)
    if u.empty:
        outputs = root / "outputs"; outputs.mkdir(exist_ok=True)
        pd.DataFrame().to_csv(outputs / "phase3b_unresolved_tickers.csv", index=False)
        summary = {"status":"PASS", "phase":"3B", "build":PHASE3B_BUILD, "unresolved_tickers":0, "message":"No unresolved terminations detected."}
        (outputs / "phase3b_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    # Per-ticker observed history facts.
    layer_stats = layer.groupby("ticker", as_index=False).agg(
        return_price_first_date=("date", "min"),
        return_price_last_date=("date", "max"),
        return_price_rows=("date", "size"),
        target_price_source=("target_price_source", lambda s: " | ".join(sorted(set(map(str, s.dropna())))[:5])),
    )
    p_agg_map = {"panel_first_date": ("date", "min"), "panel_last_date": ("date", "max"), "panel_rows": ("date", "size")}
    if "delisting_date" in panel.columns:
        panel["delisting_date"] = _dt(panel["delisting_date"])
        p_agg_map["panel_delisting_date"] = ("delisting_date", "max")
    if "source_state" in panel.columns:
        p_agg_map["panel_source_state"] = ("source_state", lambda s: " | ".join(sorted(set(map(str, s.dropna())))[:5]))
    panel_stats = panel.groupby("ticker", as_index=False).agg(**p_agg_map)

    life = _prep_listing(_read_csv_if(paths["listing_lifecycle_path"]), "lifecycle")
    av_active = _prep_listing(_read_csv_if(paths["alpha_vantage_active_path"]), "av_active")
    av_delisted = _prep_listing(_read_csv_if(paths["alpha_vantage_delisted_path"]), "av_delisted")
    cache = _cache_delist_manifest(paths["delisted_price_dir"])

    audit = u.merge(layer_stats, on="ticker", how="left").merge(panel_stats, on="ticker", how="left")
    audit = audit.merge(life, on="ticker", how="left").merge(av_active, on="ticker", how="left").merge(av_delisted, on="ticker", how="left").merge(cache, on="ticker", how="left")

    sample_end = pd.Timestamp(panel["date"].max()).normalize()
    audit["calendar_days_before_sample_end"] = (sample_end - pd.to_datetime(audit["return_price_last_date"])).dt.days
    classifications = audit.apply(lambda r: classify(r, sample_end, int(pol["sample_end_grace_calendar_days"])), axis=1)
    audit["classification"] = [x[0] for x in classifications]
    audit["reason"] = [x[1] for x in classifications]
    audit["repair_priority"] = audit["classification"].map({
        "ACTIVE_PRICE_HISTORY_GAP": 1,
        "DELISTING_DATE_PRICE_GAP": 1,
        "UNCLASSIFIED_EARLY_TERMINATION": 1,
        "DELISTED_CACHE_WITHOUT_LIFECYCLE_DATE": 2,
        "CONFIRMED_OR_NEAR_DELISTING_METADATA_GAP": 2,
        "SAMPLE_END_CENSORING_CANDIDATE": 3,
    }).fillna(9).astype(int)
    audit = audit.sort_values(["repair_priority", "unresolved_total_across_horizons", "ticker"], ascending=[True, False, True])

    # Sample unresolved rows for inspection, bounded.
    samples = []
    for h in horizons:
        col = f"target_status_{h}d"
        if col not in targets.columns:
            continue
        m = targets[col].astype(str).eq("UNRESOLVED_TERMINATION")
        if not m.any():
            continue
        cols = [c for c in ["signal_date","ticker","requested_entry_date","entry_date",col,f"target_end_date_{h}d"] if c in targets.columns]
        x = targets.loc[m, cols].copy()
        x["horizon_sessions"] = h
        samples.append(x)
    sample = pd.concat(samples, ignore_index=True) if samples else pd.DataFrame()
    if not sample.empty:
        sample = sample.sort_values(["ticker", "signal_date", "horizon_sessions"]).head(int(pol["max_sample_rows"]))

    # Summaries / repair plan.
    class_summary = audit.groupby("classification", dropna=False).agg(
        tickers=("ticker", "nunique"),
        unresolved_total=("unresolved_total_across_horizons", "sum"),
        earliest_terminal=("return_price_last_date", "min"),
        latest_terminal=("return_price_last_date", "max"),
    ).reset_index().sort_values(["unresolved_total","tickers"], ascending=False)

    repair = audit[[c for c in [
        "ticker","classification","repair_priority","reason","return_price_last_date","calendar_days_before_sample_end",
        "lifecycle_status","lifecycle_delisting_date","av_active_status","av_delisted_status","av_delisted_delisting_date",
        "cache_filename_delisting_date","cache_has_parquet","target_price_source","unresolved_total_across_horizons"
    ] if c in audit.columns]].copy()

    blocking_classes = {"ACTIVE_PRICE_HISTORY_GAP", "DELISTING_DATE_PRICE_GAP", "UNCLASSIFIED_EARLY_TERMINATION", "DELISTED_CACHE_WITHOUT_LIFECYCLE_DATE", "CONFIRMED_OR_NEAR_DELISTING_METADATA_GAP"}
    blocking_tickers = int(audit["classification"].isin(blocking_classes).sum())

    outputs = root / "outputs"; outputs.mkdir(exist_ok=True)
    audit.to_csv(outputs / "phase3b_unresolved_tickers.csv", index=False)
    class_summary.to_csv(outputs / "phase3b_classification_summary.csv", index=False)
    repair.to_csv(outputs / "phase3b_repair_plan.csv", index=False)
    sample.to_csv(outputs / "phase3b_unresolved_sample.csv", index=False)

    summary = {
        "status": "PASS_AUDIT_COMPLETE",
        "phase": "3B",
        "build": PHASE3B_BUILD,
        "name": cfg["name"],
        "objective": cfg["objective"],
        "phase3_input_status": phase3_summary.get("status"),
        "sample_end": str(sample_end.date()),
        "unresolved_tickers": int(audit["ticker"].nunique()),
        "blocking_tickers_requiring_repair": blocking_tickers,
        "classification_counts": {str(r["classification"]): int(r["tickers"]) for _, r in class_summary.iterrows()},
        "unresolved_rows_by_horizon": {str(h): int((targets.get(f"target_status_{h}d", pd.Series(index=targets.index, dtype=object)).astype(str) == "UNRESOLVED_TERMINATION").sum()) for h in horizons},
        "next_gate": "Repair termination metadata/price histories by classification, rebuild Phase 3, and require zero UNRESOLVED_TERMINATION before alpha research.",
    }
    (outputs / "phase3b_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
