from __future__ import annotations
import csv, json, os, sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

MAX_SAMPLE_ROWS = 5
TEXT_EXT = {".csv", ".json", ".jsonl", ".txt", ".md", ".yaml", ".yml"}
TAB_EXT = {".csv", ".parquet", ".feather"}
DB_EXT = {".sqlite", ".sqlite3", ".db"}


def safe_stat(p: Path):
    st = p.stat()
    return {"size_bytes": st.st_size, "mtime": datetime.fromtimestamp(st.st_mtime).isoformat()}


def inspect_csv(p: Path):
    out = {"kind": "csv", "columns": [], "sample": [], "row_count": None}
    try:
        with p.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            r = csv.reader(f)
            header = next(r, [])
            out["columns"] = header
            n = 0
            for row in r:
                if n < MAX_SAMPLE_ROWS:
                    out["sample"].append(row[: min(len(row), 40)])
                n += 1
            out["row_count"] = n
    except Exception as e:
        out["error"] = repr(e)
    return out


def inspect_json(p: Path):
    out = {"kind": "json"}
    try:
        if p.stat().st_size > 50_000_000:
            out["skipped_parse"] = "file_gt_50mb"
            return out
        obj = json.loads(p.read_text(encoding="utf-8-sig", errors="replace"))
        out["root_type"] = type(obj).__name__
        if isinstance(obj, dict):
            out["keys"] = list(obj.keys())[:200]
        elif isinstance(obj, list):
            out["length"] = len(obj)
            if obj and isinstance(obj[0], dict):
                out["first_row_keys"] = list(obj[0].keys())[:200]
    except Exception as e:
        out["error"] = repr(e)
    return out


def inspect_sqlite(p: Path):
    out = {"kind": "sqlite", "tables": {}}
    try:
        con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        names = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
        for t in names:
            q = '"' + t.replace('"', '""') + '"'
            cols = [r[1] for r in con.execute(f"pragma table_info({q})")]
            try:
                count = con.execute(f"select count(*) from {q}").fetchone()[0]
            except Exception:
                count = None
            out["tables"][t] = {"columns": cols, "row_count": count}
        con.close()
    except Exception as e:
        out["error"] = repr(e)
    return out


records = []
for p in sorted(DATA.rglob("*")):
    if not p.is_file():
        continue
    rel = p.relative_to(ROOT).as_posix()
    rec = {"path": rel, "suffix": p.suffix.lower(), **safe_stat(p)}
    if p.suffix.lower() == ".csv": rec["inspection"] = inspect_csv(p)
    elif p.suffix.lower() == ".json": rec["inspection"] = inspect_json(p)
    elif p.suffix.lower() in DB_EXT: rec["inspection"] = inspect_sqlite(p)
    records.append(rec)

summary = {
    "root": str(DATA),
    "file_count": len(records),
    "total_bytes": sum(x["size_bytes"] for x in records),
    "by_suffix": {},
    "files": records,
}
for r in records:
    summary["by_suffix"][r["suffix"]] = summary["by_suffix"].get(r["suffix"], 0) + 1

(OUT / "data_inventory.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
with (OUT / "data_inventory.csv").open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["path", "suffix", "size_bytes", "mtime", "kind", "row_count_or_tables", "columns_preview"])
    for r in records:
        ins = r.get("inspection", {})
        count = ins.get("row_count")
        if ins.get("kind") == "sqlite": count = len(ins.get("tables", {}))
        cols = ins.get("columns", [])
        if not cols and ins.get("kind") == "sqlite":
            cols = sorted({c for t in ins.get("tables", {}).values() for c in t.get("columns", [])})
        w.writerow([r["path"], r["suffix"], r["size_bytes"], r["mtime"], ins.get("kind"), count, " | ".join(cols[:40])])

print(f"PASS data inventory: {len(records)} files")
print("by_suffix:", summary["by_suffix"])
