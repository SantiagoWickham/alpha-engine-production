from __future__ import annotations
import json, math, hashlib, os, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from alpha_engine_v13 import active_alpha_persistent_portfolio as p3y
from alpha_engine_v13 import portfolio_action_shadow as p5d

BUILD='V13_P5F_AUDITED_FX_TOTAL_NAV_SHADOW_SIZING_2026-09-13'
EXPECTED_SEAL='46bbbf853561e26625ee3ecbccb6037051556f2f3ca26dcb4e311c165c08d8e9'
EPS=1e-14
MAX_FX_AGE_HOURS=120.0

def _read_json(p:Path)->dict:
    if not p.exists(): raise FileNotFoundError(p)
    return json.loads(p.read_text(encoding='utf-8'))

def _f(x, default=math.nan):
    try:
        v=float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default

def _digest(x:Any)->str:
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

def _dotenv_candidates(root:Path)->list[Path]:
    root=root.resolve()
    cands=[
        root/'.env',
        root/'secrets'/'.env',
        root.parent/'.env',
        root.parent/'secrets'/'.env',
        root.parent/'ALPHA_ENGINE_V12_RETURN_FIRST_STARTER'/'.env',
        root.parent/'ALPHA_ENGINE_V12_RETURN_FIRST_STARTER'/'secrets'/'.env',
    ]
    out=[]; seen=set()
    for p in cands:
        s=str(p)
        if s not in seen:
            seen.add(s); out.append(p)
    return out

def _parse_env_file(p:Path)->dict[str,str]:
    out={}
    if not p.exists(): return out
    for raw in p.read_text(encoding='utf-8-sig').splitlines():
        s=raw.strip()
        if not s or s.startswith('#') or '=' not in s: continue
        k,v=s.split('=',1); k=k.strip(); v=v.strip()
        if len(v)>=2 and v[0]==v[-1] and v[0] in ("'",'"'): v=v[1:-1]
        if k: out[k]=v
    return out

def _env_value(root:Path,key:str)->tuple[str|None,str|None]:
    v=os.getenv(key)
    if v: return v,f'ENV:{key}'
    for p in _dotenv_candidates(root):
        d=_parse_env_file(p)
        if d.get(key): return d[key],f'DOTENV:{p}:{key}'
    return None,None

def _http_json(url:str, headers:dict|None=None, timeout:int=20)->dict:
    req=Request(url,headers=headers or {'User-Agent':'AlphaEngineV13/5F'})
    try:
        with urlopen(req,timeout=timeout) as r:
            raw=r.read()
    except (HTTPError,URLError,TimeoutError) as e:
        raise RuntimeError(f'HTTP_REQUEST_FAILED {type(e).__name__}: {e}') from e
    try:return json.loads(raw.decode('utf-8'))
    except Exception as e: raise RuntimeError(f'HTTP_JSON_DECODE_FAILED bytes={len(raw)}') from e

def _parse_av_fx(obj:dict)->dict:
    if 'Note' in obj: raise RuntimeError('ALPHA_VANTAGE_RATE_LIMIT_NOTE')
    if 'Information' in obj and 'Realtime Currency Exchange Rate' not in obj:
        raise RuntimeError('ALPHA_VANTAGE_INFORMATION_RESPONSE')
    z=obj.get('Realtime Currency Exchange Rate') or {}
    rate=_f(z.get('5. Exchange Rate'))
    if not math.isfinite(rate) or rate<=0: raise RuntimeError('ALPHA_VANTAGE_FX_RATE_MISSING')
    refreshed=str(z.get('6. Last Refreshed') or '').strip()
    tz=str(z.get('7. Time Zone') or 'UTC').strip()
    return {'rate_ars_per_usd':rate,'last_refreshed_raw':refreshed,'source_timezone':tz}

