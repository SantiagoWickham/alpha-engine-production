from datetime import datetime, timezone
from pathlib import Path

from alpha_engine_v12.clock import DecisionTrigger, TradeAction
from alpha_engine_v12.config import load_config
from alpha_engine_v12.contracts import DecisionStamp, InformationStamp
from alpha_engine_v12.provenance import classify

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "config" / "project.toml")


def test_return_first_objective_is_locked():
    assert CFG.objective == "MAXIMIZE_OUT_OF_SAMPLE_NET_RETURN"


def test_clock_is_event_driven_not_fixed_monthly():
    assert CFG.clock.evaluation_policy == "EACH_TRADING_SESSION"
    assert CFG.clock.trade_policy == "EVENT_DRIVEN"
    assert CFG.clock.fixed_rebalance is False
    assert CFG.clock.allow_multiple_trades_per_month is True
    assert CFG.clock.allow_zero_trades_per_month is True


def test_legacy_audit_is_never_model_input():
    x = classify("data/audit_v10_4/alpha_attribution.csv", CFG.data_boundary)
    assert x.allowed_as_model_input is False


def test_old_model_artifact_in_cache_is_rejected():
    x = classify("data/cache/v10_extended_trend_panel.parquet", CFG.data_boundary)
    assert x.allowed_as_model_input is False


def test_market_data_is_approved():
    x = classify("data/cache/market_ohlcv_extended.parquet", CFG.data_boundary)
    assert x.allowed_as_model_input is True
    assert x.role == "market"


def test_raw_sec_data_is_approved():
    x = classify("data/cache/sec/example.json", CFG.data_boundary)
    assert x.allowed_as_model_input is True
    assert x.role == "fundamentals"


def test_future_information_rejected():
    info = InformationStamp(
        observation_time=datetime(2026, 9, 12, 10, tzinfo=timezone.utc),
        available_at=datetime(2026, 9, 12, 15, tzinfo=timezone.utc),
        ingested_at=datetime(2026, 9, 12, 15, 1, tzinfo=timezone.utc),
    )
    decision = DecisionStamp(
        decision_time=datetime(2026, 9, 12, 14, tzinfo=timezone.utc),
        execution_earliest=datetime(2026, 9, 12, 14, 1, tzinfo=timezone.utc),
    )
    try:
        decision.validate_against(info)
    except ValueError as e:
        assert "future information" in str(e)
    else:
        raise AssertionError("future information should have been rejected")


def test_event_trigger_holds_when_net_edge_insufficient():
    t = DecisionTrigger(0.010, 0.002, 0.003, 0.006)
    assert t.net_edge == 0.005
    assert t.action() == TradeAction.HOLD


def test_event_trigger_reoptimizes_when_net_edge_is_large():
    t = DecisionTrigger(0.025, 0.003, 0.004, 0.010)
    assert t.action() == TradeAction.REOPTIMIZE
