from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUILD = "V13_P5C_FIX1_COMPACT_DECISION_STATE_2026-09-13"
EXPECTED_SEAL = "46bbbf853561e26625ee3ecbccb6037051556f2f3ca26dcb4e311c165c08d8e9"
MODEL_VERSION = "ALPHA_ENGINE_V13_SEALED_46bbbf85"


@dataclass(frozen=True)
class BridgeCfg:
    api_url: str
    api_token: str
    env_source: str


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip(); v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in {"'", '"'}:
            v = v[1:-1]
        out[k] = v
    return out


def _candidate_envs(root: Path) -> list[Path]:
    cands = [root / ".env", root / "secrets" / ".env", root.parent / ".env", root.parent / "secrets" / ".env"]
    # Historical V12 starter locations, retained only for secret discovery.
    cands += [
        root.parent / "ALPHA_ENGINE_V12_RETURN_FIRST_STARTER" / ".env",
        root.parent / "ALPHA_ENGINE_V12_RETURN_FIRST_STARTER" / "secrets" / ".env",
    ]
    seen=[]
    for p in cands:
        p=p.resolve()
        if p not in seen: seen.append(p)
    return seen


def load_cfg(root: Path) -> BridgeCfg:
    url = os.getenv("MMM_SHEET_API_URL", "").strip()
    token = os.getenv("MMM_SHEET_API_TOKEN", "").strip()
    src = "PROCESS_ENV"
    if not (url and token):
        for p in _candidate_envs(root):
            vals = _parse_env(p)
            if not url: url = vals.get("MMM_SHEET_API_URL", "").strip()
            if not token: token = vals.get("MMM_SHEET_API_TOKEN", "").strip()
            if url and token:
                src = f"DOTENV:{p}"
                break
    if not url:
        raise RuntimeError("SHEETS_API_URL_MISSING: set MMM_SHEET_API_URL in process env or .env")
    if not token:
        raise RuntimeError("SHEETS_API_TOKEN_MISSING: set MMM_SHEET_API_TOKEN in process env or .env")
    if not re.match(r"^https?://", url):
        raise RuntimeError("SHEETS_API_URL_INVALID")
    return BridgeCfg(url, token, src)


def _safe_url(url: str) -> str:
    try:
        p=urllib.parse.urlsplit(url)
        q=urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        clean=[(k, "***" if k.lower()=="token" else v) for k,v in q]
        return urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,urllib.parse.urlencode(clean),p.fragment))
    except Exception:
        return "<redacted-url>"


