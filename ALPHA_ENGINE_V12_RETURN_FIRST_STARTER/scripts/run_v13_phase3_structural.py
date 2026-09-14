from __future__ import annotations
import argparse, json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from alpha_engine_v13.structural_portfolio_research import BUILD, build_structural


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default=str(ROOT.parent / "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"))
    a = ap.parse_args()
    ws = Path(a.workspace)
    cached = ws / "outputs" / "v13_phase3_advisor_surface.parquet"
    if not cached.exists():
        raise SystemExit("Cached Phase 3 advisor surface not found. Do NOT retrain; verify Phase 3 outputs exist.")
    for rel in ["config/v13_phase3_structural.toml", "src/alpha_engine_v13/structural_portfolio_research.py"]:
        src = ROOT / rel; dst = ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print("="*88)
    print("ALPHA ENGINE V13 - PHASE 3S: FAST STRUCTURAL REPAIR")
    print("="*88)
    print(f"BUILD: {BUILD}")
    print("CACHE: reuse existing advisor surface; NO model retraining / NO dense-score rebuild")
    print("EXECUTION: union canonical + Phase2C + provider RAW CLOSE only")
    print("HORIZONS: all six active; weights vary by asset/day from pre-2021 prior + current term structure")
    print("CARDINALITY: endogenous via return/alpha conviction gates; NO Top-N")
    print("2025+ HOLDOUT: HARD-BLOCKED")
    s = build_structural(ws)
    print(json.dumps(s, indent=2, default=str))
    if s.get("status") != "PASS":
        print("\nPhase 3S research gate did not pass. Outputs were still written for diagnosis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
