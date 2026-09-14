from __future__ import annotations

import numpy as np
import pandas as pd

from alpha_engine_v12.feature_research import (
    FUNDAMENTAL_METRICS,
    Phase4Config,
    _daily_rank_correlations,
    _partition_for_horizon,
    _per_ticker_features,
    apply_research_exclusions,
    build_feature_library,
)


def _cfg() -> Phase4Config:
    return Phase4Config(
        name="TEST", objective="TEST", panel_path="", targets_path="", phase3_summary_path="",
        exclusions_path="", adjusted_cache_dir="", output_feature_library_path="",
        research_horizons=(5, 20, 252),
        partitions={
            "development_start": pd.Timestamp("2020-01-01"),
            "validation_start": pd.Timestamp("2022-01-01"),
            "final_oos_start": pd.Timestamp("2024-01-01"),
        },
        policies={
            "minimum_cross_section_size": 2, "feature_rank_batch_size": 4, "hac_lag_cap": 20,
            "minimum_feature_coverage": 0.2, "discovery_fdr_q": 0.1, "watch_fdr_q": 0.2,
            "minimum_abs_development_ic": 0.005, "minimum_validation_aligned_ic": 0.0,
            "minimum_validation_aligned_t": 1.5, "rich_diagnostics_q_threshold": 0.2,
            "feature_return_price_coverage_required": 0.995, "minimum_usable_feature_coverage": 0.5,
            "minimum_usable_feature_count": 5,
        },
        windows={
            "return_windows": (1, 5, 10, 20, 40, 60, 120, 252),
            "vol_windows": (10, 20, 60, 120),
            "trend_windows": (20, 60, 120, 252),
            "liquidity_windows": (20, 60),
            "fundamental_change_windows": (126, 252),
        },
    )


