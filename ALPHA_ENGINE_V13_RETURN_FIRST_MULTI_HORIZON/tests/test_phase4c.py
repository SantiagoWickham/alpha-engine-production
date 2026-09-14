import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import checkpoint_v13_holdout_evidence as m

def test_build_manifest():
 with tempfile.TemporaryDirectory() as td:
  r=Path(td); (r/'outputs').mkdir();
  s={'holdout_opened':True,'seal_id':m.EXPECTED_SEAL,'research_freeze_id':'x','economic_verdict':'STRONG_CONFIRMATION','holdout_start':'2025-01-01','holdout_end':'2026-09-04','policy_changed':False,'predictor_retrained_after_holdout_open':False}
  (r/'outputs/v13_phase4_holdout_summary.json').write_text(json.dumps(s))
  (r/'outputs/v13_phase4_holdout_opened.json').write_text(json.dumps({'state':'COMPLETE','seal_id':m.EXPECTED_SEAL}))
  for n in ['v13_phase4_holdout_beta_attribution.csv','v13_phase4_holdout_horizon_evidence.csv','v13_phase4_holdout_nav_20bps.csv','v13_phase4_holdout_nav_40bps.csv','v13_phase4_holdout_nav_60bps.csv','v13_phase4_holdout_scores.parquet','v13_phase4_holdout_advisor.parquet']:
   (r/'outputs'/n).write_bytes(b'x')
  out=m.build(r)
  assert out['economic_verdict']=='STRONG_CONFIRMATION'
  assert len(out['files'])==9
  assert (r/'artifacts/validation/v13_phase4_holdout_evidence_manifest.json').exists()


def test_force_add_exact_ignored_artifact():
 import subprocess
 with tempfile.TemporaryDirectory() as td:
  r=Path(td)
  subprocess.run(['git','init'],cwd=r,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  subprocess.run(['git','config','user.email','test@example.com'],cwd=r,check=True)
  subprocess.run(['git','config','user.name','Test'],cwd=r,check=True)
  (r/'.gitignore').write_text('artifacts/\n',encoding='utf-8')
  (r/'artifacts/validation').mkdir(parents=True)
  f=r/'artifacts/validation/evidence.json'; f.write_text('{}',encoding='utf-8')
  m.git(r,'add','-f','--','artifacts/validation/evidence.json')
  staged,_=m.git(r,'diff','--cached','--name-only')
  assert 'artifacts/validation/evidence.json' in staged
