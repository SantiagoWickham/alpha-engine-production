from pathlib import Path
import argparse, json, shutil, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.fast_portfolio_replay import BUILD, build_fast

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--workspace",default=str(ROOT.parent/"ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON")); a=ap.parse_args(); ws=Path(a.workspace)
    if not (ws/"outputs"/"v13_phase3_advisor_surface.parquet").exists(): raise SystemExit("Cached Phase 3 advisor surface not found. Do NOT retrain; verify FIX2 outputs exist.")
    for rel in ["config/v13_phase3_fast.toml","src/alpha_engine_v13/fast_portfolio_replay.py"]:
        src=ROOT/rel; dst=ws/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    print("="*88); print("ALPHA ENGINE V13 - PHASE 3R: FAST CACHED PORTFOLIO RESEARCH"); print("="*88)
    print(f"BUILD: {BUILD}")
    print("CACHE: REUSE existing multi-horizon advisor; NO model retraining / NO dense-score rebuild")
    print("EXECUTION: observable raw close, independent of research_eligible")
    print("HORIZONS: all six remain active; pre-2021 OOF skill controls reliability, not holding period")
    print("CARDINALITY: endogenous via uncertainty + opportunity-cost sparsity; no Top-N")
    print("2025+ HOLDOUT: HARD-BLOCKED")
    s=build_fast(ws); print(json.dumps(s,indent=2,default=str)); return 0 if s["status"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
