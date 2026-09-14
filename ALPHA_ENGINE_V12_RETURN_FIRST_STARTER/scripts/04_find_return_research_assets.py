from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
inv = json.loads((OUT / "data_inventory.json").read_text(encoding="utf-8"))

terms = {
    "returns": re.compile(r"return|ret_|returns|price|close|adj", re.I),
    "alpha": re.compile(r"alpha|score|rank|percentile|factor", re.I),
    "fundamental": re.compile(r"revenue|sales|yield|earn|margin|roe|roa|debt|shares|fundamental", re.I),
    "risk": re.compile(r"risk|vol|variance|cov|drawdown|beta", re.I),
    "universe": re.compile(r"universe|ticker|symbol|listing|delist|lifecycle", re.I),
}

hits = {k: [] for k in terms}
for f in inv["files"]:
    hay = " ".join([f["path"], " ".join((f.get("inspection") or {}).get("columns", [])), " ".join((f.get("inspection") or {}).get("keys", []))])
    for k, pat in terms.items():
        if pat.search(hay): hits[k].append(f["path"])

(OUT / "research_asset_map.json").write_text(json.dumps(hits, indent=2, ensure_ascii=False), encoding="utf-8")
for k, v in hits.items():
    print(f"{k:12s}: {len(v)}")
    for x in v[:20]: print("  ", x)
