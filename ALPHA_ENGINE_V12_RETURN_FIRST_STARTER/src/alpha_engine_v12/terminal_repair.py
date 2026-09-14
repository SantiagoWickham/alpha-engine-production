from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

PHASE3C_BUILD = "V1_2026-09-12"


def _dt_scalar(x):
    if pd.isna(x):
        return pd.NaT
    return pd.Timestamp(x).tz_localize(None).normalize() if pd.Timestamp(x).tzinfo else pd.Timestamp(x).normalize()


def _norm_name(x: object) -> str:
    if x is None or pd.isna(x):
        return ""
    s = str(x).upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    stop = {"INC", "CORP", "CORPORATION", "LTD", "LIMITED", "PLC", "SA", "AG", "NV", "CO", "COMPANY", "GROUP", "HOLDINGS", "HOLDING", "CLASS", "A", "B"}
    return " ".join(t for t in s.split() if t not in stop)


def _truthy(x: object) -> bool:
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if x is None or pd.isna(x):
        return False
    return str(x).strip().lower() in {"1", "true", "yes", "y"}


def _consensus_date(dates: list[pd.Timestamp], terminal: pd.Timestamp) -> pd.Timestamp | pd.NaT:
    vals = [pd.Timestamp(x).normalize() for x in dates if pd.notna(x)]
    if not vals:
        return pd.NaT
    counts = Counter(vals)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], abs((kv[0] - terminal).days), kv[0]))
    return ranked[0][0]


