import numpy as np
import pandas as pd

from alpha_engine_v12.return_targets import build_return_targets, horizon_diagnostics


def _panel_layer(sessions, ticker_dates, ticker="AAA", delisting_date=pd.NaT, eligible=True):
    panel_rows = []
    layer_rows = []
    ticker_dates = pd.DatetimeIndex(ticker_dates)
    px = 100.0 + np.arange(len(ticker_dates), dtype=float)
    for i, d in enumerate(ticker_dates):
        next_global = sessions[sessions.get_loc(d) + 1] if sessions.get_loc(d) + 1 < len(sessions) else pd.NaT
        panel_rows.append({
            "date": d,
            "ticker": ticker,
            "close": px[i],
            "research_eligible": eligible,
            "earliest_execution_date": next_global,
            "delisting_date": delisting_date,
        })
        layer_rows.append({
            "date": d,
            "ticker": ticker,
            "target_total_return_price": px[i],
            "target_price_source": "TEST",
            "target_price_feature_allowed": False,
        })
    return pd.DataFrame(panel_rows), pd.DataFrame(layer_rows)


def test_entry_uses_first_actual_tradable_session_after_requested_date():
    sessions = pd.bdate_range("2024-01-02", periods=7)
    ticker_dates = sessions[[0, 2, 3, 4, 5, 6]]  # missing global session 1
    panel, layer = _panel_layer(sessions, ticker_dates)
    # Add calendar carrier so global session 1 exists in panel.
    carrier, carrier_layer = _panel_layer(sessions, sessions, ticker="CAL", eligible=False)
    panel = pd.concat([panel, carrier], ignore_index=True)
    layer = pd.concat([layer, carrier_layer], ignore_index=True)
    out = build_return_targets(panel, layer, (1,), minimum_cross_section_size=1)
    r = out[(out.ticker == "AAA") & (out.signal_date == sessions[0])].iloc[0]
    assert r["requested_entry_date"] == sessions[1]
    assert r["entry_date"] == sessions[2]
    assert r["entry_delay_calendar_days"] >= 1
    assert r["target_end_date_1d"] == sessions[3]


def test_horizon_counts_ticker_observed_sessions_not_global_dates():
    sessions = pd.bdate_range("2024-01-02", periods=8)
    ticker_dates = sessions[[0, 1, 3, 5, 6, 7]]
    panel, layer = _panel_layer(sessions, ticker_dates)
    carrier, carrier_layer = _panel_layer(sessions, sessions, ticker="CAL", eligible=False)
    panel = pd.concat([panel, carrier], ignore_index=True)
    layer = pd.concat([layer, carrier_layer], ignore_index=True)
    out = build_return_targets(panel, layer, (2,), minimum_cross_section_size=1)
    r = out[(out.ticker == "AAA") & (out.signal_date == sessions[0])].iloc[0]
    # Entry is sessions[1]; two AAA-observed sessions later is sessions[5].
    assert r["entry_date"] == sessions[1]
    assert r["target_end_date_2d"] == sessions[5]
    assert r["target_status_2d"] == "FULL_HORIZON"


def test_known_delisting_uses_terminal_price():
    sessions = pd.bdate_range("2024-01-02", periods=10)
    ticker_dates = sessions[:5]
    panel, layer = _panel_layer(sessions, ticker_dates, ticker="DEL", delisting_date=sessions[4])
    carrier, carrier_layer = _panel_layer(sessions, sessions, ticker="CAL", eligible=False)
    panel = pd.concat([panel, carrier], ignore_index=True)
    layer = pd.concat([layer, carrier_layer], ignore_index=True)
    out = build_return_targets(panel, layer, (5,), minimum_cross_section_size=1)
    r = out[(out.ticker == "DEL") & (out.signal_date == sessions[0])].iloc[0]
    assert r["target_status_5d"] == "TERMINAL_DELISTING"
    assert r["target_end_date_5d"] == sessions[4]
    assert pd.notna(r["fwd_return_5d"])


def test_sample_end_is_right_censored_without_label():
    sessions = pd.bdate_range("2024-01-02", periods=8)
    panel, layer = _panel_layer(sessions, sessions, ticker="AAA")
    out = build_return_targets(panel, layer, (5,), minimum_cross_section_size=1)
    r = out[(out.ticker == "AAA") & (out.signal_date == sessions[4])].iloc[0]
    assert r["target_status_5d"] == "RIGHT_CENSORED_SAMPLE_END"
    assert pd.isna(r["fwd_return_5d"])


def test_unknown_early_termination_is_not_silently_censored():
    sessions = pd.bdate_range("2024-01-02", periods=20)
    ticker_dates = sessions[:8]
    panel, layer = _panel_layer(sessions, ticker_dates, ticker="CUT")
    carrier, carrier_layer = _panel_layer(sessions, sessions, ticker="CAL", eligible=False)
    panel = pd.concat([panel, carrier], ignore_index=True)
    layer = pd.concat([layer, carrier_layer], ignore_index=True)
    out = build_return_targets(panel, layer, (10,), minimum_cross_section_size=1, sample_end_grace_global_sessions=2)
    r = out[(out.ticker == "CUT") & (out.signal_date == sessions[0])].iloc[0]
    assert r["target_status_10d"] == "UNRESOLVED_TERMINATION"
    assert pd.isna(r["fwd_return_10d"])


def test_cross_sectional_labels_remain_target_only():
    sessions = pd.bdate_range("2024-01-02", periods=6)
    panels, layers = [], []
    for j in range(20):
        p, l = _panel_layer(sessions, sessions, ticker=f"T{j:02d}")
        # Dispersion in exit price for day-0 signal / 1-session target.
        l.loc[l["date"] == sessions[2], "target_total_return_price"] += j * 5.0
        panels.append(p); layers.append(l)
    out = build_return_targets(pd.concat(panels), pd.concat(layers), (1,), minimum_cross_section_size=20)
    day = out[out.signal_date == sessions[0]]
    assert day["cs_rank_pct_1d"].notna().sum() == 20
    assert day["winner_top_decile_1d"].fillna(False).sum() >= 2
    assert not out["target_feature_allowed"].any()


def test_diagnostics_separate_resolution_states():
    sessions = pd.bdate_range("2024-01-02", periods=8)
    panel, layer = _panel_layer(sessions, sessions)
    out = build_return_targets(panel, layer, (1, 5), minimum_cross_section_size=1)
    d = horizon_diagnostics(out, (1, 5))
    assert set(d["horizon_sessions"]) == {1, 5}
    assert (d["resolved_label_coverage"] == 1.0).all()
    assert (d["unresolved_termination_rows"] == 0).all()
