from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from alpha_engine_v13.final_holdout import open_holdout_once
if __name__=='__main__':
    s=open_holdout_once(ROOT); print(json.dumps(s,indent=2,default=str))
