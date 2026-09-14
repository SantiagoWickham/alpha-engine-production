import numpy as np
import pandas as pd

from alpha_engine_v12.return_price_enrichment import (
    _parse_yahoo_chart,
    build_return_price_layer,
    yahoo_symbol_candidates,
)


def test_yahoo_symbol_candidates_class_share():
    assert yahoo_symbol_candidates("BRK.B") == ["BRK.B", "BRK-B"]


def test_parse_yahoo_chart_extracts_adjusted_and_actions():
    payload = {
        "chart": {
            "error": None,
            "result": [{
                "timestamp": [1704067200, 1704153600],
                "indicators": {
                    "quote": [{"open": [10, 11], "high": [11, 12], "low": [9, 10], "close": [10, 11], "volume": [100, 110]}],
                    "adjclose": [{"adjclose": [9.5, 10.6]}],
                },
                "events": {
                    "dividends": {"x": {"date": 1704153600, "amount": 0.1}},
                    "splits": {"y": {"date": 1704067200, "numerator": 2, "denominator": 1, "splitRatio": "2:1"}},
                },
            }],
        }
    }
    prices, actions = _parse_yahoo_chart(payload, "ABC", "ABC")
    assert len(prices) == 2
    assert float(prices.iloc[0]["adj_close"]) == 9.5
    assert set(actions["event_type"]) == {"DIVIDEND", "SPLIT"}


def test_return_price_layer_preserves_execution_close_and_prefers_existing_adjusted():
    panel = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-02"]),
        "ticker": ["AAA", "AAA", "BBB"],
        "close": [100.0, 101.0, 50.0],
        "adj_close": [np.nan, np.nan, 49.0],
        "research_eligible": [True, True, True],
        "market_source": ["PRIMARY", "PRIMARY", "DELISTED"],
    })
    downloaded = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-02"]),
        "ticker": ["AAA", "AAA", "BBB"],
        "adj_close": [98.0, 99.0, 48.0],
        "provider_symbol": ["AAA", "AAA", "BBB"],
    })
    layer, _, meta = build_return_price_layer(panel, downloaded)
    aaa = layer[layer.ticker.eq("AAA")]
    bbb = layer[layer.ticker.eq("BBB")].iloc[0]
    assert aaa["close"].tolist() == [100.0, 101.0]
    assert aaa["target_total_return_price"].tolist() == [98.0, 99.0]
    assert bbb["target_total_return_price"] == 49.0
    assert bbb["target_price_source"] == "PHASE2_EXISTING_ADJ_CLOSE"
    assert not layer["target_price_feature_allowed"].any()
    assert meta["coverage"] == 1.0

from alpha_engine_v12.return_price_enrichment import Phase2CConfig, validate_provider_identity, evaluate_gate


def _cfg():
    return Phase2CConfig(
        name="x", objective="x", panel_path="x", requirements_path="x",
        cache_dir="x", actions_path="x", local_adjusted_reference="x",
        policies={
            "raw_identity_relative_tolerance": 0.001,
            "minimum_validation_rows": 100,
            "minimum_short_history_validation_rows": 20,
            "raw_identity_match_required": 0.98,
            "coverage_required": 0.995,
            "per_ticker_coverage_required": 0.995,
            "local_adjusted_match_required": 0.98,
        },
    )


def test_provider_identity_accepts_adjusted_like_panel_close():
    dates = pd.date_range("2024-01-01", periods=120, freq="D")
    raw = np.linspace(100, 120, len(dates))
    adj = raw * 0.90
    panel = pd.DataFrame({
        "date": dates, "ticker": "ADR", "close": adj,
        "research_eligible": True,
    })
    downloaded = pd.DataFrame({
        "date": dates, "ticker": "ADR", "close": raw, "adj_close": adj,
    })
    out = validate_provider_identity(panel, downloaded, _cfg())
    r = out.iloc[0]
    assert r["status"] == "PASS"
    assert r["panel_price_semantics"] == "ADJUSTED_CLOSE_LIKE"
    assert r["adjusted_identity_match_rate"] == 1.0


def test_provider_identity_short_lived_ticker_can_pass_on_all_available_history():
    dates = pd.date_range("2026-06-01", periods=48, freq="D")
    px = np.linspace(10, 12, len(dates))
    panel = pd.DataFrame({
        "date": dates, "ticker": "NEW", "close": px,
        "research_eligible": True,
    })
    downloaded = pd.DataFrame({
        "date": dates, "ticker": "NEW", "close": px, "adj_close": px,
    })
    out = validate_provider_identity(panel, downloaded, _cfg())
    r = out.iloc[0]
    assert r["required_validation_rows"] == 48
    assert r["status"] == "PASS"


def test_disjoint_local_reference_is_nonblocking():
    manifest = pd.DataFrame({"status": ["CACHE_HIT"]})
    provider = pd.DataFrame({
        "identity_match_rate": [1.0], "overlap_rows": [48], "status": ["PASS"]
    })
    coverage = pd.DataFrame({"coverage": [1.0]})
    gate, status = evaluate_gate(
        manifest, provider,
        {"status": "NO_OVERLAP", "match_rate": np.nan},
        coverage, {"coverage": 1.0}, _cfg(),
    )
    assert status == "PASS"
    row = gate[gate["test"].eq("LOCAL_ADJUSTED_REFERENCE_CROSSCHECK")].iloc[0]
    assert row["status"] == "NOT_APPLICABLE"
    assert not bool(row["blocking"])
