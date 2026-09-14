from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from alpha_engine_v13 import final_holdout as p4

EXPECTED_SEAL_PREFIX = "46bbbf85"
EXPECTED_SEAL_ID = "46bbbf853561e26625ee3ecbccb6037051556f2f3ca26dcb4e311c165c08d8e9"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _restore_prejson_key_types(payload):
    """Restore only the key typing that existed when Phase4 SEAL computed seal_id.

    The original seal was computed in-memory with integer horizon keys. JSON object
    keys are strings after round-trip. Python json.dumps(sort_keys=True) sorts ints
    numerically but strings lexicographically, which changed only canonical ordering.
    """
    if not isinstance(payload, dict):
        return payload
    out = dict(payload)
    hr = out.get("horizon_reliability")
    if isinstance(hr, dict):
        converted = {}
        for k, v in hr.items():
            s = str(k)
            if s not in {"5", "10", "20", "60", "120", "252"}:
                raise RuntimeError(f"Unexpected horizon_reliability key in sealed manifest: {k!r}")
            converted[int(s)] = v
        out["horizon_reliability"] = converted
    return out


def compat_payload_hash(payload) -> str:
    return p4._ORIGINAL_SHA256_PAYLOAD(_restore_prejson_key_types(payload))


def verify_compatibility_only(root: Path) -> dict:
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

    # Prove this is exactly the known canonicalization mismatch, not a broad bypass.
    if current_hash == expected:
        raise RuntimeError("Compatibility fix is unnecessary: current verifier already recomputes seal_id")
    if restored_hash != expected:
        raise RuntimeError(
            "Legacy typed-key canonicalization does not reproduce the published seal_id; refusing to open holdout"
        )

    if json.loads(artifact_path.read_text(encoding="utf-8")) != manifest:
        raise RuntimeError("Local artifacts/freeze Phase4 seal copy differs from outputs seal manifest")

    # Verify every sealed file byte-for-byte before installing the compatibility hash.
    mismatches = []
    for rec in manifest.get("files", []):
        path = root / str(rec["path"])
        if not path.exists():
            mismatches.append((str(rec["path"]), "MISSING"))
            continue
        got = _sha256_file(path)
        if got != str(rec["sha256"]):
            mismatches.append((str(rec["path"]), f"SHA256 {got}"))
    if mismatches:
        raise RuntimeError(f"Sealed file mismatch; refusing to open holdout: {mismatches[:3]}")

    final_holdout_record = next(
        (r for r in manifest.get("files", []) if str(r.get("path")) == "src/alpha_engine_v13/final_holdout.py"),
        None,
    )
    if final_holdout_record is None:
        raise RuntimeError("final_holdout.py is not present in sealed file manifest")

    return {
        "status": "PASS",
        "seal_id": expected,
        "known_bug": "JSON_OBJECT_INTEGER_KEYS_BECOME_STRINGS_AND_SORT_ORDER_CHANGES",
        "unmodified_core_hash": current_hash,
        "typed_key_compat_hash": restored_hash,
        "sealed_files_verified": len(manifest.get("files", [])),
        "final_holdout_sha256": final_holdout_record["sha256"],
        "holdout_opened": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    # Preserve original function; patch only in process memory after proving exact bug.
    p4._ORIGINAL_SHA256_PAYLOAD = p4._sha256_payload
    report = verify_compatibility_only(ROOT)
    print("PHASE4 SEAL COMPATIBILITY PREFLIGHT")
    print(json.dumps(report, indent=2))
    if args.verify_only:
        return 0

    p4._sha256_payload = compat_payload_hash
    result = p4.open_holdout_once(ROOT)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
