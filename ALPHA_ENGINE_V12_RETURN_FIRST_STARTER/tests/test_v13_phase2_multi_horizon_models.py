import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from alpha_engine_v13.multi_horizon_models import (
    ARCHITECTURES,
    _rank_architecture,
    cross_sectional_rank_features,
    evaluate_gate,
    evaluate_scores,
    purged_split,
)


def _cfg(**kw):
    base = {
        "horizons": [5,10,20,60,120,252],
        "holdout_start": "2025-01-01",
    }
    base.update(kw)
    return SimpleNamespace(p=base)


def test_all_six_horizons_are_contractually_present():
    assert [5,10,20,60,120,252] == _cfg().p["horizons"]


def test_architecture_set_contains_return_and_rank_models():
    assert "HGB_ROBUST_EXCESS" in ARCHITECTURES
    assert "HGB_RANK" in ARCHITECTURES
    assert "RIDGE_RANK" in ARCHITECTURES


def test_cross_sectional_rank_is_same_date_only():
    d = pd.DataFrame({
        "signal_date": pd.to_datetime(["2020-01-01"]*3 + ["2020-01-02"]*3),
        "ticker": list("ABC")*2,
        "f": [1,2,3,100,200,300],
    })
    r = cross_sectional_rank_features(d, ["f"])
    assert np.allclose(r["f"].to_numpy(), [1/3,2/3,1,1/3,2/3,1])


def test_purge_rejects_labels_crossing_test_start():
    dates = pd.to_datetime(["2019-01-01","2019-06-01","2020-01-02","2020-02-01"])
    d = pd.DataFrame({
        "signal_date": dates,
        "ticker": ["A"]*4,
        "target_end_date_20d": pd.to_datetime(["2019-02-01","2020-02-01","2020-03-01","2020-03-01"]),
        "target_resolved_20d": [True]*4,
        "fwd_return_20d": [0.1]*4,
    })
    tr, te = purged_split(d, 20, "2019-01-01", "2020-01-01", "2021-01-01")
    assert list(tr["signal_date"]) == [pd.Timestamp("2019-01-01")]
    assert (tr["target_end_date_20d"] < pd.Timestamp("2020-01-01")).all()


def test_economic_score_penalizes_failure_vs_one_benchmark():
    n = 100
    d = pd.DataFrame({
        "signal_date": [pd.Timestamp("2020-01-02")]*n,
        "ticker": [f"T{i}" for i in range(n)],
        "fwd_return_20d": np.linspace(-.1,.2,n),
        "excess_spy_20d": np.linspace(-.1,.2,n),
        "excess_qqq_20d": np.linspace(-.3,0.0,n),
        "excess_uew_20d": np.linspace(-.1,.2,n),
    })
    score = np.linspace(0,1,n)
    ev = evaluate_scores(d, score, 20, [0.10])
    assert ev["economic_score"] <= 0.0


def test_architecture_ranking_is_return_first_not_ic_first():
    e = pd.DataFrame([
        {"architecture":"A","economic_score":0.02,"worst_cut_robust_excess":0.01,"mean_rank_ic":0.01},
        {"architecture":"B","economic_score":0.01,"worst_cut_robust_excess":0.01,"mean_rank_ic":0.50},
    ])
    assert _rank_architecture(e) == "A"


def test_validation_cannot_be_used_for_selection_gate():
    champions = {h:{"validation_used_for_selection":False,"validation_economic_score":0.0} for h in [5,10,20,60,120,252]}
    parts = {
        "phase1_status":"PASS",
        "max_loaded_date":pd.Timestamp("2024-12-31"),
        "champions":champions,
        "nested_counts":{h:1 for h in champions},
        "purge_violations":0,
    }
    g, status = evaluate_gate(parts, _cfg())
    assert status == "PASS"
    row = g[g.test.eq("VALIDATION_NOT_USED_FOR_MODEL_SELECTION")].iloc[0]
    assert row.status == "PASS"


def test_holdout_boundary_is_blocking():
    champions = {h:{"validation_used_for_selection":False,"validation_economic_score":0.0} for h in [5,10,20,60,120,252]}
    parts = {
        "phase1_status":"PASS",
        "max_loaded_date":pd.Timestamp("2025-01-02"),
        "champions":champions,
        "nested_counts":{h:1 for h in champions},
        "purge_violations":0,
    }
    _, status = evaluate_gate(parts, _cfg())
    assert status == "FAIL"


def test_weak_validation_does_not_discard_horizon():
    champions = {h:{"validation_used_for_selection":False,"validation_economic_score":-0.5} for h in [5,10,20,60,120,252]}
    parts = {
        "phase1_status":"PASS",
        "max_loaded_date":pd.Timestamp("2024-12-31"),
        "champions":champions,
        "nested_counts":{h:10 for h in champions},
        "purge_violations":0,
    }
    g, status = evaluate_gate(parts, _cfg())
    assert status == "PASS"
    row = g[g.test.eq("VALIDATION_ECONOMIC_CONFIRMATION")].iloc[0]
    assert row.blocking in [False, np.bool_(False)]


def test_nested_oof_must_exist_for_each_horizon():
    champions = {h:{"validation_used_for_selection":False,"validation_economic_score":0.0} for h in [5,10,20,60,120,252]}
    parts = {
        "phase1_status":"PASS",
        "max_loaded_date":pd.Timestamp("2024-12-31"),
        "champions":champions,
        "nested_counts":{5:10,10:10,20:10,60:10,120:10,252:0},
        "purge_violations":0,
    }
    _, status = evaluate_gate(parts, _cfg())
    assert status == "FAIL"
