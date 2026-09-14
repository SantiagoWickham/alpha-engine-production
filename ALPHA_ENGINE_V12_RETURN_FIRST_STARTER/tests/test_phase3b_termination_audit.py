import pandas as pd
from alpha_engine_v12.termination_audit import unresolved_counts, classify


def test_unresolved_counts_by_ticker_and_horizon():
    x = pd.DataFrame({
        "signal_date": pd.to_datetime(["2024-01-01","2024-01-02","2024-01-01"]),
        "ticker": ["AAA","AAA","BBB"],
        "target_status_1d": ["UNRESOLVED_TERMINATION","FULL_HORIZON","FULL_HORIZON"],
        "target_status_5d": ["UNRESOLVED_TERMINATION","UNRESOLVED_TERMINATION","FULL_HORIZON"],
    })
    out = unresolved_counts(x, [1,5])
    r = out.set_index("ticker").loc["AAA"]
    assert r["unresolved_1d"] == 1
    assert r["unresolved_5d"] == 2
    assert "BBB" not in set(out.ticker)


def test_confirmed_delisting_metadata_gap_classification():
    r = pd.Series({
        "return_price_last_date": pd.Timestamp("2024-01-10"),
        "av_delisted_delisting_date": pd.Timestamp("2024-01-12"),
        "lifecycle_delisting_date": pd.NaT,
        "cache_filename_delisting_date": pd.NaT,
        "av_active_status": None,
        "lifecycle_status": None,
    })
    c, _ = classify(r, pd.Timestamp("2024-12-31"), 14)
    assert c == "CONFIRMED_OR_NEAR_DELISTING_METADATA_GAP"


def test_active_gap_classification():
    r = pd.Series({
        "return_price_last_date": pd.Timestamp("2024-01-10"),
        "av_delisted_delisting_date": pd.NaT,
        "lifecycle_delisting_date": pd.NaT,
        "cache_filename_delisting_date": pd.NaT,
        "av_active_status": "Active",
        "lifecycle_status": "active",
        "cache_has_parquet": False,
    })
    c, _ = classify(r, pd.Timestamp("2024-12-31"), 14)
    assert c == "ACTIVE_PRICE_HISTORY_GAP"


def test_sample_end_candidate_only_near_end():
    r = pd.Series({
        "return_price_last_date": pd.Timestamp("2024-12-25"),
        "av_delisted_delisting_date": pd.NaT,
        "lifecycle_delisting_date": pd.NaT,
        "cache_filename_delisting_date": pd.NaT,
        "av_active_status": None,
        "lifecycle_status": None,
        "cache_has_parquet": False,
    })
    c, _ = classify(r, pd.Timestamp("2024-12-31"), 14)
    assert c == "SAMPLE_END_CENSORING_CANDIDATE"
