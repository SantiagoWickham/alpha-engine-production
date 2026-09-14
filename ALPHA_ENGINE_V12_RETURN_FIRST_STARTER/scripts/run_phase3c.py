from __future__ import annotations
import json
from pathlib import Path
import alpha_engine_v12.terminal_repair as mod
from alpha_engine_v12.terminal_repair import PHASE3C_BUILD, build_phase3c


def main() -> int:
    root = Path.cwd()
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 3C: TERMINAL OUTCOME REPAIR")
    print("=" * 88)
    print(f"BUILD: {PHASE3C_BUILD}")
    print(f"MODULE: {Path(mod.__file__).resolve()}")
    summary = build_phase3c(root)
    print(json.dumps(summary, indent=2, default=str))
    print("\nArtifacts:")
    for name in ["phase3c_summary.json", "phase3c_gate.csv", "phase3c_terminal_outcome_overlay.csv", "phase3c_research_exclusions.csv", "phase3c_evidence_audit.csv"]:
        print(f"  outputs/{name}")
    if summary.get("status") != "PASS":
        print("\nPHASE 3C GATE FAILED. Do not rebuild alpha research.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
