from pathlib import Path
import json

from alpha_engine_v12.final_oos import build_phase9, PHASE9_BUILD


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 9: FINAL OOS ONE-SHOT EVALUATION")
    print("=" * 88)
    print(f"BUILD: {PHASE9_BUILD}")
    print("ONE-SHOT CONTRACT: exact Phase 8B freeze; no tuning, no reselection, no refit")
    print("STATE CONTRACT: reconstruct pre-OOS carry-in portfolio; do NOT start 2025 from artificial cash")
    print("FINAL OOS: signal_date >= 2025-01-01 is opened NOW exactly once")
    print("AFTER SUCCESS: outputs/phase9_oos_consumption_receipt.json prevents a second run")
    summary = build_phase9(root)
    print(json.dumps(summary, indent=2, default=str))
    print("\nArtifacts:")
    for p in [
        "outputs/phase9_summary.json", "outputs/phase9_gate.csv", "outputs/phase9_acceptance_gate.csv",
        "outputs/phase9_performance_summary.csv", "outputs/phase9_predictive_diagnostics.csv",
        "outputs/phase9_oos_consumption_receipt.json", "outputs/phase9_oos_scores.parquet",
        "outputs/phase9_oos_nav_base.csv", "outputs/phase9_oos_nav_stress.csv",
        "outputs/phase9_oos_edge_decisions.csv", "outputs/phase9_oos_milp_audit.csv", "outputs/phase9_edge_realization_20d.csv",
    ]:
        print("  " + p)
    if summary.get("status") != "PASS":
        print("\nWARNING: final OOS evaluation completed but integrity status is FAIL. The holdout is still consumed; do NOT rerun or tune on 2025+.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
