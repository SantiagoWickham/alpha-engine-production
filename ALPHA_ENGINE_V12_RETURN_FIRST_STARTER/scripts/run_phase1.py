from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_engine_v12.foundation import build_foundation


def main() -> int:
    parser = argparse.ArgumentParser(description="Build V12 Phase 1 data boundary and foundation")
    parser.add_argument("--hash-allowed", action="store_true", help="SHA256 approved inputs (slower)")
    args = parser.parse_args()

    summary = build_foundation(ROOT, hash_allowed=args.hash_allowed)
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 1 FOUNDATION")
    print("=" * 88)
    print(json.dumps(summary, indent=2))
    print("\nArtifacts:")
    print("  outputs/phase1_summary.json")
    print("  outputs/phase1_data_catalog.json")
    print("  outputs/phase1_decision_clock.json")
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
