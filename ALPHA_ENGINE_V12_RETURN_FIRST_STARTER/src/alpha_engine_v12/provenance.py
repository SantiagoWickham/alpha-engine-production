from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import DataBoundaryConfig


@dataclass(frozen=True)
class Classification:
    relative_path: str
    allowed_as_model_input: bool
    role: str
    reason: str


def _norm(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def classify(relative_path: str, cfg: DataBoundaryConfig) -> Classification:
    p = _norm(relative_path)
    p_slash = "/" + p

    for frag in cfg.deny_fragments:
        f = frag.replace("\\", "/")
        if f.lower() in p_slash.lower() or f.lower() in p.lower():
            return Classification(p, False, "audit_only", f"denied fragment: {frag}")

    if not any(p == _norm(root) or p.startswith(_norm(root) + "/") for root in cfg.allowed_roots):
        return Classification(p, False, "out_of_boundary", "outside allowed data roots")

    for role, entries in cfg.roles.items():
        for entry in entries:
            e = _norm(entry)
            if p == e or p.startswith(e + "/"):
                return Classification(p, True, role, f"matched role entry: {entry}")

    return Classification(p, False, "unclassified", "inside allowed root but not explicitly approved")


def assert_allowed(relative_path: str, cfg: DataBoundaryConfig) -> None:
    result = classify(relative_path, cfg)
    if not result.allowed_as_model_input:
        raise PermissionError(f"V12 data-boundary rejection: {relative_path} ({result.reason})")
