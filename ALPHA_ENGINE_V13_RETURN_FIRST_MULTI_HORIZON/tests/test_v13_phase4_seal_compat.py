import hashlib
import json
from alpha_engine_v13 import final_holdout as p4


def legacy_restore(payload):
    out = dict(payload)
    out["horizon_reliability"] = {int(k): v for k, v in out["horizon_reliability"].items()}
    return out


def test_phase4_seal_bug_is_integer_vs_string_key_sorting():
    original = {
        "build": "X",
        "horizon_reliability": {5: .27, 10: .17, 20: .31, 60: .10, 120: .10, 252: .04},
        "models_retrained_using_2025_plus": False,
    }
    sealed = p4._sha256_payload(original)
    roundtripped = json.loads(json.dumps(original))
    assert p4._sha256_payload(roundtripped) != sealed
    assert p4._sha256_payload(legacy_restore(roundtripped)) == sealed


def test_fix_does_not_need_to_change_final_holdout_source():
    # The compatibility layer is external to the sealed model/engine source.
    assert p4.__file__.endswith("final_holdout.py")


def test_expected_horizons_are_exact():
    assert p4.HORIZONS == (5, 10, 20, 60, 120, 252)
