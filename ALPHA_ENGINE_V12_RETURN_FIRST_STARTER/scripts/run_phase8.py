from __future__ import annotations
import json
from pathlib import Path
from alpha_engine_v12.pre_freeze import PHASE8_BUILD, build_phase8

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 8: PRE-FREEZE REFIT / REPLAY / FINGERPRINT")
    print("=" * 88)
    print(f"BUILD: {PHASE8_BUILD}")
    print(f"MODULE: {root / 'src' / 'alpha_engine_v12' / 'pre_freeze.py'}")
    print("REFIT CONTRACT: fixed Phase 5 H20 feature set; refit magnitudes + calibration on mature pre-OOS only")
    print("REPLAY CONTRACT: deterministic engineering replay only; replay performance is NOT selection evidence")
    print("FINAL OOS FIREWALL: signal_date >= 2025-01-01 remains unopened")
    summary = build_phase8(root)
    print(json.dumps(summary, indent=2))
    print("\nArtifacts:")
    for x in [
        "outputs/phase8_summary.json",
        "outputs/phase8_gate.csv",
        "outputs/phase8_final_feature_weights.csv",
        "outputs/phase8_final_edge_calibration.csv",
        "outputs/phase8_final_model_spec.json",
        "outputs/phase8_freeze_manifest.json",
        "outputs/phase8_model_fingerprint.sha256",
        "outputs/phase8_replay_summary.csv",
        "outputs/phase8_final_lineage_audit.csv",
        "outputs/phase8_pre_oos_frozen_scores.parquet",
        "outputs/phase8_pre_freeze_replay_nav.csv",
        "outputs/phase8_pre_freeze_edge_decisions.csv",
    ]:
        print(" ", x)
    return 0 if summary.get("status") == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
