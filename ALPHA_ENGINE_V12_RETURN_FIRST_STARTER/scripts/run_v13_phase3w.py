from pathlib import Path
import argparse, json, shutil, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from alpha_engine_v13.preholdout_freeze import build_phase3w, BUILD


def _preflight(workspace: Path):
    required = [
        "outputs/v13_phase3v_summary.json",
        "outputs/v13_phase3v_gate.csv",
        "outputs/v13_phase3v_selected_policy.json",
        "outputs/v13_phase3v_policy_leaderboard.csv",
        "outputs/v13_phase2u_oof_scores.parquet",
        "outputs/v13_phase1_research_targets.parquet",
        "outputs/v13_phase0_summary.json",
        "outputs/v13_phase2u_summary.json",
        "config/v13_phase3v.toml",
        "src/alpha_engine_v13/economic_portfolio_closure.py",
    ]
    print("PREFLIGHT INPUTS:")
    missing=[]
    for rel in required:
        p=workspace/rel; ok=p.exists(); print(f"  [REQUIRED] {'OK' if ok else 'MISSING'} | {p}")
        if not ok: missing.append(rel)
    if missing: raise FileNotFoundError(f"Phase3W preflight missing: {missing}")


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--workspace", default=str(ROOT.parent/"ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON")); a=ap.parse_args(); workspace=Path(a.workspace)
    for rel in ["config/v13_phase3w.toml","src/alpha_engine_v13/preholdout_freeze.py"]:
        src=ROOT/rel; dst=workspace/rel; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src,dst)
    print("="*88)
    print("ALPHA ENGINE V13 - PHASE 3W: PRE-HOLDOUT STRESS + FREEZE")
    print("="*88)
    print(f"BUILD: {BUILD}")
    print(f"V13 WORKSPACE: {workspace}")
    print("POLICY: reuse the already-selected Phase3V policy; NO reselection")
    print("COVERAGE: all-six OOF row completeness is diagnostic; dynamic available-horizon weights must renormalize causally")
    print("STRESS: fixed policy at 20/40/60/80/100 bps round-trip costs")
    print("FREEZE: hash predictor/policy/config/code before any 2025+ access")
    print("2025+ HOLDOUT: STILL HARD-BLOCKED")
    _preflight(workspace)
    s=build_phase3w(workspace); print(json.dumps(s, indent=2, default=str)); return 0 if s.get("status")=="PASS" else 2

if __name__=="__main__": raise SystemExit(main())
