from __future__ import annotations

import json
from pathlib import Path
import sys

from alpha_engine_v12.paths import project_root
from alpha_engine_v12.pit_panel import build_phase2


def main() -> int:
    root = project_root(Path.cwd())
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 2: CANONICAL PIT RESEARCH PANEL")
    print("=" * 88)
    summary = build_phase2(root)
    print(json.dumps(summary, indent=2))
    print("\nArtifacts:")
    for name in [
        "phase2_summary.json",
        "phase2_source_audit.csv",
        "phase2_pit_audit.csv",
        "phase2_panel_schema.json",
        "phase2_market_conflicts.csv",
        "phase2_canonical_pit_panel.parquet",
        "phase2_fundamental_events.parquet",
        "phase2_event_calendar.parquet",
    ]:
        print(f"  outputs/{name}")
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
