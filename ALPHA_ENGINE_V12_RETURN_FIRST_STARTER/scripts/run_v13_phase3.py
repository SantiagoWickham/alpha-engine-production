from pathlib import Path
import argparse, json, shutil, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.cross_horizon_advisor import BUILD, build_phase3

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--workspace",default=str(ROOT.parent/"ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON")); a=ap.parse_args(); ws=Path(a.workspace)
    if not (ws/"outputs"/"v13_phase2_summary.json").exists(): raise SystemExit("V13 Phase 2 outputs not found in workspace")
    for rel in ["config/v13_phase3.toml","src/alpha_engine_v13/cross_horizon_advisor.py"]:
        src=ROOT/rel; dst=ws/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    print("="*88); print("ALPHA ENGINE V13 - PHASE 3: CROSS-HORIZON ADVISOR + DYNAMIC PORTFOLIO"); print("="*88)
    print(f"BUILD: {BUILD}")
    print("ADVISOR: 5/10/20/60/120/252 evaluated SIMULTANEOUSLY every session")
    print("HOLDING PERIOD: NONE; every thesis is re-evaluated every session")
    print("CARDINALITY: ENDOGENOUS from positive expected-return LCB; no Top-N")
    print("WEIGHTS: ENDOGENOUS Kelly on posterior mean return / causal covariance; uncertainty gates admission, not sizing twice")
    print("SELECTION: 2019-20 calibration -> 2021-22 policy selection -> 2023-24 confirmation")
    print("EXECUTION: partial per-ticker t+1 execution; one unavailable name cannot cancel the portfolio rebalance")
    print("AUDIT: benchmark semantics + cross-horizon influence exported")
    print("2025+ HOLDOUT: HARD-BLOCKED")
    s=build_phase3(ws); print(json.dumps(s,indent=2,default=str)); return 0 if s["status"]=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