def _ticker_frame(n=320, ticker="AAA"):
    dates = pd.bdate_range("2020-01-02", periods=n)
    x = pd.DataFrame({
        "date": dates,
        "ticker": ticker,
        "close": np.linspace(50, 100, n),
        "volume": np.linspace(1_000_000, 1_200_000, n),
        "feature_adj_price": np.linspace(50, 100, n) * (1 + 0.01 * np.sin(np.arange(n) / 10)),
    })
    vals = {
        "assets": 1000.0, "capex": 15.0, "cash": 150.0, "current_assets": 400.0,
        "current_liabilities": 200.0, "eps_diluted": 2.0, "equity": 600.0,
        "long_term_debt": 200.0, "net_income": 40.0, "operating_cash_flow": 55.0,
        "operating_income": 60.0, "revenue": 500.0, "shares_outstanding": 100.0,
    }
    for j, m in enumerate(FUNDAMENTAL_METRICS):
        x[m] = vals[m] * (1 + 0.0005 * np.arange(n))
        # Quarterly-ish disclosure events; all dates causal.
        event_idx = (np.arange(n) // 63) * 63
        avail = dates[np.minimum(event_idx, n - 1)]
        x[f"{m}__available_date"] = pd.to_datetime(avail)
        x[f"{m}__period_end"] = pd.to_datetime(avail) - pd.Timedelta(days=30 + j % 5)
    return x


def test_adjusted_price_common_rescaling_cannot_change_scale_invariant_features():
    cfg = _cfg()
    g = _ticker_frame()
    a = _per_ticker_features(g, cfg)
    g2 = g.copy()
    g2["feature_adj_price"] = g2["feature_adj_price"] * 0.037
    b = _per_ticker_features(g2, cfg)
    price_cols = [c for c in a.columns if c.startswith(("mom_", "trend_", "drawdown_", "distance_", "vol_", "downside_", "worst_", "skew_"))]
    for c in price_cols:
        av = a[c].to_numpy(float)
        bv = b[c].to_numpy(float)
        assert np.allclose(av, bv, equal_nan=True, rtol=1e-6, atol=1e-7), c


def test_future_perturbation_does_not_change_past_features():
    cfg = _cfg()
    g = _ticker_frame()
    cutoff = 220
    a = _per_ticker_features(g, cfg)
    g2 = g.copy()
    g2.loc[g2.index > cutoff, "feature_adj_price"] *= 7.0
    g2.loc[g2.index > cutoff, "revenue"] *= 100.0
    g2.loc[g2.index > cutoff, "net_income"] *= -50.0
    b = _per_ticker_features(g2, cfg)
    common = a.columns
    for c in common:
        av = pd.to_numeric(a.loc[:cutoff, c], errors="coerce").to_numpy(float)
        bv = pd.to_numeric(b.loc[:cutoff, c], errors="coerce").to_numpy(float)
        assert np.allclose(av, bv, equal_nan=True, rtol=1e-6, atol=1e-7), c


def test_research_exclusion_removes_only_declared_window():
    p = pd.DataFrame({
        "date": pd.to_datetime(["2025-12-26", "2026-01-05", "2026-02-01"]),
        "ticker": ["ABXL", "ABXL", "ABXL"],
    })
    ex = pd.DataFrame([{
        "ticker": "ABXL", "effective_start_date": pd.Timestamp("2025-12-26"),
        "effective_end_date": pd.Timestamp("2026-01-30"), "research_eligible": False,
        "feature_allowed": False,
    }])
    out, removed = apply_research_exclusions(p, ex)
    assert removed == 2
    assert list(out["date"]) == [pd.Timestamp("2026-02-01")]


def test_partition_purges_outcomes_crossing_next_boundary():
    cfg = _cfg()
    x = pd.DataFrame({
        "signal_date": pd.to_datetime(["2021-12-01", "2021-12-15", "2023-12-01", "2023-12-15"]),
        "target_end_date_20d": pd.to_datetime(["2021-12-30", "2022-01-10", "2023-12-29", "2024-01-15"]),
        "target_resolved_20d": [True, True, True, True],
    })
    dev = _partition_for_horizon(x, 20, cfg, "DEVELOPMENT")
    val = _partition_for_horizon(x, 20, cfg, "VALIDATION")
    assert list(dev["signal_date"]) == [pd.Timestamp("2021-12-01")]
    assert list(val["signal_date"]) == [pd.Timestamp("2023-12-01")]


def test_daily_rank_correlation_detects_cross_sectional_ordering():
    dates = pd.to_datetime(["2022-01-03"] * 4 + ["2022-01-04"] * 4)
    f = [1, 2, 3, 4] * 2
    y = [0.25, 0.50, 0.75, 1.00] * 2
    df = pd.DataFrame({"signal_date": dates, "f": f, "y": y})
    out = _daily_rank_correlations(df, ["f"], "y", min_cs=3)
    assert len(out) == 2
    assert np.allclose(out["f"], 1.0)


def test_feature_library_never_exports_adjusted_level_or_target_columns():
    cfg = _cfg()
    g1 = _ticker_frame(ticker="AAA")
    g2 = _ticker_frame(ticker="BBB")
    panel = pd.concat([g1.drop(columns="feature_adj_price"), g2.drop(columns="feature_adj_price")], ignore_index=True)
    surface = pd.concat([
        g1[["date", "ticker", "feature_adj_price"]], g2[["date", "ticker", "feature_adj_price"]]
    ], ignore_index=True)
    lib, cols, meta = build_feature_library(panel, surface, cfg)
    assert meta["feature_count"] == len(cols)
    assert "feature_adj_price" not in lib.columns
    assert not any(c.startswith(("fwd_", "target_", "winner_", "mfe_", "mae_")) for c in cols)
    assert lib["feature_allowed"].all()


def test_predictive_research_uses_purged_pre_oos_and_validates_known_signal():
    from alpha_engine_v12.feature_research import predictive_research
    cfg = _cfg()
    dev_dates = pd.bdate_range("2020-02-03", periods=30, freq="5B")
    val_dates = pd.bdate_range("2022-02-01", periods=30, freq="5B")
    oos_dates = pd.bdate_range("2024-02-01", periods=5, freq="5B")
    dates = list(dev_dates) + list(val_dates) + list(oos_dates)
    frows, trows = [], []
    tickers = ["A", "B", "C", "D", "E"]
    for d in dates:
        for j, t in enumerate(tickers):
            good = float(j)
            frows.append({"date": d, "ticker": t, "good": good, "noise": float((j * 7 + d.day) % 5)})
            rank = (j + 1) / 5.0
            row = {"signal_date": d, "ticker": t}
            for h in cfg.research_horizons:
                row[f"target_end_date_{h}d"] = d + pd.Timedelta(days=1)
                row[f"target_resolved_{h}d"] = True
                row[f"fwd_return_{h}d"] = 0.01 * j
                row[f"cs_rank_pct_{h}d"] = rank
                row[f"winner_top_decile_{h}d"] = (j == 4)
            trows.append(row)
    features = pd.DataFrame(frows)
    targets = pd.DataFrame(trows)
    diag, candidates, fam = predictive_research(features, targets, ["good", "noise"], cfg)
    good = candidates[candidates["feature"] == "good"].iloc[0]
    assert good["research_status"] == "VALIDATED"
    # OOS signals are explicitly excluded; only DEVELOPMENT/VALIDATION should contribute.
    assert (diag["development_rows"] > 0).all()
    assert (diag["validation_rows"] > 0).all()
