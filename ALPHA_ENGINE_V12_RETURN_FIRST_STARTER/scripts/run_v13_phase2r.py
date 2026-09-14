from pathlib import Path
import argparse,json,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.adaptive_alpha_rebuild import BUILD,build_phase2r

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--workspace",default=str(ROOT.parent/"ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON")); a=ap.parse_args(); ws=Path(a.workspace)
    if not (ws/"outputs"/"v13_phase1_summary.json").exists(): raise SystemExit("V13 Phase 1 outputs not found")
    for rel in ["config/v13_phase2r.toml","src/alpha_engine_v13/adaptive_alpha_rebuild.py"]:
        src=ROOT/rel; dst=ws/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    print("="*88); print("ALPHA ENGINE V13 - PHASE 2R: ADAPTIVE MULTI-EXPERT ALPHA REBUILD"); print("="*88)
    print(f"BUILD: {BUILD}")
    print("RESEARCH: all 2015-2024 may be used through PURGED WALK-FORWARD; 2025+ remains HARD-BLOCKED")
    print("MODELS: 5 experts per horizon; recency-weighted rolling 5Y training")
    print("TARGETS: rank + absolute return + SPY/QQQ robust excess + future-winner probability")
    print("ENSEMBLE: adaptive expert weights learned from prior OOF evidence; no single architecture winner required")
    print("PORTFOLIO: NOT RUN in this phase; predictor must earn the right to proceed")
    s=build_phase2r(ws); print(json.dumps(s,indent=2,default=str))
    print("\nPhase 2R outputs written. Research FAIL does not delete outputs or open 2025+.")
    return 0
if __name__=="__main__": raise SystemExit(main())
