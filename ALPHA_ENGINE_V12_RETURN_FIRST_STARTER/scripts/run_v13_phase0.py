from pathlib import Path
import argparse, csv, json, shutil, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from alpha_engine_v13.contracts import BUILD, load_contract, make_workspace, gate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-v12-root", default=str(ROOT))
    ap.add_argument("--workspace", default=str(ROOT.parent / "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"))
    args = ap.parse_args()
    source = Path(args.source_v12_root)
    workspace = Path(args.workspace)
    contract_path = ROOT / "config" / "v13_contract.toml"
    contract = load_contract(contract_path)

    # Copy the V13 starter itself into the new workspace, but never old V12 model code.
    for rel in ["config/v13_contract.toml", "docs/V13_MANDATE.md"]:
        src = ROOT / rel
        dst = workspace / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for pkg_rel in ["src/alpha_engine_v13/contracts.py"]:
        src = ROOT / pkg_rel
        dst = workspace / pkg_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    manifest = make_workspace(source, workspace, contract)
    gates = gate(contract, manifest)
    status = "PASS" if all(g["status"] == "PASS" for g in gates) else "FAIL"
    summary = {
        "status": status,
        "phase": "V13-P0",
        "build": BUILD,
        "name": "RESEARCH_RESET_AND_CONTRACT",
        "objective": contract["objective"]["primary"],
        "workspace": str(workspace),
        "research_contract": contract["research"],
        "portfolio_contract": contract["portfolio"],
        "benchmarks": contract["objective"]["benchmarks"],
        "holdout_label": contract["epistemic_label"]["holdout_2025_2026"],
        "true_virgin_test": contract["epistemic_label"]["true_virgin_test"],
        "source_manifest": manifest,
        "gate": gates,
        "next_gate": "V13 Phase 1: build fresh multi-horizon feature/model research using PRE-2025 data only; cardinality and weights must be endogenous and selected on pre-2025 net excess return."
    }
    out = workspace / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "v13_phase0_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (out / "v13_phase0_gate.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["test","status","blocking","value","rule"])
        w.writeheader(); w.writerows(gates)

    print("="*88)
    print("ALPHA ENGINE V13 - PHASE 0: RESEARCH RESET & CONTRACT")
    print("="*88)
    print(f"BUILD: {BUILD}")
    print(f"SOURCE V12 ROOT: {source}")
    print(f"NEW V13 WORKSPACE: {workspace}")
    print("2025+ RESEARCH SELECTION: FORBIDDEN BY CONTRACT")
    print("MULTI-HORIZON: 5/10/20/60/120/252 all remain active")
    print("CARDINALITY: ENDOGENOUS; no fixed Top-N")
    print("WEIGHTS: ENDOGENOUS; no fixed 3%-12% band")
    print(json.dumps(summary, indent=2, default=str))
    return 0 if status == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
