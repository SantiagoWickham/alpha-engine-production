from pathlib import Path
import json
from alpha_engine_v12.edge_lineage import build_phase7, PHASE7_BUILD


def main() -> int:
    root = Path.cwd()
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 7: EXPECTED EDGE CALIBRATION & ALPHA LINEAGE")
    print("=" * 88)
    print(f"BUILD: {PHASE7_BUILD}")
    print(f"MODULE: {Path(__file__).resolve().parents[1] / 'src' / 'alpha_engine_v12' / 'edge_lineage.py'}")
    print("TEMPORAL CONTRACT: 2019-2020 calibrate -> 2021-2022 select -> 2023-2024 confirm")
    print("FINAL OOS FIREWALL: signal_date >= 2025-01-01 remains untouched")
    print("DECISION RULE: expected_incremental_return - total_cost - uncertainty_buffer > 0")
    out = build_phase7(root)
    print(json.dumps(out, indent=2, default=str))
    print("\nArtifacts:")
    for x in [
        "phase7_summary.json", "phase7_gate.csv", "phase7_edge_calibration_selection.csv",
        "phase7_edge_calibration_validation.csv", "phase7_edge_policy_leaderboard.csv",
        "phase7_validation_confirmation.csv", "phase7_lineage_summary.csv",
        "phase7_lineage_snapshot_audit.csv", "phase7_pre_freeze_candidate.json",
    ]:
        print(f"  outputs/{x}")
    return 0 if out.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
