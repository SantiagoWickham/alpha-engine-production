from pathlib import Path
import json
from alpha_engine_v12.execution_parity import PHASE8B_BUILD, build_phase8b


def main():
    root = Path(__file__).resolve().parents[1]
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 8B: PRE-OOS EXECUTION PARITY LOCK")
    print("=" * 88)
    print(f"BUILD: {PHASE8B_BUILD}")
    print("CORRECTION: net-edge membership is now weighted by the frozen optimizer/MILP on actual NAV trade events")
    print("PARAMETER RESELECTION: FORBIDDEN")
    print("FINAL OOS FIREWALL: signal_date >= 2025-01-01 remains unopened")
    summary = build_phase8b(root)
    print(json.dumps(summary, indent=2))
    print("\nArtifacts:")
    for p in [
        "outputs/phase8b_summary.json","outputs/phase8b_gate.csv","outputs/phase8b_validation_confirmation.csv",
        "outputs/phase8b_execution_model_spec.json","outputs/phase8b_freeze_manifest.json",
        "outputs/phase8b_execution_parity_nav.csv","outputs/phase8b_execution_parity_edge_decisions.csv",
        "outputs/phase8b_execution_parity_milp_audit.csv",
    ]:
        print("  " + p)
    return 0 if summary.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
