from pathlib import Path
import argparse, json, shutil, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.alpha_factory import BUILD, build_phase1

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--source-v12-root",default=str(ROOT)); ap.add_argument("--workspace",default=str(ROOT.parent/"ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON")); a=ap.parse_args()
    source=Path(a.source_v12_root); ws=Path(a.workspace)
    if not (ws/"outputs"/"v13_phase0_summary.json").exists(): raise SystemExit("V13 Phase 0 outputs not found in workspace")
    for rel in ["config/v13_phase1.toml","src/alpha_engine_v13/alpha_factory.py"]:
        src=ROOT/rel; dst=ws/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    print("="*88); print("ALPHA ENGINE V13 - PHASE 1: FRESH MULTI-HORIZON ALPHA FACTORY"); print("="*88); print(f"BUILD: {BUILD}"); print("2025+ RESEARCH SELECTION: HARD-BLOCKED"); print("HORIZONS: 5/10/20/60/120/252 ALL ACTIVE"); print("FEATURE ADMISSION: DEVELOPMENT ONLY; validation is diagnostic only"); print("BENCHMARK ECONOMICS: SPY / QQQ / UNIVERSE EQUAL-WEIGHT")
    s=build_phase1(source,ws); print(json.dumps(s,indent=2,default=str)); return 0 if s["status"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