class SheetApi:
    def __init__(self, cfg: BridgeCfg, timeout: int = 45):
        self.cfg=cfg; self.timeout=timeout

    def _url(self, action: str, **params: Any) -> str:
        q={"action":action,"token":self.cfg.api_token,**{k:v for k,v in params.items() if v is not None}}
        return self.cfg.api_url + ("&" if "?" in self.cfg.api_url else "?") + urllib.parse.urlencode(q)

    def get(self, action: str, **params: Any) -> dict:
        url=self._url(action, **params)
        req=urllib.request.Request(url, headers={"Accept":"application/json","User-Agent":"AlphaEngineV13-SheetsBridge/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw=r.read().decode("utf-8")
        except Exception as exc:
            raise RuntimeError(f"SHEETS_GET_FAILED action={action} url={_safe_url(url)} error={type(exc).__name__}: {exc}") from exc
        try: obj=json.loads(raw)
        except Exception as exc: raise RuntimeError(f"SHEETS_GET_NON_JSON action={action}") from exc
        if not obj.get("ok", False): raise RuntimeError(f"SHEETS_GET_API_ERROR action={action} error={obj.get('error')} message={obj.get('message')}")
        return obj

    def post(self, action: str, body: dict) -> dict:
        url=self._url(action)
        data=json.dumps(body, separators=(",",":"), default=str).encode("utf-8")
        req=urllib.request.Request(url, data=data, method="POST", headers={"Content-Type":"application/json","Accept":"application/json","User-Agent":"AlphaEngineV13-SheetsBridge/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw=r.read().decode("utf-8")
        except Exception as exc:
            raise RuntimeError(f"SHEETS_POST_FAILED action={action} url={_safe_url(url)} error={type(exc).__name__}: {exc}") from exc
        try: obj=json.loads(raw)
        except Exception as exc: raise RuntimeError(f"SHEETS_POST_NON_JSON action={action}") from exc
        if not obj.get("ok", False): raise RuntimeError(f"SHEETS_POST_API_ERROR action={action} error={obj.get('error')} message={obj.get('message')}")
        return obj


def _read_json(path: Path) -> dict:
    if not path.exists(): raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), default=str).encode()).hexdigest()


def _contract(root: Path) -> tuple[dict, dict]:
    summary=_read_json(root/"outputs"/"live_shadow"/"v13_live_shadow_summary.json")
    contract=_read_json(root/"outputs"/"live_shadow"/"v13_live_shadow_contract_latest.json")
    if summary.get("status") != "PASS": raise RuntimeError(f"LIVE_SHADOW_NOT_PASS status={summary.get('status')}")
    if summary.get("seal_id") != EXPECTED_SEAL or contract.get("seal_id") != EXPECTED_SEAL: raise RuntimeError("LIVE_SHADOW_SEAL_MISMATCH")
    if not summary.get("shadow_only", False) or not contract.get("shadow_only", False): raise RuntimeError("LIVE_SHADOW_FLAG_MISSING")
    if summary.get("real_orders_sent") or contract.get("real_orders_sent"): raise RuntimeError("LIVE_CONTRACT_CLAIMS_REAL_ORDERS")
    if summary.get("tuning_performed"): raise RuntimeError("LIVE_SUMMARY_CLAIMS_TUNING")
    rows=contract.get("rows") or []
    if not isinstance(rows,list) or not rows: raise RuntimeError("LIVE_CONTRACT_EMPTY")
    tickers=[str(r.get("ticker","")).strip().upper() for r in rows]
    if any(not t for t in tickers) or len(set(tickers)) != len(tickers): raise RuntimeError("LIVE_CONTRACT_TICKER_KEYS_INVALID")
    if str(summary.get("latest_completed_session")) != str(contract.get("asof")): raise RuntimeError("LIVE_SUMMARY_CONTRACT_ASOF_MISMATCH")
    return summary,contract


def _payload(summary: dict, contract: dict) -> dict:
    # IMPORTANT: Apps Script decision_state_replace stores its JSON in ONE cell.
    # Google Sheets cells are capped at 50,000 characters, so the full 183-row
    # contract must never be embedded here.  The full contract remains authoritative
    # in Python; row-wise shadow decisions are published separately to _ALERT_STATE.
    rows=contract["rows"]
    payload={
        "schema_version":"ALPHA_ENGINE_V13_SHADOW_STATE_V2_COMPACT",
        "source_of_truth":"PYTHON_ALPHA_ENGINE_V13",
        "row_store":"_ALERT_STATE",
        "full_contract_store":"PYTHON_LOCAL_OUTPUTS",
        "model_version":MODEL_VERSION,
        "seal_id":EXPECTED_SEAL,
        "asof":contract["asof"],
        "input_fingerprint":contract.get("input_fingerprint"),
        "contract_digest":_digest(rows),
        "shadow_only":True,
        "real_orders_sent":False,
        "tuning_performed":False,
        "holdout_verdict":summary.get("holdout_verdict"),
        "advisor_rows":len(rows),
    }
    raw=json.dumps(payload,separators=(",",":"),default=str)
    if len(raw) >= 45000:
        raise RuntimeError(f"COMPACT_DECISION_STATE_UNEXPECTEDLY_LARGE chars={len(raw)}")
    return payload


def _alert_rows(contract: dict) -> list[dict]:
    out=[]
    for r in contract["rows"]:
        h=r.get("effective_horizon_sessions")
        try: htxt=f"EH_{float(h):.1f}D"
        except Exception: htxt="EH_NA"
        out.append({
            "ticker":str(r.get("ticker","")).upper(),
            "action":str(r.get("model_intent") or ("ELIGIBLE_ENTRY" if r.get("entry_ok") else "NO_ENTRY")),
            "severity":"SHADOW",
            "signal":htxt,
            "event":"V13_LIVE_SHADOW",
            "alpha":r.get("expected_active_total"),
            "alpha_percentile":"",
            "current_weight":"",
            "model_weight":r.get("model_target_weight"),
            "updated_at":contract.get("asof"),
        })
    return out


def _sheet_table(payload: dict) -> list[dict]:
    headers=payload.get("headers") or []; rows=payload.get("rows") or []
    return [{str(headers[i]): row[i] if i < len(row) else None for i in range(len(headers))} for row in rows]


def _decision_state_payload(api_payload: dict) -> dict | None:
    headers=api_payload.get("headers") or []; rows=api_payload.get("rows") or []
    try: ki=headers.index("key"); ji=headers.index("json")
    except ValueError: return None
    for row in rows:
        if len(row)>max(ki,ji) and str(row[ki])=="latest_runtime":
            try: return json.loads(str(row[ji]))
            except Exception: return None
    return None


def build_sheet_shadow_bridge(root: Path) -> dict:
    root=root.resolve(); cfg=load_cfg(root); summary,contract=_contract(root); api=SheetApi(cfg)
    outdir=root/"outputs"/"sheets_shadow"; outdir.mkdir(parents=True,exist_ok=True)

    # Read-only preflight first. No spreadsheet mutation occurs before all reads pass.
    health=api.get("health")
    positions=api.get("positions",limit=5000)
    cash=api.get("cash",limit=100)
    mandate=api.get("mandate",limit=500)
    preflight={
        "health":{"api_version":health.get("api_version"),"legacy_health_model_version":health.get("model_version"),"validation_status":health.get("validation_status")},
        "positions_rows":positions.get("returned",0),
        "cash_rows":cash.get("returned",0),
        "mandate_rows":mandate.get("returned",0),
        "env_source":cfg.env_source,
    }
    (outdir/"v13_sheets_preflight.json").write_text(json.dumps(preflight,indent=2,default=str),encoding="utf-8")
    (outdir/"v13_sheets_positions_snapshot.json").write_text(json.dumps({"headers":positions.get("headers",[]),"rows":positions.get("rows",[])},indent=2,default=str),encoding="utf-8")
    (outdir/"v13_sheets_cash_snapshot.json").write_text(json.dumps({"headers":cash.get("headers",[]),"rows":cash.get("rows",[])},indent=2,default=str),encoding="utf-8")
    (outdir/"v13_sheets_mandate_snapshot.json").write_text(json.dumps({"headers":mandate.get("headers",[]),"rows":mandate.get("rows",[])},indent=2,default=str),encoding="utf-8")

    pub=_payload(summary,contract); alerts=_alert_rows(contract)
    txid=_digest({"seal":EXPECTED_SEAL,"asof":pub["asof"],"contract_digest":pub["contract_digest"]})[:24]
    pub["bridge_transaction_id"]=txid

    # Publish shadow state only. Never call operation_append/cash_set/forward_event_append.
    alert_resp=api.post("alert_state_replace",{"rows":alerts})
    state_resp=api.post("decision_state_replace",{"payload":pub})

    # Read back and prove parity from the spreadsheet API.
    decision_read=api.get("decision_state",limit=10)
    alert_read=api.get("alert_state",limit=5000)
    saved=_decision_state_payload(decision_read)
    if not saved: raise RuntimeError("SHEETS_DECISION_STATE_READBACK_MISSING")
    checks={
        "seal_id":saved.get("seal_id")==EXPECTED_SEAL,
        "asof":str(saved.get("asof"))==str(pub["asof"]),
        "contract_digest":saved.get("contract_digest")==pub["contract_digest"],
        "advisor_rows":int(saved.get("advisor_rows",-1))==len(contract["rows"]),
        "alert_rows":int(alert_read.get("returned",-1))==len(alerts),
        "shadow_only":saved.get("shadow_only") is True,
        "real_orders_sent":saved.get("real_orders_sent") is False,
    }
    if not all(checks.values()): raise RuntimeError(f"SHEETS_READBACK_PARITY_FAILED {checks}")

    result={
        "status":"PASS",
        "phase":"V13-P5C",
        "build":BUILD,
        "seal_id":EXPECTED_SEAL,
        "asof":pub["asof"],
        "bridge_transaction_id":txid,
        "api_version":health.get("api_version"),
        "legacy_health_model_version":health.get("model_version"),
        "decision_state_mode":"COMPACT_METADATA_SINGLE_CELL",
        "full_contract_rows_authoritative_local":len(contract["rows"]),
        "alert_rows_published":len(alerts),
        "positions_rows_read":positions.get("returned",0),
        "cash_rows_read":cash.get("returned",0),
        "mandate_rows_read":mandate.get("returned",0),
        "readback_parity":checks,
        "python_v13_authoritative":True,
        "sheets_model_logic_authoritative":False,
        "shadow_only":True,
        "real_orders_sent":False,
        "operation_append_called":False,
        "cash_mutated":False,
        "forward_ledger_mutated":False,
        "tuning_performed":False,
        "next":"Use the captured portfolio/cash/mandate snapshots to build the portfolio-aware BUY/HOLD/REDUCE/EXIT translator without changing the sealed model.",
    }
    (outdir/"v13_sheets_shadow_bridge_summary.json").write_text(json.dumps(result,indent=2,default=str),encoding="utf-8")
    return result
