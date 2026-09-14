from pathlib import Path
import argparse, json, shutil, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.regime_tail_alpha_rebuild import BUILD, build_phase2s

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--workspace",default=str(ROOT.parent/"ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON")); a=ap.parse_args(); ws=Path(a.workspace)
    if not (ws/"outputs"/"v13_phase1_summary.json").exists(): raise SystemExit("V13 Phase 1 outputs not found")
    for rel in ["config/v13_phase2s.toml","src/alpha_engine_v13/regime_tail_alpha_rebuild.py"]:
        src=ROOT/rel; dst=ws/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    print("="*88); print("ALPHA ENGINE V13 - PHASE 2S: REGIME + TAIL + RESIDUAL ALPHA REBUILD"); print("="*88)
    print(f"BUILD: {BUILD}")
    print("RESEARCH: 2015-2024 purged walk-forward; 2025+ HARD-BLOCKED")
    print("INFORMATION EXPANSION: SPY/QQQ/IWM/TLT/HYG/UUP/VIX raw-close regime proxies + PIT beta exposures")
    print("TARGETS: beta-neutral residual alpha + upside-tail probability + downside avoidance")
    print("ENSEMBLE: nested expert weighting from PRIOR folds only; no post-hoc single winner")
    print("PORTFOLIO: NOT RUN; predictor must recover the 2021-2022 regime before portfolio research resumes")
    s=build_phase2s(ws); print(json.dumps(s,indent=2,default=str)); print("\nPhase 2S outputs written. 2025+ remains unopened regardless of PASS/FAIL.")
    return 0
if __name__=="__main__": raise SystemExit(main())
