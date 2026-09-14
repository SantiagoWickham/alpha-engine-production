from __future__ import annotations

import json
from pathlib import Path

from .catalog import build_catalog, write_catalog
from .config import load_config


def build_foundation(root: Path, hash_allowed: bool = False) -> dict:
    cfg = load_config(root / "config" / "project.toml")
    catalog = build_catalog(root, cfg, hash_allowed=hash_allowed)

    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    write_catalog(catalog, outputs / "phase1_data_catalog.json")

    approved = [f for f in catalog["files"] if f["allowed_as_model_input"]]
    decision_clock = {
        "evaluation_policy": cfg.clock.evaluation_policy,
        "trade_policy": cfg.clock.trade_policy,
        "fixed_rebalance": cfg.clock.fixed_rebalance,
        "allow_multiple_trades_per_month": cfg.clock.allow_multiple_trades_per_month,
        "allow_zero_trades_per_month": cfg.clock.allow_zero_trades_per_month,
        "principle": "Evaluate whenever information can change; trade only when expected net edge clears the trigger.",
    }
    (outputs / "phase1_decision_clock.json").write_text(
        json.dumps(decision_clock, indent=2), encoding="utf-8"
    )

    summary = {
        "status": "PASS" if approved else "FAIL",
        "project": cfg.name,
        "objective": cfg.objective,
        "research_mode": cfg.research_mode,
        "total_files_seen": catalog["total_files"],
        "allowed_model_input_files": catalog["allowed_model_input_files"],
        "rejected_or_audit_only_files": catalog["audit_only_or_rejected_files"],
        "role_counts": catalog["role_counts"],
        "clock": decision_clock,
        "next_gate": "Do not build alpha model until approved source schemas and PIT timing are reviewed.",
    }
    (outputs / "phase1_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