def _parse_yahoo_fx(obj:dict)->dict:
    try:
        result=obj['chart']['result'][0]; meta=result.get('meta') or {}
    except Exception as e: raise RuntimeError('YAHOO_FX_SCHEMA_INVALID') from e
    rate=_f(meta.get('regularMarketPrice'))
    if not math.isfinite(rate) or rate<=0:
        closes=((result.get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
        finite=[_f(x) for x in closes if math.isfinite(_f(x))]
        rate=finite[-1] if finite else math.nan
    if not math.isfinite(rate) or rate<=0: raise RuntimeError('YAHOO_FX_RATE_MISSING')
    ts=meta.get('regularMarketTime')
    iso=datetime.fromtimestamp(float(ts),tz=timezone.utc).isoformat() if ts else None
    return {'rate_ars_per_usd':rate,'market_time_utc':iso}

def _parse_refresh_utc(s:str)->datetime|None:
    s=(s or '').strip()
    if not s:return None
    fmts=('%Y-%m-%d %H:%M:%S','%Y-%m-%d')
    for f in fmts:
        try:return datetime.strptime(s,f).replace(tzinfo=timezone.utc)
        except ValueError:pass
    return None

def fetch_audited_usdars(root:Path, now_utc:datetime|None=None)->dict:
    now_utc=now_utc or datetime.now(timezone.utc)
    key,key_source=_env_value(root,'MMM_ALPHA_VANTAGE_API_KEY')
    if not key: raise RuntimeError('MISSING_MMM_ALPHA_VANTAGE_API_KEY')
    params=urlencode({'function':'CURRENCY_EXCHANGE_RATE','from_currency':'USD','to_currency':'ARS','apikey':key})
    av=_parse_av_fx(_http_json('https://www.alphavantage.co/query?'+params,timeout=25))
    refreshed=_parse_refresh_utc(av['last_refreshed_raw'])
    age_h=(now_utc-refreshed).total_seconds()/3600 if refreshed else math.nan
    if math.isfinite(age_h) and age_h < -1: raise RuntimeError('FX_TIMESTAMP_IN_FUTURE')
    if math.isfinite(age_h) and age_h > MAX_FX_AGE_HOURS:
        raise RuntimeError(f'FX_PRIMARY_STALE age_hours={age_h:.1f}')
    y=None; yerr=None
    try:
        y=_parse_yahoo_fx(_http_json('https://query1.finance.yahoo.com/v8/finance/chart/ARS=X?range=5d&interval=1d',headers={'User-Agent':'Mozilla/5.0'},timeout=20))
    except Exception as e:
        yerr=str(e)
    rate=av['rate_ars_per_usd']
    spread=None
    if y and y.get('rate_ars_per_usd'):
        spread=abs(float(y['rate_ars_per_usd'])-rate)/rate
    audit={
        'pair':'USD/ARS','quote_semantics':'ARS per 1 USD',
        'certified_rate_ars_per_usd':rate,
        'certified_source':'ALPHA_VANTAGE_CURRENCY_EXCHANGE_RATE',
        'api_key_source':key_source,
        'primary_last_refreshed_raw':av['last_refreshed_raw'],
        'primary_age_hours':age_h,
        'max_allowed_age_hours':MAX_FX_AGE_HOURS,
        'secondary_source':'YAHOO_FINANCE_ARS=X' if y else None,
        'secondary_rate_ars_per_usd':y.get('rate_ars_per_usd') if y else None,
        'secondary_market_time_utc':y.get('market_time_utc') if y else None,
        'secondary_relative_spread_vs_primary':spread,
        'secondary_error':yerr,
        'fetched_at_utc':now_utc.isoformat(),
        'certification':'PASS_PRIMARY_VALID_AND_FRESH',
    }
    audit['audit_digest']=_digest({k:v for k,v in audit.items() if k!='audit_digest'})
    return audit

def _load_inputs(root:Path):
    e=_read_json(root/'outputs'/'portfolio_review'/'v13_portfolio_review_summary.json')
    if e.get('status')!='PASS' or e.get('seal_id')!=EXPECTED_SEAL: raise RuntimeError('PHASE5E_NOT_PASS_OR_SEAL_MISMATCH')
    ss=root/'outputs'/'sheets_shadow'
    pos=p5d._parse_positions(_read_json(ss/'v13_sheets_positions_snapshot.json'))
    cash=p5d._parse_cash(_read_json(ss/'v13_sheets_cash_snapshot.json'))
    live_summary,contract=p5d.p5c._contract(root)
    if contract.get('seal_id')!=EXPECTED_SEAL: raise RuntimeError('LIVE_CONTRACT_SEAL_MISMATCH')
    if not contract.get('shadow_only',False) or contract.get('real_orders_sent'): raise RuntimeError('LIVE_CONTRACT_NOT_SHADOW')
    return e,pos,cash,contract

def _total_nav_actions(root:Path, fx:dict)->tuple[dict,list[dict]]:
    review,pos,cash,contract=_load_inputs(root)
    rate=_f(fx.get('certified_rate_ars_per_usd'))
    if not math.isfinite(rate) or rate<=0: raise RuntimeError('FX_NOT_CERTIFIED')
    nonusd_unsupported={k:v for k,v in cash.items() if k not in ('USD','ARS') and abs(_f(v,0.0))>EPS}
    if nonusd_unsupported: raise RuntimeError(f'UNSUPPORTED_NONUSD_CASH {nonusd_unsupported}')
    ars=_f(cash.get('ARS',0.0),0.0); usd=_f(cash.get('USD',0.0),0.0)
    ars_usd=ars/rate
    invested=sum(max(0.0,_f(v.get('market_value_usd_eq'),0.0)) for v in pos.values())
    nav=invested+usd+ars_usd
    if not math.isfinite(nav) or nav<=0: raise RuntimeError('TOTAL_NAV_INVALID')

    cur={}
    for t,v in pos.items():
        mv=max(0.0,_f(v.get('market_value_usd_eq'),0.0))
        if mv>EPS: cur[t]=mv/nav
    plan=p5d._plan_from_contract(contract)
    econ=p3y._economic_target(cur,plan)
    by_t={str(r.get('ticker','')).strip().upper():r for r in contract.get('rows') or []}
    names=sorted(set(by_t)|set(pos))
    rows=[]
    for t in names:
        p=pos.get(t,{})
        r=by_t.get(t,{})
        current_mv=max(0.0,_f(p.get('market_value_usd_eq'),0.0))
        current_w=current_mv/nav
        target_w=max(0.0,float(econ.get(t,0.0)))
        target_usd=target_w*nav
        delta=target_usd-current_mv
        action=p5d._classify(current_w,target_w)
        rows.append({
            'asof':contract.get('asof'),'seal_id':EXPECTED_SEAL,'ticker':t,
            'action_total_nav_basis':action,
            'currently_held':current_mv>EPS,
            'quantity_current':_f(p.get('quantity')),
            'current_market_value_usd':current_mv,
            'current_weight_total_nav':current_w,
            'phase3z_target_weight_total_nav':target_w,
            'target_value_usd':target_usd,
            'trade_value_usd_shadow':delta,
            'trade_side_shadow':'BUY' if delta>1e-9 else ('SELL' if delta<-1e-9 else 'NONE'),
            'resize_band':max(0.0,_f(r.get('resize_band'),0.0)),
            'entry_ok':bool(r.get('entry_ok',False)),
            'expected_active_total':_f(r.get('expected_active_total')),
            'effective_horizon_sessions':_f(r.get('effective_horizon_sessions')),
            'reason':p5d._reason(action,current_w,target_w,plan.get(t)),
        })
    rows.sort(key=lambda x:({'EXIT':0,'REDUCE':1,'BUY':2,'HOLD':3}.get(x['action_total_nav_basis'],9),-abs(x['trade_value_usd_shadow']),x['ticker']))
    target_sum=sum(x['phase3z_target_weight_total_nav'] for x in rows)
    residual=max(0.0,1.0-target_sum)
    rec={
        'invested_market_value_usd':invested,
        'cash_usd_native':usd,'cash_ars':ars,'cash_ars_usd_equivalent':ars_usd,
        'fx_rate_ars_per_usd':rate,'total_nav_usd':nav,
        'current_invested_weight_total_nav':invested/nav,
        'current_cash_weight_total_nav':(usd+ars_usd)/nav,
        'phase3z_target_invested_weight':target_sum,
        'phase3z_target_cash_weight':residual,
        'phase3z_target_cash_usd':residual*nav,
        'net_trade_value_usd':sum(x['trade_value_usd_shadow'] for x in rows),
        'post_trade_cash_usd_identity':nav-sum(x['target_value_usd'] for x in rows),
    }
    return rec,rows

def build_fx_total_nav_shadow_sizing(root:Path)->dict:
    root=root.resolve()
    fx=fetch_audited_usdars(root)
    rec,rows=_total_nav_actions(root,fx)
    outdir=root/'outputs'/'portfolio_sizing_shadow';outdir.mkdir(parents=True,exist_ok=True)
    (outdir/'v13_fx_audit.json').write_text(json.dumps(fx,indent=2,default=str),encoding='utf-8')
    (outdir/'v13_total_nav_reconciliation.json').write_text(json.dumps(rec,indent=2,default=str),encoding='utf-8')
    payload={
        'build':BUILD,'schema_version':'ALPHA_ENGINE_V13_TOTAL_NAV_SHADOW_SIZING_V1',
        'seal_id':EXPECTED_SEAL,'asof':rows[0]['asof'] if rows else None,
        'shadow_only':True,'real_orders_sent':False,'operation_append_called':False,
        'cash_mutated':False,'forward_ledger_mutated':False,'tuning_performed':False,
        'fx_audit_digest':fx['audit_digest'],'rows':rows,
    }
    (outdir/'v13_total_nav_shadow_sizing_latest.json').write_text(json.dumps(payload,indent=2,default=str),encoding='utf-8')
    import pandas as pd
    pd.DataFrame(rows).to_csv(outdir/'v13_total_nav_shadow_sizing_latest.csv',index=False)

    counts={a:sum(1 for x in rows if x['action_total_nav_basis']==a) for a in ['BUY','HOLD','REDUCE','EXIT']}
    attention=[x for x in rows if x['action_total_nav_basis']!='HOLD']
    top=sorted(attention,key=lambda x:-abs(x['trade_value_usd_shadow']))[:12]
    summary={
        'status':'PASS','phase':'V13-P5F','build':BUILD,'seal_id':EXPECTED_SEAL,
        'asof':payload['asof'],
        'fx_certification':fx['certification'],
        'fx_rate_ars_per_usd':fx['certified_rate_ars_per_usd'],
        'fx_primary_source':fx['certified_source'],
        'fx_secondary_rate_ars_per_usd':fx['secondary_rate_ars_per_usd'],
        'fx_secondary_relative_spread':fx['secondary_relative_spread_vs_primary'],
        'invested_market_value_usd':rec['invested_market_value_usd'],
        'cash_ars':rec['cash_ars'],'cash_ars_usd_equivalent':rec['cash_ars_usd_equivalent'],
        'cash_usd_native':rec['cash_usd_native'],'total_nav_usd':rec['total_nav_usd'],
        'current_cash_weight_total_nav':rec['current_cash_weight_total_nav'],
        'phase3z_target_cash_weight':rec['phase3z_target_cash_weight'],
        'phase3z_target_cash_usd':rec['phase3z_target_cash_usd'],
        'actions_total_nav_basis':counts,
        'absolute_execution_sizing_certified':True,
        'top_shadow_trades_by_abs_usd':top,
        'sizing_digest':_digest({'fx':fx['audit_digest'],'rec':rec,'rows':rows}),
        'no_sheet_mutation':True,'shadow_only':True,'real_orders_sent':False,
        'operation_append_called':False,'cash_mutated':False,'forward_ledger_mutated':False,'tuning_performed':False,
        'next':'Review total-NAV USD sizing. If coherent, build a confirmation-gated proposal ledger only; no auto-trading.',
    }
    (outdir/'v13_phase5f_summary.json').write_text(json.dumps(summary,indent=2,default=str),encoding='utf-8')
    return summary
