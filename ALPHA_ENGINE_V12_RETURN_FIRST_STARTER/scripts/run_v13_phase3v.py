from pathlib import Path
import argparse,json,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.economic_portfolio_closure import build_phase3v,BUILD


def _preflight(workspace:Path):
    required=[
        "outputs/v13_phase0_summary.json",
        "outputs/v13_phase2u_summary.json",
        "outputs/v13_phase2u_oof_scores.parquet",
        "outputs/v13_phase1_research_targets.parquet",
    ]
    optional=["outputs/v13_phase3s_execution_surface.parquet"]
    rows=[]
    for rel in required:
        p=workspace/rel; rows.append(("REQUIRED",rel,p.exists(),p))
    for rel in optional:
        p=workspace/rel; rows.append(("CACHE",rel,p.exists(),p))
    print("PREFLIGHT INPUTS:")
    for kind,rel,ok,p in rows:
        print(f"  [{kind}] {'OK' if ok else 'MISSING'} | {p}")
    missing=[rel for kind,rel,ok,p in rows if kind=="REQUIRED" and not ok]
    if missing:
        raise FileNotFoundError(f"Phase3V preflight missing required V13 workspace artifacts: {missing}")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--workspace",default=str(ROOT.parent/"ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"))
    a=ap.parse_args(); workspace=Path(a.workspace)
    # Keep Phase3V code/config versioned inside the canonical V13 workspace, exactly like prior V13 phases.
    for rel in ["config/v13_phase3v.toml","src/alpha_engine_v13/economic_portfolio_closure.py"]:
        src=ROOT/rel; dst=workspace/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    print("="*88)
    print("ALPHA ENGINE V13 - PHASE 3V: OOF ECONOMIC PORTFOLIO CLOSURE")
    print("="*88)
    print(f"BUILD: {BUILD}")
    print(f"V13 WORKSPACE: {workspace}")
    print("PREDICTOR: Phase2U accepted on aggregate pre-2025 evidence; 2021-22 is STRESS, not a blocking exam")
    print("ADVISOR: 5/10/20/60/120/252 always evaluated; reliability learned from PRIOR OOF folds only")
    print("PORTFOLIO: endogenous cardinality; no Top-N; no per-name min/max cap; cash allowed")
    print("SELECTION: 2019-2024 full OOF economics, 20/40bps costs; SPY is primary blocking benchmark")
    print("QQQ + Universe-EW: reported as strong comparators, not mandatory winners in every regime")
    print("2025+ HOLDOUT: HARD-BLOCKED")
    _preflight(workspace)
    s=build_phase3v(workspace); print(json.dumps(s,indent=2,default=str)); return 0 if s.get("status")=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
