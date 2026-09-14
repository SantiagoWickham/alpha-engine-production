from __future__ import annotations

import json
from pathlib import Path

import alpha_engine_v12.return_targets as phase3_mod
from alpha_engine_v12.return_targets import PHASE3_BUILD, build_phase3


def main() -> int:
    root = Path.cwd()
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 3: RETURN TARGET ENGINE")
    print("=" * 88)
    print(f"BUILD: {PHASE3_BUILD}")
    print(f"MODULE: {Path(phase3_mod.__file__).resolve()}")
    print("HORIZON SEMANTICS: TICKER_OBSERVED_TRADING_SESSIONS")
    print("TERMINAL SEMANTICS: PHASE3C_VALIDATED_TARGET_ONLY_OVERLAY")
    summary = build_phase3(root)
    print(json.dumps(summary, indent=2, default=str))
    print("\nArtifacts:")
    for name in [
        "phase3_summary.json",
        "phase3_gate.csv",
        "phase3_horizon_diagnostics.csv",
        "phase3_target_schema.json",
        "phase3_return_targets.parquet",
    ]:
        print(f"  outputs/{name}")
    if summary.get("status") != "PASS":
        print("\nPHASE 3 GATE FAILED. Do not build alpha features/model yet.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
