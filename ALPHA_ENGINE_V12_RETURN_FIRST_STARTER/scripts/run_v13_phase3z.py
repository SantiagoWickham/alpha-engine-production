from pathlib import Path
import json, shutil, sys
ROOT=Path(__file__).resolve().parents[1]
WS=ROOT.parent/'ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON'
if not WS.exists(): raise SystemExit(f'V13 workspace missing: {WS}')
(WS/'src'/'alpha_engine_v13').mkdir(parents=True,exist_ok=True); (WS/'config').mkdir(parents=True,exist_ok=True)
for name in ['roundtrip_resize_hysteresis.py','active_alpha_persistent_portfolio.py','economic_portfolio_closure.py']:
    shutil.copy2(ROOT/'src'/'alpha_engine_v13'/name,WS/'src'/'alpha_engine_v13'/name)
shutil.copy2(ROOT/'config'/'v13_phase3z.toml',WS/'config'/'v13_phase3z.toml')
print('='*88)
print('ALPHA ENGINE V13 - PHASE 3Z: ROUNDTRIP RESIZE HYSTERESIS')
print('='*88)
print('BUILD: V13_P3Z_ROUNDTRIP_RESIZE_HYSTERESIS_2026-09-13')
print(f'V13 WORKSPACE: {WS}')
print('PREDICTOR: Phase2U frozen; NO retraining')
print('ACTIVE ALPHA: unchanged from Phase3Y')
print('PERSISTENCE: an existing-weight resize must justify its full expected round trip')
print('NO Top-N / cap / fixed holding period; daily review remains active')
print('2025+ HOLDOUT: HARD-BLOCKED')
req=[WS/'outputs'/'v13_phase2u_oof_scores.parquet',WS/'outputs'/'v13_phase1_research_targets.parquet',WS/'outputs'/'v13_phase0_summary.json',WS/'outputs'/'v13_phase2u_summary.json',WS/'outputs'/'v13_phase3y_summary.json',WS/'outputs'/'v13_phase3s_execution_surface.parquet',WS/'config'/'v13_phase3v.toml']
print('PREFLIGHT INPUTS:')
for p in req: print(f"  [{'OK' if p.exists() else 'MISSING'}] {p}")
miss=[p for p in req if not p.exists()]
if miss: raise SystemExit('Missing required inputs: '+', '.join(map(str,miss)))
sys.path.insert(0,str(ROOT/'src'))
from alpha_engine_v13.roundtrip_resize_hysteresis import build_phase3z
s=build_phase3z(WS); print(json.dumps(s,indent=2,default=str)); raise SystemExit(0 if s.get('status')=='PASS' else 2)
