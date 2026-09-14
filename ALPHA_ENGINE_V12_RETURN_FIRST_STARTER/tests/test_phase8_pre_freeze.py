import json
from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine_v12.pre_freeze import (
    canonicalize,
    edge_spec_from_candidate,
    refit_composite_weights,
    score_with_frozen_refit,
    sha256_payload,
)


def _pool():
    return pd.DataFrame({
        "feature": ["a", "b"],
        "development_direction": [1, -1],
        "development_mean_spearman_ic": [0.1, -0.1],
    })


def test_sha256_payload_is_order_stable():
    a = {"b": 2, "a": {"y": 1.1234567891234, "x": True}}
    b = {"a": {"x": True, "y": 1.1234567891234}, "b": 2}
    assert sha256_payload(a) == sha256_payload(b)


def test_sha256_payload_changes_if_policy_changes():
    a = {"policy": {"edge_bps": 50.0}}
    b = {"policy": {"edge_bps": 100.0}}
    assert sha256_payload(a) != sha256_payload(b)


def test_edge_spec_copies_candidate_exactly():
    c = {
        "entry_floor": 0.8,
        "uncertainty_z": 0.5,
        "minimum_extra_edge_bps": 50.0,
        "max_replacements_per_session": 1,
    }
    s = edge_spec_from_candidate(c)
    assert s.entry_floor == 0.8
    assert s.uncertainty_z == 0.5
    assert s.minimum_extra_edge_bps == 50.0
    assert s.max_replacements == 1


def test_refit_weights_preserve_fixed_directions_and_normalize():
    dates = pd.to_datetime(["2020-01-02"]*4 + ["2020-01-03"]*4)
    tick = ["A","B","C","D"]*2
    a = [0.1,0.3,0.7,0.9,0.2,0.4,0.6,0.8]
    b = [0.9,0.7,0.3,0.1,0.8,0.6,0.4,0.2]
    ranked = pd.DataFrame({"date": dates, "ticker": tick, "a": a, "b": b})
    target = [0.1,0.3,0.7,0.9,0.2,0.4,0.6,0.8]
    targets = pd.DataFrame({
        "signal_date": dates, "ticker": tick, "cs_rank_pct_20d": target,
    })
    class C: minimum_cross_section=3; horizon_sessions=20
    out = refit_composite_weights(ranked, targets, _pool(), C())
    assert out.set_index("feature").at["a","frozen_direction"] == 1
    assert out.set_index("feature").at["b","frozen_direction"] == -1
    assert np.isclose(out["normalized_refit_weight"].abs().sum(), 1.0)
    assert not out["feature_admitted_in_phase8"].any()
    assert not out["feature_dropped_in_phase8"].any()


def test_score_with_frozen_refit_is_deterministic():
    ranked = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-02"]*3),
        "ticker": ["A","B","C"],
        "a": [0.2,0.5,0.9],
        "b": [0.8,0.5,0.1],
    })
    w = pd.DataFrame({
        "feature": ["a","b"],
        "normalized_refit_weight": [0.5,-0.5],
    })
    x = score_with_frozen_refit(ranked, w)
    y = score_with_frozen_refit(ranked, w)
    pd.testing.assert_frame_equal(x, y)
    assert x.loc[x["ticker"].eq("C"), "alpha_score"].iloc[0] == 1.0


def test_score_is_cross_sectional_rank_not_raw_level():
    ranked = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-02"]*3),
        "ticker": ["A","B","C"],
        "a": [0.2,0.5,0.9],
    })
    w = pd.DataFrame({"feature":["a"],"normalized_refit_weight":[1.0]})
    out = score_with_frozen_refit(ranked,w).set_index("ticker")
    assert np.isclose(out.at["A","alpha_score"],1/3)
    assert np.isclose(out.at["C","alpha_score"],1.0)


def test_canonicalize_converts_nonfinite_to_none():
    z = canonicalize({"x": np.nan, "y": np.inf, "z": -np.inf})
    assert z == {"x": None, "y": None, "z": None}
