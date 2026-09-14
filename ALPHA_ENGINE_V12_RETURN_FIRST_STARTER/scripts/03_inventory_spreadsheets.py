from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INP = ROOT / "inputs"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

result = {"files": []}
for p in sorted(INP.glob("*.xlsx")):
    rec = {"path": str(p), "size_bytes": p.stat().st_size}
    try:
        import pandas as pd
        xf = pd.ExcelFile(p)
        rec["sheets"] = []
        for s in xf.sheet_names:
            try:
                df = pd.read_excel(p, sheet_name=s, nrows=12)
                rec["sheets"].append({"name": s, "columns": [str(c) for c in df.columns], "preview": df.head(5).astype(object).where(df.notna(), None).to_dict("records")})
            except Exception as e:
                rec["sheets"].append({"name": s, "error": repr(e)})
    except Exception as e:
        rec["error"] = repr(e)
    result["files"].append(rec)

(OUT / "spreadsheet_inventory.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
print(f"PASS spreadsheet inventory: {len(result['files'])} xlsx files")
