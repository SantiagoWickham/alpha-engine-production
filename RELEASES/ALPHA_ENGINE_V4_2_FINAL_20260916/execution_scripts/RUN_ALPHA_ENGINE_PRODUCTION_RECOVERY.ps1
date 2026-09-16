
$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"
$BUILDER = Join-Path $REC "scripts\build_runtime_product_state.py"
$SERVER  = Join-Path $ROOT "web\run_data_recovery_server.py"

Write-Host ""
Write-Host "================================================================"
Write-Host "ALPHA ENGINE - PRODUCTION RECOVERY"
Write-Host "ONE RUNNER / NO SHEETS / NO V13 MUTATION"
Write-Host "================================================================"

if (-not (Test-Path $ROOT)) { throw "ROOT no existe." }
if (-not (Test-Path $REC))  { throw "DATA RECOVERY V1 no existe." }
if (-not (Test-Path (Join-Path $ROOT "web\server.py"))) { throw "web\server.py no existe." }


@'
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION")
REC = ROOT / "ALPHA_ENGINE_DATA_RECOVERY_V1"
V13 = ROOT / "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
PRODUCT = ROOT / "PRODUCT"
PUBLIC = ROOT / "public" / "data"
STATE = PUBLIC / "alpha_product_state.json"
RECEIPT = REC / "outputs" / "data_recovery_v1" / "production_runtime_receipt.json"

LIVE_MKT = REC / "outputs" / "data_recovery_v1" / "live" / "mercado_riesgo_live_latest.csv"
LIVE_MKT_SUMMARY = REC / "outputs" / "data_recovery_v1" / "live" / "market_refresh_summary_latest.json"
FUND = REC / "outputs" / "data_recovery_v1" / "staging" / "fundamentales_payload_latest.csv"
COVERAGE = REC / "outputs" / "data_recovery_v1" / "staging" / "recovery_coverage_summary.json"

CRITICAL_TEXT = [
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON/outputs/v13_phase2r_model_spec.json",
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON/outputs/v13_phase2u_expert_evidence.csv",
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON/outputs/v13_phase3aa_freeze_manifest.json",
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON/outputs/v13_phase4_sealed_features.csv",
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON/outputs/v13_phase4_model_seal_manifest.json",
]
CRITICAL_BINARY = [
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON/outputs/v13_phase4_sealed_model_bundle.joblib",
]

EXPECTED_SCHEMA = "ALPHA_ENGINE_PRODUCT_STATE_V1"

