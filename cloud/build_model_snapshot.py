from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
V13 = ROOT / "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
REC = ROOT / "ALPHA_ENGINE_DATA_RECOVERY_V1"

SUMMARY = V13 / "outputs" / "live_shadow" / "v13_live_shadow_summary.json"
CONTRACT = V13 / "outputs" / "live_shadow" / "v13_live_shadow_contract_latest.csv"
FORWARD = REC / "outputs" / "data_recovery_v1" / "forward_v42" / "forward_nav_latest.json"

OUT = ROOT / "mobile_snapshot" / "model.json"
HISTORY = ROOT / "cloud" / "history"
DECISIONS = HISTORY / "decisions"
RUNS = HISTORY / "model_runs.csv"

BA = ZoneInfo("America/Argentina/Buenos_Aires")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def first(d: dict, *names, default=None):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default


def fnum(v, default=None):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_targets(path: Path) -> list[dict]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return []

    cols = set(rows[0].keys())
    ticker_col = next((c for c in ["ticker", "Ticker", "symbol", "Symbol"] if c in cols), None)
    weight_col = next((c for c in [
        "model_target_weight", "target_weight", "economic_target_weight", "weight"
    ] if c in cols), None)
    entry_col = next((c for c in ["entry_ok", "eligible", "entry_eligible"] if c in cols), None)
    alpha_col = next((c for c in [
        "expected_active_total", "expected_active_alpha", "active_alpha", "alpha"
    ] if c in cols), None)

    if not ticker_col or not weight_col:
        return []

    out = []
    for r in rows:
        w = fnum(r.get(weight_col))
        if w is None or w <= 0:
            continue
        item = {
            "ticker": str(r.get(ticker_col) or "").strip(),
            "target_weight": w,
        }
        if entry_col:
            item["entry_ok"] = str(r.get(entry_col) or "").strip()
        if alpha_col:
            item["expected_active"] = fnum(r.get(alpha_col))
        out.append(item)

    out.sort(key=lambda x: x["target_weight"], reverse=True)
    return out


def append_history(row: dict) -> None:
    HISTORY.mkdir(parents=True, exist_ok=True)
    fields = list(row.keys())
    existing = []
    if RUNS.exists():
        with RUNS.open("r", encoding="utf-8-sig", newline="") as f:
            existing = list(csv.DictReader(f))

    key = (str(row["run_id"]), str(row["run_attempt"]))
    existing = [
        r for r in existing
        if (str(r.get("run_id")), str(r.get("run_attempt"))) != key
    ]
    existing.append({k: str(v) for k, v in row.items()})

    with RUNS.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(existing)


summary = load_json(SUMMARY)
forward = load_json(FORWARD)
targets = read_targets(CONTRACT)

status = str(first(summary, "status", default="UNKNOWN"))
if status != "PASS":
    raise RuntimeError(f"LIVE_SUMMARY_NOT_PASS: {status}")

real_orders = first(summary, "real_orders_sent", default=False)
tuning = first(summary, "tuning_performed", default=False)
if real_orders not in (False, "false", "False", 0, None):
    raise RuntimeError("REAL_ORDERS_FLAG_NOT_FALSE")
if tuning not in (False, "false", "False", 0, None):
    raise RuntimeError("TUNING_FLAG_NOT_FALSE")

now_utc = datetime.now(timezone.utc)
now_ba = now_utc.astimezone(BA)
trigger = os.getenv("AE_TRIGGER", "manual")
new_sessions = int(first(summary, "new_sessions", default=0) or 0)

if trigger == "schedule" and new_sessions <= 1:
    classification = "CONTEMPORANEOUS_SCHEDULED"
elif trigger == "schedule":
    classification = "SCHEDULED_WITH_CATCHUP"
else:
    classification = "MANUAL_BOOTSTRAP_OR_CATCHUP"

latest_session = str(first(summary, "latest_completed_session", "latest", default=""))
seal_id = str(first(summary, "seal_id", default=""))
entry_eligible = first(summary, "entry_eligible_latest", default="")
positive_targets = first(summary, "positive_targets_latest", default="")
target_weight_sum = fnum(first(summary, "target_weight_sum_latest", default=None))

fwd_start = str(first(forward, "start", "start_date", default=""))
fwd_latest = str(first(forward, "latest", "latest_date", default=""))
fwd_sessions = first(forward, "sessions", default="")
fwd_return = fnum(first(forward, "return", "total_return", default=None))
parity_diff = fnum(first(forward, "parity_max_diff", default=None))
parity_status = "PASS" if parity_diff is not None and parity_diff < 1e-10 else "CHECK"

run_id = os.getenv("AE_RUN_ID", "")
run_attempt = os.getenv("AE_RUN_ATTEMPT", "")
commit_sha = os.getenv("AE_COMMIT_SHA", "")

snap = {
    "schema": "ALPHA_ENGINE_MOBILE_MODEL_V1",
    "status": "PASS",
    "generated_at_utc": now_utc.isoformat(),
    "generated_at_ba": now_ba.isoformat(),
    "trigger": trigger,
    "classification": classification,
    "run_id": run_id,
    "source_commit": commit_sha,
    "latest_completed_session": latest_session,
    "new_sessions": new_sessions,
    "seal_id": seal_id,
    "shadow_only": first(summary, "shadow_only", default=True),
    "real_orders_sent": real_orders,
    "tuning_performed": tuning,
    "entry_eligible": entry_eligible,
    "positive_targets": positive_targets,
    "target_weight_sum": target_weight_sum,
    "forward": {
        "start": fwd_start,
        "latest": fwd_latest,
        "sessions": fwd_sessions,
        "return": fwd_return,
        "parity_max_diff": parity_diff,
        "holdout_parity": parity_status,
    },
    "contract_sha256": sha256(CONTRACT) if CONTRACT.exists() else "",
    "targets": targets,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")

DECISIONS.mkdir(parents=True, exist_ok=True)
stamp = now_ba.strftime("%Y%m%d_%H%M%S")
decision_path = DECISIONS / f"{stamp}_{trigger}.json"
decision_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")

append_history({
    "executed_at_ba": now_ba.isoformat(),
    "execution_mode": classification,
    "trigger": trigger,
    "run_id": run_id,
    "run_attempt": run_attempt,
    "source_commit": commit_sha,
    "latest_completed_session": latest_session,
    "new_sessions": new_sessions,
    "forward_latest": fwd_latest,
    "forward_return": "" if fwd_return is None else f"{fwd_return:.12f}",
    "entry_eligible": entry_eligible,
    "positive_targets": positive_targets,
    "target_weight_sum": "" if target_weight_sum is None else f"{target_weight_sum:.12f}",
    "holdout_parity": parity_status,
    "seal_id": seal_id,
})

print(json.dumps({
    "status": "PASS",
    "classification": classification,
    "latest_completed_session": latest_session,
    "new_sessions": new_sessions,
    "forward_latest": fwd_latest,
    "output": str(OUT),
    "decision_archive": str(decision_path),
}, indent=2))
