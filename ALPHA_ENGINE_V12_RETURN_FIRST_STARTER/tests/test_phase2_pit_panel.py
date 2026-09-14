from __future__ import annotations

import pandas as pd
import numpy as np

from alpha_engine_v12.pit_panel import _next_session_strict, attach_fundamentals, add_execution_dates


def test_next_session_is_strict_even_on_trading_day():
    cal = pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]))
    dates = pd.Series(pd.to_datetime(["2024-01-02", "2024-01-03"]))
    got = _next_session_strict(dates, cal)
    assert list(got.dt.strftime("%Y-%m-%d")) == ["2024-01-03", "2024-01-04"]


def test_weekend_filing_becomes_available_next_session():
    cal = pd.DatetimeIndex(pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-09"]))
    dates = pd.Series(pd.to_datetime(["2024-01-06"]))
    got = _next_session_strict(dates, cal)
    assert got.iloc[0] == pd.Timestamp("2024-01-08")


def test_fundamental_is_not_visible_before_available_date():
    panel = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "ticker": ["AAA", "AAA", "AAA"],
        "close": [10.0, 10.5, 11.0],
    })
    events = pd.DataFrame({
        "ticker": ["AAA"],
        "canonical_metric": ["revenue"],
        "value": [100.0],
        "filed": pd.to_datetime(["2024-01-02"]),
        "available_date": pd.to_datetime(["2024-01-03"]),
        "period_end": pd.to_datetime(["2023-12-31"]),
        "form": ["10-Q"],
        "accn": ["x"],
    })
    out, _ = attach_fundamentals(panel, events)
    jan2 = out.loc[out["date"] == pd.Timestamp("2024-01-02"), "revenue"].iloc[0]
    jan3 = out.loc[out["date"] == pd.Timestamp("2024-01-03"), "revenue"].iloc[0]
    assert pd.isna(jan2)
    assert jan3 == 100.0


def test_latest_fundamental_update_replaces_old_value_only_when_available():
    panel = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-03", "2024-01-04", "2024-01-05"]),
        "ticker": ["AAA", "AAA", "AAA"],
        "close": [10.0, 10.5, 11.0],
    })
    events = pd.DataFrame({
        "ticker": ["AAA", "AAA"],
        "canonical_metric": ["revenue", "revenue"],
        "value": [100.0, 120.0],
        "filed": pd.to_datetime(["2024-01-02", "2024-01-04"]),
        "available_date": pd.to_datetime(["2024-01-03", "2024-01-05"]),
        "period_end": pd.to_datetime(["2023-09-30", "2023-12-31"]),
        "form": ["10-Q", "10-Q"],
        "accn": ["x", "y"],
    })
    out, _ = attach_fundamentals(panel, events)
    vals = list(out.sort_values("date")["revenue"])
    assert vals == [100.0, 100.0, 120.0]


def test_execution_is_strictly_after_signal_close():
    cal = pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]))
    panel = pd.DataFrame({"date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "ticker": ["A", "A"]})
    out = add_execution_dates(panel, cal)
    assert (out["earliest_execution_date"] > out["signal_date"]).all()


def test_next_session_after_last_calendar_day_is_missing_not_same_day():
    cal = pd.DatetimeIndex(pd.to_datetime(["2024-01-02", "2024-01-03"]))
    dates = pd.Series(pd.to_datetime(["2024-01-03"]))
    got = _next_session_strict(dates, cal)
    assert pd.isna(got.iloc[0])


def test_attach_fundamentals_accepts_mixed_datetime_precision_and_multiple_tickers():
    # Regression: parquet may expose datetime64[us] while derived event dates
    # are datetime64[ns]. merge_asof requires an exact dtype match.
    panel = pd.DataFrame({
        "date": pd.Series(np.array([
            "2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03"
        ], dtype="datetime64[us]")),
        "ticker": ["AAA", "BBB", "AAA", "BBB"],
        "close": [10.0, 20.0, 11.0, 21.0],
    })
    events = pd.DataFrame({
        "ticker": ["AAA", "BBB"],
        "canonical_metric": ["revenue", "revenue"],
        "value": [100.0, 200.0],
        "filed": pd.to_datetime(["2024-01-02", "2024-01-02"]),
        "available_date": pd.to_datetime(["2024-01-03", "2024-01-03"]),
        "period_end": pd.to_datetime(["2023-12-31", "2023-12-31"]),
        "form": ["10-Q", "10-Q"],
        "accn": ["a", "b"],
    })
    out, _ = attach_fundamentals(panel, events)
    jan2 = out[out["date"] == pd.Timestamp("2024-01-02")]
    jan3 = out[out["date"] == pd.Timestamp("2024-01-03")].set_index("ticker")
    assert jan2["revenue"].isna().all()
    assert jan3.loc["AAA", "revenue"] == 100.0
    assert jan3.loc["BBB", "revenue"] == 200.0
    assert str(out["date"].dtype) == "datetime64[ns]"
