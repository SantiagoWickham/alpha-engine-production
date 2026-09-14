from __future__ import annotations

from pathlib import Path


def project_root(start: Path | None = None) -> Path:
    p = (start or Path.cwd()).resolve()
    for candidate in (p, *p.parents):
        if (candidate / "config" / "project.toml").exists():
            return candidate
    raise FileNotFoundError("Could not locate config/project.toml above current directory")
