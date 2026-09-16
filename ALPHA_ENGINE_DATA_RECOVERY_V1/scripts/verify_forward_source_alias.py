
from __future__ import annotations
import json
from pathlib import Path
import pyarrow.parquet as pq

actual = Path(r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION\ALPHA_ENGINE_V12_RETURN_FIRST_STARTER\outputs")
compat = Path(r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_V12_RETURN_FIRST\ALPHA_ENGINE_V12_RETURN_FIRST_STARTER\outputs")

files = [
    "phase2_canonical_pit_panel.parquet",
    "phase2c_return_price_layer.parquet",
]

report = {}

for name in files:
    a = actual / name
    c = compat / name

    if not a.exists():
        raise SystemExit(f"ACTUAL_MISSING: {a}")
    if not c.exists():
        raise SystemExit(f"COMPAT_MISSING: {c}")

    pa = pq.ParquetFile(a)
    pc = pq.ParquetFile(c)

    if pa.metadata.num_rows <= 0 or pc.metadata.num_rows <= 0:
        raise SystemExit(f"EMPTY_PARQUET: {name}")

    if pa.schema.names != pc.schema.names:
        raise SystemExit(f"SCHEMA_MISMATCH: {name}")

    if pa.metadata.num_rows != pc.metadata.num_rows:
        raise SystemExit(f"ROWCOUNT_MISMATCH: {name}")

    report[name] = {
        "actual": str(a),
        "compat": str(c),
        "rows": pa.metadata.num_rows,
        "columns": len(pa.schema.names),
    }

print(json.dumps(report, indent=2))
