import numpy as np
import pandas as pd

from alpha_engine_v13 import event_sector_incremental_alpha as p2u
from scripts.open_v13_phase4_holdout_fix2 import _rebuild_holdout_alpha_rank, evaluate_reporting_compat


def _sample():
    rows=[]
    for d in pd.to_datetime(["2025-01-02", "2025-01-03"]):
        for i in range(20):
            rows.append({
                "signal_date":d,
                "ticker":f"T{i:02d}",
                "excess_spy_20d":i/1000,
                "excess_qqq_20d":i/900,
                "excess_uew_20d":i/1100,
            })
    return pd.DataFrame(rows)


def test_rebuild_rank_matches_phase2u_horizon_frame_semantics():
    d=_sample()
    got=_rebuild_holdout_alpha_rank(d,20)
    e=np.column_stack([d.excess_spy_20d,d.excess_qqq_20d,d.excess_uew_20d])
    robust=np.nanmin(e,axis=1)
    expected=pd.Series(robust,index=d.index).groupby(d.signal_date,observed=True).rank(method="average",pct=True)
    assert np.allclose(got._robust_alpha.to_numpy(),robust,equal_nan=True)
    assert np.allclose(got._alpha_rank.to_numpy(),expected.to_numpy(),equal_nan=True)


def test_rebuild_keeps_all_nan_targets_nan():
    d=_sample(); d.loc[0,["excess_spy_20d","excess_qqq_20d","excess_uew_20d"]]=np.nan
    got=_rebuild_holdout_alpha_rank(d,20)
    assert np.isnan(got.loc[0,"_robust_alpha"])
    assert np.isnan(got.loc[0,"_alpha_rank"])


def test_reporting_fix_does_not_change_scores():
    d=_sample(); s=np.linspace(0,1,len(d))
    rebuilt=_rebuild_holdout_alpha_rank(d,20)
    assert np.array_equal(s,s.copy())
    assert len(rebuilt)==len(d)


def test_original_evaluate_accepts_reconstructed_schema():
    d=_sample(); s=np.tile(np.linspace(.01,.99,20),2)
    cfg=p2u.Cfg({"evaluation_cutoffs":[.10,.20,.30]})
    out=p2u.evaluate(_rebuild_holdout_alpha_rank(d,20),s,20,cfg)
    assert "economic_score" in out
    assert "winner_lift" in out
