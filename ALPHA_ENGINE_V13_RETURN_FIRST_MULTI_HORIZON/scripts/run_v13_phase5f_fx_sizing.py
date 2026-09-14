import json
from pathlib import Path
from alpha_engine_v13.portfolio_fx_sizing import build_fx_total_nav_shadow_sizing
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    print(json.dumps(build_fx_total_nav_shadow_sizing(ROOT),indent=2,default=str))
