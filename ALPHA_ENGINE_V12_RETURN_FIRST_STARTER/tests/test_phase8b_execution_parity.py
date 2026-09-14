import numpy as np
import pandas as pd

from alpha_engine_v12.edge_lineage import EdgeSpec
from alpha_engine_v12.execution_parity import _weighted_membership_target, simulate_execution_parity


class P7:
    milp_holdings = 3
    optimizer_max_weight = 0.60
    milp_min_weight = 0.20
    milp_max_weight = 0.60
    milp_weight_step = 0.10


def _calib():
    return pd.DataFrame({
        "score_center": [0.1,0.5,0.9],
        "isotonic_expected_return_20d": [0.00,0.02,0.06],
        "hac_se_expected_mean": [0.001,0.001,0.001],
    })


def test_weighted_membership_milp_preserves_exact_membership():
    scores = {"A":0.95,"B":0.90,"C":0.85}
    w, meta = _weighted_membership_target(["A","B","C"], scores, _calib(), 0.5, {}, P7())
    assert meta["success"]
    assert set(w) == {"A","B","C"}
    assert np.isclose(sum(w.values()), 1.0)
    assert all(0.20 - 1e-9 <= x <= 0.60 + 1e-9 for x in w.values())


def test_weighted_membership_rejects_wrong_count():
    w, meta = _weighted_membership_target(["A","B"], {"A":.9,"B":.8}, _calib(), .5, {}, P7())
    assert not meta["success"]
    assert w == {}


def test_simulation_applies_milp_only_on_membership_change_and_next_session():
    dates = pd.bdate_range("2023-01-02", periods=8)
    tickers = ["A","B","C","D"]
    prices = pd.DataFrame([(d,t,True,100.0 + i) for i,d in enumerate(dates) for t in tickers], columns=["date","ticker","research_eligible","target_total_return_price"])
    scores = []
    for i,d in enumerate(dates[:-1]):
        vals = {"A":.95,"B":.90,"C":.85,"D":.70}
        if i >= 3:
            vals["D"] = .99; vals["C"] = .40
        for t,s in vals.items(): scores.append((d,t,s))
    scores = pd.DataFrame(scores, columns=["signal_date","ticker","alpha_score"])
    edge = EdgeSpec(entry_floor=.8, uncertainty_z=.0, minimum_extra_edge_bps=0.0, max_replacements=1)
    met, nav, ed, milp = simulate_execution_parity(scores, prices, {}, _calib(), edge, dates[0], dates[-1] + pd.Timedelta(days=1), 3, 0.0, P7())
    assert len(milp) >= 2  # initial entry + replacement
    assert milp["success"].all()
    assert met["milp_success_rate"] == 1.0
    # first score date cannot already be invested: execution is next session.
    assert nav.iloc[0]["holdings"] == 0
    assert nav.iloc[1]["holdings"] == 3
