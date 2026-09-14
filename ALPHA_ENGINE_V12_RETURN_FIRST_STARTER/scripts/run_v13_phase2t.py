from pathlib import Path
import argparse, json, shutil, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.regime_router import BUILD, build_router

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--workspace",default=str(ROOT.parent/"ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON")); a=ap.parse_args(); ws=Path(a.workspace)
    req=ws/"outputs"/"v13_phase2s_oof_scores.parquet"
    if not req.exists(): raise SystemExit(f"Phase2S cached scores not found: {req}")
    rel="src/alpha_engine_v13/regime_router.py"; dst=ws/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(ROOT/rel,dst)
    print("="*88); print("ALPHA ENGINE V13 - PHASE 2T: REGIME ROUTER META-ADVISOR"); print("="*88)
    print(f"BUILD: {BUILD}")
    print("CACHE: Phase2S OOF scores + enriched macro surface; NO expert retraining")
    print("ROUTER: each horizon remains evaluated; confidence changes by regime and prior OOF evidence")
    print("NESTING: 2021-22 router can use only 2017-20 OOF; 2023-24 can use only 2017-22")
    print("PORTFOLIO: NOT RUN; this tests whether regime routing fixes the predictor/advisor layer")
    print("2025+ HOLDOUT: HARD-BLOCKED")
    s=build_router(ws); print(json.dumps(s,indent=2,default=str))
    print("\nPhase 2T outputs written. No 2025+ data was opened.")
    return 0
if __name__=="__main__": raise SystemExit(main())
