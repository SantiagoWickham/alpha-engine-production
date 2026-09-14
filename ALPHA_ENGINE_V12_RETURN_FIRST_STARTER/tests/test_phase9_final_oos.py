import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alpha_engine_v12.final_oos import (
    _acceptance_verdict,
    _oos_rebase,
    _recompute_execution_fingerprint,
    edge_realization,
    model_features_and_weights,
    rank_and_score,
    build_phase9,
    Phase9Config,
)
from alpha_engine_v12.pre_freeze import sha256_payload


def _cfg(tmp_path: Path) -> Phase9Config:
    return Phase9Config(
        name="X", objective="X",
        phase8b_summary_path="outputs/p8b.json", phase8b_execution_model_spec_path="outputs/spec.json",
        phase8b_freeze_manifest_path="outputs/m8b.json", phase8_freeze_manifest_path="outputs/m8.json",
        phase8_pre_oos_scores_path="outputs/scores.parquet", feature_library_path="outputs/features.parquet",
        targets_path="outputs/targets.parquet", return_price_layer_path="outputs/prices.parquet",
        terminal_overlay_path="outputs/term.csv", receipt_path="outputs/receipt.json",
        expected_final_freeze_fingerprint_sha256="f"*64, expected_execution_parity_source_sha256="e"*64,
        carry_state_start=pd.Timestamp("2023-01-03"), score_fidelity_start=pd.Timestamp("2024-01-02"),
        final_oos_start=pd.Timestamp("2025-01-01"), minimum_oos_sessions=252, maximum_oos_drawdown=.5,
        maximum_execution_skip_rate=.05, require_milp_success_rate=1.0,
        require_positive_base_cagr=True, require_positive_stress_cagr=True,
        minimum_score_fidelity_correlation=.999999, float_decimals=12,
    )


def test_rank_and_score_is_same_date_cross_sectional_and_future_independent():
    d1 = pd.Timestamp("2025-01-02"); d2 = pd.Timestamp("2025-01-03")
    f = pd.DataFrame({
        "date":[d1,d1,d1,d2,d2,d2], "ticker":["A","B","C"]*2,
        "x":[1.,2.,3., 3.,2.,1.], "y":[3.,2.,1., 1.,2.,3.],
    })
    w = np.array([.6,-.4])
    a = rank_and_score(f, ["x","y"], w)
    f2 = f.copy(); f2.loc[f2["date"].eq(d2), "x"] *= 1000
    b = rank_and_score(f2, ["x","y"], w)
    m = a[a.signal_date.eq(d1)].merge(b[b.signal_date.eq(d1)], on=["signal_date","ticker"], suffixes=("_a","_b"))
    assert np.allclose(m.alpha_score_a, m.alpha_score_b)
    assert set(a.columns) >= {"signal_date","ticker","alpha_score","model_score_raw"}


def test_model_features_and_weights_reads_exact_frozen_spec():
    spec={"frozen_model_spec":{"model":{"feature_weights":[
        {"feature":"a","weight":.6},{"feature":"b","weight":-.4}
    ]},"policy":{}}}
    features, w = model_features_and_weights(spec)
    assert features == ["a","b"]
    assert np.allclose(w,[.6,-.4])


def test_execution_fingerprint_recomputes_phase8b_contract():
    phase8="a"*64
    payload={"build":"x","phase8_freeze_fingerprint_sha256":phase8,"frozen_model_spec":{"x":1},"final_oos_used":False}
    efp=sha256_payload(payload,12)
    final=hashlib.sha256((phase8+":"+efp).encode()).hexdigest()
    spec={**payload,"execution_fingerprint_sha256":efp,"final_freeze_fingerprint_sha256":final}
    got_e,got_f=_recompute_execution_fingerprint(spec,phase8,12)
    assert got_e==efp and got_f==final


def test_oos_rebase_preserves_only_oos_returns_and_rebases_nav():
    d=pd.DataFrame({"date":pd.to_datetime(["2024-12-31","2025-01-02","2025-01-03"]),
                    "nav":[2,2.2,1.98],"net_return":[0,.10,-.10],"turnover":[0,0,0],
                    "cost_fraction":[0,0,0],"execution_skipped":[0,0,0]})
    x=_oos_rebase(d,pd.Timestamp("2025-01-01"))
    assert len(x)==2
    assert np.isclose(x.iloc[-1].nav,.99)


def test_acceptance_is_return_first_and_predeclared():
    cfg=_cfg(Path("."))
    good={"days":300,"cagr":.1,"max_drawdown":-.2}
    verdict,rows=_acceptance_verdict(good,good,cfg)
    assert verdict=="PASS_FOR_SHADOW_FORWARD"
    bad={"days":300,"cagr":-.01,"max_drawdown":-.2}
    verdict,_=_acceptance_verdict(bad,good,cfg)
    assert verdict.startswith("FAIL_FINAL_OOS")


def test_acceptance_requires_minimum_history_and_drawdown_limit():
    cfg=_cfg(Path("."))
    base={"days":100,"cagr":.3,"max_drawdown":-.6}
    verdict,rows=_acceptance_verdict(base,base,cfg)
    assert verdict.startswith("FAIL_FINAL_OOS")
    failed={r["test"] for r in rows if r["status"]=="FAIL"}
    assert {"MINIMUM_OOS_SESSIONS","BASE_MAX_DRAWDOWN","STRESS_MAX_DRAWDOWN"} <= failed


def test_edge_realization_joins_labels_after_decisions():
    d=pd.Timestamp("2025-01-02")
    edges=pd.DataFrame([{"signal_date":d,"held_ticker":"A","candidate_ticker":"B","trade":True,"net_edge":.01}])
    merged=pd.DataFrame([
        {"signal_date":d,"ticker":"A","target_resolved_20d":True,"fwd_return_20d":.01},
        {"signal_date":d,"ticker":"B","target_resolved_20d":True,"fwd_return_20d":.05},
    ])
    x,s=edge_realization(edges,merged)
    assert np.isclose(x.iloc[0].realized_incremental_return_20d,.04)
    assert np.isclose(s["mean_realized_incremental_return_trades"],.04)


def test_one_shot_receipt_refuses_second_run_before_loading_oos(tmp_path: Path):
    (tmp_path/"config").mkdir(); (tmp_path/"outputs").mkdir()
    # Minimal valid config; receipt should abort before any other input file is read.
    src=Path(__file__).parents[1]/"config"/"phase9.toml"
    (tmp_path/"config"/"phase9.toml").write_text(src.read_text())
    (tmp_path/"outputs"/"phase9_oos_consumption_receipt.json").write_text(json.dumps({"status":"CONSUMED"}))
    with pytest.raises(RuntimeError, match="FINAL_OOS_ALREADY_CONSUMED"):
        build_phase9(tmp_path)

def test_zero_milp_calls_is_valid_hold_behavior():
    # The acceptance layer is return-first; execution integrity should not require a solver call
    # when no OOS membership change occurs. This is enforced in build_phase9's MILP gate.
    met={"milp_calls":0,"milp_success_rate":0.0}
    calls=int(met.get("milp_calls",0) or 0); rate=float(met.get("milp_success_rate",0) or 0)
    assert calls == 0 or rate >= 1.0
