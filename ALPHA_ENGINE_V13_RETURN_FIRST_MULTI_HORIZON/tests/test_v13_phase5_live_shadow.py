from datetime import datetime, timezone
import pandas as pd
import numpy as np
from alpha_engine_v13.live_shadow import latest_completed_cutoff,_parse_yahoo,_sha_payload

def test_cutoff_before_close_uses_prior_date():
    # 2026-09-11 17:00 UTC = 13:00 New York (EDT), before close+grace.
    d=latest_completed_cutoff(datetime(2026,9,11,17,0,tzinfo=timezone.utc),45)
    assert d==pd.Timestamp('2026-09-10')

def test_parse_yahoo_chart():
    p={'chart':{'result':[{'timestamp':[1789147800], 'indicators':{'quote':[{'close':[100.0],'volume':[1000]}],'adjclose':[{'adjclose':[99.5]}]}}], 'error':None}}
    x=_parse_yahoo(p,'ABC','ABC')
    assert len(x)==1 and x.ticker.iloc[0]=='ABC' and np.isclose(x.adj_close.iloc[0],99.5)

def test_payload_hash_deterministic():
    assert _sha_payload({'b':2,'a':1})==_sha_payload({'a':1,'b':2})

from alpha_engine_v13.live_shadow import _anchor_scale, Cfg

def test_anchor_scale_preserves_frozen_anchor():
    hist=pd.DataFrame({'date':pd.to_datetime(['2026-09-04']), 'ticker':['ABC'], 'feature_price':[100.0]})
    live=pd.DataFrame({'date':pd.to_datetime(['2026-09-04','2026-09-08']), 'ticker':['ABC','ABC'], 'adj_close':[50.0,55.0], 'close':[50.0,55.0], 'volume':[1,1]})
    cfg=Cfg({'minimum_anchor_coverage':1.0,'maximum_anchor_scale_deviation':99.0})
    scaled,audit=_anchor_scale(live,hist,pd.Timestamp('2026-09-04'),cfg)
    assert np.isclose(scaled.loc[scaled.date.eq(pd.Timestamp('2026-09-04')),'feature_price'].iloc[0],100.0)
    assert np.isclose(scaled.loc[scaled.date.eq(pd.Timestamp('2026-09-08')),'feature_price'].iloc[0],110.0)
    assert np.isclose(audit.scale.iloc[0],2.0)

def test_cutoff_weekend_is_bounded_then_market_calendar_resolves():
    d=latest_completed_cutoff(datetime(2026,9,13,16,0,tzinfo=timezone.utc),45)
    assert d==pd.Timestamp('2026-09-12')

import gzip, json
from alpha_engine_v13.live_shadow import _decode_http_bytes

def test_http_gzip_decode_for_sec_companyfacts():
    payload={"facts":{"us-gaap":{}}}
    raw=json.dumps(payload).encode("utf-8")
    enc=gzip.compress(raw)
    assert json.loads(_decode_http_bytes(enc,"gzip").decode("utf-8"))==payload

def test_http_gzip_magic_is_detected_even_without_header():
    raw=b'{"ok":true}'
    assert _decode_http_bytes(gzip.compress(raw),None)==raw

from pathlib import Path
from alpha_engine_v13.live_shadow import _read_dotenv_value, _sec_user_agent

def test_dotenv_reader_supports_quoted_mmm_sec_user_agent(tmp_path, monkeypatch):
    monkeypatch.delenv('MMM_SEC_USER_AGENT', raising=False)
    monkeypatch.delenv('ALPHA_ENGINE_SEC_USER_AGENT', raising=False)
    (tmp_path/'.env').write_text('MMM_SEC_USER_AGENT="Alpha Engine Research user@example.com"\n', encoding='utf-8')
    ua, source = _sec_user_agent(tmp_path)
    assert ua == 'Alpha Engine Research user@example.com'
    assert source.startswith('DOTENV:')

