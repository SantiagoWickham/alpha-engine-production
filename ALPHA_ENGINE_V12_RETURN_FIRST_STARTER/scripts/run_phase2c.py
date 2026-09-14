from __future__ import annotations

import json
from pathlib import Path

import alpha_engine_v12.return_price_enrichment as phase2c_mod
from alpha_engine_v12.return_price_enrichment import PHASE2C_BUILD, build_phase2c


def main() -> int:
    root = Path.cwd()
    print("=" * 88)
    print("ALPHA ENGINE V12 - PHASE 2C: RETURN PRICE ENRICHMENT")
    print("=" * 88)
    print(f"BUILD: {PHASE2C_BUILD}")
    print(f"MODULE: {Path(phase2c_mod.__file__).resolve()}")
    summary = build_phase2c(root)
    print(json.dumps(summary, indent=2, default=str))
    print("\nArtifacts:")
    for name in [
        "phase2c_summary.json",
        "phase2c_gate.csv",
        "phase2c_download_manifest.csv",
        "phase2c_provider_validation.csv",
        "phase2c_ticker_coverage.csv",
        "phase2c_return_price_layer.parquet",
    ]:
        print(f"  outputs/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
