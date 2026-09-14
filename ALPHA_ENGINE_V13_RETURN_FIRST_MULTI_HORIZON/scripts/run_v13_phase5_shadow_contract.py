from pathlib import Path
import json
from alpha_engine_v13.shadow_contract import build_contract
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__': print(json.dumps(build_contract(ROOT),indent=2))
