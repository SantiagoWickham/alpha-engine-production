from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class ClockConfig:
    evaluation_policy: str
    trade_policy: str
    fixed_rebalance: bool
    allow_multiple_trades_per_month: bool
    allow_zero_trades_per_month: bool


@dataclass(frozen=True)
class DataBoundaryConfig:
    allowed_roots: tuple[str, ...]
    deny_fragments: tuple[str, ...]
    roles: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    timezone: str
    objective: str
    research_mode: str
    clock: ClockConfig
    data_boundary: DataBoundaryConfig


def load_config(path: Path) -> ProjectConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    p = raw["project"]
    c = raw["clock"]
    db = raw["data_boundary"]
    roles = {k: tuple(v) for k, v in db.get("roles", {}).items()}
    return ProjectConfig(
        name=p["name"],
        timezone=p["timezone"],
        objective=p["objective"],
        research_mode=p["research_mode"],
        clock=ClockConfig(
            evaluation_policy=c["evaluation_policy"],
            trade_policy=c["trade_policy"],
            fixed_rebalance=bool(c["fixed_rebalance"]),
            allow_multiple_trades_per_month=bool(c["allow_multiple_trades_per_month"]),
            allow_zero_trades_per_month=bool(c["allow_zero_trades_per_month"]),
        ),
        data_boundary=DataBoundaryConfig(
            allowed_roots=tuple(db["allowed_roots"]),
            deny_fragments=tuple(db["deny_fragments"]),
            roles=roles,
        ),
    )
