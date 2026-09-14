from __future__ import annotations
import hashlib, json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

CANDIDATES = [
    ROOT.parent / "mmm-advisor-deploy",
    ROOT.parent / "ALPHA_ENGINE_V10_4_FORWARD_CORE_FINAL_PRE_FORWARD",
]
IGNORE = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "data"}


def sha256(p: Path):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

found = []
for repo in CANDIDATES:
    if not repo.exists():
        continue
    files = []
    for p in repo.rglob("*"):
        if not p.is_file() or any(part in IGNORE for part in p.parts):
            continue
        # Never hash/read secret values; only record existence.
        if p.name == ".env":
            files.append({"path": p.relative_to(repo).as_posix(), "secret_file": True})
            continue
        try:
            files.append({"path": p.relative_to(repo).as_posix(), "size_bytes": p.stat().st_size, "sha256": sha256(p)})
        except Exception as e:
            files.append({"path": p.relative_to(repo).as_posix(), "error": repr(e)})
    found.append({"repo": str(repo), "file_count": len(files), "files": files})

obj = {"repos": found}
(OUT / "repo_inventory.json").write_text(json.dumps(obj, indent=2), encoding="utf-8")
print("PASS repo inventory", [(x["repo"], x["file_count"]) for x in found])
