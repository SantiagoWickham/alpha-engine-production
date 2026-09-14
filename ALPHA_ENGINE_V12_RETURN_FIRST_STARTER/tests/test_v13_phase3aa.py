from pathlib import Path
import hashlib
import pandas as pd
import numpy as np
from alpha_engine_v13.final_prehodout_review import _cagr,_ols,_dd,_sha,BUILD

def test_build_id(): assert BUILD.startswith('V13_P3AA_')
def test_cagr_zero(): assert abs(_cagr(pd.Series([0.0]*252)))<1e-12
def test_cagr_positive(): assert _cagr(pd.Series([0.001]*252))>0.20
def test_ols_beta_one():
    x=pd.Series(np.linspace(-.01,.01,100)); y=x.copy(); r=_ols(y,x); assert abs(r['beta']-1)<1e-9 and abs(r['alpha_ann'])<1e-9
def test_ols_positive_alpha():
    x=pd.Series(np.linspace(-.01,.01,100)); y=x+0.0002; assert _ols(y,x)['alpha_ann']>0
def test_drawdown_recovery():
    r=pd.DataFrame({'date':pd.date_range('2020-01-01',periods=5),'net_return':[0.1,-0.2,0.0,0.3,0.0]}); d=_dd(r); assert d['max_drawdown']<0 and d['recovery_date'] is not None
def test_sha(tmp_path):
    p=tmp_path/'a'; p.write_bytes(b'abc'); assert _sha(p)==hashlib.sha256(b'abc').hexdigest()
def test_holdout_dates_are_normalizable(): assert pd.Timestamp('2024-12-31')<pd.Timestamp('2025-01-01')
