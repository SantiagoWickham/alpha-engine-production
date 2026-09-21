from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REC = ROOT / "ALPHA_ENGINE_DATA_RECOVERY_V1"
RUNNER = REC / "scripts" / "run_dr1f_market_refresh.py"
LIVE = REC / "outputs" / "data_recovery_v1" / "live"
MARKET_CSV = LIVE / "mercado_riesgo_live_latest.csv"
MARKET_SUMMARY = LIVE / "market_refresh_summary_latest.json"
OUT = ROOT / "mobile_snapshot" / "market.json"

BA = ZoneInfo("America/Argentina/Buenos_Aires")
UA = "Mozilla/5.0 AlphaEngineGitHubLive/1.0"


def chart_meta(symbol: str = "SPY") -> dict:
    enc = quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}?range=1d&interval=1m&includePrePost=true"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/plain,*/*"})
    with urlopen(req, timeout=20) as r:
        payload = json.loads(r.read().decode("utf-8"))
    result = ((payload.get("chart") or {}).get("result") or [])
    if not result:
        raise RuntimeError("Yahoo chart returned no result for SPY")
    return result[0].get("meta") or {}


def inferred_market_state(meta: dict) -> tuple[str, dict]:
    now = time.time()
    ctp = meta.get("currentTradingPeriod") or {}

    def win(name: str):
        x = ctp.get(name) or {}
        try:
            return float(x.get("start")), float(x.get("end"))
        except (TypeError, ValueError):
            return None, None

    pre_s, pre_e = win("pre")
    reg_s, reg_e = win("regular")
    post_s, post_e = win("post")

    state = str(meta.get("marketState") or "").upper().strip()
    if state in {"PRE", "REGULAR", "POST", "POSTPOST", "CLOSED"}:
        direct = state
    else:
        direct = ""

    if reg_s is not None and reg_e is not None and reg_s <= now < reg_e:
        inferred = "REGULAR"
    elif pre_s is not None and pre_e is not None and pre_s <= now < pre_e:
        inferred = "PRE"
    elif post_s is not None and post_e is not None and post_s <= now < post_e:
        inferred = "POST"
    else:
        inferred = direct or "CLOSED"

    detail = {
        "direct_market_state": direct or None,
        "inferred_market_state": inferred,
        "regular_start_epoch": reg_s,
        "regular_end_epoch": reg_e,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return inferred, detail


def fnum(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")
    if not s:
        return None
    try:
        x = float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_snapshot(state: str, state_detail: dict, forced: bool) -> dict:
    if not MARKET_CSV.exists():
        raise FileNotFoundError(MARKET_CSV)

    rows = []
    with MARKET_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "ticker": (r.get("Ticker") or "").strip(),
                "provider_symbol": (r.get("Yahoo Symbol") or "").strip(),
                "benchmark": (r.get("Benchmark") or "").strip(),
                "price": fnum(r.get("Precio")),
                "var_1d": fnum(r.get("Var 1D")),
                "ret_1m": fnum(r.get("Ret 1M")),
                "ret_3m": fnum(r.get("Ret 3M")),
                "ret_6m": fnum(r.get("Ret 6M")),
                "ret_12m": fnum(r.get("Ret 12M")),
                "vol_20d": fnum(r.get("Vol 20D")),
                "rs_3m": fnum(r.get("RS 3M")),
                "beta_6m": fnum(r.get("Beta 6M")),
                "dist_52w_high": fnum(r.get("Dist 52W High")),
                "coverage": fnum(r.get("Cobertura Mercado")),
                "source": (r.get("Fuente") or "").strip(),
                "source_updated": (r.get("Actualización") or "").strip(),
            })

    rows = [x for x in rows if x["ticker"]]
    rows.sort(key=lambda x: x["ticker"])

    summary = load_json(MARKET_SUMMARY)
    now_utc = datetime.now(timezone.utc)
    now_ba = now_utc.astimezone(BA)

    return {
        "schema": "ALPHA_ENGINE_MOBILE_MARKET_V1",
        "status": "PASS",
        "generated_at_utc": now_utc.isoformat(),
        "generated_at_ba": now_ba.isoformat(),
        "market_state_at_run": state,
        "forced_manual_refresh": forced,
        "regular_session_guard": True,
        "refresh_target_seconds": 300,
        "asset_rows": len(rows),
        "provider_coverage": summary.get("provider_coverage") or summary.get("coverage") or None,
        "summary": summary,
        "session_clock": state_detail,
        "rows": rows,
    }


def github_output(name: str, value: str) -> None:
    p = os.getenv("GITHUB_OUTPUT")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not RUNNER.exists():
        raise FileNotFoundError(RUNNER)

    meta = chart_meta("SPY")
    state, detail = inferred_market_state(meta)

    if state != "REGULAR" and not args.force:
        github_output("updated", "false")
        github_output("market_state", state)
        print(json.dumps({
            "status": "SKIP",
            "reason": "US_REGULAR_SESSION_NOT_OPEN",
            "market_state": state,
            "checked_at_utc": detail["checked_at_utc"],
        }, indent=2))
        return 0

    cmd = [sys.executable, str(RUNNER), "--market-workers", "6"]
    proc = subprocess.run(cmd, cwd=str(REC))
    if proc.returncode != 0:
        raise RuntimeError(f"DR1F market refresh failed returncode={proc.returncode}")

    snap = build_snapshot(state, detail, args.force)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    github_output("updated", "true")
    github_output("market_state", state)
    print(json.dumps({
        "status": "PASS",
        "market_state": state,
        "forced": args.force,
        "rows": snap["asset_rows"],
        "output": str(OUT),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
