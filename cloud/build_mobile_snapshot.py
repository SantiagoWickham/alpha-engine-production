from __future__ import annotations

import csv
import hashlib
import html
import json
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

SITE = ROOT / "mobile_snapshot"
HISTORY = ROOT / "cloud" / "history"
DECISIONS = HISTORY / "decisions"
RUNS = HISTORY / "runs.csv"

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
        return float(v)
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
    weight_col = next(
        (
            c
            for c in [
                "model_target_weight",
                "target_weight",
                "economic_target_weight",
                "weight",
            ]
            if c in cols
        ),
        None,
    )
    entry_col = next((c for c in ["entry_ok", "eligible", "entry_eligible"] if c in cols), None)
    alpha_col = next(
        (
            c
            for c in [
                "expected_active_total",
                "expected_active_alpha",
                "active_alpha",
                "alpha",
            ]
            if c in cols
        ),
        None,
    )

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

    key = (row["run_id"], row["run_attempt"])
    existing = [
        r
        for r in existing
        if (str(r.get("run_id")), str(r.get("run_attempt"))) != key
    ]
    existing.append({k: str(v) for k, v in row.items()})

    with RUNS.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(existing)


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


summary = load_json(SUMMARY)
forward = load_json(FORWARD)
targets = read_targets(CONTRACT)

now_utc = datetime.now(timezone.utc)
now_ba = now_utc.astimezone(BA)
trigger = os.getenv("AE_TRIGGER", "manual")
execution_mode = "SCHEDULED_LIVE" if trigger == "schedule" else "BOOTSTRAP_OR_MANUAL"

latest_session = str(first(summary, "latest_completed_session", "latest", default=""))
status = str(first(summary, "status", default="UNKNOWN"))
seal_id = str(first(summary, "seal_id", default=""))
entry_eligible = first(summary, "entry_eligible_latest", default="")
positive_targets = first(summary, "positive_targets_latest", default="")
target_weight_sum = fnum(first(summary, "target_weight_sum_latest", default=None))
shadow_only = first(summary, "shadow_only", default=True)
real_orders = first(summary, "real_orders_sent", default=False)
tuning = first(summary, "tuning_performed", default=False)

fwd_start = str(first(forward, "start", "start_date", default=""))
fwd_latest = str(first(forward, "latest", "latest_date", default=""))
fwd_sessions = first(forward, "sessions", default="")
fwd_return = fnum(first(forward, "return", "total_return", default=None))
parity_diff = fnum(first(forward, "parity_max_diff", default=None))
parity_status = "PASS" if parity_diff is not None and parity_diff < 1e-10 else "CHECK"

if status != "PASS":
    raise RuntimeError(f"LIVE_SUMMARY_NOT_PASS: {status}")
if real_orders not in (False, "false", "False", 0, None):
    raise RuntimeError("REAL_ORDERS_FLAG_NOT_FALSE")
if tuning not in (False, "false", "False", 0, None):
    raise RuntimeError("TUNING_FLAG_NOT_FALSE")

run_id = os.getenv("AE_RUN_ID", "")
run_attempt = os.getenv("AE_RUN_ATTEMPT", "")
commit_sha = os.getenv("AE_COMMIT_SHA", "")

run_row = {
    "executed_at_ba": now_ba.isoformat(),
    "executed_at_utc": now_utc.isoformat(),
    "execution_mode": execution_mode,
    "trigger": trigger,
    "run_id": run_id,
    "run_attempt": run_attempt,
    "source_commit": commit_sha,
    "latest_completed_session": latest_session,
    "phase5b_status": status,
    "forward_start": fwd_start,
    "forward_latest": fwd_latest,
    "forward_sessions": fwd_sessions,
    "forward_return": "" if fwd_return is None else f"{fwd_return:.12f}",
    "entry_eligible": entry_eligible,
    "positive_targets": positive_targets,
    "target_weight_sum": "" if target_weight_sum is None else f"{target_weight_sum:.12f}",
    "holdout_parity": parity_status,
    "contract_sha256": sha256(CONTRACT) if CONTRACT.exists() else "",
    "seal_id": seal_id,
}
append_history(run_row)

