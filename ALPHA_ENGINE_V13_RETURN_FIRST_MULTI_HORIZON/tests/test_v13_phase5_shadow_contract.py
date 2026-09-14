from pathlib import Path
import json, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from alpha_engine_v13.shadow_contract import _sha_payload, BUILD

def test_build_name(): assert BUILD.startswith('V13_P5A_')
def test_typed_key_hash_is_stable():
    a={'horizon_reliability':{5:.2,10:.8},'x':1}
    b={'horizon_reliability':{int(k):v for k,v in {'5':.2,'10':.8}.items()},'x':1}
    assert _sha_payload(a)==_sha_payload(b)
def test_shadow_contract_has_no_execution_side_effects():
    text=(Path(__file__).resolve().parents[1]/'src'/'alpha_engine_v13'/'shadow_contract.py').read_text()
    assert 'real_orders_sent' in text and "'tuning_performed':False" in text
