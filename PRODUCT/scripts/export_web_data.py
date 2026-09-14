from pathlib import Path
import json
import pandas as pd
import numpy as np

# File lives at ROOT/PRODUCT/scripts/export_web_data.py
ROOT = Path(__file__).resolve().parents[2]
V13 = ROOT / "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
BYMA = ROOT / "ALPHA_ENGINE_BYMA"
WEB_DATA = ROOT / "PRODUCT" / "web" / "data"
WEB_DATA.mkdir(parents=True, exist_ok=True)

def metrics(path):
    if not path.exists():
        return None
    d = pd.read_csv(path)
    if d.empty or "nav" not in d:
        return None
    nav = pd.to_numeric(d["nav"], errors="coerce").dropna()
    if nav.empty:
        return None
    n = len(nav)
    years = n / 252.0
    final = float(nav.iloc[-1])
    cagr = float(final**(1/years)-1) if final > 0 and years > 0 else None
    dd = float((nav/nav.cummax()-1).min())
    return {"nav": final, "cagr": cagr, "max_drawdown": dd, "rows": int(n)}

v13_hold = metrics(V13/"outputs"/"v13_phase4_holdout_nav_20bps.csv")
v13_pre = metrics(V13/"outputs"/"v13_phase3z_nav_20bps.csv")
byma_hold = metrics(BYMA/"outputs"/"byma_holdout_nav_20bps.csv")
byma_pre = metrics(BYMA/"outputs"/"byma_pre2025_nav_20bps.csv")

target_path = BYMA/"outputs"/"byma_current_target.csv"
target = []
asof = None
if target_path.exists():
    t = pd.read_csv(target_path)
    if "signal_date" in t and len(t):
        asof = str(t["signal_date"].iloc[0])
    keep = [
        "ticker","target_weight","vehicle","byma_ticker","quantity",
        "actual_weight","signal_date","price_date","ratio","unit_usd"
    ]
    cols = [c for c in keep if c in t.columns]
    target = t[cols].replace({np.nan:None}).to_dict(orient="records")

personal_path = ROOT/"PRODUCT"/"personal_portfolio.json"
personal = None
if personal_path.exists():
    personal = json.loads(personal_path.read_text(encoding="utf-8-sig"))

payload = {
    "asof": asof,
    "tracks": {
        "v13_ideal": v13_hold,
        "byma_transfer": byma_hold,
        "personal": personal,
    },
    "research_reference": {
        "v13_pre2025": v13_pre,
        "byma_transfer_pre2025": byma_pre,
    },
    "byma_current_target": target,
    "policy": {
        "v13_ideal": "frozen international/reference model",
        "byma_transfer": "V13 forecast surface restricted to current BYMA universe before portfolio allocation",
        "personal": "actual discretionary portfolio; never mutates model tracks",
    },
}
out = WEB_DATA/"dashboard.json"
out.write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")
print("WROTE", out)
