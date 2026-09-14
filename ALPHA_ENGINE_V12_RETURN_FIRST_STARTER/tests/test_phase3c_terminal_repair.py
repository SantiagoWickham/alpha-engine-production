import numpy as np
import pandas as pd

from alpha_engine_v12.terminal_repair import build_terminal_overlay
from alpha_engine_v12.return_targets import build_return_targets, horizon_diagnostics


def _audit_row(**overrides):
    row = {
        "ticker": "AAA",
        "classification": "CONFIRMED_OR_NEAR_DELISTING_METADATA_GAP",
        "return_price_last_date": "2024-01-10",
        "lifecycle_status": "Delisted",
        "lifecycle_delisting_date": "2024-01-08",
        "lifecycle_name": "Alpha Example Inc",
        "av_delisted_status": "Delisted",
        "av_delisted_delisting_date": "2024-01-08",
        "av_delisted_name": "Alpha Example Inc",
        "cache_filename_delisting_date": "2024-01-08",
        "cache_has_parquet": True,
        "panel_delisting_date": pd.NaT,
    }
    row.update(overrides)
    return row


def _policies():
    return {
        "required_classification": "CONFIRMED_OR_NEAR_DELISTING_METADATA_GAP",
        "min_evidence_sources": 3,
        "max_terminal_gap_calendar_days": 4,
        "require_lifecycle_delisted": True,
        "require_av_delisted": True,
        "require_cache_parquet": True,
        "require_historical_name_identity": True,
    }


def test_overlay_accepts_three_independent_sources_and_matching_identity():
    overlay, exclusions, gate, status = build_terminal_overlay(pd.DataFrame([_audit_row()]), _policies())
    assert status == "PASS"
    assert overlay.loc[0, "overlay_validated"]
    assert overlay.loc[0, "evidence_count"] == 3
    assert not overlay.loc[0, "feature_allowed"]
    assert set(gate["status"]) == {"PASS"}


def test_overlay_rejects_insufficient_evidence():
    r = _audit_row(av_delisted_delisting_date=pd.NaT, cache_filename_delisting_date=pd.NaT)
    overlay, exclusions, gate, status = build_terminal_overlay(pd.DataFrame([r]), _policies())
    assert status == "FAIL"
    assert not overlay.loc[0, "overlay_validated"]
    assert (gate.loc[gate.test == "MINIMUM_INDEPENDENT_EVIDENCE", "status"].iloc[0] == "FAIL")


def test_overlay_rejects_historical_name_mismatch_even_if_ticker_reused():
    r = _audit_row(av_delisted_name="Different Historical Company")
    overlay, exclusions, gate, status = build_terminal_overlay(pd.DataFrame([r]), _policies())
    assert status == "FAIL"
    assert not overlay.loc[0, "historical_name_identity_match"]


def test_manual_non_equity_resolution_excludes_instead_of_terminalizing():
    audit = pd.DataFrame([_audit_row(
        ticker="ABXL", lifecycle_name=pd.NA, av_delisted_name=pd.NA,
        return_price_last_date="2026-01-30", lifecycle_delisting_date="2026-01-27",
        av_delisted_delisting_date="2026-01-27", cache_filename_delisting_date="2026-01-27",
    )])
    manual = pd.DataFrame([{
        "ticker": "ABXL", "resolution_type": "EXCLUDE_NON_EQUITY_SECURITY",
        "effective_start_date": "2025-12-26", "effective_end_date": "2026-01-30",
        "security_type": "SENIOR_NOTE", "evidence_source": "SEC", "evidence_note": "not common equity",
        "target_only": True, "feature_allowed": False,
    }])
    overlay, exclusions, gate, status = build_terminal_overlay(audit, _policies(), manual_resolutions=manual)
    assert status == "PASS"
    assert overlay.empty
    assert list(exclusions["ticker"]) == ["ABXL"]
    assert not exclusions["research_eligible"].any()


def _panel_layer_for_terminal():
    sessions = pd.bdate_range("2024-01-02", periods=12)
    aaa_dates = sessions[:5]
    p_rows, l_rows = [], []
    for i, d in enumerate(aaa_dates):
        p_rows.append({
            "date": d, "ticker": "AAA", "close": 100.0 + i, "research_eligible": True,
            "earliest_execution_date": sessions[i + 1] if i + 1 < len(sessions) else pd.NaT,
            "delisting_date": pd.NaT,
        })
        l_rows.append({
            "date": d, "ticker": "AAA", "target_total_return_price": 100.0 + i,
            "target_price_source": "TEST", "target_price_feature_allowed": False,
        })
    # Calendar carrier extends global sample past AAA termination.
    for i, d in enumerate(sessions):
        p_rows.append({
            "date": d, "ticker": "CAL", "close": 200.0 + i, "research_eligible": False,
            "earliest_execution_date": sessions[i + 1] if i + 1 < len(sessions) else pd.NaT,
            "delisting_date": pd.NaT,
        })
        l_rows.append({
            "date": d, "ticker": "CAL", "target_total_return_price": 200.0 + i,
            "target_price_source": "TEST", "target_price_feature_allowed": False,
        })
    return sessions, pd.DataFrame(p_rows), pd.DataFrame(l_rows)


def test_validated_overlay_converts_only_terminal_outcome_not_features():
    sessions, panel, layer = _panel_layer_for_terminal()
    overlay = pd.DataFrame([{
        "ticker": "AAA",
        "terminal_price_date": sessions[4],
        "consensus_delisting_date": sessions[3],
        "evidence_count": 3,
        "overlay_validated": True,
        "target_only": True,
        "feature_allowed": False,
    }])
    out = build_return_targets(panel, layer, (10,), minimum_cross_section_size=1, sample_end_grace_global_sessions=1, terminal_overlay=overlay)
    r = out[(out.ticker == "AAA") & (out.signal_date == sessions[0])].iloc[0]
    assert r["target_status_10d"] == "TERMINAL_DELISTING_REPAIRED"
    assert r["target_end_date_10d"] == sessions[4]
    assert pd.notna(r["fwd_return_10d"])
    assert r["terminal_resolution_source"] == "PHASE3C_VALIDATED_DELISTING_OVERLAY"
    assert not r["target_feature_allowed"]
    d = horizon_diagnostics(out, (10,)).iloc[0]
    assert d["unresolved_termination_rows"] == 0
    assert d["repaired_terminal_delisting_rows"] >= 1


def test_without_overlay_unknown_early_termination_still_blocks():
    sessions, panel, layer = _panel_layer_for_terminal()
    out = build_return_targets(panel, layer, (10,), minimum_cross_section_size=1, sample_end_grace_global_sessions=1)
    r = out[(out.ticker == "AAA") & (out.signal_date == sessions[0])].iloc[0]
    assert r["target_status_10d"] == "UNRESOLVED_TERMINATION"
    assert pd.isna(r["fwd_return_10d"])


def test_research_exclusion_removes_only_contaminated_window():
    sessions, panel, layer = _panel_layer_for_terminal()
    exclusions = pd.DataFrame([{
        "ticker": "AAA", "effective_start_date": sessions[0], "effective_end_date": sessions[1],
        "research_eligible": False, "feature_allowed": False,
    }])
    out = build_return_targets(panel, layer, (1,), minimum_cross_section_size=1, research_exclusions=exclusions)
    aaa = out[out["ticker"] == "AAA"]
    assert len(aaa) > 0
    assert (aaa["signal_date"] > sessions[1]).all()