DECISIONS.mkdir(parents=True, exist_ok=True)
stamp = now_ba.strftime("%Y%m%d_%H%M%S")
decision = {
    "executed_at_ba": now_ba.isoformat(),
    "execution_mode": execution_mode,
    "trigger": trigger,
    "run_id": run_id,
    "source_commit": commit_sha,
    "latest_completed_session": latest_session,
    "phase5b_status": status,
    "seal_id": seal_id,
    "forward": {
        "start": fwd_start,
        "latest": fwd_latest,
        "sessions": fwd_sessions,
        "return": fwd_return,
        "holdout_parity": parity_status,
        "parity_max_diff": parity_diff,
    },
    "model": {
        "entry_eligible": entry_eligible,
        "positive_targets": positive_targets,
        "target_weight_sum": target_weight_sum,
        "shadow_only": shadow_only,
        "real_orders_sent": real_orders,
        "tuning_performed": tuning,
    },
    "targets": targets,
}
decision_path = DECISIONS / f"{stamp}_{trigger}.json"
decision_path.write_text(json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8")

SITE.mkdir(parents=True, exist_ok=True)
snapshot = decision | {
    "generated_at_ba": now_ba.isoformat(),
    "decision_file": str(decision_path.relative_to(ROOT)).replace("\\", "/"),
}
(SITE / "snapshot.json").write_text(
    json.dumps(snapshot, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
(SITE / ".nojekyll").write_text("", encoding="utf-8")

logo_src = ROOT / "web" / "v4" / "alpha_engine_logo.jpeg"
if logo_src.exists():
    (SITE / "alpha_engine_logo.jpeg").write_bytes(logo_src.read_bytes())

top = targets[:25]
rows_html = "".join(
    f"""
    <tr>
      <td>{esc(x.get("ticker"))}</td>
      <td>{x.get("target_weight", 0)*100:.2f}%</td>
      <td>{esc(x.get("entry_ok", ""))}</td>
      <td>{"" if x.get("expected_active") is None else f'{x["expected_active"]:.4f}'}</td>
    </tr>
    """
    for x in top
)

fwd_pct = "—" if fwd_return is None else f"{fwd_return*100:.2f}%"
weight_pct = "—" if target_weight_sum is None else f"{target_weight_sum*100:.2f}%"

page = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0f14">
<title>Alpha Engine</title>
<style>
:root{{--bg:#0b0f14;--card:#121923;--muted:#92a0b3;--line:#263244;--text:#f5f7fb;--good:#49d17d;--warn:#ffcc66}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif}}
.wrap{{max-width:920px;margin:0 auto;padding:18px 14px 42px}}
.header{{display:flex;gap:14px;align-items:center;margin:8px 0 18px}}
.logo{{width:54px;height:54px;border-radius:14px;object-fit:cover;background:#151b24}}
h1{{font-size:24px;margin:0}} .sub{{color:var(--muted);font-size:13px;margin-top:3px}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:15px}}
.k{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}}
.v{{font-size:21px;font-weight:700;margin-top:6px}}
.good{{color:var(--good)}} .warn{{color:var(--warn)}}
.wide{{grid-column:1/-1}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:10px 7px;border-bottom:1px solid var(--line);text-align:right}}
th:first-child,td:first-child{{text-align:left}}
th{{color:var(--muted);font-size:11px;text-transform:uppercase}}
.footer{{color:var(--muted);font-size:12px;margin-top:18px;line-height:1.5}}
.badge{{display:inline-block;padding:5px 9px;border-radius:999px;border:1px solid var(--line);font-size:12px}}
@media(max-width:600px){{.grid{{grid-template-columns:1fr}} .v{{font-size:20px}}}}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <img class="logo" src="alpha_engine_logo.jpeg" onerror="this.style.display='none'">
    <div>
      <h1>Alpha Engine</h1>
      <div class="sub">Snapshot read-only · {esc(execution_mode)}</div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="k">Estado</div>
      <div class="v good">{esc(status)}</div>
    </div>
    <div class="card">
      <div class="k">Última sesión completa</div>
      <div class="v">{esc(latest_session)}</div>
    </div>
    <div class="card">
      <div class="k">Forward</div>
      <div class="v">{esc(fwd_start)} → {esc(fwd_latest)}</div>
    </div>
    <div class="card">
      <div class="k">Retorno Forward</div>
      <div class="v">{esc(fwd_pct)}</div>
    </div>
    <div class="card">
      <div class="k">Entradas elegibles</div>
      <div class="v">{esc(entry_eligible)}</div>
    </div>
    <div class="card">
      <div class="k">Targets positivos</div>
      <div class="v">{esc(positive_targets)}</div>
    </div>
    <div class="card">
      <div class="k">Peso total objetivo</div>
      <div class="v">{esc(weight_pct)}</div>
    </div>
    <div class="card">
      <div class="k">Holdout parity</div>
      <div class="v good">{esc(parity_status)}</div>
    </div>

    <div class="card wide">
      <div class="k" style="margin-bottom:8px">Targets del modelo</div>
      <table>
        <thead><tr><th>Ticker</th><th>Objetivo</th><th>Entry OK</th><th>Alpha esp.</th></tr></thead>
        <tbody>{rows_html or '<tr><td colspan="4">Sin targets positivos.</td></tr>'}</tbody>
      </table>
    </div>
  </div>

  <div class="footer">
    <span class="badge">NO REAL ORDERS</span>
    <span class="badge">NO TUNING</span>
    <span class="badge">V13 SEALED</span><br><br>
    Actualizado: {esc(now_ba.strftime("%Y-%m-%d %H:%M:%S %Z"))}<br>
    Trigger: {esc(trigger)} · Run ID: {esc(run_id)}<br>
    Seal: {esc(seal_id[:20] + "…" if seal_id else "—")}
  </div>
</div>
<script>
(() => {{
  const generated = new Date({json.dumps(now_utc.isoformat())});
  const ageHours = (Date.now() - generated.getTime()) / 36e5;
  if (ageHours > 36) {{
    document.querySelector('.sub').innerHTML += ' · <span style="color:#ffcc66">STALE &gt;36h</span>';
  }}
}})();
</script>
</body>
</html>
"""
(SITE / "index.html").write_text(page, encoding="utf-8")

print(json.dumps({
    "status": "PASS",
    "execution_mode": execution_mode,
    "latest_completed_session": latest_session,
    "forward_latest": fwd_latest,
    "positive_targets": positive_targets,
    "mobile_site": str(SITE),
    "decision_archive": str(decision_path),
}, indent=2))
