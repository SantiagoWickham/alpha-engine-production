from __future__ import annotations

import argparse
import csv
import hashlib
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
    print("[1/8] V13 IMMUTABILITY GATE", flush=True)
    failures: list[str] = []

    for rel in CRITICAL_TEXT:
        disk = ROOT / rel
        if not disk.exists():
            failures.append(f"MISSING {rel}")
            continue
        try:
            committed = git_show(rel, "HEAD")
        except subprocess.CalledProcessError as exc:
            failures.append(
                f"HEAD_MISSING {rel}: "
                f"{exc.output.decode(errors='replace')[:200]}"
            )
            continue
        if norm_text_bytes(disk.read_bytes()) != norm_text_bytes(committed):
            failures.append(f"REAL_CONTENT_DIFF {rel}")
        else:
            print(f"  PASS text-normalized: {Path(rel).name}", flush=True)

    for rel in CRITICAL_BINARY:
        disk = ROOT / rel
        if not disk.exists():
            failures.append(f"MISSING {rel}")
            continue
        try:
            committed = git_show(rel, "HEAD")
        except subprocess.CalledProcessError as exc:
            failures.append(
                f"HEAD_MISSING {rel}: "
                f"{exc.output.decode(errors='replace')[:200]}"
            )
            continue

        if committed.startswith(b"version https://git-lfs.github.com/spec/v1"):
            pointer = committed.decode("utf-8", errors="strict")
            expected_hash = None
            expected_size = None
            for line in pointer.splitlines():
                if line.startswith("oid sha256:"):
                    expected_hash = line.split("oid sha256:", 1)[1].strip().lower()
                elif line.startswith("size "):
                    expected_size = int(line.split(" ", 1)[1].strip())

            if not expected_hash or expected_size is None:
                failures.append(f"INVALID_LFS_POINTER {rel}")
                continue

            raw = disk.read_bytes()
            actual_hash = hashlib.sha256(raw).hexdigest().lower()
            actual_size = len(raw)

            if actual_hash != expected_hash or actual_size != expected_size:
                failures.append(
                    f"LFS_OBJECT_DIFF {rel} "
                    f"sha={actual_hash}/{expected_hash} "
                    f"size={actual_size}/{expected_size}"
                )
            else:
                print(
                    f"  PASS git-lfs sha256+size: {Path(rel).name}",
                    flush=True,
                )
        elif disk.read_bytes() != committed:
            failures.append(f"BINARY_DIFF {rel}")
        else:
            print(f"  PASS exact-binary: {Path(rel).name}", flush=True)

    if failures:
        print("", flush=True)
        for item in failures:
            print("  FAIL", item, flush=True)
        raise RuntimeError("V13_IMMUTABILITY_GATE_FAILED")

    print("  PASS V13 critical artifacts immutable", flush=True)


def refresh_market() -> None:
    print("", flush=True)
    print("[2/8] REFRESH DATA RECOVERY MARKET - LOCAL ONLY", flush=True)
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


def validate_recovery_files():
    print("", flush=True)
    print("[3/8] RECOVERY PAYLOAD GATES", flush=True)

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
            raise RuntimeError(
                f"MARKET_QUARANTINE ticker={row.get('Ticker')} var1d={v}"
            )

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

    print("  PASS market: 200x41 / provider coverage 212/212", flush=True)
    print("  PASS fundamentals: 187x29", flush=True)
    print("  PASS old V8/V10 score columns blank", flush=True)
    return mr, fr, ms, cs


def normalize_market(rows):
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
    return [
        {new: typed(r.get(old)) for old, new in mapping.items()}
        for r in rows
    ]


def normalize_fundamentals(rows):
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
    return [
        {new: typed(r.get(old)) for old, new in mapping.items()}
        for r in rows
    ]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


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
    obj = read_json(manifest)
    seal = str(obj.get("seal_id") or "").strip()
    if not seal:
        raise RuntimeError("MISSING_LOCAL_V13_SEAL_ID")
    return seal


def load_base_state():
    print("", flush=True)
    print("[4/8] LOAD STRUCTURAL BASE STATE", flush=True)

    try:
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=ROOT,
            check=True,
            timeout=45,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("  origin/main refreshed", flush=True)
    except Exception:
        print("  WARN git fetch unavailable; using existing refs", flush=True)

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
            print(f"  PASS base state from {ref}", flush=True)
            return state, ref
        except Exception as exc:
            errors.append(f"{ref}: {type(exc).__name__}: {exc}")

    raise RuntimeError("NO_VALID_BASE_PRODUCT_STATE | " + " | ".join(errors))


