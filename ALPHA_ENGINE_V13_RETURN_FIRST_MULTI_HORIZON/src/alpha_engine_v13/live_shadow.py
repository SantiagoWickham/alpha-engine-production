from __future__ import annotations

import concurrent.futures
import decimal
import re
import gzip
import hashlib
import json
import os
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd

from alpha_engine_v13 import adaptive_alpha_rebuild as p2r
from alpha_engine_v13 import alpha_factory as p1
from alpha_engine_v13 import economic_portfolio_closure as p3v
from alpha_engine_v13 import event_sector_incremental_alpha as p2u
from alpha_engine_v13 import final_holdout as p4
from alpha_engine_v13 import roundtrip_resize_hysteresis as p3z
from alpha_engine_v13 import shadow_contract as p5a

BUILD = "V13_P5B_FIX4_SEC_FACT_SCHEMA_ALIGNMENT_2026-09-13"
HORIZONS = (5, 10, 20, 60, 120, 252)
NY = ZoneInfo("America/New_York")
UTC = timezone.utc

@dataclass(frozen=True)
class Cfg:
    p: dict


def load_cfg(root: Path) -> Cfg:
    with (root / "config" / "v13_phase5b.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase5b"])


def _date(s):
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")


def _ticker(s):
    return s.astype(str).str.upper().str.replace(".", "-", regex=False).str.strip()


def _ticker_value(x: str) -> str:
    return str(x).upper().replace(".", "-").strip()