FUND_SCORE_HEADERS = [
    "Score Calidad (Shrink)",
    "Score Crecimiento (Shrink)",
    "Score Valuación (Shrink)",
]
MKT_SCORE_HEADERS = [
    "Score Tendencia",
    "Score RS",
    "Score Participación",
    "Score Mercado",
    "Score Volatilidad",
    "Score Tail Risk",
    "Score Liquidez",
    "Beta/Corr Info Score",
    "RISK SCORE",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm_text_bytes(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def git_show(path: str, ref: str = "HEAD") -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{ref}:{path}"],
        cwd=ROOT,
        stderr=subprocess.STDOUT,
    )


def verify_v13_immutable() -> None:
    print("[1/8] V13 IMMUTABILITY GATE")
    failures: list[str] = []

    for rel in CRITICAL_TEXT:
        disk = ROOT / rel
        if not disk.exists():
            failures.append(f"MISSING {rel}")
            continue
        try:
            committed = git_show(rel, "HEAD")
        except subprocess.CalledProcessError as exc:
            failures.append(f"HEAD_MISSING {rel}: {exc.output.decode(errors='replace')[:200]}")
            continue
        if norm_text_bytes(disk.read_bytes()) != norm_text_bytes(committed):
            failures.append(f"REAL_CONTENT_DIFF {rel}")
        else:
            print(f"  PASS text-normalized: {Path(rel).name}")

    for rel in CRITICAL_BINARY:
        disk = ROOT / rel
        if not disk.exists():
            failures.append(f"MISSING {rel}")
            continue
        try:
            committed = git_show(rel, "HEAD")
        except subprocess.CalledProcessError as exc:
            failures.append(f"HEAD_MISSING {rel}: {exc.output.decode(errors='replace')[:200]}")
            continue
        if disk.read_bytes() != committed:
            failures.append(f"BINARY_DIFF {rel}")
        else:
            print(f"  PASS exact-binary: {Path(rel).name}")

    if failures:
        print("")
        for item in failures:
            print("  FAIL", item)
        raise RuntimeError("V13_IMMUTABILITY_GATE_FAILED")

    print("  V13 critical artifacts match HEAD (EOL differences ignored for text).")


def refresh_market() -> None:
    print("")
    print("[2/8] REFRESH DATA RECOVERY MARKET - LOCAL ONLY / NO SHEETS")
    script = REC / "scripts" / "run_dr1f_market_refresh.py"
    if not script.exists():
        raise RuntimeError(f"MISSING_MARKET_REFRESHER: {script}")

    proc = subprocess.run(
        [sys.executable, str(script), "--market-workers", "6"],
        cwd=REC,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"MARKET_REFRESH_FAILED exit={proc.returncode}")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        headers = reader.fieldnames or []
    return headers, rows


def blank(v: Any) -> bool:
    return v is None or str(v).strip() == ""


def number(v: Any) -> float | int | None:
    if blank(v):
        return None
    s = str(v).strip()
    try:
        x = float(s)
        if not math.isfinite(x):
            return None
        if x.is_integer() and "." not in s and "e" not in s.lower():
            return int(x)
        return x
    except Exception:
        return None


def typed(v: Any) -> Any:
    if blank(v):
        return None
    n = number(v)
    return n if n is not None else str(v)


def validate_recovery_files() -> tuple[list[dict[str, str]], list[dict[str, str]], dict, dict]:
    print("")
    print("[3/8] RECOVERY PAYLOAD GATES")

    mh, mr = read_csv(LIVE_MKT)
    fh, fr = read_csv(FUND)

    if len(mh) != 41 or len(mr) != 200:
        raise RuntimeError(f"MARKET_SHAPE_FAILED rows={len(mr)} cols={len(mh)}")
    if len(fh) != 29 or len(fr) != 187:
        raise RuntimeError(f"FUND_SHAPE_FAILED rows={len(fr)} cols={len(fh)}")

    for i, row in enumerate(mr, start=1):
        for h in MKT_SCORE_HEADERS:
            if not blank(row.get(h)):
                raise RuntimeError(f"OLD_MARKET_SCORE_FOUND row={i} field={h}")
        v = number(row.get("Var 1D"))
        if v is not None and abs(float(v)) > 0.35:
            raise RuntimeError(f"MARKET_QUARANTINE ticker={row.get('Ticker')} var1d={v}")

    for i, row in enumerate(fr, start=1):
        for h in FUND_SCORE_HEADERS:
            if not blank(row.get(h)):
                raise RuntimeError(f"OLD_FUND_SCORE_FOUND row={i} field={h}")

    ms = json.loads(LIVE_MKT_SUMMARY.read_text(encoding="utf-8"))
    cs = json.loads(COVERAGE.read_text(encoding="utf-8"))

    if int(ms.get("market_asset_rows", -1)) != 200:
        raise RuntimeError("MARKET_SUMMARY_ROWS_FAILED")
    if int(ms.get("unique_provider_symbols_requested", -1)) != 212:
        raise RuntimeError("MARKET_SUMMARY_PROVIDER_COUNT_FAILED")
    if int(ms.get("provider_symbols_failed", -1)) != 0:
        raise RuntimeError("MARKET_PROVIDER_FAILURES_PRESENT")
    if int(ms.get("asset_symbols_missing", -1)) != 0:
        raise RuntimeError("MARKET_ASSET_SYMBOLS_MISSING")

    print("  PASS market: 200x41, provider coverage 212/212, score cells blank")
    print("  PASS fundamentals: 187x29, score cells blank")
    return mr, fr, ms, cs


def normalize_market(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    mapping = {
        "Ticker": "ticker",
        "Yahoo Symbol": "market_symbol",
        "Benchmark": "benchmark",
        "Precio": "price",
        "Var 1D": "var_1d",
        "Ret 1M": "ret_1m",
        "Ret 3M": "ret_3m",
        "Ret 6M": "ret_6m",
        "Ret 12M": "ret_12m",
        "SMA20": "sma20",
        "SMA50": "sma50",
        "SMA200": "sma200",
        "Dist SMA20": "dist_sma20",
        "Dist SMA50": "dist_sma50",
        "Dist SMA200": "dist_sma200",
        "RSI14": "rsi14",
        "Vol 20D": "vol_20d",
        "Vol 60D": "vol_60d",
        "Vol 1A": "vol_1y",
        "Downside Dev 60D": "downside_dev_60d",
        "Max Drawdown 1A": "max_drawdown_1y",
        "Avg Vol 20D": "avg_volume_20d",
        "Dollar Vol 20D": "dollar_volume_20d",
        "Vol 20/60": "relative_volume_20v60",
        "RS 3M": "rs_3m",
        "RS 6M": "rs_6m",
        "Beta 6M": "beta_6m",
        "Corr 6M": "corr_6m",
        "Dist 52W High": "dist_52w_high",
        "Cobertura Mercado": "coverage",
        "Fuente": "source",
        "Actualización": "updated_at",
    }
    out = []
    for r in rows:
        item = {new: typed(r.get(old)) for old, new in mapping.items()}
        out.append(item)
    return out


def normalize_fundamentals(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    mapping = {
        "Ticker": "ticker",
        "Nombre": "name",
        "Sector": "sector",
        "Precio USD": "price_usd",
        "Market Cap": "market_cap",
        "P/E": "pe",
        "Fwd P/E": "forward_pe",
        "PEG": "peg",
        "ROE": "roe",
        "ROA": "roa",
        "Debt/Eq": "debt_to_equity",
        "Margen Neto": "net_margin",
        "EPS Growth": "eps_growth",
        "Revenue Growth": "revenue_growth",
        "FCF": "fcf",
        "FCF Yield": "fcf_yield",
        "EV/EBITDA": "ev_ebitda",
        "Current Ratio": "current_ratio",
        "Quick Ratio": "quick_ratio",
        "Dividend Yield": "dividend_yield",
        "Beta Yahoo": "beta_yahoo",
        "Target Price": "target_price",
        "Upside": "upside",
        "Recom. Analistas": "analyst_recommendation",
        "Fuente": "source",
        "Price / Book": "price_to_book",
    }
    out = []
    for r in rows:
        item = {new: typed(r.get(old)) for old, new in mapping.items()}
        out.append(item)
    return out


def read_json_optional(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"INVALID_JSON {path}: {exc}") from exc


def extract_positions(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("positions", "portfolio", "holdings"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def recursive_values_for_key(obj: Any, target: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) == target:
                found.append(v)
            found.extend(recursive_values_for_key(v, target))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(recursive_values_for_key(v, target))
    return found


def expected_seal_id() -> str:
    manifest = V13 / "outputs" / "v13_phase4_model_seal_manifest.json"
    obj = json.loads(manifest.read_text(encoding="utf-8-sig"))
    seal = str(obj.get("seal_id") or "").strip()
    if not seal:
        raise RuntimeError("MISSING_LOCAL_V13_SEAL_ID")
    return seal


def load_base_state() -> tuple[dict, str]:
    print("")
    print("[4/8] LOAD STRUCTURAL BASE STATE")

    # Refresh remote tracking ref if possible. Never changes the working tree.
    try:
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=ROOT,
            check=True,
            timeout=45,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("  git origin/main refreshed")
    except Exception:
        print("  git fetch unavailable; using existing local Git refs")

    errors = []
    for ref in ("origin/main", "HEAD"):
        try:
            raw = git_show("public/data/alpha_product_state.json", ref)
            state = json.loads(raw.decode("utf-8"))
            if state.get("schema") != EXPECTED_SCHEMA:
                errors.append(f"{ref}: schema={state.get('schema')}")
                continue
            if (state.get("system") or {}).get("status") != "PASS":
                errors.append(f"{ref}: system.status != PASS")
                continue
            print(f"  PASS base state from {ref}")
            return state, ref
        except Exception as exc:
            errors.append(f"{ref}: {type(exc).__name__}: {exc}")

    raise RuntimeError("NO_VALID_BASE_PRODUCT_STATE | " + " | ".join(errors))


def build_personal(existing: Any) -> dict:
    pfile = PRODUCT / "personal_portfolio.json"
    lfile = PRODUCT / "personal_portfolio_ledger.json"
    payload = read_json_optional(pfile)
    ledger = read_json_optional(lfile)
    positions = extract_positions(payload)

    out = dict(existing) if isinstance(existing, dict) else {}
    out.update({
        "status": "PASS" if positions else "EMPTY_INPUT",
        "source": "PRODUCT/personal_portfolio.json",
        "source_exists": pfile.exists(),
        "position_rows": len(positions),
        "positions": positions,
        "ledger_source": "PRODUCT/personal_portfolio_ledger.json",
        "ledger_source_exists": lfile.exists(),
        "ledger": ledger,
    })
    return out


def build_state() -> dict:
    verify_v13_immutable()
    refresh_market()
    mr, fr, ms, cs = validate_recovery_files()
    state, base_ref = load_base_state()

    print("")
    print("[5/8] MODEL SEAL GATE")
    seal = expected_seal_id()
    base_seals = {str(v) for v in recursive_values_for_key(state, "seal_id") if v is not None}
    if seal not in base_seals:
        raise RuntimeError(
            f"BASE_STATE_SEAL_MISMATCH expected={seal} found={sorted(base_seals)[:8]}"
        )
    print(f"  PASS seal_id={seal}")

    market = normalize_market(mr)
    funds = normalize_fundamentals(fr)

    print("")
    print("[6/8] OVERLAY AUDITED DATA")
    existing_market = state.get("market")
    market_section = dict(existing_market) if isinstance(existing_market, dict) else {}
    market_section.update({
        "status": "PASS",
        "source": "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "contract": "regular_market_price / immediately_preceding_raw_daily_close - 1",
        "forbidden_var_1d_input": "Yahoo meta.chartPreviousClose",
        "regular_session_only": True,
        "prepost": False,
        "rows": len(market),
        "provider_symbols_requested": int(ms["unique_provider_symbols_requested"]),
        "provider_symbols_failed": int(ms["provider_symbols_failed"]),
        "asof": ms.get("asof"),
        "assets": market,
    })
    state["market"] = market_section

    existing_fund = state.get("fundamentals")
    fund_section = dict(existing_fund) if isinstance(existing_fund, dict) else {}
    fund_section.update({
        "status": "PASS",
        "source": "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "rows": len(funds),
        "asof": cs.get("asof"),
        "companies": funds,
        "exceptions": [
            {"ticker": "ECOG", "status": "INCOMPLETE", "policy": "provider_native_gap_no_imputation"},
            {"ticker": "SPCX", "status": "PARTIAL", "policy": "provider_native_gap_no_imputation"},
        ],
    })
    state["fundamentals"] = fund_section

    state["personal"] = build_personal(state.get("personal"))

    system = state.get("system")
    system = dict(system) if isinstance(system, dict) else {}
    system.update({
        "status": "PASS",
        "runtime": "LOCAL_DATA_RECOVERY_V1",
        "data_authority": "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "model_authority": "V13_IDEAL",
        "real_orders_sent": False,
    })
    state["system"] = system

    state["data_recovery"] = {
        "status": "PASS",
        "stage": "DR1_PRODUCT_RUNTIME",
        "generated_at_utc": now_iso(),
        "base_product_state_ref": base_ref,
        "v13_critical_artifacts_immutable": True,
        "v13_seal_id": seal,
        "market": {
            "rows": len(market),
            "provider_coverage": "212/212",
            "source": "Yahoo Finance via Data Recovery V1",
            "regular_session_only": True,
            "var_1d_contract": "price / previous_session_daily_close - 1",
        },
        "fundamentals": {
            "rows": len(funds),
            "source": "Yahoo quoteSummary + SEC fallback via Data Recovery V1",
            "old_v8_v10_scores_imported": False,
        },
        "sheets_required_for_web": False,
        "v13_mutated": False,
    }

    # Hard final gates.
    if state.get("schema") != EXPECTED_SCHEMA:
        raise RuntimeError("FINAL_SCHEMA_CHANGED")
    if state["market"]["rows"] != 200:
        raise RuntimeError("FINAL_MARKET_ROWS_FAILED")
    if state["fundamentals"]["rows"] != 187:
        raise RuntimeError("FINAL_FUND_ROWS_FAILED")
    if state["data_recovery"]["v13_seal_id"] != seal:
        raise RuntimeError("FINAL_SEAL_FAILED")

    print(f"  market assets={len(market)}")
    print(f"  fundamentals companies={len(funds)}")
    print(f"  personal positions={state['personal']['position_rows']}")
    return state


def atomic_publish(state: dict) -> dict:
    print("")
    print("[7/8] ATOMIC LOCAL PRODUCT-STATE PUBLISH")
    PUBLIC.mkdir(parents=True, exist_ok=True)
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = None
    had_previous = STATE.exists()

    if had_previous:
        backup_dir = REC / "outputs" / "data_recovery_v1" / "state_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"alpha_product_state_{timestamp}.json"
        shutil.copy2(STATE, backup)

    temp = STATE.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    # Parse the exact temp file before replacement.
    check = json.loads(temp.read_text(encoding="utf-8"))
    if check.get("schema") != EXPECTED_SCHEMA:
        temp.unlink(missing_ok=True)
        raise RuntimeError("TEMP_STATE_VALIDATION_FAILED")

    os.replace(temp, STATE)

    receipt = {
        "status": "PASS",
        "generated_at_utc": now_iso(),
        "state_path": str(STATE),
        "had_previous_state": had_previous,
        "backup_path": str(backup) if backup else None,
        "schema": state["schema"],
        "market_rows": state["market"]["rows"],
        "fundamental_rows": state["fundamentals"]["rows"],
        "personal_position_rows": state["personal"]["position_rows"],
        "v13_seal_id": state["data_recovery"]["v13_seal_id"],
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"  PASS state={STATE}")
    print(f"  backup={backup if backup else 'none (no prior local state)'}")
    return receipt


def rollback() -> int:
    if not RECEIPT.exists():
        print("ROLLBACK: no receipt; nothing to do.")
        return 0
    r = json.loads(RECEIPT.read_text(encoding="utf-8"))
    backup = r.get("backup_path")
    had_previous = bool(r.get("had_previous_state"))

    if had_previous and backup and Path(backup).exists():
        shutil.copy2(Path(backup), STATE)
        print(f"ROLLBACK PASS: restored {backup}")
    elif not had_previous and STATE.exists():
        STATE.unlink()
        print("ROLLBACK PASS: removed newly-created local state.")
    else:
        print("ROLLBACK: no applicable state mutation found.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    if args.rollback:
        return rollback()

    state = build_state()
    atomic_publish(state)

    print("")
    print("[8/8] BUILD COMPLETE")
    print("  V13: UNCHANGED")
    print("  SHEETS: NOT USED")
    print("  PRODUCT STATE: LOCAL + AUDITED DATA RECOVERY")
    print("  ALPHA LLM: NOT CHANGED BY BUILDER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

'@ | Set-Content -Path $BUILDER -Encoding UTF8

@'
from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION")
REC = ROOT / "ALPHA_ENGINE_DATA_RECOVERY_V1"
STATE = ROOT / "public" / "data" / "alpha_product_state.json"
MARKET = REC / "outputs" / "data_recovery_v1" / "live" / "mercado_riesgo_live_latest.csv"

spec = importlib.util.spec_from_file_location(
    "alpha_web_base",
    ROOT / "web" / "server.py",
)
if spec is None or spec.loader is None:
    raise RuntimeError("CANNOT_LOAD_BASE_WEB_SERVER")

base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

sys.path.insert(0, str(REC / "src"))
from alpha_data_recovery.yahoo_chart import recover_market


def num(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


_market_cache_mtime = None
_market_lookup = {}


def load_market_lookup():
    global _market_cache_mtime, _market_lookup

    mtime = MARKET.stat().st_mtime
    if _market_cache_mtime == mtime and _market_lookup:
        return _market_lookup

    with MARKET.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    lookup = {}
    for row in rows:
        canonical = str(row.get("Ticker") or "").strip().upper()
        symbol = str(row.get("Yahoo Symbol") or "").strip().upper()
        if canonical:
            lookup[canonical] = row
        if symbol:
            lookup[symbol] = row

    _market_cache_mtime = mtime
    _market_lookup = lookup
    return lookup


def row_snapshot(requested: str, row: dict) -> dict:
    price = num(row.get("Precio"))
    var = num(row.get("Var 1D"))
    previous = None
    if price is not None and var is not None and (1.0 + var) != 0:
        previous = price / (1.0 + var)

    change = None
    if price is not None and previous is not None:
        change = price - previous

    return base.sanitize({
        "status": "PASS",
        "ticker": requested,
        "symbol": row.get("Yahoo Symbol") or requested,
        "regular_market_price": price,
        "previous_close": previous,
        "change": change,
        "change_pct": var,
        "regular_market_time": row.get("Actualización"),
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
        "last_volume": None,
        "source": row.get("Fuente") or "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "data_authority": "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "var_1d_contract": "price / previous_session_daily_close - 1",
        "include_prepost": False,
        "sparkline": [],
    })


def recovery_snapshot(requested: str) -> dict:
    snap, history = recover_market(requested, requested)
    f = snap.fields

    price = f["price"].value
    previous = f["previous_close"].value
    var = f["var_1d"].value

    if snap.overall_status in {"INVALID", "MISSING", "QUARANTINE"}:
        return base.sanitize({
            "status": snap.overall_status,
            "ticker": requested,
            "symbol": requested,
            "regular_market_price": price,
            "previous_close": previous,
            "change_pct": var,
            "source": f["price"].source,
            "data_authority": "ALPHA_ENGINE_DATA_RECOVERY_V1",
            "include_prepost": False,
            "error": f["price"].detail,
        })

    return base.sanitize({
        "status": "PASS",
        "ticker": requested,
        "symbol": snap.market_symbol,
        "regular_market_price": price,
        "previous_close": previous,
        "change": (
            price - previous
            if price is not None and previous is not None
            else None
        ),
        "change_pct": var,
        "regular_market_time": f["price"].asof,
        "source": f["price"].source,
        "data_authority": "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "var_1d_contract": "price / previous_session_daily_close - 1",
        "include_prepost": False,
        "sparkline": [
            {
                "time": r.get("timestamp"),
                "close": r.get("close"),
            }
            for r in history[-60:]
            if r.get("close") is not None
        ],
    })


def audited_market_snapshot(ticker, force=False):
    requested = str(ticker or "").strip().upper()
    if not requested:
        raise ValueError("EMPTY_TICKER")

    row = load_market_lookup().get(requested)
    if row is not None:
        return row_snapshot(requested, row)

    # Benchmark-only symbols are fetched through the same audited DR engine,
    # never through server.py's chartPreviousClose path.
    return recovery_snapshot(requested)


def local_only_state(force=False):
    if not STATE.exists():
        raise FileNotFoundError(f"MISSING_PRODUCT_STATE: {STATE}")

    state = json.loads(STATE.read_text(encoding="utf-8"))
    state = base.sanitize(state)

    if state.get("schema") != "ALPHA_ENGINE_PRODUCT_STATE_V1":
        raise RuntimeError("INVALID_PRODUCT_STATE_SCHEMA")

    if (state.get("system") or {}).get("status") != "PASS":
        raise RuntimeError("PRODUCT_STATE_NOT_PASS")

    state["_web"] = {
        "source": "LOCAL_DATA_RECOVERY_V1",
        "version": "ALPHA_WEB_V3_DR1",
        "alpha_configured": False,
        "alpha_model": "DISABLED_PENDING_GROQ_QWEN",
        "market_source": "ALPHA_ENGINE_DATA_RECOVERY_V1",
        "market_prepost": False,
    }
    return state


# Replace only runtime behavior. Original server.py remains untouched.
base.load_state = local_only_state
base.yahoo_market_snapshot = audited_market_snapshot

# The old OpenAI path is intentionally disabled. The requested Groq/Qwen
# Decision Desk is a separate integration gate.
base.OPENAI_API_KEY = ""
base.OPENAI_MODEL = "DISABLED_PENDING_GROQ_QWEN"

if __name__ == "__main__":
    base.main()

'@ | Set-Content -Path $SERVER -Encoding UTF8

Write-Host ""
Write-Host "[A] Python syntax gates"
python -m py_compile $BUILDER
if ($LASTEXITCODE -ne 0) { throw "Builder syntax gate failed." }

python -m py_compile $SERVER
if ($LASTEXITCODE -ne 0) { throw "Server wrapper syntax gate failed." }

Write-Host "  PASS"

Write-Host ""
Write-Host "[B] Build audited local product state"
Set-Location $ROOT
python $BUILDER
if ($LASTEXITCODE -ne 0) {
    throw "Product-state build aborted. Previous local state was not replaced unless [7/8] had already passed."
}

Write-Host ""
Write-Host "[C] Port 8765 gate"

$listener = @(
    Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue
)

$serverProcess = $null
$startedHere = $false

if ($listener.Count -gt 0) {
    $pidExisting = $listener[0].OwningProcess
    $procExisting = Get-CimInstance Win32_Process -Filter "ProcessId = $pidExisting"
    $cmdExisting = [string]$procExisting.CommandLine

    if ($cmdExisting -notlike "*run_data_recovery_server.py*") {
        throw "Puerto 8765 ocupado por otro proceso PID=$pidExisting. No se mató ningún proceso."
    }

    Write-Host "  Existing DR1 server detected PID=$pidExisting"
}
else {
    Write-Host "  Starting local DR1 production server..."
    $serverProcess = Start-Process `
        -FilePath "python" `
        -ArgumentList @($SERVER) `
        -WorkingDirectory $ROOT `
        -PassThru

    $startedHere = $true
    Write-Host "  PID=$($serverProcess.Id)"
}

Write-Host ""
Write-Host "[D] HTTP smoke gates"

$ok = $false
$lastError = $null

for ($attempt = 1; $attempt -le 20; $attempt++) {
    try {
        Start-Sleep -Milliseconds 750

        $health = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8765/api/health" `
            -TimeoutSec 5

        $state = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8765/api/state?refresh=1" `
            -TimeoutSec 8

        $nke = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8765/api/market?ticker=NKE" `
            -TimeoutSec 10

        if ($health.status -ne "PASS") { throw "health != PASS" }
        if ($state.schema -ne "ALPHA_ENGINE_PRODUCT_STATE_V1") { throw "schema inválido" }
        if ($state.system.status -ne "PASS") { throw "system.status != PASS" }
        if ($state._web.source -ne "LOCAL_DATA_RECOVERY_V1") { throw "web no está local-first" }
        if ([int]$state.data_recovery.market.rows -ne 200) { throw "market rows != 200" }
        if ([int]$state.data_recovery.fundamentals.rows -ne 187) { throw "fundamental rows != 187" }
        if ($nke.status -ne "PASS") { throw "NKE market status != PASS" }

        $nkeVar = [double]$nke.change_pct
        if ([math]::Abs($nkeVar) -gt 0.35) { throw "NKE Var1D quarantine" }

        $ok = $true
        break
    }
    catch {
        $lastError = $_.Exception.Message
    }
}

if (-not $ok) {
    Write-Host ""
    Write-Host "SMOKE FAILED: $lastError"

    if ($startedHere -and $null -ne $serverProcess) {
        Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    }

    python $BUILDER --rollback
    throw "Production smoke failed. Local product state rolled back."
}

Write-Host ""
Write-Host "================================================================"
Write-Host "ALPHA ENGINE PRODUCTION RECOVERY: PASS"
Write-Host "================================================================"
Write-Host ("WEB                 : http://127.0.0.1:8765/")
Write-Host ("STATE SOURCE        : {0}" -f $state._web.source)
Write-Host ("V13 SEAL            : {0}" -f $state.data_recovery.v13_seal_id)
Write-Host ("MARKET              : {0}/200 assets" -f $state.data_recovery.market.rows)
Write-Host ("PROVIDER COVERAGE   : {0}" -f $state.data_recovery.market.provider_coverage)
Write-Host ("FUNDAMENTALS        : {0}/187 companies" -f $state.data_recovery.fundamentals.rows)
Write-Host ("PERSONAL POSITIONS  : {0}" -f $state.personal.position_rows)
Write-Host ("NKE PRICE           : {0}" -f $nke.regular_market_price)
Write-Host ("NKE VAR 1D          : {0:P2}" -f ([double]$nke.change_pct))
Write-Host ("MARKET SOURCE       : {0}" -f $nke.data_authority)
Write-Host ("PRE / POST MARKET   : DISABLED")
Write-Host ("SHEETS REQUIRED     : NO")
Write-Host ("OLD OPENAI LLM PATH : DISABLED")
Write-Host ("GROQ/QWEN            : PENDING NEXT GATE")
Write-Host ("V13 MUTATED          : NO")
Write-Host "================================================================"
