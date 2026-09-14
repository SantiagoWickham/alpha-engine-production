from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

def load(name):
    p=OUT/name
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None

env=load("environment.json") or {}
data=load("data_inventory.json") or {}
repo=load("repo_inventory.json") or {}
sheets=load("spreadsheet_inventory.json") or {}
assets=load("research_asset_map.json") or {}

lines=[]
lines.append("="*88)
lines.append("ALPHA ENGINE V12.0 RETURN FIRST - PHASE 0 SUMMARY")
lines.append("="*88)
lines.append(f"Root: {env.get('root')}")
lines.append(f"Data exists: {env.get('data_exists')}")
lines.append(f"Data files: {data.get('file_count')}")
lines.append(f"Data bytes: {data.get('total_bytes')}")
lines.append(f"Extensions: {data.get('by_suffix')}")
lines.append(f"Existing repos detected: {len(repo.get('repos',[]))}")
lines.append(f"Spreadsheet exports detected: {len(sheets.get('files',[]))}")
lines.append("")
lines.append("RESEARCH ASSET MAP")
for k,v in assets.items(): lines.append(f"{k}: {len(v)} candidate files")
lines.append("")
lines.append("PHASE 0 STATUS: PASS if the data inventory completed without errors.")
lines.append("No signal, optimizer, Google Sheet, cloud workflow or forward state was modified.")
(OUT/"phase0_summary.txt").write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
