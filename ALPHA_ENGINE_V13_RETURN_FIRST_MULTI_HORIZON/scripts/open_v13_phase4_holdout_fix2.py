from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alpha_engine_v13 import final_holdout as p4

EXPECTED_SEAL_ID = "46bbbf853561e26625ee3ecbccb6037051556f2f3ca26dcb4e311c165c08d8e9"
EXPECTED_FINAL_HOLDOUT_SHA256 = "d12d1e04bde3a9248c7374650fc71c552c90081135810e3037125e2b9c0c23fa"
HORIZON_KEYS = {"5", "10", "20", "60", "120", "252"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _restore_prejson_key_types(payload):
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    hr = out.get("horizon_reliability")
    if isinstance(hr, dict):
        converted = {}
        for k, v in hr.items():
            s = str(k)
            if s not in HORIZON_KEYS:
                raise RuntimeError(f"Unexpected horizon_reliability key in sealed manifest: {k!r}")
            converted[int(s)] = v
        out["horizon_reliability"] = converted
    return out


def compat_payload_hash(payload) -> str:
    return p4._ORIGINAL_SHA256_PAYLOAD(_restore_prejson_key_types(payload))


def _rebuild_holdout_alpha_rank(test: pd.DataFrame, h: int) -> pd.DataFrame:
    """Reconstruct reporting-only fields exactly as Phase2U horizon_frame did in research.

    This function changes no predictor score, portfolio weight, trade, cost, or NAV.
    It only supplies the target-derived rank required by p2u.evaluate() after outcomes
    are already observed.
    """
    z = test.copy()
    excess_cols = [f"excess_spy_{h}d", f"excess_qqq_{h}d", f"excess_uew_{h}d"]
    missing = [c for c in excess_cols if c not in z.columns]
    if missing:
        raise RuntimeError(f"Holdout evidence is missing required excess-return columns h={h}: {missing}")

    e = np.column_stack([pd.to_numeric(z[c], errors="coerce") for c in excess_cols])
    # Match Phase2U horizon_frame semantics. Suppress only the expected all-NaN-row warning.
    finite_any = np.isfinite(e).any(axis=1)
    robust = np.full(len(z), np.nan, dtype=float)
    if finite_any.any():
        robust[finite_any] = np.nanmin(e[finite_any], axis=1)
    z["_robust_alpha"] = robust
    z["_alpha_rank"] = z.groupby("signal_date", observed=True)["_robust_alpha"].rank(
        method="average", pct=True
    )
    return z


def evaluate_reporting_compat(test: pd.DataFrame, score: np.ndarray, h: int, cfg):
    """Compatibility shim for a reporting-only schema omission in Phase4.

    The sealed engine called Phase2U.evaluate on holdout targets without first adding
    _alpha_rank. During research that field was created by horizon_frame. Recreate it
    identically here, then delegate to the original sealed evaluate function.
    """
    if "_alpha_rank" not in test.columns:
        test = _rebuild_holdout_alpha_rank(test, h)
    return p4._ORIGINAL_P2U_EVALUATE(test, score, h, cfg)


def verify_resume_only(root: Path) -> dict:
    cfg = p4.load_cfg(root)
    manifest_path = root / cfg.p["seal_manifest"]
    artifact_path = root / cfg.p["seal_artifact_copy"]
    if not manifest_path.exists() or not artifact_path.exists():
        raise FileNotFoundError("Phase4 seal manifest/artifact copy missing")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = str(manifest.get("seal_id", ""))
    if expected != EXPECTED_SEAL_ID:
        raise RuntimeError(f"Unexpected seal_id: {expected}; expected {EXPECTED_SEAL_ID}")

    core = {k: v for k, v in manifest.items() if k != "seal_id"}
    current_hash = p4._ORIGINAL_SHA256_PAYLOAD(core)
    restored_hash = compat_payload_hash(core)
    if restored_hash != expected:
        raise RuntimeError("Typed-key compatibility no longer reproduces published seal_id")

    if json.loads(artifact_path.read_text(encoding="utf-8")) != manifest:
        raise RuntimeError("Local freeze artifact differs from output seal manifest")

    mismatches = []
    for rec in manifest.get("files", []):
        path = root / str(rec["path"])
        if not path.exists():
            mismatches.append((str(rec["path"]), "MISSING"))
            continue
        got = _sha256_file(path)
        if got != str(rec["sha256"]):
            mismatches.append((str(rec["path"]), got))
    if mismatches:
        raise RuntimeError(f"Sealed file mismatch; refusing resume: {mismatches[:3]}")

    fh = root / "src" / "alpha_engine_v13" / "final_holdout.py"
    fh_sha = _sha256_file(fh)
    if fh_sha != EXPECTED_FINAL_HOLDOUT_SHA256:
        raise RuntimeError(f"final_holdout.py changed: {fh_sha}")

    marker = root / cfg.p["holdout_open_marker"]
    if not marker.exists():
        raise RuntimeError(
            "FIX2 is resume-only. No OPENING marker exists, so it refuses to initiate a fresh holdout open."
        )
    mk = json.loads(marker.read_text(encoding="utf-8"))
    if mk.get("state") == "COMPLETE":
        raise RuntimeError("Holdout is already COMPLETE; second open is forbidden")
    if mk.get("state") != "OPENING":
        raise RuntimeError(f"Unexpected holdout marker state: {mk.get('state')}")
    if mk.get("seal_id") != expected:
        raise RuntimeError("OPENING marker seal_id differs from published seal")
    if mk.get("source_sha256") != fh_sha:
        raise RuntimeError("OPENING marker final_holdout source hash differs from sealed source")

    summary = root / cfg.p["summary"]
    if summary.exists():
        raise RuntimeError("Holdout summary already exists while marker is OPENING; refusing ambiguous resume")

    return {
        "status": "PASS",
        "mode": "RESUME_ONLY_AFTER_TECHNICAL_FAILURE",
        "seal_id": expected,
        "holdout_state": "OPENING",
        "holdout_already_observed": True,
        "sealed_files_verified": len(manifest.get("files", [])),
        "final_holdout_sha256": fh_sha,
        "reporting_fix": "REBUILD_PHASE2U_ALPHA_RANK_FOR_HORIZON_EVIDENCE_ONLY",
        "portfolio_logic_changed": False,
        "predictor_changed": False,
        "policy_changed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    # Compatibility patches are external and in-memory only. Sealed files stay untouched.
    p4._ORIGINAL_SHA256_PAYLOAD = p4._sha256_payload
    p4._ORIGINAL_P2U_EVALUATE = p4.p2u.evaluate

    report = verify_resume_only(ROOT)
    print("PHASE4 TECHNICAL RESUME PREFLIGHT")
    print(json.dumps(report, indent=2))
    if args.verify_only:
        return 0

    p4._sha256_payload = compat_payload_hash
    p4.p2u.evaluate = evaluate_reporting_compat
    result = p4.open_holdout_once(ROOT)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