def _sha_payload(x) -> str:
    raw = json.dumps(x, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _decode_http_bytes(raw: bytes, content_encoding: str | None) -> bytes:
    enc = str(content_encoding or "").lower().strip()
    if enc == "gzip" or raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    if enc == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def _http_json(url: str, headers: dict[str, str], timeout: int, tries: int = 3) -> dict:
    last = None
    for i in range(max(1, int(tries))):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = _decode_http_bytes(r.read(), r.headers.get("Content-Encoding"))
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = _decode_http_bytes(exc.read(), exc.headers.get("Content-Encoding")).decode("utf-8", errors="replace")[:300]
            except Exception:
                body = ""
            last = RuntimeError(f"HTTP {exc.code} {exc.reason}; body={body!r}")
            if exc.code not in (403, 429, 500, 502, 503, 504):
                break
        except Exception as exc:
            last = exc
        if i + 1 < tries:
            time.sleep(0.8 * (i + 1))
    raise RuntimeError(f"HTTP_FAILED {url}: {last}")


def latest_completed_cutoff(now_utc: datetime | None, grace_minutes: int) -> pd.Timestamp:
    now = (now_utc or datetime.now(UTC)).astimezone(NY)
    close_plus_grace = datetime.combine(now.date(), dtime(16, 0), tzinfo=NY) + timedelta(minutes=int(grace_minutes))
    d = pd.Timestamp(now.date())
    if now < close_plus_grace:
        d -= pd.Timedelta(days=1)
    return d.normalize()


def _parse_yahoo(payload: dict, ticker: str, provider_symbol: str) -> pd.DataFrame:
    result = ((payload.get("chart") or {}).get("result") or [])
    if not result:
        err = ((payload.get("chart") or {}).get("error"))
        raise RuntimeError(f"YAHOO_NO_RESULT {provider_symbol} {err}")
    r = result[0]
    ts = r.get("timestamp") or []
    quote = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((r.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    close = quote.get("close") or []
    vol = quote.get("volume") or []
    n = len(ts)
    if not n:
        return pd.DataFrame(columns=["date", "ticker", "provider_symbol", "close", "volume", "adj_close"])
    if len(close) < n: close = list(close) + [None] * (n-len(close))
    if len(vol) < n: vol = list(vol) + [None] * (n-len(vol))
    if len(adj) < n: adj = list(adj) + [None] * (n-len(adj))
    dates = pd.to_datetime(pd.Series(ts), unit="s", utc=True).dt.tz_convert(NY).dt.tz_localize(None).dt.normalize()
    out = pd.DataFrame({
        "date": dates,
        "ticker": _ticker_value(ticker),
        "provider_symbol": provider_symbol,
        "close": pd.to_numeric(pd.Series(close), errors="coerce"),
        "volume": pd.to_numeric(pd.Series(vol), errors="coerce"),
        "adj_close": pd.to_numeric(pd.Series(adj), errors="coerce"),
    })
    out["adj_close"] = out["adj_close"].where(out["adj_close"] > 0, out["close"])
    return out[out["close"].gt(0)].drop_duplicates(["date","ticker"], keep="last").sort_values("date").reset_index(drop=True)


def fetch_yahoo_history(ticker: str, provider_symbol: str, start: pd.Timestamp, end_exclusive: pd.Timestamp, timeout: int) -> pd.DataFrame:
    p1s = int(pd.Timestamp(start, tz="UTC").timestamp())
    p2s = int(pd.Timestamp(end_exclusive, tz="UTC").timestamp())
    sym = urllib.parse.quote(str(provider_symbol), safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1s}&period2={p2s}&interval=1d&events=div%2Csplits&includeAdjustedClose=true"
    payload = _http_json(url, {"User-Agent":"Mozilla/5.0 AlphaEngineV13-Shadow/1.0"}, timeout)
    return _parse_yahoo(payload, ticker, provider_symbol)


def _schema(path: Path) -> list[str]:
    import pyarrow.parquet as pq
    return pq.ParquetFile(path).schema.names


def _source_root(root: Path) -> Path:
    return p4.source_root_from_phase0(root)


def _last_observed(root: Path, cfg: Cfg) -> pd.Timestamp:
    s = json.loads((root / cfg.p["phase5a_summary"]).read_text(encoding="utf-8"))
    if s.get("status") != "PASS" or not s.get("shadow_only") or s.get("tuning_performed") is not False:
        raise RuntimeError("PHASE5A_PARITY_NOT_PASS")
    if str(s.get("seal_id")) != str(cfg.p["expected_seal_id"]):
        raise RuntimeError("PHASE5A_SEAL_MISMATCH")
    return pd.Timestamp(s["asof"]).normalize()


def _latest_universe(source: Path, root: Path, last_observed: pd.Timestamp, cfg: Cfg) -> tuple[pd.DataFrame, dict]:
    p1cfg = p1.load_cfg(root)
    panel = source / p1cfg.p["source_canonical_pit_panel"]
    cols = _schema(panel)
    use = [c for c in ["date","ticker","research_eligible","provider_symbol"] if c in cols]
    x = pd.read_parquet(panel, columns=use)
    x["date"] = _date(x.date); x["ticker"] = _ticker(x.ticker)
    if "provider_symbol" not in x: x["provider_symbol"] = x["ticker"]
    x = x[(x.date <= last_observed) & x.research_eligible.fillna(False).astype(bool)].copy()
    if x.empty: raise RuntimeError("NO_ELIGIBLE_UNIVERSE")
    snap = pd.Timestamp(x.date.max()).normalize()
    age = int((last_observed - snap).days)
    if age > int(cfg.p["universe_snapshot_max_age_days"]):
        raise RuntimeError(f"UNIVERSE_SNAPSHOT_STALE days={age}")
    u = x[x.date.eq(snap)][["ticker","provider_symbol"]].drop_duplicates("ticker").copy()
    u["provider_symbol"] = u.provider_symbol.fillna(u.ticker).astype(str)
    return u.sort_values("ticker").reset_index(drop=True), {"snapshot_date":str(snap.date()),"snapshot_age_days":age,"tickers":int(len(u))}


def fetch_market_universe(universe: pd.DataFrame, start: pd.Timestamp, end_exclusive: pd.Timestamp, cfg: Cfg) -> tuple[pd.DataFrame,pd.DataFrame]:
    rows=[]; audit=[]
    def one(r):
        try:
            x=fetch_yahoo_history(str(r.ticker),str(r.provider_symbol),start,end_exclusive,int(cfg.p["yahoo_timeout_seconds"]))
            return x,{"ticker":str(r.ticker),"provider_symbol":str(r.provider_symbol),"status":"OK","rows":int(len(x)),"last_date":str(x.date.max().date()) if len(x) else ""}
        except Exception as exc:
            return pd.DataFrame(),{"ticker":str(r.ticker),"provider_symbol":str(r.provider_symbol),"status":"FAIL","rows":0,"error":str(exc)[:500]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,int(cfg.p["market_workers"]))) as ex:
        futs=[ex.submit(one,r) for r in universe.itertuples(index=False)]
        for fut in concurrent.futures.as_completed(futs):
            x,a=fut.result(); audit.append(a)
            if len(x): rows.append(x)
    market=pd.concat(rows,ignore_index=True) if rows else pd.DataFrame(columns=["date","ticker","provider_symbol","close","volume","adj_close"])
    aud=pd.DataFrame(audit).sort_values("ticker").reset_index(drop=True) if audit else pd.DataFrame()
    return market.sort_values(["date","ticker"]).reset_index(drop=True),aud


def _anchor_scale(live: pd.DataFrame, hist: pd.DataFrame, last_observed: pd.Timestamp, cfg: Cfg) -> tuple[pd.DataFrame,pd.DataFrame]:
    h = hist[hist.date.le(last_observed)][["date","ticker","feature_price"]].dropna().copy()
    l = live[live.date.le(last_observed)][["date","ticker","adj_close"]].dropna().copy()
    z = h.merge(l,on=["date","ticker"],how="inner")
    z = z[z.feature_price.gt(0)&z.adj_close.gt(0)].sort_values(["ticker","date"]).groupby("ticker",as_index=False).tail(1)
    z["scale"] = z.feature_price/z.adj_close
    z["scale_deviation"] = (z.scale-1).abs()
    universe = set(live.ticker.unique())
    coverage = len(set(z.ticker)) / max(len(universe),1)
    if coverage < float(cfg.p["minimum_anchor_coverage"]):
        raise RuntimeError(f"ANCHOR_COVERAGE_LOW {coverage:.4f}")
    extreme = z.scale_deviation > float(cfg.p["maximum_anchor_scale_deviation"])
    # Large scale itself is not a failure (splits/dividends can legitimately rebase adjusted history),
    # but it is explicitly audited. The anchor makes the live total-return surface continuous.
    smap = z.set_index("ticker")["scale"]
    q = live.copy(); q["feature_price"] = q.adj_close * q.ticker.map(smap)
    return q, z[["ticker","date","feature_price","adj_close","scale","scale_deviation"]].sort_values("ticker")


def _extend_market(root: Path, source: Path, universe: pd.DataFrame, live: pd.DataFrame, last_observed: pd.Timestamp, latest: pd.Timestamp, cfg: Cfg):
    cfg1 = p1.load_cfg(root); fullcfg = p1.Cfg({**cfg1.p,"holdout_start":"2100-01-01"})
    hist, meta = p4._load_full_market(source, fullcfg)
    hist = hist[hist.date.le(last_observed)].copy()
    live_scaled, anchors = _anchor_scale(live, hist, last_observed, cfg)
    new = live_scaled[(live_scaled.date>last_observed)&(live_scaled.date<=latest)].copy()
    new["research_eligible"] = True
    need=["date","ticker","close","adj_close","volume","research_eligible","feature_price"]
    for c in need:
        if c not in hist: hist[c]=np.nan
        if c not in new: new[c]=np.nan
    ext=pd.concat([hist[need],new[need]],ignore_index=True).drop_duplicates(["date","ticker"],keep="last").sort_values(["ticker","date"]).reset_index(drop=True)
    return ext, anchors, meta


def _extend_bench(root: Path, source: Path, market_ext: pd.DataFrame, last_observed: pd.Timestamp, latest: pd.Timestamp, cfg: Cfg) -> pd.DataFrame:
    cfg1=p1.load_cfg(root); fullcfg=p1.Cfg({**cfg1.p,"holdout_start":"2100-01-01"})
    hist=p4._load_full_bench(source,fullcfg,market_ext[market_ext.date.le(last_observed)])
    out=hist[hist.date.le(last_observed)].copy()
    for sym in ["SPY","QQQ"]:
        y=fetch_yahoo_history(sym,sym,last_observed-pd.Timedelta(days=20),latest+pd.Timedelta(days=2),int(cfg.p["yahoo_timeout_seconds"]))
        anchor=out[out.date.le(last_observed)][["date",sym]].dropna().merge(y[["date","adj_close"]],on="date",how="inner").sort_values("date").tail(1)
        if anchor.empty: raise RuntimeError(f"BENCH_ANCHOR_MISSING {sym}")
        scale=float(anchor[sym].iloc[0]/anchor.adj_close.iloc[0])
        n=y[(y.date>last_observed)&(y.date<=latest)][["date","adj_close"]].rename(columns={"adj_close":sym}); n[sym]*=scale
        out=out.merge(n,on="date",how="outer",suffixes=("",f"_{sym}_new"))
        nc=f"{sym}_{sym}_new"
        if nc in out: out[sym]=out[sym].fillna(out[nc]);out=out.drop(columns=[nc])
        # merge can produce plain <sym>_new depending pandas suffix behavior
        if f"{sym}_new" in out: out[sym]=out[sym].fillna(out[f"{sym}_new"]);out=out.drop(columns=[f"{sym}_new"])
    return out.sort_values("date").drop_duplicates("date",keep="last")


def _mapping_columns(df: pd.DataFrame) -> tuple[str,str] | None:
    low={str(c).lower():str(c) for c in df.columns}
    t=next((low[k] for k in ["ticker","symbol"] if k in low),None)
    c=next((low[k] for k in ["cik","cik_str","cik_number","sec_cik"] if k in low),None)
    return (t,c) if t and c else None


def _normalize_cik_value(value) -> str:
    """Return the SEC canonical 10-digit CIK without the CIK prefix.

    Mapping CSVs are frequently inferred by pandas as float, so a valid CIK such as
    789019 may arrive as 789019.0. Stripping non-digits from that representation
    would incorrectly produce 7890190. Normalize numerically first, then zero-pad.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    s=str(value).strip()
    if not s or s.lower() in {"nan","none","null"}:
        return ""
    if s.upper().startswith("CIK"):
        s=s[3:].strip()
    # Exact decimal parsing handles integer strings, 789019.0 and scientific notation.
    try:
        d=decimal.Decimal(s)
        if not d.is_finite() or d != d.to_integral_value():
            return ""
        digits=str(int(d))
    except decimal.InvalidOperation:
        # Accept formatting noise only when what remains is an integer digit string.
        m=re.fullmatch(r"[+]?([0-9]+)(?:\.0+)?", s)
        if not m:
            return ""
        digits=m.group(1).lstrip("0") or "0"
    if not digits.isdigit() or len(digits)>10:
        return ""
    return digits.zfill(10)


def _canonicalize_sec_mapping(x: pd.DataFrame, t: str, c: str, universe: set[str]) -> pd.DataFrame:
    out=x[[t,c]].rename(columns={t:"ticker",c:"cik"}).copy()
    out["ticker"]=_ticker(out.ticker)
    out["cik"]=out.cik.map(_normalize_cik_value)
    out=out[out.ticker.isin(universe)&out.cik.str.fullmatch(r"[0-9]{10}",na=False)].copy()
    return out.drop_duplicates("ticker")


def _sec_mapping(source: Path, hist: pd.DataFrame, universe: set[str], cfg: Cfg) -> pd.DataFrame:
    for rel in cfg.p["sec_mapping_candidates"]:
        p=source/rel
        if p.exists():
            # Preserve leading zeros and avoid pandas converting CIK integers to floats.
            x=pd.read_csv(p,dtype=str); mc=_mapping_columns(x)
            if mc:
                t,c=mc; return _canonicalize_sec_mapping(x,t,c,universe)
    mc=_mapping_columns(hist)
    if mc:
        t,c=mc; return _canonicalize_sec_mapping(hist,t,c,universe)
    return pd.DataFrame(columns=["ticker","cik"])


def _concept_map(hist: pd.DataFrame) -> dict[tuple[str,str,str],str]:
    req={"canonical_metric","taxonomy","concept"}
    if not req.issubset(hist.columns): raise RuntimeError(f"SEC_HISTORY_CONCEPT_METADATA_MISSING {sorted(req-set(hist.columns))}")
    x=hist[list(req | ({"unit"} if "unit" in hist.columns else set()))].copy();x["unit"]=x.unit.astype(str) if "unit" in x else "*"
    x["taxonomy"]=x.taxonomy.astype(str);x["concept"]=x.concept.astype(str);x["canonical_metric"]=x.canonical_metric.astype(str)
    cnt=x.groupby(["taxonomy","concept","unit","canonical_metric"],dropna=False).size().reset_index(name="n").sort_values(["taxonomy","concept","unit","n","canonical_metric"],ascending=[True,True,True,False,True])
    b=cnt.drop_duplicates(["taxonomy","concept","unit"],keep="first")
    return {(str(r.taxonomy),str(r.concept),str(r.unit)):str(r.canonical_metric) for r in b.itertuples(index=False)}


def _parse_companyfacts(payload: dict, ticker: str, cmap: dict[tuple[str,str,str],str]) -> pd.DataFrame:
    rows=[]
    for taxonomy, concepts in (payload.get("facts") or {}).items():
        for concept, meta in (concepts or {}).items():
            for unit, obs in ((meta or {}).get("units") or {}).items():
                metric=cmap.get((str(taxonomy),str(concept),str(unit))) or cmap.get((str(taxonomy),str(concept),"*"))
                if metric is None: continue
                for r in obs or []:
                    if r.get("val") is None or not r.get("filed") or not r.get("end"): continue
                    rows.append({"ticker":_ticker_value(ticker),"canonical_metric":metric,"value":r.get("val"),"end":r.get("end"),"filed":r.get("filed"),"form":r.get("form"),"fy":r.get("fy"),"fp":r.get("fp"),"frame":r.get("frame"),"accn":r.get("accn"),"unit":unit,"taxonomy":taxonomy,"concept":concept})
    return pd.DataFrame(rows)


def _read_dotenv_value(path: Path, key: str) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() != key:
                continue
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("\"", "'"):
                v = v[1:-1]
            return v.strip()
    except OSError:
        return None
    return None


def _dotenv_candidates(root: Path) -> list[Path]:
    candidates = [
        root / ".env",
        root / "secrets" / ".env",
        root.parent / ".env",
        root.parent / "secrets" / ".env",
        root.parent / "ALPHA_ENGINE_V12_RETURN_FIRST_STARTER" / ".env",
        root.parent / "ALPHA_ENGINE_V12_RETURN_FIRST_STARTER" / "secrets" / ".env",
        Path.cwd() / ".env",
        Path.cwd() / "secrets" / ".env",
    ]
    out=[]; seen=set()
    for x in candidates:
        y=x.resolve() if x.exists() else x.absolute()
        key=str(y).lower()
        if key not in seen:
            seen.add(key); out.append(x)
    return out


def _sec_user_agent(root: Path) -> tuple[str, str]:
    # Prefer an already-exported environment variable, then the user's existing .env.
    # Support both the current MMM name and the generic Alpha Engine alias. Secrets are
    # never printed or copied into outputs/Git; only the source path/name is reported.
    for key in ("MMM_SEC_USER_AGENT", "ALPHA_ENGINE_SEC_USER_AGENT"):
        value = os.getenv(key, "").strip()
        if value:
            if "@" not in value:
                raise RuntimeError(f"SEC_USER_AGENT_INVALID_ENV key={key}: expected an email-bearing identity")
            return value, f"ENV:{key}"
    checked=[]
    for path in _dotenv_candidates(root):
        checked.append(str(path))
        for key in ("MMM_SEC_USER_AGENT", "ALPHA_ENGINE_SEC_USER_AGENT"):
            value = (_read_dotenv_value(path, key) or "").strip()
            if value:
                if "@" not in value:
                    raise RuntimeError(f"SEC_USER_AGENT_INVALID_DOTENV path={path} key={key}: expected an email-bearing identity")
                return value, f"DOTENV:{path}:{key}"
    raise RuntimeError("SEC_USER_AGENT_MISSING: define MMM_SEC_USER_AGENT in the existing .env or environment. checked=" + " | ".join(checked))


def _sec_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }


def _sec_identity_preflight(mapping: pd.DataFrame, cfg: Cfg, user_agent: str, identity_source: str) -> None:
    if mapping.empty:
        return
    r = mapping.iloc[0]
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{r.cik}.json"
    try:
        _http_json(url, _sec_headers(user_agent), int(cfg.p["sec_timeout_seconds"]), tries=1)
    except Exception as exc:
        msg = str(exc)[:800]
        raise RuntimeError(f"SEC_IDENTITY_PREFLIGHT_FAILED source={identity_source}; {msg}") from exc


def _fetch_sec(root: Path, mapping: pd.DataFrame, cmap: dict, cfg: Cfg, cache: Path) -> tuple[pd.DataFrame,pd.DataFrame,str]:
    audit_cache = cache.with_name(cache.stem + "_audit.csv")
    # FIX1: never trust a legacy cache merely because a parquet exists. The previous
    # build could write an empty parquet after 100% request failure and then call it
    # CACHE=OK on the next run. A cache is valid only when both facts + audit exist and
    # the recorded fetch success rate still satisfies the configured gate.
    if cache.exists() and audit_cache.exists():
        try:
            facts = pd.read_parquet(cache)
            aud = pd.read_csv(audit_cache)
            success = float(aud.status.isin(["OK", "CACHE", "VALID_CACHE"]).mean()) if len(aud) else 0.0
            if len(facts) and success >= float(cfg.p["minimum_sec_success_rate"]):
                aud = aud.copy(); aud["status"] = aud["status"].replace({"OK":"VALID_CACHE", "CACHE":"VALID_CACHE"})
                return facts, aud, "VALID_CACHE"
        except Exception:
            pass
    frames=[];aud=[];ua,identity_source=_sec_user_agent(root)
    headers=_sec_headers(ua)
    _sec_identity_preflight(mapping,cfg,ua,identity_source)
    for r in mapping.itertuples(index=False):
        try:
            url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{r.cik}.json"
            payload=_http_json(url,headers,int(cfg.p["sec_timeout_seconds"]))
            x=_parse_companyfacts(payload,str(r.ticker),cmap);frames.append(x);aud.append({"ticker":r.ticker,"cik":r.cik,"status":"OK","rows":int(len(x)),"error":"","identity_source":identity_source})
        except Exception as exc: aud.append({"ticker":r.ticker,"cik":r.cik,"status":"FAIL","rows":0,"error":str(exc)[:500],"identity_source":identity_source})
        time.sleep(max(0.0,float(cfg.p["sec_request_spacing_seconds"])))
    facts=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame();audf=pd.DataFrame(aud)
    cache.parent.mkdir(parents=True,exist_ok=True)
    # Always persist audit diagnostics, but only bless the fact parquet as reusable cache
    # when the SEC success-rate gate passed and facts are non-empty.
    audf.to_csv(audit_cache,index=False)
    success=float(audf.status.eq("OK").mean()) if len(audf) else 0.0
    if len(facts) and success >= float(cfg.p["minimum_sec_success_rate"]):
        facts.to_parquet(cache,index=False)
    elif cache.exists():
        try: cache.unlink()
        except OSError: pass
    return facts,audf,"SEC_LIVE"


def _sec_date_iso_series(s: pd.Series) -> pd.Series:
    """Canonicalize SEC date-like values to nullable ISO YYYY-MM-DD strings.

    Historical files may surface SEC dates as strings, datetime/date objects, or
    numeric YYYYMMDD values depending on the parquet writer/version.  The live SEC
    API emits strings.  Normalizing both sides before concat prevents mixed-object
    Arrow inference while preserving the date semantics used downstream.
    """
    def one(v):
        if v is None or v is pd.NA:
            return pd.NA
        try:
            if pd.isna(v):
                return pd.NA
        except Exception:
            pass
        # Handle numeric YYYYMMDD (including floats such as 20241231.0) explicitly.
        if isinstance(v, (int, np.integer, float, np.floating)) and not isinstance(v, (bool, np.bool_)):
            try:
                fv=float(v)
                if np.isfinite(fv) and abs(fv-round(fv)) < 1e-9:
                    txt=str(int(round(fv)))
                    if len(txt)==8 and txt[:4].isdigit():
                        dt=pd.to_datetime(txt, format="%Y%m%d", errors="coerce")
                        return dt.strftime("%Y-%m-%d") if not pd.isna(dt) else pd.NA
            except Exception:
                pass
        txt=str(v).strip()
        if not txt or txt.lower() in {"nan","nat","none","null","<na>"}:
            return pd.NA
        if re.fullmatch(r"\d{8}(?:\.0+)?", txt):
            dt=pd.to_datetime(txt.split(".")[0], format="%Y%m%d", errors="coerce")
        else:
            dt=pd.to_datetime(txt, errors="coerce")
        return dt.strftime("%Y-%m-%d") if not pd.isna(dt) else pd.NA
    return pd.Series((one(v) for v in s.tolist()), index=s.index, dtype="string")


def _align_sec_fact_schema(hist: pd.DataFrame, live: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    """Align historical and live SEC facts to one deterministic parquet-safe schema.

    This is a transport/schema operation only.  It does not alter which facts are
    selected or their PIT availability; downstream Phase1/Phase2U still parse the
    same `filed`, `end`, and `value` semantics.
    """
    h=hist.copy(); l=live.copy()
    cols=sorted(set(h.columns)|set(l.columns))
    for c in cols:
        if c not in h: h[c]=pd.NA
        if c not in l: l[c]=pd.NA

    date_cols={"start","end","filed"}
    float_cols={"value"}
    int_cols={"fy"}
    string_cols={"ticker","canonical_metric","form","fp","frame","accn","unit","taxonomy","concept"}

    for c in cols:
        if c in date_cols:
            h[c]=_sec_date_iso_series(h[c]); l[c]=_sec_date_iso_series(l[c]); continue
        if c in float_cols:
            h[c]=pd.to_numeric(h[c],errors="coerce").astype("float64")
            l[c]=pd.to_numeric(l[c],errors="coerce").astype("float64"); continue
        if c in int_cols:
            hn=pd.to_numeric(h[c],errors="coerce"); ln=pd.to_numeric(l[c],errors="coerce")
            h[c]=hn.where(hn.isna()|np.isclose(hn, np.round(hn), equal_nan=True)).round().astype("Int64")
            l[c]=ln.where(ln.isna()|np.isclose(ln, np.round(ln), equal_nan=True)).round().astype("Int64"); continue
        if c in string_cols:
            h[c]=h[c].astype("string"); l[c]=l[c].astype("string"); continue

        # Any additional historical columns inherit an unambiguous common dtype.
        hd=h[c].dtype; ld=l[c].dtype
        if pd.api.types.is_datetime64_any_dtype(hd) or pd.api.types.is_datetime64_any_dtype(ld):
            h[c]=pd.to_datetime(h[c],errors="coerce"); l[c]=pd.to_datetime(l[c],errors="coerce")
        elif pd.api.types.is_numeric_dtype(hd) or pd.api.types.is_numeric_dtype(ld):
            h[c]=pd.to_numeric(h[c],errors="coerce").astype("float64")
            l[c]=pd.to_numeric(l[c],errors="coerce").astype("float64")
        elif pd.api.types.is_bool_dtype(hd) or pd.api.types.is_bool_dtype(ld):
            h[c]=h[c].astype("boolean"); l[c]=l[c].astype("boolean")
        else:
            # Object columns are unsafe for Arrow when values mix str/int/date.
            # Treat unknown SEC metadata as nullable strings; model inputs do not
            # consume these columns numerically.
            h[c]=h[c].astype("string"); l[c]=l[c].astype("string")
    return h[cols],l[cols]


def _combined_sec_source(root: Path, source: Path, universe: set[str], latest: pd.Timestamp, cfg: Cfg) -> tuple[Path,dict,pd.DataFrame]:
    cfg1=p1.load_cfg(root); hist=pd.read_parquet(source/cfg1.p["source_sec_facts"]); hist["ticker"]=_ticker(hist.ticker);hist=hist[hist.ticker.isin(universe)].copy()
    mapping=_sec_mapping(source,hist,universe,cfg);map_cov=len(set(mapping.ticker))/max(len(universe),1)
    if map_cov < float(cfg.p["minimum_sec_mapping_coverage"]): raise RuntimeError(f"SEC_MAPPING_COVERAGE_LOW {map_cov:.4f}")
    cmap=_concept_map(hist);cache=root/cfg.p["shadow_dir"]/"cache"/f"sec_companyfacts_{latest.date()}.parquet";live,aud,src=_fetch_sec(root,mapping,cmap,cfg,cache)
    diag=root/cfg.p["shadow_dir"]/"v13_live_sec_audit.csv";diag.parent.mkdir(parents=True,exist_ok=True);aud.to_csv(diag,index=False)
    if len(mapping):
        success=float(aud.status.isin(["OK","CACHE","VALID_CACHE"]).mean())
        if success < float(cfg.p["minimum_sec_success_rate"]):
            sample=" | ".join(aud.loc[aud.status.eq("FAIL"),"error"].dropna().astype(str).head(3).tolist())
            raise RuntimeError(f"SEC_SUCCESS_RATE_LOW {success:.4f}; diagnostics={diag}; sample_errors={sample}")
    else: success=0.0
    hist,live=_align_sec_fact_schema(hist,live)
    cols=list(hist.columns)
    comb=pd.concat([hist,live],ignore_index=True)
    ded=[c for c in ["ticker","canonical_metric","end","filed","form","accn","taxonomy","concept","unit"] if c in comb]
    if ded: comb=comb.drop_duplicates(ded,keep="last")
    temp=root/cfg.p["shadow_dir"]/"runtime_source";p=temp/cfg1.p["source_sec_facts"];p.parent.mkdir(parents=True,exist_ok=True);comb.to_parquet(p,index=False)
    identity_source = str(aud.identity_source.dropna().iloc[0]) if len(aud) and "identity_source" in aud.columns and aud.identity_source.notna().any() else "CACHE_OR_UNKNOWN"
    meta={"mapping_coverage":map_cov,"mapped_tickers":int(len(mapping)),"universe_tickers":int(len(universe)),"success_rate":success,"source":src,"identity_source":identity_source,"live_fact_rows":int(len(live))}
    return temp,meta,aud


def _post2025_keys(source: Path, live_market: pd.DataFrame, last_observed: pd.Timestamp, latest: pd.Timestamp) -> pd.DataFrame:
    hold=pd.Timestamp("2025-01-01")
    hist=p4._holdout_target_keys(source,hold,last_observed)
    live=live_market[(live_market.date>last_observed)&(live_market.date<=latest)][["date","ticker"]].rename(columns={"date":"signal_date"}).drop_duplicates()
    return pd.concat([hist,live],ignore_index=True).drop_duplicates(["signal_date","ticker"]).sort_values(["signal_date","ticker"])


def _score_live(root: Path, temp_source: Path, source: Path, market_ext: pd.DataFrame, bench: pd.DataFrame, keys: pd.DataFrame, last_observed: pd.Timestamp, latest: pd.Timestamp, bundle: dict):
    cfg1=p1.load_cfg(root); cfg1full=p1.Cfg({**cfg1.p,"holdout_start":"2100-01-01"})
    price_meta={"rows":int(len(market_ext)),"coverage":float(market_ext.feature_price.notna().mean()),"tickers":int(market_ext.ticker.nunique())}
    postfeat,_=p1.build_feature_library(temp_source,keys,cfg1full,market=market_ext,bench=bench,price_meta=price_meta)
    research=pd.read_parquet(root/"outputs"/"v13_phase1_feature_library.parquet");research["signal_date"]=_date(research.signal_date);research["ticker"]=_ticker(research.ticker)
    combined=pd.concat([research,postfeat],ignore_index=True,sort=False).sort_values(["signal_date","ticker"])
    base_cols=list(bundle.get("base_feature_universe",[]));missing=[c for c in base_cols if c not in combined]
    if missing: raise RuntimeError(f"LIVE_RAW_FEATURE_UNIVERSE_MISSING {missing[:8]}")
    ranked=p2r.cross_sectional_rank_features(combined,base_cols);transformed,_=p2r.add_regime_features(combined,ranked);livefeat=transformed[(transformed.signal_date>last_observed)&(transformed.signal_date<=latest)].copy()
    parts=[]
    for h in HORIZONS:
        b=bundle["base"][h];missing=[c for c in b["features"] if c not in livefeat]
        if missing:raise RuntimeError(f"LIVE_BASE_FEATURES_MISSING h={h} {missing[:8]}")
        pred=p4._apply_base_models(livefeat,b);sf=livefeat[["signal_date","ticker"]].copy()
        for e,r in pred.items():sf[e]=p2r.normalize(livefeat,r)
        score=p2r.normalize(livefeat,p2r.blend_scores(sf,b["expert_weights"]));q=livefeat[["signal_date","ticker"]].copy();q["horizon_sessions"]=h;q["fold"]="LIVE_SHADOW";q["score"]=score;parts.append(q)
    base=pd.concat(parts,ignore_index=True)
    cfg2u=p2u.load_cfg(root); info=p4._newinfo_holdout(temp_source,cfg2u,base[["signal_date","ticker"]].drop_duplicates(),postfeat[postfeat.signal_date>last_observed],market_ext,latest)
    meta=[]
    for h in HORIZONS:
        q=base[base.horizon_sessions.eq(h)][["signal_date","ticker","score"]].rename(columns={"score":"base_score"}).merge(info,on=["signal_date","ticker"],how="left",validate="one_to_one")
        b=bundle["meta"][h];missing=[c for c in b["features"] if c not in q]
        if missing:raise RuntimeError(f"LIVE_META_FEATURES_MISSING h={h} {missing[:8]}")
        pred=p4._apply_meta_models(q,b);sf=q[["signal_date","ticker"]].copy()
        for e,r in pred.items():sf[e]=p2u.daily_rank(q,r)
        score=p2u.daily_rank(q,p2u.blend(sf,b["expert_weights"]));o=q[["signal_date","ticker"]].copy();o["horizon_sessions"]=h;o["fold"]="LIVE_SHADOW";o["score"]=score;meta.append(o)
    scores=pd.concat(meta,ignore_index=True).sort_values(["signal_date","ticker","horizon_sessions"]);advisor=p4._advisor_from_sealed(scores,bundle);advisor["fold"]="LIVE_SHADOW"
    return scores,advisor,postfeat


def _market_for_plans(source: Path, root: Path, market_ext: pd.DataFrame, bench: pd.DataFrame, start: pd.Timestamp, latest: pd.Timestamp):
    # Historical total-return layer anchors live adjusted prices; the scaled feature price is used as mark price for new sessions.
    cfg1=p1.load_cfg(root); c=pd.read_parquet(source/cfg1.p["source_canonical_pit_panel"],columns=["date","ticker","close","research_eligible"]);c["date"]=_date(c.date);c["ticker"]=_ticker(c.ticker)
    r=pd.read_parquet(source/"outputs"/"phase2c_return_price_layer.parquet",columns=["date","ticker","target_total_return_price"]);r["date"]=_date(r.date);r["ticker"]=_ticker(r.ticker)
    surf=c.merge(r,on=["date","ticker"],how="left");surf=surf[surf.date.le(start)].copy();surf["execution_close"]=pd.to_numeric(surf.close,errors="coerce");surf["mark_price"]=pd.to_numeric(surf.target_total_return_price,errors="coerce");surf["research_eligible"]=surf.research_eligible.fillna(False).astype(bool);surf=surf[["date","ticker","execution_close","mark_price","research_eligible"]]
    new=market_ext[(market_ext.date>start)&(market_ext.date<=latest)][["date","ticker","close","feature_price","research_eligible"]].rename(columns={"close":"execution_close","feature_price":"mark_price"})
    surf=pd.concat([surf,new],ignore_index=True).drop_duplicates(["date","ticker"],keep="last")
    spy=bench.dropna(subset=["SPY"]).drop_duplicates("date").set_index("date")["SPY"]
    return p3v.prepare_market(surf,spy,start-pd.Timedelta(days=180),latest+pd.Timedelta(days=1),int(p3z.load_cfg(root).p["risk_lookback_sessions"]))


def _append_parquet(path: Path, df: pd.DataFrame, keys: list[str]):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): df=pd.concat([pd.read_parquet(path),df],ignore_index=True,sort=False)
    df=df.drop_duplicates(keys,keep="first").sort_values(keys).reset_index(drop=True);df.to_parquet(path,index=False)


def _append_csv(path: Path, df: pd.DataFrame, keys: list[str]):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): df=pd.concat([pd.read_csv(path),df],ignore_index=True,sort=False)
    df=df.drop_duplicates(keys,keep="first").sort_values(keys).reset_index(drop=True);df.to_csv(path,index=False)


def build_live_shadow(root: Path, now_utc: datetime | None = None) -> dict:
    cfg=load_cfg(root); seal=p5a.verify_seal_compat(root,p5a.load_cfg(root));hs=p5a.validate_observed_holdout(root,p5a.load_cfg(root))
    if str(seal.get("seal_id"))!=str(cfg.p["expected_seal_id"]):raise RuntimeError("LIVE_SEAL_MISMATCH")
    last=_last_observed(root,cfg);source=_source_root(root);universe,umeta=_latest_universe(source,root,last,cfg)
    cutoff=latest_completed_cutoff(now_utc,int(cfg.p["completed_session_grace_minutes"]));spy_probe=fetch_yahoo_history("SPY","SPY",last-pd.Timedelta(days=15),cutoff+pd.Timedelta(days=2),int(cfg.p["yahoo_timeout_seconds"]));probe=spy_probe[spy_probe.date<=cutoff]
    if probe.empty:raise RuntimeError("NO_SPY_SESSION_BEFORE_CUTOFF")
    latest=pd.Timestamp(probe.date.max()).normalize()
    sd=root/cfg.p["shadow_dir"];sd.mkdir(parents=True,exist_ok=True)
    if latest<=last:
        summary={"status":"NO_NEW_COMPLETED_SESSION","phase":"V13-P5B","build":BUILD,"seal_id":cfg.p["expected_seal_id"],"last_observed":str(last.date()),"latest_completed_session":str(latest.date()),"shadow_only":True,"real_orders_sent":False,"tuning_performed":False}
        (sd/"v13_live_shadow_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8");return summary
    fetch_start=last-pd.Timedelta(days=int(cfg.p["market_fetch_overlap_calendar_days"]));live,aud=fetch_market_universe(universe,fetch_start,latest+pd.Timedelta(days=2),cfg)
    got=set(live[live.date.eq(latest)].ticker);coverage=len(got)/max(len(universe),1)
    if coverage<float(cfg.p["minimum_market_coverage"]):raise RuntimeError(f"LIVE_MARKET_COVERAGE_LOW {coverage:.4f}")
    market_ext,anchors,_=_extend_market(root,source,universe,live,last,latest,cfg);bench=_extend_bench(root,source,market_ext,last,latest,cfg)
    temp_source,secmeta,secaud=_combined_sec_source(root,source,set(universe.ticker),latest,cfg);keys=_post2025_keys(source,market_ext,last,latest);bundle=joblib.load(root/cfg.p["sealed_model_bundle"]);scores,advisor,postfeat=_score_live(root,temp_source,source,market_ext,bench,keys,last,latest,bundle)
    live_scores=scores[scores.signal_date>last].copy();live_adv=advisor[advisor.signal_date>last].copy()
    if live_adv[live_adv.signal_date.eq(latest)].ticker.nunique()<int(cfg.p["minimum_live_advisor_rows"]):raise RuntimeError("LIVE_ADVISOR_CROSS_SECTION_TOO_SMALL")
    market_plan=_market_for_plans(source,root,market_ext,bench,last,latest);plans=p3z.build_plans(live_adv,market_plan,p3z.load_cfg(root))
    rows=[]
    piv=live_scores.pivot(index=["signal_date","ticker"],columns="horizon_sessions",values="score").reset_index();piv.columns=["signal_date","ticker"]+[f"score_{int(c)}d" for c in piv.columns[2:]]
    c=live_adv.merge(piv,on=["signal_date","ticker"],how="left",validate="one_to_one")
    c["expected_active_total"]=c.expected_active_per_session*c.effective_horizon_sessions
    for r in c.itertuples(index=False):
        p=plans.get(pd.Timestamp(r.signal_date),{}).get(str(r.ticker),{});rows.append({**r._asdict(),"model_target_weight":float(p.get("desired",0.0)),"entry_ok":bool(p.get("entry_ok",False)),"resize_band":float(p.get("band",1.0))})
    contract=pd.DataFrame(rows);contract["seal_id"]=cfg.p["expected_seal_id"];contract["shadow_only"]=True;contract["real_orders_sent"]=False;contract["model_intent"]=np.where(contract.entry_ok&contract.model_target_weight.gt(0),"ELIGIBLE_ENTRY","NO_ENTRY")
    contract=contract.sort_values(["signal_date","model_target_weight","expected_active_total"],ascending=[True,False,False]).reset_index(drop=True)
    latest_contract=contract[contract.signal_date.eq(latest)].copy();sw=float(latest_contract.model_target_weight.sum())
    if sw>1.0000001:raise RuntimeError(f"LIVE_TARGET_WEIGHT_SUM_GT_1 {sw}")
    # Fingerprint raw external inputs and sealed model identity. No tuning is performed.
    fp=_sha_payload({"seal_id":cfg.p["expected_seal_id"],"latest":str(latest.date()),"market_rows":int(len(live)),"market_last":str(live.date.max()),"market_digest":hashlib.sha256(live[["date","ticker","close","volume","adj_close"]].sort_values(["date","ticker"]).to_csv(index=False,na_rep="NA").encode()).hexdigest(),"sec_live_rows":secmeta["live_fact_rows"],"sec_source":secmeta["source"]})
    contract["input_fingerprint"]=fp
    _append_parquet(sd/"v13_live_shadow_scores.parquet",live_scores,["signal_date","ticker","horizon_sessions"]);_append_parquet(sd/"v13_live_shadow_advisor.parquet",live_adv,["signal_date","ticker"]);_append_csv(sd/"v13_live_shadow_contract_history.csv",contract,["signal_date","ticker"])
    latest_contract.to_csv(sd/"v13_live_shadow_contract_latest.csv",index=False);(sd/"v13_live_shadow_contract_latest.json").write_text(json.dumps({"build":BUILD,"seal_id":cfg.p["expected_seal_id"],"asof":str(latest.date()),"input_fingerprint":fp,"shadow_only":True,"real_orders_sent":False,"rows":latest_contract.to_dict(orient="records")},indent=2,default=str),encoding="utf-8")
    aud.to_csv(sd/"v13_live_market_audit.csv",index=False);anchors.to_csv(sd/"v13_live_adjusted_anchor_audit.csv",index=False);secaud.to_csv(sd/"v13_live_sec_audit.csv",index=False)
    summary={"status":"PASS","phase":"V13-P5B","build":BUILD,"seal_id":cfg.p["expected_seal_id"],"holdout_verdict":hs["economic_verdict"],"last_observed":str(last.date()),"latest_completed_session":str(latest.date()),"new_sessions":int(pd.Series(live_adv.signal_date.unique()).gt(last).sum()),"universe":umeta,"market_coverage_latest":coverage,"sec":secmeta,"advisor_rows_latest":int(len(latest_contract)),"entry_eligible_latest":int(latest_contract.entry_ok.sum()),"positive_targets_latest":int(latest_contract.model_target_weight.gt(0).sum()),"target_weight_sum_latest":sw,"input_fingerprint":fp,"shadow_only":True,"real_orders_sent":False,"tuning_performed":False,"production_contract_csv":"outputs/live_shadow/v13_live_shadow_contract_latest.csv","production_contract_json":"outputs/live_shadow/v13_live_shadow_contract_latest.json","next":"Connect Sheets/App Script to this exact contract as portfolio/ledger UI; keep Alpha Engine Python authoritative."}
    (sd/"v13_live_shadow_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    return summary