def build_personal(existing: Any) -> dict:
    pfile = V13 / "outputs" / "sheets_shadow" / "v13_sheets_positions_snapshot.json"
    cfile = V13 / "outputs" / "sheets_shadow" / "v13_sheets_cash_snapshot.json"
    lfile = PRODUCT / "personal_portfolio_ledger.json"

    pobj = read_json(pfile)
    cobj = read_json(cfile)
    ledger = read_json(lfile) if lfile.exists() else None

    if not isinstance(pobj, dict):
        raise RuntimeError("PERSONAL_POSITION_SNAPSHOT_INVALID")
    if not isinstance(cobj, dict):
        raise RuntimeError("PERSONAL_CASH_SNAPSHOT_INVALID")

    ph = pobj.get("headers")
    prows = pobj.get("rows")
    ch = cobj.get("headers")
    crows = cobj.get("rows")

    if not isinstance(ph, list) or not isinstance(prows, list):
        raise RuntimeError("PERSONAL_POSITION_SNAPSHOT_INVALID")
    if not isinstance(ch, list) or not isinstance(crows, list):
        raise RuntimeError("PERSONAL_CASH_SNAPSHOT_INVALID")

    required = [
        "Ticker",
        "Cantidad",
        "Costo Medio USD Eq.",
        "Precio Actual USD Eq.",
        "Valor Mercado USD Eq.",
        "Costo Base USD",
        "P&L No Real.",
        "Peso Actual",
    ]
    missing = [h for h in required if h not in ph]
    if missing:
        raise RuntimeError(f"PERSONAL_POSITION_HEADERS_MISSING {missing}")

    positions = []
    for raw in prows:
        if not isinstance(raw, list) or len(raw) != len(ph):
            raise RuntimeError("PERSONAL_POSITION_ROW_WIDTH_INVALID")
        row = dict(zip(ph, raw))

        ticker = str(row.get("Ticker") or "").strip().upper()
        qty = number(row.get("Cantidad"))
        if not ticker or qty is None or float(qty) <= 0:
            continue

        avg_cost = number(row.get("Costo Medio USD Eq."))
        px = number(row.get("Precio Actual USD Eq."))
        mv = number(row.get("Valor Mercado USD Eq."))
        cost = number(row.get("Costo Base USD"))
        pnl = number(row.get("P&L No Real."))
        weight = number(row.get("Peso Actual"))

        positions.append({
            "ticker": ticker,
            "quantity": qty,
            "avg_cost_usd": avg_cost,
            "price_usd": px,
            "market_value_usd": mv,
            "cost_basis_usd": cost,
            "unrealized_pnl_usd": pnl,
            "current_weight": weight,
            "valuation_mode": "AUDITED_SNAPSHOT_NOT_LIVE",
        })

    expected = {"GOOGL", "AVGO", "NVDA"}
    actual = {p["ticker"] for p in positions}
    if actual != expected:
        raise RuntimeError(f"PERSONAL_POSITION_SET_UNEXPECTED {sorted(actual)}")

    cash = []
    cash_by_currency = {}
    for raw in crows:
        if not isinstance(raw, list) or len(raw) != len(ch):
            raise RuntimeError("PERSONAL_CASH_ROW_WIDTH_INVALID")
        row = dict(zip(ch, raw))
        currency = str(row.get("Moneda") or "").strip().upper()
        if not currency:
            continue
        balance = number(row.get("Saldo"))
        cash.append({
            "currency": currency,
            "balance": balance,
            "updated_at": row.get("Actualizado"),
            "source": row.get("Fuente"),
        })
        cash_by_currency[currency] = balance

    total_mv = sum(float(p["market_value_usd"] or 0) for p in positions)
    total_cost = sum(float(p["cost_basis_usd"] or 0) for p in positions)
    total_pnl = sum(float(p["unrealized_pnl_usd"] or 0) for p in positions)

    out = dict(existing) if isinstance(existing, dict) else {}
    out.update({
        "status": "PASS",
        "source": "V13_SHEETS_SHADOW_POSITION_SNAPSHOT",
        "valuation_mode": "AUDITED_SNAPSHOT_NOT_LIVE",
        "valuation_note": (
            "CEDEAR quantities and USD-equivalent valuations are preserved "
            "from the audited V13 Sheets shadow snapshot. Live BYMA+MEP "
            "revaluation is intentionally deferred to a separate validated gate."
        ),
        "summary": {
            "snapshot_market_value_usd_equiv": total_mv,
            "snapshot_cost_basis_usd": total_cost,
            "snapshot_unrealized_pnl_usd": total_pnl,
            "cash_ars_snapshot": cash_by_currency.get("ARS"),
            "cash_usd_snapshot": cash_by_currency.get("USD"),
            "nav_usd": None,
            "nav_status": "NOT_RECOMPUTED_WITHOUT_CURRENT_BYMA_MEP",
        },
        "positions": positions,
        "position_rows": len(positions),
        "positions_count": len(positions),
        "cash": cash,
        "cash_by_currency": cash_by_currency,
        "cash_rows": len(cash),
        "operations": [],
        "operations_count": 0,
        "legacy_scores_imported": False,
        "legacy_signals_imported": False,
        "legacy_actions_imported": False,
        "snapshot_file_mtime_utc": datetime.fromtimestamp(
            pfile.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat(),
        "placeholder_ledger_observed": isinstance(ledger, dict),
        "placeholder_ledger_positions_count": (
            ledger.get("positions_count") if isinstance(ledger, dict) else None
        ),
    })
    return out


def build_state():
    verify_v13_immutable()
    refresh_market()
    mr, fr, ms, cs = validate_recovery_files()
    state, base_ref = load_base_state()

    print("", flush=True)
    print("[5/8] MODEL SEAL GATE", flush=True)
    seal = expected_seal_id()
    base_seals = {
        str(v)
        for v in recursive_values_for_key(state, "seal_id")
        if v is not None
    }
    if seal not in base_seals:
        raise RuntimeError(
            f"BASE_STATE_SEAL_MISMATCH expected={seal} "
            f"found={sorted(base_seals)[:8]}"
        )
    print(f"  PASS seal_id={seal}", flush=True)

    market = normalize_market(mr)
    funds = normalize_fundamentals(fr)

    print("", flush=True)
    print("[6/8] OVERLAY AUDITED DATA", flush=True)

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
            {
                "ticker": "ECOG",
                "status": "INCOMPLETE",
                "policy": "provider_native_gap_no_imputation",
            },
            {
                "ticker": "SPCX",
                "status": "PARTIAL",
                "policy": "provider_native_gap_no_imputation",
            },
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
        "personal": {
            "position_rows": state["personal"]["position_rows"],
            "valuation_mode": state["personal"]["valuation_mode"],
        },
        "sheets_required_for_web": False,
        "v13_mutated": False,
    }

    if state.get("schema") != EXPECTED_SCHEMA:
        raise RuntimeError("FINAL_SCHEMA_CHANGED")
    if state["market"]["rows"] != 200:
        raise RuntimeError("FINAL_MARKET_ROWS_FAILED")
    if state["fundamentals"]["rows"] != 187:
        raise RuntimeError("FINAL_FUND_ROWS_FAILED")
    if state["personal"]["position_rows"] != 3:
        raise RuntimeError("FINAL_PERSONAL_POSITION_ROWS_FAILED")
    if state["personal"]["valuation_mode"] != "AUDITED_SNAPSHOT_NOT_LIVE":
        raise RuntimeError("FINAL_PERSONAL_VALUATION_MODE_FAILED")
    if state["data_recovery"]["v13_seal_id"] != seal:
        raise RuntimeError("FINAL_SEAL_FAILED")

    print(f"  market assets={len(market)}", flush=True)
    print(f"  fundamentals companies={len(funds)}", flush=True)
    print(
        "  personal positions="
        + ", ".join(f"{p['ticker']}={p['quantity']}" for p in state["personal"]["positions"]),
        flush=True,
    )
    return state


