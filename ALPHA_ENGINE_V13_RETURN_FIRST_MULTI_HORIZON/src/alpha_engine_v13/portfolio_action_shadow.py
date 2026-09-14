from __future__ import annotations
import json, math, hashlib
from pathlib import Path
from typing import Any

from alpha_engine_v13 import active_alpha_persistent_portfolio as p3y
from alpha_engine_v13 import sheets_shadow_bridge as p5c

BUILD='V13_P5D_PORTFOLIO_AWARE_SHADOW_ACTIONS_2026-09-13'
EXPECTED_SEAL='46bbbf853561e26625ee3ecbccb6037051556f2f3ca26dcb4e311c165c08d8e9'
EPS=1e-14


def _read_json(p:Path)->dict:
    if not p.exists(): raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding='utf-8'))


def _f(x, default=math.nan):
    try:
        v=float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def _norm(s:Any)->str:
    return ''.join(ch for ch in str(s or '').strip().lower() if ch.isalnum())


def _idx(headers:list[str], *names:str):
    hm={_norm(h):i for i,h in enumerate(headers)}
    for n in names:
        if _norm(n) in hm:return hm[_norm(n)]
    return None


def _parse_positions(snapshot:dict)->dict[str,dict]:
    headers=[str(x or '') for x in snapshot.get('headers',[])]
    rows=snapshot.get('rows') or []
    ti=_idx(headers,'Ticker')
    qi=_idx(headers,'Cantidad','Quantity')
    wi=_idx(headers,'Peso Actual','Peso','Current Weight','Weight')
    mvi=_idx(headers,'Valor Mercado USD Eq.','Valor Mercado USD','Market Value USD Eq.','Market Value')
    # Legacy V8 layout written by actualizarPortfolioV8: ticker=0, qty=1, market_value=4, current_weight=10.
    if ti is None and rows: ti=0
    if qi is None and rows and max(len(r) for r in rows)>1: qi=1
    if mvi is None and rows and max(len(r) for r in rows)>4: mvi=4
    if wi is None and rows and max(len(r) for r in rows)>10: wi=10
    if ti is None: raise RuntimeError(f'POSITIONS_TICKER_COLUMN_NOT_FOUND headers={headers}')
    out={}
    for r in rows:
        if ti>=len(r): continue
        t=str(r[ti] or '').strip().upper()
        if not t: continue
        out[t]={
            'ticker':t,
            'quantity':_f(r[qi]) if qi is not None and qi<len(r) else math.nan,
            'current_weight':max(0.0,_f(r[wi],0.0)) if wi is not None and wi<len(r) else 0.0,
            'market_value_usd_eq':max(0.0,_f(r[mvi],0.0)) if mvi is not None and mvi<len(r) else 0.0,
        }
    return out


def _parse_cash(snapshot:dict)->dict[str,float]:
    headers=[str(x or '') for x in snapshot.get('headers',[])]
    rows=snapshot.get('rows') or []
    ci=_idx(headers,'Moneda','Currency')
    bi=_idx(headers,'Saldo','Balance')
    if ci is None and rows: ci=0
    if bi is None and rows and max(len(r) for r in rows)>1: bi=1
    out={}
    if ci is None:return out
    for r in rows:
        if ci>=len(r):continue
        c=str(r[ci] or '').strip().upper()
        if not c:continue
        out[c]=_f(r[bi],0.0) if bi is not None and bi<len(r) else 0.0
    return out


def _plan_from_contract(contract:dict)->dict[str,dict]:
    plan={}
    for r in contract.get('rows') or []:
        t=str(r.get('ticker','')).strip().upper()
        if not t:continue
        plan[t]={
            'desired':max(0.0,_f(r.get('model_target_weight'),0.0)),
            'alpha_total':_f(r.get('expected_active_total')),
            'entry_ok':bool(r.get('entry_ok',False)),
            'band':max(0.0,_f(r.get('resize_band'),0.0)),
        }
    return plan


def _classify(c:float, e:float)->str:
    c=max(0.0,float(c)); e=max(0.0,float(e))
    if c<=EPS:
        return 'BUY' if e>EPS else 'HOLD'
    if e<=EPS:return 'EXIT'
    d=e-c
    if abs(d)<=1e-12:return 'HOLD'
    return 'BUY' if d>0 else 'REDUCE'


def _reason(action:str,c:float,e:float,p:dict|None)->str:
    if p is None:return 'Held ticker absent from latest V13 plan; exact Phase3Z persistence target is zero.'
    alpha=_f(p.get('alpha_total'))
    desired=max(0.0,_f(p.get('desired'),0.0)); band=max(0.0,_f(p.get('band'),0.0)); entry=bool(p.get('entry_ok',False))
    if c<=EPS:
        if action=='BUY':return 'No current position; sealed Phase3Z entry gate is open.'
        return 'No current position; sealed Phase3Z entry gate is closed.'
    if not math.isfinite(alpha) or alpha<=0:return 'Existing position loses positive expected active alpha; exact Phase3Z rule exits.'
    if desired<=EPS:return 'Existing position retains positive active alpha; Phase3Z persistence holds rather than forcing exit.'
    if abs(desired-c)<=band+1e-15:return 'Current weight lies inside the sealed round-trip-cost resize no-trade band.'
    if action=='BUY':return 'Current weight is below desired weight by more than the sealed resize band.'
    if action=='REDUCE':return 'Current weight is above desired weight by more than the sealed resize band.'
    return 'No portfolio change required under sealed Phase3Z hysteresis.'


def build_portfolio_action_shadow(root:Path)->dict:
    root=root.resolve()
    live_summary,contract=p5c._contract(root)
    if contract.get('seal_id')!=EXPECTED_SEAL: raise RuntimeError('SEAL_MISMATCH')
    if not contract.get('shadow_only',False) or contract.get('real_orders_sent'): raise RuntimeError('LIVE_CONTRACT_NOT_SHADOW')

    ssdir=root/'outputs'/'sheets_shadow'
    pos_snap=_read_json(ssdir/'v13_sheets_positions_snapshot.json')
    cash_snap=_read_json(ssdir/'v13_sheets_cash_snapshot.json')
    mandate_snap=_read_json(ssdir/'v13_sheets_mandate_snapshot.json')
    positions=_parse_positions(pos_snap); cash=_parse_cash(cash_snap); plan=_plan_from_contract(contract)

    # IMPORTANT: This calls the original Phase3Y/3Z economic-target translator.
    # No new threshold, Top-N, holding period or cap is introduced here.
    cur={t:max(0.0,_f(v.get('current_weight'),0.0)) for t,v in positions.items() if _f(v.get('current_weight'),0.0)>EPS}
    econ=p3y._economic_target(cur,plan)

    by_t={str(r.get('ticker','')).strip().upper():r for r in contract.get('rows') or []}
    names=sorted(set(by_t)|set(positions))
    rows=[]
    for t in names:
        r=by_t.get(t,{})
        c=max(0.0,float(cur.get(t,0.0))); e=max(0.0,float(econ.get(t,0.0))); p=plan.get(t)
        action=_classify(c,e)
        rows.append({
            'asof':contract.get('asof'),'seal_id':EXPECTED_SEAL,'ticker':t,'action':action,
            'currently_held':bool(c>EPS),'current_weight':c,'phase3z_economic_target_weight':e,
            'raw_model_target_weight':max(0.0,_f(r.get('model_target_weight'),0.0)),
            'weight_delta':e-c,'resize_band':max(0.0,_f(r.get('resize_band'),0.0)),
            'entry_ok':bool(r.get('entry_ok',False)),'expected_active_total':_f(r.get('expected_active_total')),
            'effective_horizon_sessions':_f(r.get('effective_horizon_sessions')),
            'positive_active_horizon_share':_f(r.get('positive_active_horizon_share')),
            'score_5d':_f(r.get('score_5d')),'score_10d':_f(r.get('score_10d')),'score_20d':_f(r.get('score_20d')),
            'score_60d':_f(r.get('score_60d')),'score_120d':_f(r.get('score_120d')),'score_252d':_f(r.get('score_252d')),
            'reason':_reason(action,c,e,p),
        })

    # Deterministic ordering: actions needing attention first, then target weight.
    pri={'EXIT':0,'REDUCE':1,'BUY':2,'HOLD':3}
    rows.sort(key=lambda x:(pri.get(x['action'],9),-abs(x['weight_delta']),x['ticker']))
    counts={a:sum(1 for x in rows if x['action']==a) for a in ['BUY','HOLD','REDUCE','EXIT']}
    held_count=sum(1 for x in rows if x['currently_held'])
    target_sum=sum(x['phase3z_economic_target_weight'] for x in rows)
    current_sum=sum(x['current_weight'] for x in rows)

    outdir=root/'outputs'/'portfolio_shadow';outdir.mkdir(parents=True,exist_ok=True)
    payload={
        'build':BUILD,'schema_version':'ALPHA_ENGINE_V13_PORTFOLIO_ACTION_SHADOW_V1','seal_id':EXPECTED_SEAL,
        'asof':contract.get('asof'),'source_of_truth':'PYTHON_ALPHA_ENGINE_V13','translator':'ORIGINAL_PHASE3Z_ECONOMIC_TARGET',
        'shadow_only':True,'real_orders_sent':False,'operation_append_called':False,'cash_mutated':False,
        'tuning_performed':False,'rows':rows,
    }
    js=outdir/'v13_portfolio_actions_latest.json';csv=outdir/'v13_portfolio_actions_latest.csv'
    js.write_text(json.dumps(payload,indent=2,default=str),encoding='utf-8')
    import pandas as pd
    pd.DataFrame(rows).to_csv(csv,index=False)

    # Publish DISPLAY-ONLY portfolio-aware rows to _ALERT_STATE. No operation/cash/forward actions.
    api=p5c.SheetApi(p5c.load_cfg(root))
    alert_rows=[]
    for x in rows:
        sev='ACTION' if x['action'] in ('BUY','REDUCE','EXIT') else 'INFO'
        alert_rows.append({
            'ticker':x['ticker'],'action':x['action'],'severity':sev,
            'signal':f"EH_{x['effective_horizon_sessions']:.1f}D" if math.isfinite(x['effective_horizon_sessions']) else 'EH_NA',
            'event':'V13_PORTFOLIO_SHADOW','alpha':x['expected_active_total'] if math.isfinite(x['expected_active_total']) else '',
            'alpha_percentile':'','current_weight':x['current_weight'],'model_weight':x['phase3z_economic_target_weight'],
            'updated_at':contract.get('asof'),
        })
    resp=api.post('alert_state_replace',{'rows':alert_rows})
    rb=api.get('alert_state',limit=5000)
    if int(rb.get('returned',-1))!=len(alert_rows): raise RuntimeError('ALERT_READBACK_ROWCOUNT_MISMATCH')

    digest=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    summary={
        'status':'PASS','phase':'V13-P5D','build':BUILD,'seal_id':EXPECTED_SEAL,'asof':contract.get('asof'),
        'positions_rows_consumed':len(positions),'cash_rows_consumed':len(cash),'mandate_rows_consumed':len(mandate_snap.get('rows') or []),
        'held_tickers':held_count,'contract_tickers':len(by_t),'actions':counts,
        'current_weight_sum_input':current_sum,'phase3z_economic_target_weight_sum':target_sum,
        'cash_snapshot':cash,'weight_basis':'SHEETS_CURRENT_WEIGHT_FIELD (legacy V8 positions; typically invested-equity normalized)',
        'portfolio_action_digest':digest,'alert_rows_published':len(alert_rows),'alert_readback_rows_match':True,
        'python_v13_authoritative':True,'sheets_display_only':True,'shadow_only':True,'real_orders_sent':False,
        'operation_append_called':False,'cash_mutated':False,'forward_ledger_mutated':False,'tuning_performed':False,
        'readback_checks':{'alert_row_count_matches':True,'real_orders_sent_is_false':True},
        'note':'Directional actions are exact Phase3Z hysteresis applied to the current_weight values read from Sheets. No execution is performed.',
        'next':'Review the shadow BUY/HOLD/REDUCE/EXIT output against the real portfolio. If coherent, build a confirmation-gated execution ledger; do not auto-trade.',
    }
    (outdir/'v13_portfolio_actions_summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
    return summary
