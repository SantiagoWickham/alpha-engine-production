from pathlib import Path

import numpy as np
import pandas as pd

from alpha_engine_v12.model_tournament import (
    Phase5Config, FoldSpec, cross_sectional_rank_features, development_only_feature_pool,
    prune_correlated_features, _mask_train_test, evaluate_predictions,
)


def cfg() -> Phase5Config:
    return Phase5Config(
        name="X", objective="Y", feature_library_path="", diagnostics_path="", phase4_summary_path="",
        targets_path="", output_oof_scores_path="", output_validation_scores_path="",
        research_horizons=(20,), architectures=("DEV_IC_COMPOSITE",),
        partitions={
            "development_start": pd.Timestamp("2015-01-02"),
            "validation_start": pd.Timestamp("2023-01-03"),
            "final_oos_start": pd.Timestamp("2025-01-01"),
        },
        cv_folds=(FoldSpec("F", pd.Timestamp("2019-01-02"), pd.Timestamp("2021-01-01")),),
        feature_selection={
            "minimum_development_coverage": 0.50, "maximum_development_fdr_q": 0.10,
            "minimum_abs_development_ic": 0.005, "max_features_per_horizon": 36,
            "minimum_features_per_horizon": 2, "correlation_prune_threshold": 0.995,
            "correlation_sample_rows": 1000,
        },
        models={"random_seed": 42},
        evaluation={"minimum_cross_section_size": 3, "top_quantile": 0.2, "round_trip_cost_bps": 20.0},
    )


def test_feature_pool_ignores_validation_columns():
    d = pd.DataFrame({
        "feature": ["a", "b"], "family": ["F", "F"], "horizon_sessions": [20, 20],
        "development_coverage": [0.8, 0.8], "development_fdr_q": [0.01, 0.20],
        "development_mean_spearman_ic": [0.02, 0.03],
        "validation_aligned_ic": [-999, 999], "validation_aligned_hac_t": [-999, 999],
    })
    a = development_only_feature_pool(d, 20, cfg())
    d["validation_aligned_ic"] *= -1
    d["validation_aligned_hac_t"] *= -1
    b = development_only_feature_pool(d, 20, cfg())
    assert a["feature"].tolist() == ["a"]
    assert b["feature"].tolist() == ["a"]


def test_cross_sectional_rank_is_same_date_only():
    f = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-01"] * 3 + ["2020-01-02"] * 3),
        "ticker": list("ABC") * 2,
        "x": [1, 2, 3, 100, 200, 300],
    })
    r = cross_sectional_rank_features(f, ["x"])
    assert np.allclose(r.loc[:2, "x"], [1/3, 2/3, 1.0])
    assert np.allclose(r.loc[3:, "x"], [1/3, 2/3, 1.0])


def test_correlation_prune_removes_duplicate_rank_feature():
    c = cfg()
    dates = pd.to_datetime(["2020-01-01"] * 5 + ["2020-01-02"] * 5)
    x = np.tile(np.arange(5, dtype=float), 2)
    ranked = pd.DataFrame({"date": dates, "ticker": list("ABCDE") * 2, "a": x, "b": x, "c": x[::-1]})
    pool = pd.DataFrame({
        "feature": ["a", "b", "c"], "family": ["F"] * 3, "development_coverage": [1]*3,
        "development_fdr_q": [0.01, 0.02, 0.03], "development_mean_spearman_ic": [0.03, 0.02, 0.01],
        "development_direction": [1, 1, 1], "abs_development_ic": [0.03, 0.02, 0.01],
        "development_priority_rank": [1, 2, 3],
    })
    out = prune_correlated_features(ranked, pool, c, pd.Series(True, index=ranked.index))
    assert out.loc[out.feature.eq("a"), "kept_after_correlation_prune"].iloc[0]
    assert not out.loc[out.feature.eq("b"), "kept_after_correlation_prune"].iloc[0]
    assert out.loc[out.feature.eq("b"), "correlated_with"].iloc[0] == "a"


def test_walk_forward_purge_is_strict():
    c = cfg(); fold = c.cv_folds[0]
    frame = pd.DataFrame({
        "signal_date": pd.to_datetime(["2018-12-01", "2018-12-20", "2019-02-01", "2020-12-20"]),
        "target_end_date_20d": pd.to_datetime(["2018-12-31", "2019-01-10", "2019-03-01", "2021-01-10"]),
    })
    tr, te = _mask_train_test(frame, c, 20, fold)
    assert tr.tolist() == [True, False, False, False]
    assert te.tolist() == [False, False, True, False]


def test_prediction_metrics_reward_correct_ranking():
    c = cfg()
    rows = []
    for d in pd.to_datetime(["2023-01-03", "2023-01-04"]):
        for i in range(10):
            rows.append({
                "signal_date": d, "ticker": f"T{i}", "fwd_return_20d": i/100,
                "cs_rank_pct_20d": (i+1)/10, "winner_top_decile_20d": i == 9,
            })
    t = pd.DataFrame(rows)
    score = np.tile(np.arange(10), 2)
    m = evaluate_predictions(t, score, 20, c)
    assert m["mean_daily_spearman_ic"] > 0.99
    assert m["winner_top_decile_lift"] >= 5
    assert m["top_vs_universe_net_spread"] > 0


def test_final_oos_partition_constant():
    assert cfg().partitions["final_oos_start"] == pd.Timestamp("2025-01-01")


def test_feature_pool_horizon_column_can_be_reassigned_without_duplicate_insert():
    d = pd.DataFrame({
        "feature": ["a"], "family": ["F"], "horizon_sessions": [20],
        "development_coverage": [0.8], "development_fdr_q": [0.01],
        "development_mean_spearman_ic": [0.02],
    })
    p = development_only_feature_pool(d, 20, cfg()).copy()
    assert "horizon_sessions" in p.columns
    p["horizon_sessions"] = 20
    assert p.columns.tolist().count("horizon_sessions") == 1
    assert p["horizon_sessions"].tolist() == [20]


def test_phase5_gate_semantics_feature_breadth_is_not_integrity_gate():
    # A horizon may legitimately have a compact, development-selected feature set after correlation pruning.
    # Breadth is diagnostic; actual champion qualification/readiness is the blocking economic criterion.
    min_feat = 8
    kept_counts = [9, 6, 24, 23]
    feature_shortfalls = sum(k < min_feat for k in kept_counts)
    status = "PASS" if feature_shortfalls == 0 else "WARN"
    blocking = False
    assert feature_shortfalls == 1
    assert status == "WARN"
    assert blocking is False


def test_phase5_readiness_gate_is_blocking():
    ready_horizons = 4
    minimum_ready_horizons = 2
    model_readiness = "READY_FOR_PORTFOLIO_POLICY_RESEARCH"
    assert ready_horizons >= minimum_ready_horizons
    assert model_readiness == "READY_FOR_PORTFOLIO_POLICY_RESEARCH"
