from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from alpha_engine_v13 import portfolio_action_review as m


def test_build_constant():
    assert m.EXPECTED_SEAL.startswith('46bbbf85')
    assert 'BASIS_AUDIT' in m.BUILD


def test_nonusd_cash_blocks_exact_sizing(tmp_path, monkeypatch):
    ss=tmp_path/'outputs'/'sheets_shadow'; ps=tmp_path/'outputs'/'portfolio_shadow'
    ss.mkdir(parents=True); ps.mkdir(parents=True)
    pos={'headers':['Ticker','Qty','Avg','Price','Market Value','Cost','U','R','D','Ret','Weight'],
         'rows':[['AAA',2,10,20,40,20,20,0,0,1,1.0]]}
    cash={'headers':['Moneda','Saldo'], 'rows':[['ARS',1809],['USD',0]]}
    man={'headers':['Campo','Valor'],'rows':[]}
    (ss/'v13_sheets_positions_snapshot.json').write_text(json.dumps(pos))
    (ss/'v13_sheets_cash_snapshot.json').write_text(json.dumps(cash))
    (ss/'v13_sheets_mandate_snapshot.json').write_text(json.dumps(man))
    actrow={'ticker':'AAA','action':'EXIT','currently_held':True,'current_weight':1.0,'phase3z_economic_target_weight':0.0,'raw_model_target_weight':0.0,'weight_delta':-1.0,'resize_band':0.01,'entry_ok':False,'expected_active_total':-0.01,'effective_horizon_sessions':20,'reason':'x'}
    (ps/'v13_portfolio_actions_latest.json').write_text(json.dumps({'seal_id':m.EXPECTED_SEAL,'shadow_only':True,'real_orders_sent':False,'rows':[actrow]}))
    (ps/'v13_portfolio_actions_summary.json').write_text(json.dumps({'status':'PASS','seal_id':m.EXPECTED_SEAL,'asof':'2026-09-11'}))
    audit,held,buys,att=m._review(tmp_path)
    assert audit['basis_status']=='BLOCKED_NONUSD_CASH_REQUIRES_AUDITED_FX'
    assert audit['absolute_execution_sizing_certified'] is False
    assert held[0]['ticker']=='AAA' and held[0]['action']=='EXIT'
    assert len(att)==1


def test_usd_only_cash_allows_reconciliation(tmp_path):
    ss=tmp_path/'outputs'/'sheets_shadow'; ps=tmp_path/'outputs'/'portfolio_shadow'
    ss.mkdir(parents=True); ps.mkdir(parents=True)
    (ss/'v13_sheets_positions_snapshot.json').write_text(json.dumps({'headers':['Ticker','Qty','','','Market Value','','','','','','Weight'],'rows':[['AAA',1,'','',100,'','','','','',1.0]]}))
    (ss/'v13_sheets_cash_snapshot.json').write_text(json.dumps({'headers':['Moneda','Saldo'],'rows':[['USD',10]]}))
    (ss/'v13_sheets_mandate_snapshot.json').write_text(json.dumps({'headers':[],'rows':[]}))
    row={'ticker':'AAA','action':'HOLD','currently_held':True,'current_weight':1.0,'phase3z_economic_target_weight':0.9,'raw_model_target_weight':0.9,'weight_delta':-0.1,'resize_band':0.2,'entry_ok':False,'expected_active_total':0.1,'effective_horizon_sessions':60,'reason':'x'}
    (ps/'v13_portfolio_actions_latest.json').write_text(json.dumps({'seal_id':m.EXPECTED_SEAL,'shadow_only':True,'real_orders_sent':False,'rows':[row]}))
    (ps/'v13_portfolio_actions_summary.json').write_text(json.dumps({'status':'PASS','seal_id':m.EXPECTED_SEAL,'asof':'2026-09-11'}))
    audit,held,buys,att=m._review(tmp_path)
    assert audit['absolute_execution_sizing_certified'] is True
    assert audit['basis_status']=='PASS_TOTAL_NAV_RECONCILABLE'
