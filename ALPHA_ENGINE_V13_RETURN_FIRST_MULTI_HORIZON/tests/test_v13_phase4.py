import json
from pathlib import Path
import numpy as np
import pandas as pd
from alpha_engine_v13 import final_holdout as p4


def test_build_id():
    assert p4.BUILD.startswith('V13_P4_ONE_SHOT')


def test_horizons_exact():
    assert p4.HORIZONS==(5,10,20,60,120,252)


def test_payload_hash_stable():
    a={'b':2,'a':1}; assert p4._sha256_payload(a)==p4._sha256_payload({'a':1,'b':2})


def test_economic_verdict_strong():
    beta=pd.DataFrame([{'benchmark':'SPY','alpha_ann':.02},{'benchmark':'UEW','alpha_ann':.01}])
    assert p4._economic_verdict({'cagr':.2,'spy_cagr':.1},{'cagr':.15},beta)=='STRONG_CONFIRMATION'


def test_economic_verdict_partial():
    beta=pd.DataFrame([{'benchmark':'SPY','alpha_ann':.02},{'benchmark':'UEW','alpha_ann':-.01}])
    assert p4._economic_verdict({'cagr':.08,'spy_cagr':.1},{'cagr':.04},beta)=='PARTIAL_CONFIRMATION'


def test_economic_verdict_none():
    beta=pd.DataFrame([{'benchmark':'SPY','alpha_ann':-.02},{'benchmark':'UEW','alpha_ann':-.01}])
    assert p4._economic_verdict({'cagr':-.02,'spy_cagr':.1},{'cagr':-.03},beta)=='NO_CONFIRMATION'


def test_constant_calibrator():
    b={'kind':'constant','value':.001,'sd':.01}; q=p4._predict_iso(b,[.1,.9]); assert np.allclose(q,[.001,.001])


def test_source_contains_no_automatic_retune_after_open():
    src=Path(p4.__file__).read_text(encoding='utf-8')
    assert 'predictor_retrained_after_holdout_open": False' in src
    assert 'second open is forbidden' in src
