from pathlib import Path
import argparse, json, shutil, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from alpha_engine_v13.multi_horizon_models import BUILD, build_phase2

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default=str(ROOT.parent / "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"))
    a = ap.parse_args()
    ws = Path(a.workspace)
    if not (ws / "outputs" / "v13_phase1_summary.json").exists():
        raise SystemExit("V13 Phase 1 outputs not found in workspace")
    for rel in ["config/v13_phase2.toml", "src/alpha_engine_v13/multi_horizon_models.py"]:
        src = ROOT / rel
        dst = ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print("=" * 88)
    print("ALPHA ENGINE V13 - PHASE 2: NESTED MULTI-HORIZON MODEL FACTORY")
    print("=" * 88)
    print(f"BUILD: {BUILD}")
    print("2025+ HOLDOUT: HARD-BLOCKED")
    print("HORIZONS: 5/10/20/60/120/252 - ALL RECEIVE AN INDEPENDENT CHAMPION")
    print("PRIMARY MODEL OBJECTIVE: robust future excess return vs SPY / QQQ / Universe-EW")
    print("FEATURE SELECTION: no global outcome-based pre-screen; fold-train only transforms/weights")
    print("NESTING: 2019-20 architecture chosen from 2017-18; 2021-22 chosen from evidence through 2020")
    print("VALIDATION 2023-24: confirmation only; never model selection")
    s = build_phase2(ws)
    print(json.dumps(s, indent=2, default=str))
    return 0 if s["status"] == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
