import json
from pathlib import Path
from alpha_engine_v13.portfolio_action_shadow import build_portfolio_action_shadow
ROOT=Path(__file__).resolve().parents[1]
print(json.dumps(build_portfolio_action_shadow(ROOT),indent=2,default=str))
