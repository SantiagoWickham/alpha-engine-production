import json, math
from pathlib import Path
import pytest
from alpha_engine_v13 import portfolio_action_shadow as m
from alpha_engine_v13 import active_alpha_persistent_portfolio as p3y


def test_position_parser_legacy_v8_layout():
    snap={'headers':['Ticker','Cantidad','Costo Medio USD Eq.','Precio Actual USD Eq.','Valor Mercado USD Eq.','','','','','','Peso Actual'],
          'rows':[['AAPL',2,100,200,400,0,0,0,0,0,.4],['MSFT',1,100,300,300,0,0,0,0,0,.3]]}
    p=m._parse_positions(snap)
    assert p['AAPL']['current_weight']==pytest.approx(.4)
    assert p['MSFT']['market_value_usd_eq']==pytest.approx(300)


def test_exact_phase3z_economic_target_matches_original():
    cur={'A':.2,'B':.3,'C':.1}
    plan={'A':{'desired':.30,'alpha_total':.02,'entry_ok':True,'band':.03},
          'B':{'desired':.10,'alpha_total':.02,'entry_ok':True,'band':.04},
          'C':{'desired':0,'alpha_total':.01,'entry_ok':False,'band':.02},
          'D':{'desired':.20,'alpha_total':.03,'entry_ok':True,'band':.01}}
    assert m.p3y._economic_target(cur,plan)==p3y._economic_target(cur,plan)


def test_classification():
    assert m._classify(0,.1)=='BUY'
    assert m._classify(.1,0)=='EXIT'
    assert m._classify(.2,.1)=='REDUCE'
    assert m._classify(.1,.2)=='BUY'
    assert m._classify(.1,.1)=='HOLD'
    assert m._classify(0,0)=='HOLD'


def test_no_new_threshold_in_reasonable_plan():
    cur={'A':.20}
    plan={'A':{'desired':.25,'alpha_total':.02,'entry_ok':True,'band':.06}}
    econ=p3y._economic_target(cur,plan)
    assert econ['A']==pytest.approx(.20)  # inside band => exact hold
    assert m._classify(.20,econ['A'])=='HOLD'


def test_cash_parser():
    s={'headers':['Moneda','Saldo','Actualizado','Fuente'],'rows':[['USD',123,None,'x'],['ARS',456,None,'x']]}
    assert m._parse_cash(s)=={'USD':123.0,'ARS':456.0}