def atomic_publish(state):
    print("", flush=True)
    print("[7/8] ATOMIC LOCAL PRODUCT-STATE PUBLISH", flush=True)

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

    print(f"  PASS state={STATE}", flush=True)
    print(f"  backup={backup if backup else 'none'}", flush=True)


def rollback() -> int:
    if not RECEIPT.exists():
        print("ROLLBACK: no receipt; nothing to do.", flush=True)
        return 0

    r = json.loads(RECEIPT.read_text(encoding="utf-8"))
    backup = r.get("backup_path")
    had_previous = bool(r.get("had_previous_state"))

    if had_previous and backup and Path(backup).exists():
        shutil.copy2(Path(backup), STATE)
        print(f"ROLLBACK PASS: restored {backup}", flush=True)
    elif not had_previous and STATE.exists():
        STATE.unlink()
        print("ROLLBACK PASS: removed newly-created state.", flush=True)
    else:
        print("ROLLBACK: nothing applicable.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    if args.rollback:
        return rollback()

    state = build_state()
    atomic_publish(state)

    print("", flush=True)
    print("[8/8] BUILD COMPLETE", flush=True)
    print("  V13: UNCHANGED", flush=True)
    print("  SHEETS: NOT USED", flush=True)
    print("  PRODUCT STATE: LOCAL + AUDITED DATA RECOVERY", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
