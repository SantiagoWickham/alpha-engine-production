from pathlib import Path
import json
from alpha_engine_v13.live_shadow import build_live_shadow
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    print(json.dumps(build_live_shadow(ROOT),indent=2,default=str))
