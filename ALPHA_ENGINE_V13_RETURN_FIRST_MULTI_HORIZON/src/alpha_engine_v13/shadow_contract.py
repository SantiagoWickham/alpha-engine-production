from __future__ import annotations
import hashlib, json, tomllib
from dataclasses import dataclass
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from alpha_engine_v13 import final_holdout as p4
from alpha_engine_v13 import roundtrip_resize_hysteresis as p3z
from alpha_engine_v13 import economic_portfolio_closure as p3v
from alpha_engine_v13 import alpha_factory as p1

BUILD="V13_P5A_SHADOW_PRODUCTION_PARITY_CONTRACT_2026-09-13"
H=(5,10,20,60,120,252)

@dataclass(frozen=True)
class Cfg: p:dict

def load_cfg(root:Path)->Cfg:
    with (root/'config'/'v13_phase5.toml').open('rb') as f:return Cfg(tomllib.load(f)['v13_phase5'])

def _sha_file(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def _sha_payload(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

def _date(s):return pd.to_datetime(s,errors='coerce').dt.tz_localize(None).dt.normalize().astype('datetime64[ns]')
def _ticker(s):return s.astype(str).str.upper().str.replace('.', '-', regex=False).str.strip()

def verify_seal_compat(root:Path,cfg:Cfg)->dict:
    m=json.loads((root/cfg.p['seal_manifest']).read_text(encoding='utf-8')); expected=str(m.get('seal_id'))
    if expected!=str(cfg.p['expected_seal_id']):raise RuntimeError('UNEXPECTED_SEAL_ID')
    core={k:v for k,v in m.items() if k!='seal_id'}
    # Phase4 known JSON-key compatibility: restore original integer horizon keys only.
    hr=core.get('horizon_reliability',{})
    core['horizon_reliability']={int(k):v for k,v in hr.items()}
    if _sha_payload(core)!=expected:raise RuntimeError('SEAL_COMPAT_RECOMPUTE_FAILED')
    bad=[]
    for r in m.get('files',[]):
        p=root/r['path']
        if not p.exists():bad.append((r['path'],'MISSING'))
        elif _sha_file(p)!=r['sha256']:bad.append((r['path'],'SHA256_MISMATCH'))
    if bad:raise RuntimeError(f'SEALED_FILE_MISMATCH {bad[:3]}')
    return m

def validate_observed_holdout(root:Path,cfg:Cfg)->dict:
    s=json.loads((root/cfg.p['holdout_summary']).read_text(encoding='utf-8'))
    mk=json.loads((root/cfg.p['holdout_marker']).read_text(encoding='utf-8'))
    if s.get('status')!='PASS' or not s.get('holdout_opened'):raise RuntimeError('HOLDOUT_NOT_COMPLETE')
    if s.get('economic_verdict')!=cfg.p['expected_holdout_verdict']:raise RuntimeError('UNEXPECTED_HOLDOUT_VERDICT')
    if s.get('policy_changed') is not False or s.get('predictor_retrained_after_holdout_open') is not False:raise RuntimeError('HOLDOUT_IMMUTABILITY_BREACH')
    if mk.get('state')!='COMPLETE' or mk.get('seal_id')!=cfg.p['expected_seal_id']:raise RuntimeError('HOLDOUT_MARKER_INVALID')
    return s

def _source_root(root:Path)->Path:
    x=json.loads((root/'outputs'/'v13_phase0_summary.json').read_text(encoding='utf-8'))
    p=x.get('source_manifest',{}).get('source_v12_root')
    if not p:raise RuntimeError('source_v12_root missing')
    return Path(p)

def replay_advisor_parity(root:Path,cfg:Cfg,bundle:dict):
    scores=pd.read_parquet(root/cfg.p['holdout_scores']); scores['signal_date']=_date(scores.signal_date);scores['ticker']=_ticker(scores.ticker)
    saved=pd.read_parquet(root/cfg.p['holdout_advisor']); saved['signal_date']=_date(saved.signal_date);saved['ticker']=_ticker(saved.ticker)
    rep=p4._advisor_from_sealed(scores,bundle)
    keys=['signal_date','ticker']; cols=[c for c in rep.columns if c not in keys and c!='fold']
    z=saved[keys+cols].merge(rep[keys+cols],on=keys,suffixes=('_saved','_replay'),validate='one_to_one')
    if len(z)!=len(saved) or len(z)!=len(rep):raise RuntimeError('ADVISOR_KEY_PARITY_FAILED')
    diffs={}
    for c in cols:
        a=pd.to_numeric(z[c+'_saved'],errors='coerce').to_numpy(float);b=pd.to_numeric(z[c+'_replay'],errors='coerce').to_numpy(float)
        mask=np.isfinite(a)|np.isfinite(b)
        d=np.nanmax(np.abs(a[mask]-b[mask])) if mask.any() else 0.0
        diffs[c]=float(d)
    mx=max(diffs.values()) if diffs else 0.0
    if mx>float(cfg.p['parity_tolerance']):raise RuntimeError(f'ADVISOR_NUMERIC_PARITY_FAILED max_abs_diff={mx}')
    return scores,saved,rep,mx,diffs

def _latest_market(root:Path, latest:pd.Timestamp):
    source=_source_root(root); cfg1=p1.load_cfg(root); full=p1.Cfg({**cfg1.p,'holdout_start':'2100-01-01'})
    market_full,_=p4._load_full_market(source,full); bench=p4._load_full_bench(source,full,market_full)
    c=pd.read_parquet(source/'outputs'/'phase2_canonical_pit_panel.parquet',columns=['date','ticker','close','research_eligible'])
    r=pd.read_parquet(source/'outputs'/'phase2c_return_price_layer.parquet',columns=['date','ticker','target_total_return_price'])
    c['date']=_date(c.date);c['ticker']=_ticker(c.ticker);r['date']=_date(r.date);r['ticker']=_ticker(r.ticker)
    surf=c.merge(r,on=['date','ticker'],how='left');surf['execution_close']=pd.to_numeric(surf.close,errors='coerce');surf['mark_price']=pd.to_numeric(surf.target_total_return_price,errors='coerce');surf['research_eligible']=surf.research_eligible.fillna(False).astype(bool)
    surf=surf[['date','ticker','execution_close','mark_price','research_eligible']]
    spy=bench.dropna(subset=['SPY']).drop_duplicates('date').set_index('date')['SPY']
    m=p3v.prepare_market(surf,spy,latest-pd.Timedelta(days=150),latest+pd.Timedelta(days=1),int(p3z.load_cfg(root).p['risk_lookback_sessions']))
    return m

def build_contract(root:Path)->dict:
    cfg=load_cfg(root);seal=verify_seal_compat(root,cfg);hs=validate_observed_holdout(root,cfg)
    bundle=joblib.load(root/cfg.p['sealed_model_bundle'])
    scores,saved,rep,mx,diffs=replay_advisor_parity(root,cfg,bundle)
    latest=pd.Timestamp(saved.signal_date.max()); adv=saved[saved.signal_date.eq(latest)].copy()
    market=_latest_market(root,latest); plans=p3z.build_plans(adv,market,p3z.load_cfg(root)); plan=plans.get(latest,{})
    piv=scores[scores.signal_date.eq(latest)].pivot(index='ticker',columns='horizon_sessions',values='score').reset_index();piv.columns=['ticker']+[f'score_{int(c)}d' for c in piv.columns[1:]]
    out=adv.drop(columns=['fold'],errors='ignore').merge(piv,on='ticker',how='left',validate='one_to_one')
    out['expected_active_total']=out.expected_active_per_session*out.effective_horizon_sessions
    out['model_target_weight']=out.ticker.map(lambda t:float(plan.get(str(t),{}).get('desired',0.0)))
    out['entry_ok']=out.ticker.map(lambda t:bool(plan.get(str(t),{}).get('entry_ok',False)))
    out['resize_band']=out.ticker.map(lambda t:float(plan.get(str(t),{}).get('band',1.0)))
    out['model_intent']=np.where(out.entry_ok & out.model_target_weight.gt(0),'ELIGIBLE_ENTRY','NO_ENTRY')
    out.insert(0,'seal_id',cfg.p['expected_seal_id']);out.insert(0,'asof',latest)
    out=out.sort_values(['model_target_weight','expected_active_total'],ascending=[False,False]).reset_index(drop=True)
    sw=float(out.model_target_weight.sum())
    if sw>1.0000001:raise RuntimeError(f'TARGET_WEIGHT_SUM_GT_1 {sw}')
    sd=root/cfg.p['shadow_dir'];sd.mkdir(parents=True,exist_ok=True)
    csv=sd/'v13_shadow_contract_latest.csv';js=sd/'v13_shadow_contract_latest.json';summ=sd/'v13_shadow_contract_summary.json'
    out.to_csv(csv,index=False)
    payload={'build':BUILD,'mode':'SHADOW_CONTRACT_PARITY','shadow_only':True,'real_orders_sent':False,'tuning_performed':False,'seal_id':cfg.p['expected_seal_id'],'asof':str(latest.date()),'rows':out.to_dict(orient='records')}
    js.write_text(json.dumps(payload,indent=2,default=str),encoding='utf-8')
    summary={'status':'PASS','phase':'V13-P5A','build':BUILD,'seal_id':cfg.p['expected_seal_id'],'holdout_verdict':hs['economic_verdict'],'asof':str(latest.date()),'advisor_rows':int(len(out)),'advisor_parity_max_abs_diff':mx,'target_weight_sum':sw,'entry_eligible_count':int(out.entry_ok.sum()),'positive_target_count':int(out.model_target_weight.gt(0).sum()),'shadow_only':True,'real_orders_sent':False,'tuning_performed':False,'production_contract_csv':str(csv.relative_to(root)).replace('\\','/'),'production_contract_json':str(js.relative_to(root)).replace('\\','/'),'next':'If PASS, extend the exact sealed inference pipeline to new completed sessions only; then connect Sheets/App Script as portfolio/input/output interface.'}
    summ.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary
