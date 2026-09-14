import json
from pathlib import Path
from alpha_engine_v13.portfolio_action_review import build_portfolio_action_review
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    print(json.dumps(build_portfolio_action_review(ROOT),indent=2,default=str))