def build_terminal_overlay(
    audit: pd.DataFrame,
    policies: dict[str, object],
    manual_resolutions: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    required = [
        "ticker", "classification", "return_price_last_date", "lifecycle_status", "lifecycle_delisting_date",
        "lifecycle_name", "av_delisted_status", "av_delisted_delisting_date", "av_delisted_name",
        "cache_filename_delisting_date", "cache_has_parquet",
    ]
    missing = [c for c in required if c not in audit.columns]
    if missing:
        raise ValueError(f"Phase 3B unresolved audit missing columns: {missing}")

    required_class = str(policies["required_classification"])
    min_sources = int(policies["min_evidence_sources"])
    max_gap = int(policies["max_terminal_gap_calendar_days"])
    req_life = bool(policies["require_lifecycle_delisted"])
    req_av = bool(policies["require_av_delisted"])
    req_cache = bool(policies["require_cache_parquet"])
    req_name = bool(policies["require_historical_name_identity"])

    manual = manual_resolutions.copy() if manual_resolutions is not None else pd.DataFrame()
    excluded_tickers: set[str] = set()
    exclusion_rows: list[dict] = []
    if not manual.empty:
        req_manual = ["ticker", "resolution_type", "effective_start_date", "effective_end_date", "security_type", "evidence_source", "evidence_note", "target_only", "feature_allowed"]
        missing_manual = [c for c in req_manual if c not in manual.columns]
        if missing_manual:
            raise ValueError(f"Phase 3C manual resolutions missing columns: {missing_manual}")
        for _, m in manual.iterrows():
            ticker = str(m["ticker"]).upper().replace(".", "-").strip()
            if str(m["resolution_type"]) != "EXCLUDE_NON_EQUITY_SECURITY":
                raise ValueError(f"Unsupported manual resolution for {ticker}: {m['resolution_type']}")
            target_only = _truthy(m.get("target_only"))
            feature_allowed = _truthy(m.get("feature_allowed"))
            if not target_only or feature_allowed:
                raise ValueError(f"Manual research exclusion {ticker} must be target/data-quality only and feature-forbidden")
            excluded_tickers.add(ticker)
            exclusion_rows.append({
                "ticker": ticker,
                "effective_start_date": _dt_scalar(m["effective_start_date"]),
                "effective_end_date": _dt_scalar(m["effective_end_date"]),
                "resolution_type": str(m["resolution_type"]),
                "security_type": str(m["security_type"]),
                "evidence_source": str(m["evidence_source"]),
                "evidence_note": str(m["evidence_note"]),
                "evidence_url": m.get("evidence_url"),
                "research_eligible": False,
                "target_only": True,
                "feature_allowed": False,
            })

    rows: list[dict] = []
    for _, r in audit.iterrows():
        ticker = str(r["ticker"]).upper().replace(".", "-").strip()
        if ticker in excluded_tickers:
            continue
        terminal = _dt_scalar(r["return_price_last_date"])
        evidence_fields = [
            ("LIFECYCLE", "lifecycle_delisting_date"),
            ("ALPHA_VANTAGE_DELISTED", "av_delisted_delisting_date"),
            ("DELISTED_CACHE_FILENAME", "cache_filename_delisting_date"),
            ("PANEL", "panel_delisting_date"),
        ]
        evidence_dates: list[pd.Timestamp] = []
        evidence_sources: list[str] = []
        for source, col in evidence_fields:
            if col not in audit.columns:
                continue
            d = _dt_scalar(r.get(col))
            if pd.notna(d) and pd.notna(terminal) and abs((d - terminal).days) <= max_gap:
                evidence_dates.append(d)
                evidence_sources.append(source)

        classification_ok = str(r.get("classification")) == required_class
        lifecycle_ok = str(r.get("lifecycle_status", "")).strip().lower() == "delisted" if req_life else True
        av_ok = str(r.get("av_delisted_status", "")).strip().lower() == "delisted" if req_av else True
        cache_ok = _truthy(r.get("cache_has_parquet")) if req_cache else True
        life_name = _norm_name(r.get("lifecycle_name"))
        av_name = _norm_name(r.get("av_delisted_name"))
        name_ok = bool(life_name and av_name and life_name == av_name) if req_name else True
        evidence_ok = len(evidence_sources) >= min_sources
        terminal_ok = pd.notna(terminal)
        validated = bool(classification_ok and lifecycle_ok and av_ok and cache_ok and name_ok and evidence_ok and terminal_ok)
        consensus = _consensus_date(evidence_dates, terminal) if terminal_ok else pd.NaT

        failures = []
        for label, ok in [
            ("classification", classification_ok), ("lifecycle_delisted", lifecycle_ok),
            ("av_delisted", av_ok), ("cache_parquet", cache_ok),
            ("historical_name_identity", name_ok), ("evidence_sources", evidence_ok), ("terminal_date", terminal_ok),
        ]:
            if not ok:
                failures.append(label)

        rows.append({
            "ticker": ticker,
            "terminal_price_date": terminal,
            "consensus_delisting_date": consensus,
            "evidence_count": int(len(evidence_sources)),
            "evidence_sources": " | ".join(evidence_sources),
            "classification": str(r.get("classification")),
            "lifecycle_name": r.get("lifecycle_name"),
            "av_delisted_name": r.get("av_delisted_name"),
            "historical_name_identity_match": bool(name_ok),
            "max_allowed_gap_calendar_days": max_gap,
            "overlay_validated": validated,
            "validation_failures": " | ".join(failures),
            "target_only": True,
            "feature_allowed": False,
            "repair_semantics": "LAST_OBSERVED_VALIDATED_TOTAL_RETURN_PRICE_IS_TERMINAL_OUTCOME",
        })

    overlay_columns = [
        "ticker", "terminal_price_date", "consensus_delisting_date", "evidence_count", "evidence_sources",
        "classification", "lifecycle_name", "av_delisted_name", "historical_name_identity_match",
        "max_allowed_gap_calendar_days", "overlay_validated", "validation_failures", "target_only",
        "feature_allowed", "repair_semantics",
    ]
    overlay = pd.DataFrame(rows, columns=overlay_columns)
    if not overlay.empty:
        overlay = overlay.sort_values("ticker").reset_index(drop=True)
    gate_rows: list[dict] = []

    def add(test: str, ok: bool, value: object, rule: str, blocking: bool = True) -> None:
        gate_rows.append({"test": test, "status": "PASS" if ok else "FAIL", "blocking": blocking, "value": value, "rule": rule})

    add("UNIQUE_TICKERS", not overlay.duplicated("ticker").any(), int(overlay.duplicated("ticker").sum()), "0 duplicate ticker overlays")
    add("ALL_CLASSIFICATIONS_ELIGIBLE", bool(overlay["classification"].eq(required_class).all()), int((~overlay["classification"].eq(required_class)).sum()), f"all rows classification == {required_class}")
    add("MINIMUM_INDEPENDENT_EVIDENCE", bool((overlay["evidence_count"] >= min_sources).all()), int((overlay["evidence_count"] < min_sources).sum()), f"every overlay has >= {min_sources} independent date sources within {max_gap} days")
    add("HISTORICAL_NAME_IDENTITY", bool(overlay["historical_name_identity_match"].all()), int((~overlay["historical_name_identity_match"]).sum()), "historical lifecycle name must match Alpha Vantage delisted name")
    add("ALL_OVERLAYS_VALIDATED", bool(overlay["overlay_validated"].all()), int((~overlay["overlay_validated"]).sum()), "0 unvalidated terminal overlays")
    add("OVERLAY_TARGET_ONLY", bool(overlay["target_only"].all()), int((~overlay["target_only"]).sum()), "all overlay rows are target-only")
    add("OVERLAY_FEATURE_FORBIDDEN", bool((~overlay["feature_allowed"].astype(bool)).all()), int(overlay["feature_allowed"].astype(bool).sum()), "0 overlay rows feature-allowed")

    exclusions = pd.DataFrame(exclusion_rows)
    if not exclusions.empty:
        add("RESEARCH_EXCLUSIONS_FEATURE_FORBIDDEN", bool((~exclusions["feature_allowed"].astype(bool)).all()), int(exclusions["feature_allowed"].astype(bool).sum()), "0 research exclusions feature-allowed")
        valid_windows = exclusions["effective_start_date"].notna() & exclusions["effective_end_date"].notna() & (exclusions["effective_end_date"] >= exclusions["effective_start_date"])
        add("RESEARCH_EXCLUSION_WINDOWS_VALID", bool(valid_windows.all()), int((~valid_windows).sum()), "all manual exclusion windows have valid start/end dates")
    gate = pd.DataFrame(gate_rows)
    blocking_fail = gate["blocking"].astype(bool) & gate["status"].eq("FAIL")
    status = "PASS" if not blocking_fail.any() else "FAIL"
    return overlay, exclusions, gate, status


def build_phase3c(root: Path) -> dict:
    cfg_path = root / "config" / "phase3c.toml"
    with cfg_path.open("rb") as f:
        cfg = tomllib.load(f)["phase3c"]
    policies = dict(cfg["policies"])

    phase3b_summary_path = root / cfg["phase3b_summary_path"]
    audit_path = root / cfg["unresolved_tickers_path"]
    if not phase3b_summary_path.exists():
        raise FileNotFoundError(phase3b_summary_path)
    if not audit_path.exists():
        raise FileNotFoundError(audit_path)

    phase3b_summary = json.loads(phase3b_summary_path.read_text(encoding="utf-8"))
    if phase3b_summary.get("status") != "PASS_AUDIT_COMPLETE":
        raise RuntimeError("Phase 3B audit must be complete before Phase 3C repair")

    audit = pd.read_csv(audit_path, low_memory=False)
    manual_path = root / cfg["manual_resolutions_path"]
    manual = pd.read_csv(manual_path, low_memory=False) if manual_path.exists() else pd.DataFrame()
    overlay, exclusions, gate, status = build_terminal_overlay(audit, policies, manual_resolutions=manual)

    expected = int(phase3b_summary.get("unresolved_tickers", -1))
    resolved_tickers = set(overlay["ticker"].astype(str)) | (set(exclusions["ticker"].astype(str)) if not exclusions.empty else set())
    count_match = expected == len(resolved_tickers)
    extra = pd.DataFrame([{
        "test": "OVERLAY_COVERS_PHASE3B_UNRESOLVED_TICKERS",
        "status": "PASS" if count_match else "FAIL",
        "blocking": True,
        "value": len(resolved_tickers),
        "rule": f"terminal overlays + research exclusions must equal Phase 3B unresolved_tickers={expected}",
    }])
    gate = pd.concat([extra, gate], ignore_index=True)
    if not count_match:
        status = "FAIL"

    outputs = root / "outputs"
    outputs.mkdir(exist_ok=True)
    overlay_path = root / cfg["terminal_overlay_path"]
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.to_csv(overlay_path, index=False)
    exclusions_path = root / cfg["research_exclusions_path"]
    exclusions_path.parent.mkdir(parents=True, exist_ok=True)
    exclusions.to_csv(exclusions_path, index=False)
    gate.to_csv(outputs / "phase3c_gate.csv", index=False)
    evidence_audit = overlay.copy()
    if not evidence_audit.empty:
        evidence_audit["resolution_type"] = "TERMINAL_DELISTING_OVERLAY"
    if not exclusions.empty:
        ex_audit = exclusions.copy()
        ex_audit["overlay_validated"] = True
        evidence_audit = pd.concat([evidence_audit, ex_audit], ignore_index=True, sort=False)
    evidence_audit.to_csv(outputs / "phase3c_evidence_audit.csv", index=False)

    summary = {
        "status": status,
        "phase": "3C",
        "build": PHASE3C_BUILD,
        "name": cfg["name"],
        "objective": cfg["objective"],
        "phase3b_input_status": phase3b_summary.get("status"),
        "phase3b_unresolved_tickers": expected,
        "terminal_overlays": int(len(overlay)),
        "validated_terminal_overlays": int(overlay["overlay_validated"].sum()),
        "research_exclusions": int(len(exclusions)),
        "resolved_unresolved_tickers": int(len(resolved_tickers)),
        "minimum_evidence_sources": int(policies["min_evidence_sources"]),
        "max_terminal_gap_calendar_days": int(policies["max_terminal_gap_calendar_days"]),
        "evidence_count_distribution": {str(k): int(v) for k, v in overlay["evidence_count"].value_counts().sort_index().items()},
        "historical_name_identity_failures": int((~overlay["historical_name_identity_match"]).sum()),
        "feature_allowed": False,
        "terminal_overlay_path": cfg["terminal_overlay_path"],
        "research_exclusions_path": cfg["research_exclusions_path"],
        "gate": gate.to_dict(orient="records"),
        "next_gate": "Rebuild Phase 3 with the validated target-only terminal overlay and require zero UNRESOLVED_TERMINATION.",
    }
    (outputs / "phase3c_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
