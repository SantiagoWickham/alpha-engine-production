from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from .config import ProjectConfig
from .provenance import classify


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def _csv_columns(path: Path) -> list[str] | None:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            return next(csv.reader(f), None)
    except Exception:
        return None


def _parquet_columns(path: Path) -> list[str] | None:
    try:
        import pyarrow.parquet as pq
        return list(pq.read_schema(path).names)
    except Exception:
        return None


def schema_columns(path: Path) -> list[str] | None:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _csv_columns(path)
    if suffix == ".parquet":
        return _parquet_columns(path)
    return None


def build_catalog(root: Path, cfg: ProjectConfig, hash_allowed: bool = False) -> dict[str, Any]:
    data_root = root / "data"
    rows: list[dict[str, Any]] = []
    if not data_root.exists():
        raise FileNotFoundError(f"Missing data directory: {data_root}")

    for path in sorted(p for p in data_root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        c = classify(rel, cfg.data_boundary)
        row = {
            "path": rel,
            "size_bytes": path.stat().st_size,
            "suffix": path.suffix.lower(),
            "allowed_as_model_input": c.allowed_as_model_input,
            "role": c.role,
            "reason": c.reason,
        }
        if c.allowed_as_model_input:
            row["columns"] = schema_columns(path)
            if hash_allowed:
                row["sha256"] = _sha256(path)
        rows.append(row)

    allowed = [r for r in rows if r["allowed_as_model_input"]]
    role_counts: dict[str, int] = {}
    for r in allowed:
        role_counts[r["role"]] = role_counts.get(r["role"], 0) + 1

    return {
        "project": cfg.name,
        "objective": cfg.objective,
        "total_files": len(rows),
        "allowed_model_input_files": len(allowed),
        "audit_only_or_rejected_files": len(rows) - len(allowed),
        "role_counts": role_counts,
        "files": rows,
    }


def write_catalog(catalog: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
