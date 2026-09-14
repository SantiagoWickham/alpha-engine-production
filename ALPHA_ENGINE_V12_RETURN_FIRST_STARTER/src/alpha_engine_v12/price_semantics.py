from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import json
import math
import tomllib

import numpy as np
import pandas as pd


DENIED_FRAGMENTS = (
    "/audit_", "/extreme_audit", "/red_team/", "/state/", "/validation/",
    "/v10", "/v11", "/backtest", "/forward_test",
)


@dataclass(frozen=True)
class Phase2BConfig:
    name: str
    objective: str
    panel_path: str
    market_primary: str
    market_secondary: str
    delisted_market_dir: str
    policies: dict[str, object]


def load_phase2b_config(path: Path) -> Phase2BConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))["phase2b"]
    return Phase2BConfig(
        name=raw["name"],
        objective=raw["objective"],
        panel_path=raw["panel_path"],
        market_primary=raw["market_primary"],
        market_secondary=raw["market_secondary"],
        delisted_market_dir=raw["delisted_market_dir"],
        policies=dict(raw["policies"]),
    )


def _norm_ticker(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.upper()


def _as_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.normalize().astype("datetime64[ns]")


def _rel_diff(a: pd.Series, b: pd.Series) -> pd.Series:
    aa = pd.to_numeric(a, errors="coerce").astype(float)
    bb = pd.to_numeric(b, errors="coerce").astype(float)
    denom = np.maximum(np.maximum(np.abs(aa), np.abs(bb)), 1e-12)
    return np.abs(aa - bb) / denom


def _require_columns(df: pd.DataFrame, cols: Iterable[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label}: missing required columns {missing}")


def load_panel(root: Path, cfg: Phase2BConfig) -> pd.DataFrame:
    path = root / cfg.panel_path
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Phase 2 must complete successfully before Phase 2B."
        )
    panel = pd.read_parquet(path)
    _require_columns(
        panel,
        ["date", "ticker", "close", "adj_close", "market_source", "research_eligible"],
        str(path),
    )
    panel = panel.copy()
    panel["date"] = _as_date(panel["date"])
    panel["ticker"] = _norm_ticker(panel["ticker"])
    panel["close"] = pd.to_numeric(panel["close"], errors="coerce")
    panel["adj_close"] = pd.to_numeric(panel["adj_close"], errors="coerce")
    panel["research_eligible"] = panel["research_eligible"].fillna(False).astype(bool)
    return panel.sort_values(["ticker", "date"]).reset_index(drop=True)


def build_price_coverage(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    work = panel.copy()
    work["adj_available"] = np.isfinite(work["adj_close"]) & (work["adj_close"] > 0)
    rows = []
    for scope_name, scope_df in (
        ("ALL", work),
        ("RESEARCH_ELIGIBLE", work[work["research_eligible"]]),
    ):
        for source, g in scope_df.groupby("market_source", dropna=False, observed=True):
            rows.append({
                "scope": scope_name,
                "market_source": str(source),
                "rows": int(len(g)),
                "tickers": int(g["ticker"].nunique()),
                "adj_close_rows": int(g["adj_available"].sum()),
                "adj_close_coverage": float(g["adj_available"].mean()) if len(g) else math.nan,
            })
        rows.append({
            "scope": scope_name,
            "market_source": "TOTAL",
            "rows": int(len(scope_df)),
            "tickers": int(scope_df["ticker"].nunique()),
            "adj_close_rows": int(scope_df["adj_available"].sum()),
            "adj_close_coverage": float(scope_df["adj_available"].mean()) if len(scope_df) else math.nan,
        })
    out = pd.DataFrame(rows)
    eligible = work[work["research_eligible"]]
    meta = {
        "eligible_rows": int(len(eligible)),
        "eligible_tickers": int(eligible["ticker"].nunique()),
        "eligible_adj_close_rows": int(eligible["adj_available"].sum()),
        "eligible_adj_close_coverage": float(eligible["adj_available"].mean()) if len(eligible) else 0.0,
    }
    return out, meta


def _load_source_close(path: Path, source_name: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    _require_columns(df, ["date", "ticker", "close"], str(path))
    out = df[[c for c in ["date", "ticker", "close", "adj_close"] if c in df.columns]].copy()
    out["date"] = _as_date(out["date"])
    out["ticker"] = _norm_ticker(out["ticker"])
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    if "adj_close" in out:
        out["adj_close"] = pd.to_numeric(out["adj_close"], errors="coerce")
    out["source_name"] = source_name
    return out.dropna(subset=["date", "ticker", "close"])


def _load_delisted_adjusted(root: Path, cfg: Phase2BConfig) -> pd.DataFrame:
    ddir = root / cfg.delisted_market_dir
    frames = []
    for p in sorted(ddir.glob("*.parquet")):
        try:
            import pyarrow.parquet as pq
            schema = set(pq.read_schema(p).names)
            if not {"date", "ticker", "close", "adj_close"}.issubset(schema):
                continue
            df = pd.read_parquet(p, columns=["date", "ticker", "close", "adj_close"])
            df["date"] = _as_date(df["date"])
            df["ticker"] = _norm_ticker(df["ticker"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["adj_close"] = pd.to_numeric(df["adj_close"], errors="coerce")
            frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=["date", "ticker", "close", "adj_close"])
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["date", "ticker", "close", "adj_close"])
    out = out[(out["close"] > 0) & (out["adj_close"] > 0)]
    return out.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")


def classify_source_semantics(
    source: pd.DataFrame,
    reference: pd.DataFrame,
    source_name: str,
    tolerance: float = 1e-6,
    minimum_overlap_rows: int = 250,
) -> dict:
    left = source[["date", "ticker", "close"]].rename(columns={"close": "source_close"})
    right = reference[["date", "ticker", "close", "adj_close"]].rename(
        columns={"close": "reference_raw_close", "adj_close": "reference_adj_close"}
    )
    m = left.merge(right, on=["date", "ticker"], how="inner")
    m = m.dropna(subset=["source_close", "reference_raw_close", "reference_adj_close"])
    n = len(m)
    if n == 0:
        return {
            "source": source_name,
            "overlap_rows": 0,
            "overlap_tickers": 0,
            "raw_match_rate": math.nan,
            "adjusted_match_rate": math.nan,
            "median_rel_diff_to_raw": math.nan,
            "median_rel_diff_to_adjusted": math.nan,
            "classification": "NO_OVERLAP",
        }
    raw_diff = _rel_diff(m["source_close"], m["reference_raw_close"])
    adj_diff = _rel_diff(m["source_close"], m["reference_adj_close"])
    raw_rate = float((raw_diff <= tolerance).mean())
    adj_rate = float((adj_diff <= tolerance).mean())
    if n < minimum_overlap_rows:
        cls = "INSUFFICIENT_OVERLAP"
    elif raw_rate >= 0.995 and adj_rate < 0.95:
        cls = "RAW_CLOSE_LIKE"
    elif adj_rate >= 0.995 and raw_rate < 0.95:
        cls = "ADJUSTED_CLOSE_LIKE"
    elif raw_rate >= 0.995 and adj_rate >= 0.995:
        cls = "AMBIGUOUS_IDENTICAL"
    else:
        raw_med = float(raw_diff.median())
        adj_med = float(adj_diff.median())
        if raw_med * 10 < adj_med and raw_rate > adj_rate:
            cls = "RAW_CLOSE_LIKE"
        elif adj_med * 10 < raw_med and adj_rate > raw_rate:
            cls = "ADJUSTED_CLOSE_LIKE"
        else:
            cls = "UNRESOLVED"
    return {
        "source": source_name,
        "overlap_rows": int(n),
        "overlap_tickers": int(m["ticker"].nunique()),
        "raw_match_rate": raw_rate,
        "adjusted_match_rate": adj_rate,
        "median_rel_diff_to_raw": float(raw_diff.median()),
        "median_rel_diff_to_adjusted": float(adj_diff.median()),
        "classification": cls,
    }


def build_source_semantics(root: Path, cfg: Phase2BConfig) -> pd.DataFrame:
    ref = _load_delisted_adjusted(root, cfg)
    rows = []
    for name, rel in (
        ("PRIMARY", cfg.market_primary),
        ("SECONDARY", cfg.market_secondary),
    ):
        src = _load_source_close(root / rel, name)
        rows.append(classify_source_semantics(
            src,
            ref,
            name,
            tolerance=float(cfg.policies["source_match_tolerance"]),
            minimum_overlap_rows=int(cfg.policies["minimum_overlap_rows"]),
        ))
    rows.append({
        "source": "DELISTED_REFERENCE",
        "overlap_rows": int(len(ref)),
        "overlap_tickers": int(ref["ticker"].nunique()) if len(ref) else 0,
        "raw_match_rate": math.nan,
        "adjusted_match_rate": math.nan,
        "median_rel_diff_to_raw": math.nan,
        "median_rel_diff_to_adjusted": math.nan,
        "classification": "HAS_RAW_AND_ADJUSTED" if len(ref) else "MISSING",
    })
    return pd.DataFrame(rows)


def build_corporate_action_diagnostics(panel: pd.DataFrame, cfg: Phase2BConfig) -> tuple[pd.DataFrame, dict]:
    x = panel[["date", "ticker", "close", "adj_close", "market_source", "research_eligible"]].copy()
    x = x.sort_values(["ticker", "date"])
    x["prev_close"] = x.groupby("ticker", observed=True)["close"].shift(1)
    x["prev_adj_close"] = x.groupby("ticker", observed=True)["adj_close"].shift(1)
    x["raw_return_1d"] = x["close"] / x["prev_close"] - 1.0
    x["adj_return_1d"] = x["adj_close"] / x["prev_adj_close"] - 1.0
    x["raw_vs_adj_gap"] = (x["raw_return_1d"] - x["adj_return_1d"]).abs()
    threshold = float(cfg.policies["extreme_raw_return_abs"])
    material_gap = float(cfg.policies["material_raw_vs_adjusted_gap"])
    extreme = x[x["raw_return_1d"].abs() >= threshold].copy()
    extreme["adjusted_pair_available"] = extreme[["adj_close", "prev_adj_close"]].notna().all(axis=1)
    extreme["likely_corporate_action_where_adjusted"] = (
        extreme["adjusted_pair_available"]
        & (extreme["raw_vs_adj_gap"] >= material_gap)
        & (extreme["adj_return_1d"].abs() < extreme["raw_return_1d"].abs())
    )
    keep = [
        "date", "ticker", "market_source", "research_eligible", "prev_close", "close",
        "raw_return_1d", "prev_adj_close", "adj_close", "adj_return_1d", "raw_vs_adj_gap",
        "adjusted_pair_available", "likely_corporate_action_where_adjusted",
    ]
    extreme = extreme[keep].sort_values("raw_return_1d", key=lambda s: s.abs(), ascending=False)
    meta = {
        "extreme_raw_return_rows": int(len(extreme)),
        "extreme_research_eligible_rows": int(extreme["research_eligible"].sum()) if len(extreme) else 0,
        "extreme_rows_with_adjusted_pair": int(extreme["adjusted_pair_available"].sum()) if len(extreme) else 0,
        "likely_corporate_action_rows_where_adjusted": int(extreme["likely_corporate_action_where_adjusted"].sum()) if len(extreme) else 0,
    }
    return extreme.head(500).reset_index(drop=True), meta


def _denied(path: Path, root: Path) -> bool:
    rel = "/" + path.relative_to(root).as_posix().lower()
    return any(fragment in rel for fragment in DENIED_FRAGMENTS)


def discover_adjustment_candidates(root: Path, cfg: Phase2BConfig) -> pd.DataFrame:
    keywords = {"adj_close", "adjusted_close", "adjusted", "dividend", "dividends", "split", "splits", "stock_splits", "split_factor"}
    rows = []
    max_files = int(cfg.policies["candidate_scan_max_files"])
    seen = 0
    for p in root.joinpath("data").rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in {".parquet", ".csv", ".json"}:
            continue
        seen += 1
        if seen > max_files:
            break
        cols: list[str] = []
        try:
            if p.suffix.lower() == ".parquet":
                import pyarrow.parquet as pq
                cols = list(pq.read_schema(p).names)
            elif p.suffix.lower() == ".csv":
                cols = list(pd.read_csv(p, nrows=0).columns)
            else:
                # JSON is not parsed wholesale; filename itself can reveal a corporate-action resource.
                cols = []
        except Exception:
            continue
        lower_cols = {str(c).lower() for c in cols}
        name_tokens = set(p.stem.lower().replace("-", "_").split("_"))
        hit_cols = sorted(lower_cols & keywords)
        name_hit = bool(name_tokens & keywords) or any(k in p.name.lower() for k in ["corporate_action", "dividend", "split"])
        if hit_cols or name_hit:
            rows.append({
                "path": p.relative_to(root).as_posix(),
                "suffix": p.suffix.lower(),
                "blocked_by_contamination_boundary": _denied(p, root),
                "relevant_columns": ",".join(hit_cols),
                "all_columns": ",".join(cols[:80]),
                "size_bytes": int(p.stat().st_size),
            })
    if not rows:
        return pd.DataFrame(columns=[
            "path", "suffix", "blocked_by_contamination_boundary", "relevant_columns", "all_columns", "size_bytes"
        ])
    return pd.DataFrame(rows).sort_values(
        ["blocked_by_contamination_boundary", "path"], ascending=[True, True]
    ).reset_index(drop=True)


def build_adjusted_requirements(panel: pd.DataFrame) -> pd.DataFrame:
    x = panel[panel["research_eligible"]].copy()
    x["adj_available"] = np.isfinite(x["adj_close"]) & (x["adj_close"] > 0)
    out = (
        x.groupby("ticker", observed=True)
        .agg(
            first_date=("date", "min"),
            last_date=("date", "max"),
            rows=("date", "size"),
            adj_close_rows=("adj_available", "sum"),
            dominant_market_source=("market_source", lambda s: s.mode().iat[0] if len(s.mode()) else str(s.iloc[0])),
        )
        .reset_index()
    )
    out["adj_close_coverage"] = out["adj_close_rows"] / out["rows"]
    out["needs_adjusted_history"] = out["adj_close_coverage"] < 0.995
    out["first_date"] = out["first_date"].dt.strftime("%Y-%m-%d")
    out["last_date"] = out["last_date"].dt.strftime("%Y-%m-%d")
    return out.sort_values(["needs_adjusted_history", "adj_close_coverage", "ticker"], ascending=[False, True, True])


def evaluate_gate(
    coverage_meta: dict,
    source_semantics: pd.DataFrame,
    requirements: pd.DataFrame,
    cfg: Phase2BConfig,
) -> tuple[pd.DataFrame, str, str]:
    required = float(cfg.policies["adjusted_coverage_required"])
    eligible_cov = float(coverage_meta["eligible_adj_close_coverage"])
    dominant = source_semantics[source_semantics["source"].isin(["PRIMARY", "SECONDARY"])].copy()
    classifications = set(dominant["classification"].dropna().astype(str))
    all_adjusted_like = bool(len(dominant)) and classifications.issubset({"ADJUSTED_CLOSE_LIKE"})
    unresolved = sorted(classifications - {"ADJUSTED_CLOSE_LIKE"})
    need_tickers = int(requirements["needs_adjusted_history"].sum()) if len(requirements) else 0

    rows = [
        {
            "test": "RESEARCH_ELIGIBLE_ADJUSTED_COVERAGE",
            "status": "PASS" if eligible_cov >= required else "FAIL",
            "value": eligible_cov,
            "rule": f">= {required:.3f}",
        },
        {
            "test": "DOMINANT_SOURCE_CLOSE_SEMANTICS",
            "status": "PASS" if all_adjusted_like else "FAIL",
            "value": ";".join(sorted(classifications)) if classifications else "NONE",
            "rule": "PRIMARY and SECONDARY must be proven ADJUSTED_CLOSE_LIKE if adj_close is not complete",
        },
        {
            "test": "TICKERS_REQUIRING_ADJUSTED_HISTORY",
            "status": "PASS" if need_tickers == 0 else "FAIL",
            "value": need_tickers,
            "rule": "0 tickers below 99.5% adjusted-price coverage before target creation",
        },
    ]
    gate = pd.DataFrame(rows)
    if (gate["status"] == "PASS").all():
        status = "PASS"
        recommendation = "RETURN_TARGETS_MAY_USE_ADJUSTED_PRICE_SEMANTICS"
    else:
        status = "FAIL"
        if eligible_cov >= required:
            recommendation = "USE_ADJ_CLOSE_FOR_RETURN_TARGETS; CLOSE_SEMANTICS_REMAIN_NONAUTHORITATIVE"
        elif all_adjusted_like:
            recommendation = "CLOSE_APPEARS_ADJUSTED; REQUIRE_EXPLICIT_SOURCE_PROOF_BEFORE TARGETS"
        else:
            recommendation = "ENRICH_ADJUSTED_PRICE_HISTORY_BEFORE_RETURN_TARGETS"
    return gate, status, recommendation


def build_phase2b(root: Path) -> dict:
    cfg = load_phase2b_config(root / "config" / "phase2b.toml")
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    panel = load_panel(root, cfg)
    coverage, coverage_meta = build_price_coverage(panel)
    semantics = build_source_semantics(root, cfg)
    diagnostics, diagnostic_meta = build_corporate_action_diagnostics(panel, cfg)
    candidates = discover_adjustment_candidates(root, cfg)
    requirements = build_adjusted_requirements(panel)
    gate, status, recommendation = evaluate_gate(coverage_meta, semantics, requirements, cfg)

    coverage.to_csv(outputs / "phase2b_price_coverage.csv", index=False)
    semantics.to_csv(outputs / "phase2b_source_semantics.csv", index=False)
    diagnostics.to_csv(outputs / "phase2b_corporate_action_diagnostics.csv", index=False)
    candidates.to_csv(outputs / "phase2b_adjusted_price_candidates.csv", index=False)
    requirements.to_csv(outputs / "phase2b_adjusted_price_requirements.csv", index=False)
    gate.to_csv(outputs / "phase2b_gate.csv", index=False)

    summary = {
        "status": status,
        "phase": "2B",
        "name": cfg.name,
        "objective": cfg.objective,
        "panel": {
            "rows": int(len(panel)),
            "tickers": int(panel["ticker"].nunique()),
            **coverage_meta,
        },
        "source_semantics": semantics.to_dict(orient="records"),
        "corporate_action_diagnostics": diagnostic_meta,
        "adjusted_price_candidates": int(len(candidates)),
        "nonblocked_adjusted_price_candidates": int((~candidates["blocked_by_contamination_boundary"]).sum()) if len(candidates) else 0,
        "tickers_requiring_adjusted_history": int(requirements["needs_adjusted_history"].sum()) if len(requirements) else 0,
        "gate": gate.to_dict(orient="records"),
        "recommendation": recommendation,
        "next_gate": (
            "If PASS: build forward-return targets. If FAIL: enrich/repair corporate-action-adjusted price history first; do not train alpha."
        ),
    }
    (outputs / "phase2b_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary
