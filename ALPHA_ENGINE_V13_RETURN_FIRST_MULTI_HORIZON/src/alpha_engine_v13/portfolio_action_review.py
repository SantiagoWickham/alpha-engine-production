from __future__ import annotations
import json, math, hashlib
from pathlib import Path
from typing import Any

BUILD='V13_P5E_PORTFOLIO_ACTION_REVIEW_BASIS_AUDIT_2026-09-13'
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


def _digest(obj:Any)->str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


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
    qi=_idx(headers,'Cantidad','Quantity','Qty')
    wi=_idx(headers,'Peso Actual','Peso','Current Weight','Weight')
    mvi=_idx(headers,'Valor Mercado USD Eq.','Valor Mercado USD','Market Value USD Eq.','Market Value')
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


def _review(root:Path)->tuple[dict,list[dict],list[dict],list[dict]]:
    root=root.resolve()
    ssdir=root/'outputs'/'sheets_shadow'
    pdir=root/'outputs'/'portfolio_shadow'
    pos=_parse_positions(_read_json(ssdir/'v13_sheets_positions_snapshot.json'))
    cash=_parse_cash(_read_json(ssdir/'v13_sheets_cash_snapshot.json'))
    actions_payload=_read_json(pdir/'v13_portfolio_actions_latest.json')
    summary=_read_json(pdir/'v13_portfolio_actions_summary.json')
    if summary.get('status')!='PASS': raise RuntimeError('PHASE5D_NOT_PASS')
    if summary.get('seal_id')!=EXPECTED_SEAL or actions_payload.get('seal_id')!=EXPECTED_SEAL: raise RuntimeError('SEAL_MISMATCH')
    if not actions_payload.get('shadow_only',False) or actions_payload.get('real_orders_sent'): raise RuntimeError('ACTIONS_NOT_SHADOW')

    rows=actions_payload.get('rows') or []
    by_t={str(r.get('ticker','')).upper():r for r in rows}
    held=[]
    for t,p in sorted(pos.items()):
        q=_f(p.get('quantity'))
        mv=max(0.0,_f(p.get('market_value_usd_eq'),0.0))
        cw=max(0.0,_f(p.get('current_weight'),0.0))
        if abs(q if math.isfinite(q) else 0.0)<=EPS and mv<=EPS and cw<=EPS:
            continue
        a=by_t.get(t)
        if a is None: raise RuntimeError(f'HELD_TICKER_MISSING_FROM_ACTIONS {t}')
        held.append({
            'ticker':t,'quantity':q,'market_value_usd':mv,'current_weight_invested_basis':cw,
            'action':a.get('action'),'phase3z_target_weight':_f(a.get('phase3z_economic_target_weight')),
            'raw_model_target_weight':_f(a.get('raw_model_target_weight')),
            'weight_delta_invested_basis':_f(a.get('weight_delta')),
            'resize_band':_f(a.get('resize_band')),'expected_active_total':_f(a.get('expected_active_total')),
            'effective_horizon_sessions':_f(a.get('effective_horizon_sessions')),
            'reason':a.get('reason',''),
        })

    buys=[]
    for a in rows:
        if str(a.get('action'))!='BUY': continue
        buys.append({
            'ticker':str(a.get('ticker','')).upper(),
            'currently_held':bool(a.get('currently_held')),
            'phase3z_target_weight':_f(a.get('phase3z_economic_target_weight')),
            'raw_model_target_weight':_f(a.get('raw_model_target_weight')),
            'expected_active_total':_f(a.get('expected_active_total')),
            'effective_horizon_sessions':_f(a.get('effective_horizon_sessions')),
            'resize_band':_f(a.get('resize_band')),
            'entry_ok':bool(a.get('entry_ok',False)),
            'reason':a.get('reason',''),
        })
    buys.sort(key=lambda x:(-max(0.0,_f(x['phase3z_target_weight'],0.0)),-_f(x['expected_active_total'],-999),x['ticker']))

    attention=[a for a in rows if str(a.get('action')) in ('EXIT','REDUCE')]
    attention.sort(key=lambda x:({'EXIT':0,'REDUCE':1}.get(str(x.get('action')),9),-abs(_f(x.get('weight_delta'),0.0)),str(x.get('ticker'))))

    invested_mv=sum(max(0.0,_f(x.get('market_value_usd'),0.0)) for x in held)
    current_weight_sum=sum(max(0.0,_f(x.get('current_weight_invested_basis'),0.0)) for x in held)
    target_sum=sum(max(0.0,_f(r.get('phase3z_economic_target_weight'),0.0)) for r in rows)
    model_cash_weight=max(0.0,1.0-target_sum)

    nonusd_cash={k:v for k,v in cash.items() if k!='USD' and abs(_f(v,0.0))>EPS}
    usd_cash=_f(cash.get('USD',0.0),0.0)
    # We deliberately do NOT invent FX conversion here.  Exact total-NAV sizing is certified only
    # when all material cash is already in USD or a separately audited FX source is supplied later.
    weight_basis_execution_ready = not nonusd_cash
    basis_status='PASS_TOTAL_NAV_RECONCILABLE' if weight_basis_execution_ready else 'BLOCKED_NONUSD_CASH_REQUIRES_AUDITED_FX'

    audit={
        'build':BUILD,'seal_id':EXPECTED_SEAL,'asof':summary.get('asof'),
        'held_tickers':len(held),'invested_market_value_usd':invested_mv,
        'current_weight_sum_invested_basis':current_weight_sum,
        'phase3z_target_weight_sum_total_nav_basis':target_sum,
        'phase3z_model_cash_weight':model_cash_weight,
        'cash_snapshot':cash,'usd_cash':usd_cash,'nonusd_cash':nonusd_cash,
        'legacy_current_weight_definition':'market_value / total_invested_market_value (cash excluded)',
        'phase3z_target_weight_definition':'total-NAV target weights with residual cash allowed',
        'directional_actions_valid_as_phase3z_on_legacy_weights':True,
        'absolute_execution_sizing_certified':weight_basis_execution_ready,
        'basis_status':basis_status,
        'note':'No FX conversion is inferred. Non-USD cash blocks absolute sizing until an audited conversion source is used.',
    }
    return audit,held,buys,attention


def build_portfolio_action_review(root:Path)->dict:
    root=root.resolve(); audit,held,buys,attention=_review(root)
    outdir=root/'outputs'/'portfolio_review'; outdir.mkdir(parents=True,exist_ok=True)
    import pandas as pd
    pd.DataFrame(held).to_csv(outdir/'v13_held_positions_review.csv',index=False)
    pd.DataFrame(buys).to_csv(outdir/'v13_buy_candidates_review.csv',index=False)
    pd.DataFrame(attention).to_csv(outdir/'v13_reduce_exit_review.csv',index=False)
    (outdir/'v13_portfolio_basis_audit.json').write_text(json.dumps(audit,indent=2,default=str),encoding='utf-8')

    held_actions={a:sum(1 for x in held if x['action']==a) for a in ['BUY','HOLD','REDUCE','EXIT']}
    top_buys=buys[:10]
    summary={
        'status':'PASS','phase':'V13-P5E','build':BUILD,'seal_id':EXPECTED_SEAL,'asof':audit['asof'],
        'held_tickers':len(held),'held_actions':held_actions,
        'invested_market_value_usd':audit['invested_market_value_usd'],
        'cash_snapshot':audit['cash_snapshot'],
        'phase3z_model_cash_weight':audit['phase3z_model_cash_weight'],
        'weight_basis_status':audit['basis_status'],
        'absolute_execution_sizing_certified':audit['absolute_execution_sizing_certified'],
        'held_positions':held,
        'top_10_buy_candidates':top_buys,
        'no_sheet_mutation':True,'shadow_only':True,'real_orders_sent':False,'tuning_performed':False,
        'review_digest':_digest({'audit':audit,'held':held,'top_buys':top_buys}),
        'next':('If basis_status is PASS, build confirmation-gated sizing/ledger. If BLOCKED, add one audited FX conversion source before computing dollar trade sizes. Do not change V13 model/policy.'),
    }
    (outdir/'v13_portfolio_review_summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
    return summary
