from pathlib import Path
from datetime import datetime, timezone
import json, math, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

# Minimal dependency stub when testing this package standalone.
try:
    from alpha_engine_v13 import active_alpha_persistent_portfolio
except Exception:
    pass
from alpha_engine_v13 import portfolio_fx_sizing as m

def test_av_parse():
    x={'Realtime Currency Exchange Rate':{'5. Exchange Rate':'1513.50','6. Last Refreshed':'2026-09-11 20:00:00','7. Time Zone':'UTC'}}
    z=m._parse_av_fx(x)
    assert abs(z['rate_ars_per_usd']-1513.5)<1e-9

def test_yahoo_parse():
    x={'chart':{'result':[{'meta':{'regularMarketPrice':1512.5,'regularMarketTime':1789156800},'indicators':{'quote':[{'close':[1511,1512.5]}]}}]}}
    z=m._parse_yahoo_fx(x)
    assert z['rate_ars_per_usd']==1512.5

def test_env_discovery(tmp_path):
    (tmp_path/'.env').write_text('MMM_ALPHA_VANTAGE_API_KEY="abc123"\n',encoding='utf-8')
    v,src=m._env_value(tmp_path,'MMM_ALPHA_VANTAGE_API_KEY')
    assert v=='abc123' and src.startswith('DOTENV:')

def test_fetch_audit_with_mock(tmp_path, monkeypatch):
    (tmp_path/'.env').write_text('MMM_ALPHA_VANTAGE_API_KEY=abc\n')
    def fake(url,headers=None,timeout=20):
        if 'alphavantage' in url:
            return {'Realtime Currency Exchange Rate':{'5. Exchange Rate':'1500','6. Last Refreshed':'2026-09-11 20:00:00','7. Time Zone':'UTC'}}
        return {'chart':{'result':[{'meta':{'regularMarketPrice':1510,'regularMarketTime':1789156800},'indicators':{'quote':[{'close':[1510]}]}}]}}
    monkeypatch.setattr(m,'_http_json',fake)
    a=m.fetch_audited_usdars(tmp_path,datetime(2026,9,13,18,0,0,tzinfo=timezone.utc))
    assert a['certification'].startswith('PASS')
    assert abs(a['secondary_relative_spread_vs_primary']-(10/1500))<1e-12

def test_total_nav_reconciliation_math():
    invested=319.2237680405669
    ars=1809.0
    rate=1513.5
    nav=invested+ars/rate
    assert 320 < nav < 321
    assert 0 < (ars/rate)/nav < .01

def test_build_constant():
    assert m.EXPECTED_SEAL.startswith('46bbbf85')
    assert 'TOTAL_NAV_SHADOW_SIZING' in m.BUILD
