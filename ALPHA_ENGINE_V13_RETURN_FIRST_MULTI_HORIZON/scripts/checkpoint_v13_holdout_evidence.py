from __future__ import annotations
import hashlib, json, shutil, subprocess, sys
from pathlib import Path

EXPECTED_SEAL='46bbbf853561e26625ee3ecbccb6037051556f2f3ca26dcb4e311c165c08d8e9'
TAG='v13-holdout-observed-46bbbf85'
BUILD='V13_P4C_OBSERVED_HOLDOUT_EVIDENCE_CHECKPOINT_2026-09-13'
SMALL=[
 'outputs/v13_phase4_holdout_summary.json',
 'outputs/v13_phase4_holdout_beta_attribution.csv',
 'outputs/v13_phase4_holdout_horizon_evidence.csv',
 'outputs/v13_phase4_holdout_opened.json',
]
HASH_ONLY=[
 'outputs/v13_phase4_holdout_nav_20bps.csv',
 'outputs/v13_phase4_holdout_nav_40bps.csv',
 'outputs/v13_phase4_holdout_nav_60bps.csv',
 'outputs/v13_phase4_holdout_scores.parquet',
 'outputs/v13_phase4_holdout_advisor.parquet',
]

def sha(p:Path):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def git(root,*args,check=True):
 r=subprocess.run(['git',*args],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if check and r.returncode: raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
 return r.stdout.strip(),r.returncode

def build(root:Path):
 summary_p=root/SMALL[0]; marker_p=root/SMALL[3]
 if not summary_p.exists() or not marker_p.exists(): raise FileNotFoundError('Completed Phase4 holdout outputs are required')
 s=json.loads(summary_p.read_text(encoding='utf-8')); m=json.loads(marker_p.read_text(encoding='utf-8'))
 if s.get('holdout_opened') is not True or m.get('state')!='COMPLETE': raise RuntimeError('Phase4 holdout is not COMPLETE')
 if s.get('seal_id')!=EXPECTED_SEAL or m.get('seal_id')!=EXPECTED_SEAL: raise RuntimeError('Unexpected seal id')
 if s.get('policy_changed') is not False or s.get('predictor_retrained_after_holdout_open') is not False: raise RuntimeError('Holdout economics were modified after open')
 rows=[]
 for rel in SMALL+HASH_ONLY:
  p=root/rel
  if not p.exists(): raise FileNotFoundError(rel)
  rows.append({'path':rel,'sha256':sha(p),'bytes':p.stat().st_size,'stored_in_git':rel in SMALL})
 art=root/'artifacts'/'validation'; art.mkdir(parents=True,exist_ok=True)
 for rel in SMALL:
  shutil.copy2(root/rel, art/Path(rel).name)
 manifest={
  'build':BUILD,'seal_id':EXPECTED_SEAL,'research_freeze_id':s.get('research_freeze_id'),
  'economic_verdict':s.get('economic_verdict'),'holdout_start':s.get('holdout_start'),'holdout_end':s.get('holdout_end'),
  'policy_changed':False,'predictor_retrained_after_holdout_open':False,
  'files':rows,
  'note':'Observed 2025+ validation evidence. This checkpoint is archival only and MUST NOT be used to retune V13.'
 }
 mp=art/'v13_phase4_holdout_evidence_manifest.json'; mp.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 doc=root/'docs'/'V13_OBSERVED_HOLDOUT.md'; doc.parent.mkdir(exist_ok=True)
 doc.write_text(f'''# V13 observed 2025+ holdout\n\n- Seal: `{EXPECTED_SEAL}`\n- Verdict: `{s.get('economic_verdict')}`\n- Window: `{s.get('holdout_start')}` to `{s.get('holdout_end')}`\n- Policy changed after open: `false`\n- Predictor retrained after open: `false`\n\nThis evidence is observed validation data and is not a tuning set. Large NAV/parquet outputs are hash-pinned in `artifacts/validation/v13_phase4_holdout_evidence_manifest.json` rather than committed to Git.\n''',encoding='utf-8')
 return manifest

def main():
 root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path.cwd().resolve()
 manifest=build(root)
 print(json.dumps(manifest,indent=2))
 files=['artifacts/validation/v13_phase4_holdout_summary.json','artifacts/validation/v13_phase4_holdout_beta_attribution.csv','artifacts/validation/v13_phase4_holdout_horizon_evidence.csv','artifacts/validation/v13_phase4_holdout_opened.json','artifacts/validation/v13_phase4_holdout_evidence_manifest.json','docs/V13_OBSERVED_HOLDOUT.md']
 # artifacts/validation is intentionally ignored by the repository's general .gitignore.
 # Force-add ONLY the exact archival evidence files listed above; never force-add the directory broadly.
 git(root,'add','-f','--',*files)
 staged,_=git(root,'diff','--cached','--name-only')
 if not staged.strip(): print('Evidence checkpoint already staged/committed; no new commit required.')
 else:
  git(root,'commit','-m','validation: archive observed V13 2025+ holdout 46bbbf85')
 # Ensure main is published before tag.
 git(root,'push','origin','main')
 _,rc=git(root,'rev-parse','-q','--verify',f'refs/tags/{TAG}',check=False)
 if rc!=0: git(root,'tag','-a',TAG,'-m',f'Observed V13 2025+ holdout; sealed model {EXPECTED_SEAL}')
 git(root,'push','origin',TAG)
 commit,_=git(root,'rev-parse','HEAD')
 print('\n'+'='*60)
 print('OBSERVED HOLDOUT EVIDENCE CHECKPOINT PUBLISHED')
 print('Commit:',commit)
 print('Tag:   ',TAG)
 print('Seal:  ',EXPECTED_SEAL)
 print('Verdict:',manifest['economic_verdict'])
 print('NO MODEL OR POLICY CHANGE WAS MADE.')
 print('='*60)
 return 0
if __name__=='__main__': raise SystemExit(main())
