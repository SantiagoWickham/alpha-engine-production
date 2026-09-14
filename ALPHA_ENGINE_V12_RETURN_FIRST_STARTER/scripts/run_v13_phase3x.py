from pathlib import Path
import json, shutil, sys
ROOT=Path(__file__).resolve().parents[1]
WS=ROOT.parent/'ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON'
if not WS.exists(): raise SystemExit(f'V13 workspace missing: {WS}')
# copy module into V13 workspace for audit trail
(WS/'src'/'alpha_engine_v13').mkdir(parents=True,exist_ok=True)
shutil.copy2(ROOT/'src'/'alpha_engine_v13'/'alpha_attribution_audit.py',WS/'src'/'alpha_engine_v13'/'alpha_attribution_audit.py')
print('='*88)
print('ALPHA ENGINE V13 - PHASE 3X: ALPHA ATTRIBUTION + TURNOVER AUDIT')
print('='*88)
print('BUILD: V13_P3X_ALPHA_ATTRIBUTION_TURNOVER_AUDIT_2026-09-13')
print(f'V13 WORKSPACE: {WS}')
print('NO OPTIMIZATION: selected Phase3V policy is replayed unchanged')
print('AUDIT: beta/universe attribution + UEW integrity + conviction + turnover + holding persistence')
print('2025+ HOLDOUT: HARD-BLOCKED')
required=[WS/'outputs'/'v13_phase3v_selected_policy.json',WS/'outputs'/'v13_phase2u_oof_scores.parquet',WS/'outputs'/'v13_phase1_research_targets.parquet',WS/'config'/'v13_phase3v.toml',WS/'outputs'/'v13_phase0_summary.json',WS/'outputs'/'v13_phase2u_summary.json']
print('PREFLIGHT INPUTS:')
for p in required: print(f"  [{'OK' if p.exists() else 'MISSING'}] {p}")
miss=[p for p in required if not p.exists()]
if miss: raise SystemExit('Missing required inputs: '+', '.join(map(str,miss)))
sys.path.insert(0,str(ROOT/'src'))
from alpha_engine_v13.alpha_attribution_audit import build_audit
s=build_audit(WS); print(json.dumps(s,indent=2,default=str))
