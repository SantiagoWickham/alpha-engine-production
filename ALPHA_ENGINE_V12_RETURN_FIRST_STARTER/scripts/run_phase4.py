from __future__ import annotations
import json
from pathlib import Path
import alpha_engine_v12.feature_research as mod
from alpha_engine_v12.feature_research import PHASE4_BUILD, build_phase4


def main() -> int:
    root = Path.cwd()
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 4: LEAKAGE-FREE FEATURE LIBRARY & PREDICTIVE RESEARCH")
    print("=" * 88)
    print(f"BUILD: {PHASE4_BUILD}")
    print(f"MODULE: {Path(mod.__file__).resolve()}")
    print("FINAL OOS FIREWALL: signal_date >= 2025-01-01 is NOT used for predictive research")
    print("PURGING: target_end_date must remain inside DEVELOPMENT or VALIDATION boundary")
    summary = build_phase4(root)
    print(json.dumps(summary, indent=2, default=str))
    print("\nArtifacts:")
    for name in [
        "phase4_summary.json", "phase4_gate.csv", "phase4_feature_schema.json",
        "phase4_feature_coverage.csv", "phase4_price_source_manifest.csv",
        "phase4_predictive_diagnostics.csv", "phase4_candidate_features.csv",
        "phase4_family_summary.csv", "phase4_research_partitions.csv",
        "phase4_feature_library.parquet",
    ]:
        print(f"  outputs/{name}")
    if summary.get("status") != "PASS":
        print("\nPHASE 4 INTEGRITY GATE FAILED. Do not fit alpha models.")
        return 2
    print(f"\nRESEARCH READINESS: {(summary.get('predictive_evidence') or {}).get('readiness')}")
    print("Do not inspect or tune on final OOS. Send the SMALL diagnostic files to ChatGPT before model research.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
