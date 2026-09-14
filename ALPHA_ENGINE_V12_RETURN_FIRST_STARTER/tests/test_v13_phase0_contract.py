from pathlib import Path
import sys, tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from alpha_engine_v13.contracts import load_contract, research_date_allowed, is_denied

ROOT = Path(__file__).resolve().parents[1]
C = load_contract(ROOT / "config" / "v13_contract.toml")

def test_2024_allowed_2025_denied():
    cutoff = C["research"]["code_blinded_holdout_start"]
    assert research_date_allowed("2024-12-31", cutoff)
    assert not research_date_allowed("2025-01-01", cutoff)
    assert not research_date_allowed("2026-09-04", cutoff)

def test_multi_horizon_not_collapsed():
    assert C["research"]["multi_horizons"] == [5,10,20,60,120,252]

def test_no_fixed_cardinality_or_weight_bands():
    r=C["research"]
    assert r["fixed_cardinality"] is False
    assert r["fixed_max_weight"] is False
    assert r["fixed_min_weight"] is False

def test_old_oos_and_model_outputs_denied():
    pats=C["denied_sources"]["patterns"]
    assert is_denied("outputs/phase9_summary.json", pats)
    assert is_denied("outputs/phase6_leaderboard.csv", pats)
    assert is_denied("src/alpha_engine_v12/model_tournament.py", pats)
    assert not is_denied("outputs/phase3_return_targets.parquet", pats)

def test_objective_is_excess_return_first():
    assert C["objective"]["primary"] == "MAXIMIZE_PRE_OOS_NET_EXCESS_RETURN"
    assert C["objective"]["selection_metric_order"][0] == "net_excess_return"
