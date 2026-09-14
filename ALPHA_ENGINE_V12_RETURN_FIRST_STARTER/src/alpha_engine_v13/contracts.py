from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from datetime import date
import fnmatch, hashlib, json, shutil, tomllib

BUILD = "V13_P0_RESET_CONTRACT_2026-09-12"

@dataclass(frozen=True)
class ResearchBoundary:
    development_start: date
    validation_start: date
    holdout_start: date


def load_contract(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_denied(relpath: str, patterns: list[str]) -> bool:
    relpath = relpath.replace("\\", "/")
    return any(fnmatch.fnmatch(relpath, p) for p in patterns)


def research_date_allowed(d, holdout_start: str) -> bool:
    # Accept date-like or ISO string. Strictly before holdout.
    if hasattr(d, "date") and not isinstance(d, date):
        d = d.date()
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    cutoff = date.fromisoformat(holdout_start)
    return d < cutoff


def make_workspace(source_root: Path, workspace_root: Path, contract: dict) -> dict:
    source_root = source_root.resolve()
    workspace_root = workspace_root.resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    for sub in ["config", "docs", "src/alpha_engine_v13", "scripts", "tests", "outputs", "state"]:
        (workspace_root / sub).mkdir(parents=True, exist_ok=True)

    manifest = {
        "build": BUILD,
        "source_v12_root": str(source_root),
        "workspace_root": str(workspace_root),
        "holdout_start": contract["research"]["code_blinded_holdout_start"],
        "holdout_label": contract["epistemic_label"]["holdout_2025_2026"],
        "true_virgin_test": contract["epistemic_label"]["true_virgin_test"],
        "allowed_sources": [],
        "missing_allowed_sources": [],
        "denied_source_patterns": contract["denied_sources"]["patterns"],
    }

    for rel in contract["allowed_sources"]["files"]:
        p = source_root / rel
        if p.exists():
            manifest["allowed_sources"].append({
                "path": rel,
                "bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            })
        else:
            manifest["missing_allowed_sources"].append(rel)

    for root_rel in contract["allowed_sources"]["roots"]:
        p = source_root / root_rel
        if p.exists():
            manifest["allowed_sources"].append({"path": root_rel, "type": "root", "exists": True})
        else:
            manifest["missing_allowed_sources"].append(root_rel)

    (workspace_root / "outputs" / "v13_phase0_source_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def gate(contract: dict, manifest: dict) -> list[dict]:
    r = contract["research"]
    p = contract["portfolio"]
    gates = []
    def add(test, ok, value, rule):
        gates.append({"test": test, "status": "PASS" if ok else "FAIL", "blocking": True, "value": value, "rule": rule})

    add("NO_2025_PLUS_RESEARCH_SELECTION", not r["use_2025_plus_for_research_selection"], r["use_2025_plus_for_research_selection"], "must be false")
    add("MULTI_HORIZON_ACTIVE", len(r["multi_horizons"]) >= 4, r["multi_horizons"], "at least four simultaneous horizons")
    add("NO_FIXED_HOLDING_PERIOD", not r["fixed_holding_period"], r["fixed_holding_period"], "must be false")
    add("NO_FIXED_CARDINALITY", not r["fixed_cardinality"], r["fixed_cardinality"], "must be false")
    add("NO_FIXED_MAX_WEIGHT", not r["fixed_max_weight"], r["fixed_max_weight"], "must be false")
    add("NO_FIXED_MIN_WEIGHT", not r["fixed_min_weight"], r["fixed_min_weight"], "must be false")
    add("NO_OLD_MODEL_ARTIFACTS_AS_RESEARCH_INPUT", all(x.startswith("outputs/phase4") or x.startswith("outputs/phase5") or x.startswith("outputs/phase6") or x.startswith("outputs/phase7") or x.startswith("outputs/phase8") or x.startswith("outputs/phase9") or x.startswith("outputs/live_shadow") or x.startswith("src/alpha_engine_v12") for x in contract["denied_sources"]["patterns"]), len(contract["denied_sources"]["patterns"]), "old feature/model/policy/OOS artifacts denied")
    add("SOURCE_DATA_PRESENT", len(manifest["missing_allowed_sources"]) == 0, manifest["missing_allowed_sources"], "all required causal source artifacts must exist")
    add("CONCENTRATION_NOT_ARTIFICIALLY_CAPPED", float(p["hard_max_position_weight"]) >= 0.999, p["hard_max_position_weight"], "research hard cap must permit up to 100% before economic/risk penalties")
    return gates
