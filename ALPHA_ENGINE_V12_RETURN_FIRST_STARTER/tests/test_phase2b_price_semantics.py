from __future__ import annotations

from types import SimpleNamespace
import pandas as pd
import numpy as np

from alpha_engine_v12.price_semantics import (
    build_price_coverage,
    classify_source_semantics,
    build_corporate_action_diagnostics,
    build_adjusted_requirements,
)


def test_price_coverage_counts_only_positive_finite_adjusted_prices():
    p = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02"] * 4),
        "ticker": ["A", "B", "C", "D"],
        "close": [10, 20, 30, 40],
        "adj_close": [10.0, np.nan, 0.0, np.inf],
        "market_source": ["PRIMARY"] * 4,
        "research_eligible": [True] * 4,
    })
    _, meta = build_price_coverage(p)
    assert meta["eligible_adj_close_rows"] == 1
    assert meta["eligible_adj_close_coverage"] == 0.25


def test_source_semantics_classifies_raw_close_like():
    dates = pd.date_range("2024-01-01", periods=300, freq="D")
    src = pd.DataFrame({"date": dates, "ticker": ["AAA"] * 300, "close": np.linspace(100, 200, 300)})
    ref = src.rename(columns={"close": "raw"}).copy()
    ref["close"] = ref["raw"]
    ref["adj_close"] = ref["raw"] * 0.8
    ref = ref[["date", "ticker", "close", "adj_close"]]
    got = classify_source_semantics(src, ref, "PRIMARY", minimum_overlap_rows=250)
    assert got["classification"] == "RAW_CLOSE_LIKE"


def test_source_semantics_classifies_adjusted_close_like():
    dates = pd.date_range("2024-01-01", periods=300, freq="D")
    raw = np.linspace(100, 200, 300)
    ref = pd.DataFrame({"date": dates, "ticker": ["AAA"] * 300, "close": raw, "adj_close": raw * 0.8})
    src = pd.DataFrame({"date": dates, "ticker": ["AAA"] * 300, "close": raw * 0.8})
    got = classify_source_semantics(src, ref, "PRIMARY", minimum_overlap_rows=250)
    assert got["classification"] == "ADJUSTED_CLOSE_LIKE"


def test_corporate_action_diagnostic_flags_raw_adjusted_divergence():
    cfg = SimpleNamespace(policies={"extreme_raw_return_abs": 0.35, "material_raw_vs_adjusted_gap": 0.01})
    p = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        "ticker": ["AAA", "AAA"],
        "close": [100.0, 50.0],
        "adj_close": [50.0, 51.0],
        "market_source": ["DELISTED", "DELISTED"],
        "research_eligible": [True, True],
    })
    out, meta = build_corporate_action_diagnostics(p, cfg)
    assert meta["extreme_raw_return_rows"] == 1
    assert bool(out.iloc[0]["likely_corporate_action_where_adjusted"])


def test_adjusted_requirements_marks_incomplete_ticker():
    p = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"]),
        "ticker": ["A", "A", "B", "B"],
        "adj_close": [10.0, 10.2, 20.0, np.nan],
        "market_source": ["PRIMARY"] * 4,
        "research_eligible": [True] * 4,
    })
    out = build_adjusted_requirements(p).set_index("ticker")
    assert not bool(out.loc["A", "needs_adjusted_history"])
    assert bool(out.loc["B", "needs_adjusted_history"])
