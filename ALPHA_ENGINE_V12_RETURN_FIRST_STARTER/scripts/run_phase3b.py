from __future__ import annotations
import json
from pathlib import Path
import alpha_engine_v12.termination_audit as mod
from alpha_engine_v12.termination_audit import PHASE3B_BUILD, build_phase3b

def main() -> int:
    root = Path.cwd()
    print("="*88)
    print("ALPHA ENGINE V12 - PHASE 3B: UNRESOLVED TERMINATION AUDIT")
    print("="*88)
    print(f"BUILD: {PHASE3B_BUILD}")
    print(f"MODULE: {Path(mod.__file__).resolve()}")
    summary = build_phase3b(root)
    print(json.dumps(summary, indent=2, default=str))
    print("\nArtifacts:")
    for n in ["phase3b_summary.json","phase3b_unresolved_tickers.csv","phase3b_classification_summary.csv","phase3b_repair_plan.csv","phase3b_unresolved_sample.csv"]:
        print(f"  outputs/{n}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
