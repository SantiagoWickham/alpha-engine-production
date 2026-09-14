from pathlib import Path
import json, shutil, sys
ROOT=Path(__file__).resolve().parents[1]; WS=ROOT.parent/'ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON'
if not WS.exists(): raise SystemExit(f'V13 workspace missing: {WS}')
(WS/'src'/'alpha_engine_v13').mkdir(parents=True,exist_ok=True); (WS/'config').mkdir(parents=True,exist_ok=True)
for n in ['final_prehodout_review.py','roundtrip_resize_hysteresis.py','active_alpha_persistent_portfolio.py','economic_portfolio_closure.py']:
    shutil.copy2(ROOT/'src'/'alpha_engine_v13'/n,WS/'src'/'alpha_engine_v13'/n)
for n in ['v13_phase3aa.toml','v13_phase3z.toml']: shutil.copy2(ROOT/'config'/n,WS/'config'/n)
print('='*88); print('ALPHA ENGINE V13 - PHASE 3AA: FINAL PRE-HOLDOUT REVIEW + FREEZE'); print('='*88)
print('BUILD: V13_P3AA_FINAL_PREHOLDOUT_REVIEW_FREEZE_2026-09-13'); print(f'V13 WORKSPACE: {WS}')
print('NO OPTIMIZATION / NO RETRAINING / NO POLICY CHANGE'); print('AUDIT: annual returns + annual alpha + turnover + drawdown recovery + freeze hashes'); print('2025+ HOLDOUT: STILL HARD-BLOCKED')
req=[WS/'outputs'/'v13_phase3z_summary.json',WS/'outputs'/'v13_phase3z_nav_20bps.csv',WS/'outputs'/'v13_phase3z_nav_40bps.csv',WS/'outputs'/'v13_phase3z_nav_60bps.csv',WS/'outputs'/'v13_phase3z_universe_lineage.csv',WS/'outputs'/'v13_phase0_summary.json',WS/'outputs'/'v13_phase3s_execution_surface.parquet']
print('PREFLIGHT INPUTS:')
for p in req: print(f"  [{'OK' if p.exists() else 'MISSING'}] {p}")
miss=[p for p in req if not p.exists()]
if miss: raise SystemExit('Missing required inputs: '+', '.join(map(str,miss)))
sys.path.insert(0,str(ROOT/'src')); from alpha_engine_v13.final_prehodout_review import build_phase3aa
s=build_phase3aa(WS); print(json.dumps(s,indent=2,default=str)); raise SystemExit(0 if s.get('status')=='PASS' else 2)
