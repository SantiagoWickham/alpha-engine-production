from __future__ import annotations

import json
from pathlib import Path

from alpha_engine_v12.model_tournament import PHASE5_BUILD, build_phase5


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 5: MODEL ARCHITECTURE TOURNAMENT")
    print("=" * 88)
    print(f"BUILD: {PHASE5_BUILD}")
    print(f"MODULE: {Path(__file__).resolve().parents[1] / 'src' / 'alpha_engine_v12' / 'model_tournament.py'}")
    print("FEATURE POOL: DEVELOPMENT-ONLY evidence; Phase 4 validation status is NOT used for feature admission")
    print("FINAL OOS FIREWALL: signal_date >= 2025-01-01 is NOT loaded for model selection")
    summary = build_phase5(root)
    print(json.dumps(summary, indent=2))
    print("\nArtifacts:")
    for p in [
        "outputs/phase5_summary.json", "outputs/phase5_gate.csv", "outputs/phase5_feature_pool.csv",
        "outputs/phase5_cv_results.csv", "outputs/phase5_cv_aggregate.csv", "outputs/phase5_validation_results.csv",
        "outputs/phase5_leaderboard.csv", "outputs/phase5_model_spec.json", "outputs/phase5_oof_scores.parquet",
        "outputs/phase5_validation_scores.parquet",
    ]:
        print(f"  {p}")
    return 0 if summary.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
