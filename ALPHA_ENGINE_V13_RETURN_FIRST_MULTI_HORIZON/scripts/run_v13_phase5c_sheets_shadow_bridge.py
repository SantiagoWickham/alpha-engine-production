import json
from pathlib import Path
from alpha_engine_v13.sheets_shadow_bridge import build_sheet_shadow_bridge
ROOT=Path(__file__).resolve().parents[1]
print(json.dumps(build_sheet_shadow_bridge(ROOT),indent=2,default=str))
