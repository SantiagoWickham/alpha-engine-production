from __future__ import annotations

import json
from pathlib import Path

from alpha_engine_v12.portfolio_policy import PHASE6_BUILD, build_phase6


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 6: PORTFOLIO POLICY TOURNAMENT")
    print("=" * 88)
    print(f"BUILD: {PHASE6_BUILD}")
    print(f"MODULE: {root / 'src' / 'alpha_engine_v12' / 'portfolio_policy.py'}")
    print("PRIMARY OBJECTIVE: robust PRE-OOS NET PORTFOLIO RETURN; Sharpe is not the selection objective")
    print("POLICY SELECTION: purged OOF 2019-2022 ONLY")
    print("VALIDATION: 2023-2024 confirmation only; no policy hyperparameter tuning")
    print("FINAL OOS FIREWALL: signal_date >= 2025-01-01 is not loaded")
    summary = build_phase6(root)
    print(json.dumps(summary, indent=2))
    print("\nArtifacts:")
    for p in [
        "outputs/phase6_summary.json", "outputs/phase6_gate.csv", "outputs/phase6_policy_grid.csv",
        "outputs/phase6_oof_results.csv", "outputs/phase6_leaderboard.csv", "outputs/phase6_validation_confirmation.csv",
        "outputs/phase6_score_fidelity.csv", "outputs/phase6_policy_class_summary.csv", "outputs/phase6_champion_spec.json",
        "outputs/phase6_policy_scores.parquet", "outputs/phase6_champion_validation_nav.csv",
    ]:
        print(f"  {p}")
    return 0 if summary.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
