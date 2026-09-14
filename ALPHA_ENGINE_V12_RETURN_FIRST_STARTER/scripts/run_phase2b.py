from __future__ import annotations

from pathlib import Path
import json

from alpha_engine_v12.price_semantics import build_phase2b


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 2B: PRICE SEMANTICS & CORPORATE ACTION GATE")
    print("=" * 88)
    summary = build_phase2b(root)
    print(json.dumps(summary, indent=2, default=str))
    print("\nArtifacts:")
    for name in [
        "phase2b_summary.json",
        "phase2b_gate.csv",
        "phase2b_price_coverage.csv",
        "phase2b_source_semantics.csv",
        "phase2b_corporate_action_diagnostics.csv",
        "phase2b_adjusted_price_candidates.csv",
        "phase2b_adjusted_price_requirements.csv",
    ]:
        print(f"  outputs/{name}")
    # A FAIL is a valid research result: it blocks target creation but is not a script error.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
