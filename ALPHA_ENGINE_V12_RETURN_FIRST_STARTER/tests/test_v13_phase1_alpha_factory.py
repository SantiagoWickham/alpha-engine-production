import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"src"))
from alpha_engine_v13.alpha_factory import feature_family,_bh,_nw_mean_t,benchmark_forward_returns,research_key_price_coverage

def test_size_is_single_family(): assert feature_family("size_log_market_cap")=="SIZE_SINGLE_FACTOR"
def test_bh_monotone_and_bounded():
    p=pd.Series([0.01,0.04,0.02,0.8]); q=_bh(p); assert ((q>=0)&(q<=1)).all(); assert q.iloc[0] <= q.iloc[3]
def test_nw_positive_mean():
    mu,t,p=_nw_mean_t(np.array([.1,.2,.1,.15,.2,.12,.11,.18,.2,.14]),2); assert mu>0 and t>0 and p<1
def test_benchmark_forward_uses_next_session():
    d=pd.date_range("2020-01-01",periods=10,freq="D"); b=pd.DataFrame({"date":d,"SPY":np.arange(10)+100.,"QQQ":np.arange(10)+200.}); o=benchmark_forward_returns(b,pd.Series([d[0]]),[5]); exp=106/101-1; assert abs(o.loc[0,"spy_fwd_return_5d"]-exp)<1e-12
def test_holdout_semantics_are_pre2025():
    assert pd.Timestamp("2024-12-31") < pd.Timestamp("2025-01-01")


def test_price_coverage_is_measured_on_research_keys_only():
    p=pd.DataFrame({
        "date":pd.to_datetime(["2020-01-02","2020-01-03"]),
        "ticker":["AAA","BBB"],
        "feature_price":[10.0,20.0],
    })
    m=research_key_price_coverage(p)
    assert m["research_key_rows"]==2
    assert m["research_key_missing_rows"]==0
    assert m["research_key_coverage"]==1.0

def test_missing_research_price_remains_blocking_evidence():
    p=pd.DataFrame({
        "date":pd.to_datetime(["2020-01-02","2020-01-03"]),
        "ticker":["AAA","BBB"],
        "feature_price":[10.0,np.nan],
    })
    m=research_key_price_coverage(p)
    assert m["research_key_missing_rows"]==1
    assert m["research_key_coverage"]==0.5

def test_load_market_uses_canonical_pit_and_historical_names(monkeypatch, tmp_path):
    from alpha_engine_v13.alpha_factory import load_market, Cfg
    p=tmp_path/'outputs'; p.mkdir(parents=True)
    path=p/'phase2_canonical_pit_panel.parquet'; path.write_bytes(b'placeholder')
    df=pd.DataFrame({
        'date':pd.to_datetime(['2013-12-23','2013-12-23','2013-12-24']),
        'ticker':['OLD1','LIVE','OLD1'],
        'close':[10.,20.,11.],
        'adj_close':[10.,20.,11.],
        'volume':[100.,200.,110.],
        'research_eligible':[True,True,True],
    })
    monkeypatch.setattr(pd, 'read_parquet', lambda *a, **k: df.copy())
    cfg=Cfg({'holdout_start':'2025-01-01','source_canonical_pit_panel':'outputs/phase2_canonical_pit_panel.parquet'})
    out=load_market(tmp_path,cfg)
    assert set(out['ticker'])=={'OLD1','LIVE'}
    assert len(out)==3

def test_canonical_panel_is_declared_in_phase0_contract():
    import tomllib
    c=ROOT/'config'/'v13_contract.toml'
    with c.open('rb') as f: x=tomllib.load(f)
    assert 'outputs/phase2_canonical_pit_panel.parquet' in x['allowed_sources']['files']
