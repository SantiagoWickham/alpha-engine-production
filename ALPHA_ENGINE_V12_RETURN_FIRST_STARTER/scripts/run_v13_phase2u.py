from pathlib import Path
import argparse,json,shutil,sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.event_sector_incremental_alpha import BUILD,build_phase2u

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--workspace",default=str(ROOT.parent/"ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON")); a=ap.parse_args(); ws=Path(a.workspace)
    for rel in ["config/v13_phase2u.toml","src/alpha_engine_v13/event_sector_incremental_alpha.py"]:
        src=ROOT/rel; dst=ws/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    print("="*88); print("ALPHA ENGINE V13 - PHASE 2U: EVENT + SECTOR INCREMENTAL ALPHA"); print("="*88); print(f"BUILD: {BUILD}")
    print("CACHE: Phase2R OOF is the base predictor; NO base-model retraining")
    print("NEW PIT INFORMATION: SEC earnings/filing events + sector/rates/inflation/commodity rotation")
    print("STACKING: only prior OOF folds train each new-info meta model")
    print("2025+ HOLDOUT: HARD-BLOCKED; target maturity must remain before each fold end")
    s=build_phase2u(ws); print(json.dumps(s,indent=2,default=str)); print("\nPhase 2U outputs written. No portfolio and no 2025+ data were opened.")
    return 0
if __name__=="__main__": raise SystemExit(main())