def test_exported_mmm_sec_user_agent_has_priority(tmp_path, monkeypatch):
    monkeypatch.setenv('MMM_SEC_USER_AGENT', 'Alpha Engine Research ops@example.com')
    (tmp_path/'.env').write_text('MMM_SEC_USER_AGENT="Other user@example.com"\n', encoding='utf-8')
    ua, source = _sec_user_agent(tmp_path)
    assert ua == 'Alpha Engine Research ops@example.com'
    assert source == 'ENV:MMM_SEC_USER_AGENT'

from alpha_engine_v13.live_shadow import _normalize_cik_value, _canonicalize_sec_mapping

def test_cik_normalization_handles_float_without_appending_zero():
    assert _normalize_cik_value(789019.0) == '0000789019'
    assert _normalize_cik_value('789019.0') == '0000789019'
    assert _normalize_cik_value('7.89019E+5') == '0000789019'

def test_cik_normalization_preserves_zero_padded_string():
    assert _normalize_cik_value('0000789019') == '0000789019'
    assert _normalize_cik_value('CIK0000789019') == '0000789019'

def test_canonical_mapping_repairs_msft_float_cik():
    x=pd.DataFrame({'ticker':['MSFT','AAPL'],'cik':[789019.0,320193.0]})
    out=_canonicalize_sec_mapping(x,'ticker','cik',{'MSFT','AAPL'}).set_index('ticker')
    assert out.loc['MSFT','cik']=='0000789019'
    assert out.loc['AAPL','cik']=='0000320193'

from alpha_engine_v13.live_shadow import _align_sec_fact_schema, _sec_date_iso_series

def test_sec_date_iso_normalizes_numeric_and_string_dates():
    s=pd.Series([20241231, 20250331.0, '2025-04-25', pd.Timestamp('2025-05-01'), None], dtype='object')
    out=_sec_date_iso_series(s)
    assert out.tolist()[:4]==['2024-12-31','2025-03-31','2025-04-25','2025-05-01']
    assert pd.isna(out.iloc[4])

def test_sec_fact_schema_alignment_makes_mixed_end_parquet_safe(tmp_path):
    hist=pd.DataFrame({
        'ticker':['MSFT'], 'canonical_metric':['revenue'], 'value':[100],
        'end':[20241231], 'filed':[20250130], 'form':['10-Q'], 'fy':[2024],
        'fp':['Q2'], 'frame':[None], 'accn':['x'], 'unit':['USD'],
        'taxonomy':['us-gaap'], 'concept':['RevenueFromContractWithCustomerExcludingAssessedTax']
    })
    live=pd.DataFrame({
        'ticker':['MSFT'], 'canonical_metric':['revenue'], 'value':['120.5'],
        'end':['2025-03-31'], 'filed':['2025-04-25'], 'form':['10-Q'], 'fy':['2025'],
        'fp':['Q3'], 'frame':['CY2025Q1'], 'accn':['y'], 'unit':['USD'],
        'taxonomy':['us-gaap'], 'concept':['RevenueFromContractWithCustomerExcludingAssessedTax']
    })
    h,l=_align_sec_fact_schema(hist,live)
    comb=pd.concat([h,l],ignore_index=True)
    assert list(comb.select_dtypes(include=['object']).columns)==[]
    assert comb['end'].tolist()==['2024-12-31','2025-03-31']
    assert comb['filed'].tolist()==['2025-01-30','2025-04-25']
    assert comb['fy'].tolist()==[2024,2025]
    assert np.isclose(comb['value'].iloc[1],120.5)
    # Exercise the exact parquet round-trip whenever pyarrow is present.
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        return
    p=tmp_path/'facts.parquet'
    comb.to_parquet(p,index=False)
    reread=pd.read_parquet(p)
    assert reread['end'].tolist()==['2024-12-31','2025-03-31']
    assert reread['filed'].tolist()==['2025-01-30','2025-04-25']
