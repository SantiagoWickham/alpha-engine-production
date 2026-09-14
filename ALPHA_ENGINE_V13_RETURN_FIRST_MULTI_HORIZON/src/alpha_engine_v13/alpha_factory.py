from __future__ import annotations

import json, math, tomllib, time, urllib.request, hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import norm

BUILD = "V13_P1_FIX2_CANONICAL_PIT_PANEL_2026-09-12"
FUND_METRICS = (
    "assets", "capex", "cash", "current_assets", "current_liabilities",
    "eps_diluted", "equity", "long_term_debt", "net_income",
    "operating_cash_flow", "operating_income", "revenue", "shares_outstanding",
)

@dataclass(frozen=True)
class Cfg:
    p: dict


def _date(s):
    return pd.to_datetime(s, errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")

def _ticker(s):
    return s.astype(str).str.upper().str.replace(".", "-", regex=False).str.strip()

def _require(df: pd.DataFrame, cols: Iterable[str], label: str):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")

def load_cfg(workspace: Path) -> Cfg:
    with (workspace / "config" / "v13_phase1.toml").open("rb") as f:
        p = tomllib.load(f)["v13_phase1"]
    return Cfg(p)

def load_phase0(workspace: Path) -> dict:
    p = workspace / "outputs" / "v13_phase0_summary.json"
    if not p.exists():
        raise FileNotFoundError(p)
    x = json.loads(p.read_text(encoding="utf-8"))
    if x.get("status") != "PASS":
        raise RuntimeError("V13 Phase 0 must PASS")
    rc = x.get("research_contract", {})
    if rc.get("use_2025_plus_for_research_selection") is not False:
        raise RuntimeError("V13 Phase 0 holdout firewall is not active")
    allowed = {str(r.get("path", "")) for r in (x.get("source_manifest", {}).get("allowed_sources", []) or [])}
    required = "outputs/phase2_canonical_pit_panel.parquet"
    if required not in allowed:
        raise RuntimeError(
            "V13 Phase 0 contract must be rerun with the canonical causal PIT panel formally allowed before Phase 1 FIX2"
        )
    return x

def load_target_keys_and_labels(source: Path, cfg: Cfg) -> pd.DataFrame:
    hold = pd.Timestamp(cfg.p["holdout_start"])
    horizons = [int(x) for x in cfg.p["horizons"]]
    cols = ["signal_date", "ticker", "entry_date"]
    for h in horizons:
        cols += [f"target_end_date_{h}d", f"target_resolved_{h}d", f"fwd_return_{h}d", f"winner_top_decile_{h}d"]
    path = source / cfg.p["phase3_targets"]
    try:
        t = pd.read_parquet(path, columns=cols, filters=[("signal_date", "<", hold.to_pydatetime())])
    except Exception:
        t = pd.read_parquet(path, columns=cols)
        t["signal_date"] = _date(t["signal_date"])
        t = t[t["signal_date"] < hold].copy()
    t["signal_date"] = _date(t["signal_date"])
    t["ticker"] = _ticker(t["ticker"])
    t["entry_date"] = _date(t["entry_date"])
    for h in horizons:
        t[f"target_end_date_{h}d"] = _date(t[f"target_end_date_{h}d"])
        t[f"fwd_return_{h}d"] = pd.to_numeric(t[f"fwd_return_{h}d"], errors="coerce")
        t[f"target_resolved_{h}d"] = t[f"target_resolved_{h}d"].fillna(False).astype(bool)
    if (t["signal_date"] >= hold).any():
        raise RuntimeError("HOLDOUT BREACH: Phase 1 loaded 2025+ target rows")
    return t.sort_values(["signal_date", "ticker"]).reset_index(drop=True)

def _load_market_one(path: Path, priority: int) -> pd.DataFrame:
    x = pd.read_parquet(path)
    _require(x, ["date", "ticker", "close"], str(path))
    cols = [c for c in ["date","ticker","close","adj_close","volume"] if c in x.columns]
    x = x[cols].copy()
    x["date"] = _date(x["date"]); x["ticker"] = _ticker(x["ticker"])
    for c in ["close","adj_close","volume"]:
        if c not in x: x[c] = np.nan
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x["priority"] = priority
    return x

def load_market(source: Path, cfg: Cfg) -> pd.DataFrame:
    """Load the canonical causal Phase-2 PIT market surface.

    V13 must not reconstruct research history from only the current/extended market caches:
    those omit a material share of historical/delisted names. Phase 2 already merged primary,
    secondary and delisted sources, applied the trading calendar, universe snapshots and
    lifecycle eligibility. This panel is foundational data, not a Phase-4+ model artifact.
    """
    hold = pd.Timestamp(cfg.p["holdout_start"])
    rel = cfg.p["source_canonical_pit_panel"]
    path = source / rel
    if not path.exists():
        raise FileNotFoundError(path)
    cols = ["date", "ticker", "close", "adj_close", "volume", "research_eligible"]
    x = pd.read_parquet(path, columns=cols)
    x["date"] = _date(x["date"]); x["ticker"] = _ticker(x["ticker"])
    x["research_eligible"] = x["research_eligible"].fillna(False).astype(bool)
    for c in ["close", "adj_close", "volume"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x[(x["date"] < hold) & x["research_eligible"] & x["close"].notna() & (x["close"] > 0) & x["ticker"].ne("")].copy()
    if x.duplicated(["date", "ticker"]).any():
        raise RuntimeError("Canonical PIT panel has duplicate research-eligible (date,ticker) keys")
    return x.sort_values(["ticker", "date"]).reset_index(drop=True)

def _cache_file(d: Path, t: str) -> Path:
    return d / f"{t.replace('/', '_').replace(chr(92), '_')}.parquet"

def add_feature_price(market: pd.DataFrame, source: Path, cfg: Cfg) -> tuple[pd.DataFrame, dict]:
    out=market.copy()
    out["feature_price"] = out["adj_close"].where(out["adj_close"].notna() & (out["adj_close"]>0))
    need=sorted(out.loc[out["feature_price"].isna(),"ticker"].unique())
    cache_dir=source/cfg.p["adjusted_cache_dir"]
    frames=[]
    for t in need:
        p=_cache_file(cache_dir,str(t))
        if not p.exists(): continue
        try:
            x=pd.read_parquet(p,columns=["date","ticker","adj_close"])
            x["date"]=_date(x["date"]); x["ticker"]=_ticker(x["ticker"]); x["adj_close"]=pd.to_numeric(x["adj_close"],errors="coerce")
            x=x[(x["date"]<pd.Timestamp(cfg.p["holdout_start"])) & x["adj_close"].notna() & (x["adj_close"]>0)]
            frames.append(x.rename(columns={"adj_close":"cache_adj"}))
        except Exception:
            continue
    if frames:
        c=pd.concat(frames,ignore_index=True).drop_duplicates(["date","ticker"],keep="last")
        out=out.merge(c,on=["date","ticker"],how="left")
        out["feature_price"]=out["feature_price"].fillna(out["cache_adj"])
        out=out.drop(columns=["cache_adj"])
    cov=float(out["feature_price"].notna().mean()) if len(out) else 0.0
    return out,{"rows":int(len(out)),"coverage":cov,"tickers":int(out["ticker"].nunique())}

def _yahoo_benchmark(symbol: str, source: Path, cfg: Cfg) -> pd.DataFrame:
    cache = source / "data" / "v13" / "benchmarks" / f"{symbol}.parquet"
    if cache.exists():
        x=pd.read_parquet(cache); x["date"]=_date(x["date"]); x[symbol]=pd.to_numeric(x[symbol],errors="coerce"); return x[["date",symbol]]
    period1=int(pd.Timestamp("2013-01-01",tz="UTC").timestamp()); period2=int(pd.Timestamp(cfg.p["holdout_start"],tz="UTC").timestamp())
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={period1}&period2={period2}&interval=1d&events=div%2Csplits&includeAdjustedClose=true"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 AlphaEngineV13/1.0"})
    last=None
    for k in range(3):
        try:
            with urllib.request.urlopen(req,timeout=25) as r: payload=json.loads(r.read().decode("utf-8"))
            res=payload["chart"]["result"][0]; ts=res.get("timestamp",[]); adj=((res.get("indicators",{}).get("adjclose") or [{}])[0].get("adjclose") or [])
            if not ts or len(ts)!=len(adj): raise RuntimeError(f"Yahoo {symbol} adjusted history missing")
            x=pd.DataFrame({"date":pd.to_datetime(ts,unit="s",utc=True).tz_convert(None).normalize(),symbol:pd.to_numeric(pd.Series(adj),errors="coerce")}).dropna()
            x=x[(x[symbol]>0)&(x["date"]<pd.Timestamp(cfg.p["holdout_start"]))].drop_duplicates("date",keep="last")
            cache.parent.mkdir(parents=True,exist_ok=True); x.to_parquet(cache,index=False); return x
        except Exception as exc:
            last=exc; time.sleep(1.0+k)
    raise RuntimeError(f"Unable to obtain adjusted {symbol} benchmark history: {last}")

def _local_benchmark(symbol: str, source: Path, market: pd.DataFrame, cfg: Cfg) -> pd.DataFrame:
    x=market[market["ticker"].eq(symbol)][["date","feature_price"]].dropna().rename(columns={"feature_price":symbol})
    if len(x)>=500: return x.drop_duplicates("date",keep="last")
    cp=_cache_file(source/cfg.p["adjusted_cache_dir"],symbol)
    if cp.exists():
        c=pd.read_parquet(cp); c["date"]=_date(c["date"]); c[symbol]=pd.to_numeric(c["adj_close"],errors="coerce"); c=c[(c[symbol]>0)&(c["date"]<pd.Timestamp(cfg.p["holdout_start"]))]
        if len(c)>=500: return c[["date",symbol]].drop_duplicates("date",keep="last")
    return _yahoo_benchmark(symbol,source,cfg)

def load_benchmarks(source: Path, market: pd.DataFrame, cfg: Cfg) -> pd.DataFrame:
    # Fair benchmark economics require adjusted histories. Raw close is never the preferred benchmark.
    s=_local_benchmark("SPY",source,market,cfg); q=_local_benchmark("QQQ",source,market,cfg)
    b=s.merge(q,on="date",how="outer").sort_values("date").drop_duplicates("date",keep="last")
    for c in ["SPY","QQQ"]: b[c]=pd.to_numeric(b[c],errors="coerce")
    return b

def benchmark_forward_returns(bench: pd.DataFrame, dates: pd.Series, horizons: list[int]) -> pd.DataFrame:
    b=bench.sort_values("date").dropna(subset=["date"]).copy()
    calendar=pd.DatetimeIndex(b.loc[b["SPY"].notna(),"date"].unique()).sort_values()
    out=pd.DataFrame({"signal_date":pd.DatetimeIndex(sorted(pd.Series(dates).dropna().unique()))})
    for symbol in ["SPY","QQQ"]:
        s=b[["date",symbol]].dropna().drop_duplicates("date",keep="last").set_index("date")[symbol]
        vals=[]
        sd=out["signal_date"].to_numpy(dtype="datetime64[ns]")
        cal=calendar.to_numpy(dtype="datetime64[ns]")
        entry=np.searchsorted(cal,sd,side="right")
        for h in horizons:
            ret=np.full(len(sd),np.nan)
            exitp=entry+int(h)
            valid=(entry<len(cal))&(exitp<len(cal))
            if valid.any():
                ed=pd.DatetimeIndex(cal[entry[valid]]); xd=pd.DatetimeIndex(cal[exitp[valid]])
                ep=s.reindex(ed).to_numpy(float); xp=s.reindex(xd).to_numpy(float)
                ok=np.isfinite(ep)&np.isfinite(xp)&(ep>0)
                idx=np.flatnonzero(valid)[ok]
                ret[idx]=xp[ok]/ep[ok]-1.0
            out[f"{symbol.lower()}_fwd_return_{h}d"]=ret
    return out

def _roll_min(w): return max(3,int(math.ceil(w*0.8)))

def price_features_one(g: pd.DataFrame) -> pd.DataFrame:
    g=g.sort_values("date").copy(); p=g["feature_price"].astype(float); v=g["volume"].astype(float); r=p.pct_change(fill_method=None)
    o=pd.DataFrame(index=g.index)
    for h in [1,5,10,20,60,120,252]: o[f"mom_{h}d"]=p/p.shift(h)-1
    for a,b in [(20,5),(60,5),(120,20),(252,20)]: o[f"mom_skip_{a}_{b}"]=p.shift(b)/p.shift(a)-1
    for h in [20,60,120,252]:
        mp=_roll_min(h); sma=p.rolling(h,min_periods=mp).mean(); hi=p.rolling(h,min_periods=mp).max(); lo=p.rolling(h,min_periods=mp).min()
        o[f"trend_sma_{h}"]=p/sma-1; o[f"dist_high_{h}"]=p/hi-1; o[f"dist_low_{h}"]=p/lo-1
    for h in [10,20,60,120]:
        mp=_roll_min(h); o[f"vol_{h}"]=r.rolling(h,min_periods=mp).std()*np.sqrt(252); o[f"downside_vol_{h}"]=r.where(r<0,0).rolling(h,min_periods=mp).std()*np.sqrt(252)
    for h in [20,60,120]: o[f"skew_{h}"]=r.rolling(h,min_periods=_roll_min(h)).skew()
    for h in [20,60]:
        o[f"worst_day_{h}"]=r.rolling(h,min_periods=_roll_min(h)).min(); o[f"best_day_{h}"]=r.rolling(h,min_periods=_roll_min(h)).max()
    o["mom_accel_20_60"]=(p/p.shift(20)-1)-((p.shift(20)/p.shift(60)-1)/2)
    o["mom_accel_60_120"]=(p/p.shift(60)-1)-(p.shift(60)/p.shift(120)-1)
    dv=p*v
    for h in [20,60]:
        o[f"log_dollar_volume_{h}"]=np.log1p(dv.rolling(h,min_periods=_roll_min(h)).mean().clip(lower=0))
        o[f"amihud_{h}"]=(r.abs()/dv.replace(0,np.nan)).rolling(h,min_periods=_roll_min(h)).mean()*1e6
    o["volume_surprise_20_60"]=v.rolling(20,min_periods=15).mean()/v.rolling(60,min_periods=45).mean()-1
    return o

def build_price_feature_panel(market: pd.DataFrame, keys: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    br=bench.sort_values("date").copy()
    for s in ["SPY","QQQ"]:
        br[f"{s.lower()}_r1"]=br[s].pct_change(fill_method=None)
        for h in [5,10,20,60,120,252]: br[f"{s.lower()}_mom_{h}"]=br[s]/br[s].shift(h)-1
        br[f"{s.lower()}_vol_20"]=br[f"{s.lower()}_r1"].rolling(20,min_periods=15).std()*np.sqrt(252)
        br[f"{s.lower()}_vol_60"]=br[f"{s.lower()}_r1"].rolling(60,min_periods=45).std()*np.sqrt(252)
    m=market.merge(br[[c for c in br.columns if c!="SPY" and c!="QQQ"]],on="date",how="left")
    frames=[]
    for _,g in m.groupby("ticker",sort=False):
        f=price_features_one(g); z=g[["date","ticker","feature_price","close","volume","spy_r1","qqq_r1"]].copy()
        z=pd.concat([z,f],axis=1)
        for h in [5,10,20,60,120,252]:
            z[f"rel_mom_spy_{h}"]=z[f"mom_{h}d"]-g[f"spy_mom_{h}"].to_numpy()
            z[f"rel_mom_qqq_{h}"]=z[f"mom_{h}d"]-g[f"qqq_mom_{h}"].to_numpy()
        rr=z["feature_price"].pct_change(fill_method=None)
        for h in [60,120]:
            z[f"corr_spy_{h}"]=rr.rolling(h,min_periods=_roll_min(h)).corr(g["spy_r1"])
            z[f"corr_qqq_{h}"]=rr.rolling(h,min_periods=_roll_min(h)).corr(g["qqq_r1"])
        frames.append(z)
    pf=pd.concat(frames,ignore_index=True)
    k=keys.rename(columns={"signal_date":"date"})[["date","ticker"]].drop_duplicates()
    pf=k.merge(pf,on=["date","ticker"],how="left",validate="one_to_one")
    # Cross-sectional market breadth/regime interactions; no global level is exported alone.
    for h in [20,60,120]:
        mcol=f"mom_{h}d"; breadth=pf.groupby("date",observed=True)[mcol].transform(lambda s: float((s>0).mean()) if s.notna().sum() else np.nan)
        pf[f"{mcol}_x_breadth"]=pf[mcol]*breadth
    return pf

def load_fund_events(source: Path, cfg: Cfg, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    p=source/cfg.p["source_sec_facts"]
    x=pd.read_parquet(p)
    _require(x,["ticker","canonical_metric","value","end","filed"],str(p))
    x=x[x["canonical_metric"].isin(FUND_METRICS)].copy(); x["ticker"]=_ticker(x["ticker"]); x["filed"]=_date(x["filed"]); x["period_end"]=_date(x["end"]); x["value"]=pd.to_numeric(x["value"],errors="coerce")
    x=x.dropna(subset=["ticker","canonical_metric","filed","value"]); x=x[x["filed"]<pd.Timestamp(cfg.p["holdout_start"])]
    cal=calendar.to_numpy(dtype="datetime64[ns]"); vals=x["filed"].to_numpy(dtype="datetime64[ns]"); idx=np.searchsorted(cal,vals,side="right"); ok=idx<len(cal)
    x=x.loc[ok].copy(); x["available_date"]=pd.to_datetime(cal[idx[ok]]).astype("datetime64[ns]")
    x=x.sort_values(["ticker","canonical_metric","available_date","period_end"]).drop_duplicates(["ticker","canonical_metric","available_date"],keep="last")
    return x[["ticker","canonical_metric","value","period_end","filed","available_date"]]

def attach_fundamentals(keys: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    base=keys.rename(columns={"signal_date":"date"})[["date","ticker"]].drop_duplicates().sort_values(["date","ticker"]).copy()
    for metric in FUND_METRICS:
        e=events[events["canonical_metric"].eq(metric)][["ticker","available_date","value","period_end"]].copy()
        if e.empty: base[metric]=np.nan; base[f"{metric}__available_date"]=pd.NaT; continue
        e=e.rename(columns={"value":metric,"available_date":f"{metric}__available_date","period_end":f"{metric}__period_end"})
        base=pd.merge_asof(base.sort_values(["date","ticker"]),e.sort_values([f"{metric}__available_date","ticker"]),left_on="date",right_on=f"{metric}__available_date",by="ticker",direction="backward",allow_exact_matches=True)
    return base.sort_values(["date","ticker"]).reset_index(drop=True)

def _div(a,b):
    a=pd.to_numeric(a,errors="coerce"); b=pd.to_numeric(b,errors="coerce"); out=a/b.where(b.abs()>1e-12); return out.replace([np.inf,-np.inf],np.nan)

def build_fund_features(f: pd.DataFrame, price_base: pd.DataFrame) -> pd.DataFrame:
    x=f.merge(price_base[["date","ticker","feature_price"]],on=["date","ticker"],how="left")
    A=x["assets"]; sh=x["shares_outstanding"]; mcap=x["feature_price"]*sh
    o=pd.DataFrame({"date":x["date"],"ticker":x["ticker"]})
    # Exactly one explicit size-level feature: no triple size bet.
    o["size_log_market_cap"]=np.log(mcap.where(mcap>0))
    o["cash_assets"]=_div(x["cash"],A); o["debt_assets"]=_div(x["long_term_debt"],A); o["equity_assets"]=_div(x["equity"],A)
    o["current_ratio"]=_div(x["current_assets"],x["current_liabilities"]); o["ocf_assets"]=_div(x["operating_cash_flow"],A); o["opinc_assets"]=_div(x["operating_income"],A); o["netinc_assets"]=_div(x["net_income"],A); o["revenue_assets"]=_div(x["revenue"],A); o["capex_assets"]=_div(x["capex"],A)
    o["debt_equity"]=_div(x["long_term_debt"],x["equity"])
    o["earnings_yield"]=_div(x["net_income"],mcap); o["operating_income_yield"]=_div(x["operating_income"],mcap); o["sales_yield"]=_div(x["revenue"],mcap); o["cash_yield"]=_div(x["cash"],mcap)
    # Approximate year-over-year change from PIT daily surfaces; direction not imposed.
    for metric in ["revenue","net_income","operating_income","operating_cash_flow","eps_diluted","assets","cash","long_term_debt"]:
        cur=pd.to_numeric(x[metric],errors="coerce"); lag=x.groupby("ticker",sort=False)[metric].shift(252); denom=lag.abs().replace(0,np.nan); o[f"chg_{metric}_252d"]=(cur-lag)/denom
    ages=[]
    for metric in ["revenue","eps_diluted","assets","cash","operating_income"]:
        c=f"{metric}__available_date"; age=(x["date"]-x[c]).dt.days.astype(float); o[f"age_{metric}"]=age; ages.append(age)
    o["fundamental_freshness_mean_days"]=pd.concat(ages,axis=1).mean(axis=1)
    # update activity derived only from known availability dates
    update_dates=pd.DataFrame({"date":x["date"],"ticker":x["ticker"]})
    av=[c for c in x.columns if c.endswith("__available_date")]
    upd=pd.Series(False,index=x.index)
    for c in av: upd |= x.groupby("ticker",sort=False)[c].transform(lambda s: s.notna() & s.ne(s.shift())).fillna(False)
    update_dates["upd"]=upd.astype(int)
    for h in [20,60]: o[f"fund_update_count_{h}d"]=update_dates.groupby("ticker",sort=False)["upd"].transform(lambda s:s.rolling(h,min_periods=1).sum())
    return o

def feature_family(name: str) -> str:
    if name.startswith(("mom_","rel_mom","trend_","dist_","vol_","downside_","skew_","worst_","best_","corr_")): return "PRICE_TREND_RISK"
    if name.startswith(("log_dollar","amihud","volume_")): return "LIQUIDITY"
    if name.startswith("size_"): return "SIZE_SINGLE_FACTOR"
    if name.startswith(("chg_","age_","fund_update","fundamental_freshness")): return "FUNDAMENTAL_CHANGE_FRESHNESS"
    if name.endswith("yield"): return "VALUATION"
    if name in {"cash_assets","debt_assets","equity_assets","current_ratio","ocf_assets","opinc_assets","netinc_assets","revenue_assets","capex_assets","debt_equity"}: return "QUALITY_BALANCE_SHEET"
    return "INTERACTION_OR_OTHER"

def research_key_price_coverage(price_panel: pd.DataFrame) -> dict:
    """Coverage relevant to Phase 1: only (date,ticker) keys that actually enter research.

    Raw market files may legitimately contain stale/warm-up/non-target rows. Those rows are
    diagnostic, not part of the feature-research denominator. Missing prices on research keys
    remain blocking and are exported for audit.
    """
    _require(price_panel, ["date", "ticker", "feature_price"], "research price panel")
    n=int(len(price_panel)); ok=price_panel["feature_price"].notna() & (pd.to_numeric(price_panel["feature_price"], errors="coerce")>0)
    return {
        "research_key_rows": n,
        "research_key_price_rows": int(ok.sum()),
        "research_key_missing_rows": int((~ok).sum()),
        "research_key_coverage": float(ok.mean()) if n else 0.0,
    }

def build_feature_library(source: Path, targets: pd.DataFrame, cfg: Cfg, market: pd.DataFrame | None=None, bench: pd.DataFrame | None=None, price_meta: dict | None=None) -> tuple[pd.DataFrame,dict]:
    if market is None:
        market=load_market(source,cfg); market,price_meta=add_feature_price(market,source,cfg)
    if bench is None:
        bench=load_benchmarks(source,market,cfg)
    if price_meta is None:
        price_meta={"rows":int(len(market)),"coverage":float(market["feature_price"].notna().mean()),"tickers":int(market["ticker"].nunique())}
    keys=targets[["signal_date","ticker"]].drop_duplicates()
    pf=build_price_feature_panel(market,keys,bench)
    aligned_price_meta=research_key_price_coverage(pf)
    raw_price_meta=dict(price_meta)
    price_meta={
        "canonical_market_source": True,
        "raw_market_rows": int(raw_price_meta.get("rows", len(market))),
        "raw_market_tickers": int(raw_price_meta.get("tickers", market["ticker"].nunique())),
        "raw_market_coverage": float(raw_price_meta.get("coverage", market["feature_price"].notna().mean() if len(market) else 0.0)),
        **aligned_price_meta,
    }
    cal=pd.DatetimeIndex(sorted(bench.loc[bench["SPY"].notna(),"date"].unique()))
    events=load_fund_events(source,cfg,cal); ff=attach_fundamentals(keys,events); ff=build_fund_features(ff,pf)
    out=pf.merge(ff,on=["date","ticker"],how="left",validate="one_to_one")
    # remove direct price levels / raw execution fields from exported features
    out=out.drop(columns=[c for c in ["feature_price","close","volume","spy_r1","qqq_r1"] if c in out.columns])
    out=out.rename(columns={"date":"signal_date"})
    feat=[c for c in out.columns if c not in ["signal_date","ticker"]]
    # no infinities
    for c in feat: out[c]=pd.to_numeric(out[c],errors="coerce").replace([np.inf,-np.inf],np.nan)
    return out.sort_values(["signal_date","ticker"]).reset_index(drop=True),{"feature_count":len(feat),"price":price_meta,"fundamental_events":int(len(events)),"features":feat,"families":{c:feature_family(c) for c in feat}}

def build_research_targets(targets: pd.DataFrame, bench: pd.DataFrame, cfg: Cfg) -> pd.DataFrame:
    hs=[int(x) for x in cfg.p["horizons"]]; b=benchmark_forward_returns(bench,targets["signal_date"],hs)
    t=targets.merge(b,on="signal_date",how="left",validate="many_to_one")
    for h in hs:
        r=pd.to_numeric(t[f"fwd_return_{h}d"],errors="coerce")
        uew=t.groupby("signal_date",observed=True)[f"fwd_return_{h}d"].transform("mean")
        t[f"uew_fwd_return_{h}d"]=uew
        t[f"excess_uew_{h}d"]=r-uew
        t[f"excess_spy_{h}d"]=r-t[f"spy_fwd_return_{h}d"]
        t[f"excess_qqq_{h}d"]=r-t[f"qqq_fwd_return_{h}d"]
    keep=["signal_date","ticker","entry_date"]
    for h in hs: keep += [f"target_end_date_{h}d",f"target_resolved_{h}d",f"fwd_return_{h}d",f"winner_top_decile_{h}d",f"uew_fwd_return_{h}d",f"spy_fwd_return_{h}d",f"qqq_fwd_return_{h}d",f"excess_uew_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d"]
    return t[keep]

def _nw_mean_t(x: np.ndarray, lag: int) -> tuple[float,float,float]:
    x=np.asarray(x,float); x=x[np.isfinite(x)]; n=len(x)
    if n<8: return math.nan,math.nan,math.nan
    mu=float(x.mean()); u=x-mu; gamma0=float(np.dot(u,u)/n); v=gamma0
    L=min(int(lag),n-1)
    for k in range(1,L+1):
        gamma=float(np.dot(u[k:],u[:-k])/n); v += 2*(1-k/(L+1))*gamma
    se=math.sqrt(max(v,0)/n) if v>=0 else math.nan; t=mu/se if se and np.isfinite(se) and se>0 else math.nan
    p=2*(1-norm.cdf(abs(t))) if np.isfinite(t) else math.nan
    return mu,t,p

def _bh(pvals: pd.Series) -> pd.Series:
    out=pd.Series(np.nan,index=pvals.index,dtype=float); ok=pvals.notna()&np.isfinite(pvals); p=pvals[ok].astype(float)
    if p.empty:return out
    order=p.sort_values().index; m=len(order); ranked=p.loc[order].to_numpy(); q=ranked*m/np.arange(1,m+1); q=np.minimum.accumulate(q[::-1])[::-1]; out.loc[order]=np.clip(q,0,1); return out

def _daily_rank_correlations(df: pd.DataFrame, feature_cols: list[str], y_col: str, min_cs: int) -> pd.DataFrame:
    if df.empty or not feature_cols:
        return pd.DataFrame(columns=["date", *feature_cols])
    work=df[["signal_date",y_col,*feature_cols]].sort_values(["signal_date"]).copy()
    xr=work.groupby("signal_date",observed=True)[feature_cols].rank(method="average",pct=True).to_numpy(float)
    yr=work.groupby("signal_date",observed=True)[y_col].rank(method="average",pct=True).to_numpy(float)
    dates=work["signal_date"].to_numpy(dtype="datetime64[ns]")
    uniq,starts=np.unique(dates,return_index=True); ends=np.r_[starts[1:],len(work)]
    out=np.full((len(uniq),len(feature_cols)),np.nan)
    for i,(a,b) in enumerate(zip(starts,ends)):
        xb=xr[a:b]; yb=yr[a:b]; yok=np.isfinite(yb)
        valid=np.isfinite(xb)&yok[:,None]; n=valid.sum(axis=0).astype(float); enough=n>=min_cs
        if not enough.any(): continue
        xv=np.where(valid,xb,0.); yv=np.where(valid,yb[:,None],0.)
        sx=xv.sum(0); sy=yv.sum(0); sxx=(xv*xv).sum(0); syy=(yv*yv).sum(0); sxy=(xv*yv).sum(0)
        den_n=np.where(n>0,n,1.); cov=sxy-sx*sy/den_n; vx=sxx-sx*sx/den_n; vy=syy-sy*sy/den_n; den=np.sqrt(np.maximum(vx*vy,0.))
        corr=np.full(len(feature_cols),np.nan); ok=(den>0)&enough; corr[ok]=cov[ok]/den[ok]; out[i]=corr
    return pd.DataFrame(out,index=pd.to_datetime(uniq),columns=feature_cols).rename_axis("date").reset_index()

def _partition(df: pd.DataFrame, h: int, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    e=f"target_end_date_{h}d"; r=f"target_resolved_{h}d"
    m=(df["signal_date"]>=start)&(df["signal_date"]<end)&df[e].notna()&(df[e]<end)&df[r].fillna(False).astype(bool)
    return df.loc[m].sort_values(["signal_date","ticker"]).copy()

def _feature_economics(part: pd.DataFrame, feature: str, h: int, direction: int) -> tuple[float,float,float,float,int]:
    cols=["signal_date",feature,f"fwd_return_{h}d",f"spy_fwd_return_{h}d",f"qqq_fwd_return_{h}d",f"uew_fwd_return_{h}d"]
    z=part[cols].dropna(subset=[feature,f"fwd_return_{h}d"]).copy()
    if z.empty:return (math.nan,)*4+(0,)
    rk=z.groupby("signal_date",observed=True)[feature].rank(pct=True); score=rk if direction>0 else 1-rk+1e-12
    z=z.loc[score>=.90].copy()
    if z.empty:return (math.nan,)*4+(0,)
    y=z[f"fwd_return_{h}d"]
    return float(y.mean()),float((y-z[f"spy_fwd_return_{h}d"]).mean()),float((y-z[f"qqq_fwd_return_{h}d"]).mean()),float((y-z[f"uew_fwd_return_{h}d"]).mean()),int(z["signal_date"].nunique())

def research_diagnostics(features: pd.DataFrame, rt: pd.DataFrame, cfg: Cfg) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    hs=[int(x) for x in cfg.p["horizons"]]; start=pd.Timestamp(cfg.p["research_start"]); val=pd.Timestamp(cfg.p["validation_start"]); hold=pd.Timestamp(cfg.p["holdout_start"]); mincs=int(cfg.p["minimum_cross_section"])
    df=features.merge(rt,on=["signal_date","ticker"],how="inner",validate="one_to_one").sort_values(["signal_date","ticker"]).reset_index(drop=True)
    if (df["signal_date"]>=hold).any(): raise RuntimeError("HOLDOUT BREACH inside diagnostics")
    feat=[c for c in features.columns if c not in ["signal_date","ticker"]]
    coverage=features.loc[features["signal_date"]>=start,feat].notna().mean().rename("coverage").reset_index().rename(columns={"index":"feature"}); coverage["family"]=coverage["feature"].map(feature_family)
    all_rows=[]; batch_size=16
    for h in hs:
        y=f"fwd_return_{h}d"; dev=_partition(df,h,start,val); va=_partition(df,h,val,hold)
        hrows=[]
        for a in range(0,len(feat),batch_size):
            batch=feat[a:a+batch_size]; dic=_daily_rank_correlations(dev,batch,y,mincs); vic=_daily_rank_correlations(va,batch,y,mincs)
            for f in batch:
                dmu,dt,dp=_nw_mean_t(dic[f].to_numpy() if f in dic else np.array([]),min(h,60)); vraw,vt_raw,vp=_nw_mean_t(vic[f].to_numpy() if f in vic else np.array([]),min(h,60)); direction=1 if (np.isfinite(dmu) and dmu>=0) else -1
                hrows.append({"feature":f,"family":feature_family(f),"horizon_sessions":h,"development_coverage":float(dev[f].notna().mean()) if len(dev) else 0.,"validation_coverage":float(va[f].notna().mean()) if len(va) else 0.,"direction_from_development":direction,"development_mean_ic":dmu,"development_hac_t":dt,"development_p":dp,"development_rich_dates":int(dic[f].notna().sum()) if f in dic else 0,"validation_aligned_ic":vraw*direction if np.isfinite(vraw) else math.nan,"validation_aligned_hac_t":vt_raw*direction if np.isfinite(vt_raw) else math.nan,"validation_rich_dates":int(vic[f].notna().sum()) if f in vic else 0})
        hdf=pd.DataFrame(hrows); hdf["development_fdr_q"]=_bh(hdf["development_p"])
        q=float(cfg.p["candidate_fdr_q"]); mic=float(cfg.p["candidate_min_abs_ic"]); cov=float(cfg.p["minimum_feature_coverage"])
        hdf["development_candidate"]=(hdf["development_coverage"]>=cov)&(hdf["development_fdr_q"]<=q)&(hdf["development_mean_ic"].abs()>=mic)
        # Rich economics only for plausible DEV candidates, capped before any validation information is consulted.
        rich_idx=hdf[hdf["development_candidate"]].assign(_strength=lambda x:x["development_hac_t"].abs()).sort_values(["_strength","development_fdr_q"],ascending=[False,True]).head(max(60,int(cfg.p["max_candidates_per_horizon"])) ).index
        for ix in rich_idx:
            f=str(hdf.at[ix,"feature"]); direction=int(hdf.at[ix,"direction_from_development"]); de=_feature_economics(dev,f,h,direction); ve=_feature_economics(va,f,h,direction)
            for name,valx in zip(["development_top10_return","development_top10_excess_spy","development_top10_excess_qqq","development_top10_excess_uew","development_top10_dates"],de): hdf.at[ix,name]=valx
            for name,valx in zip(["validation_top10_return","validation_top10_excess_spy","validation_top10_excess_qqq","validation_top10_excess_uew","validation_top10_dates"],ve): hdf.at[ix,name]=valx
        hdf["validation_confirmation"]=(hdf["validation_aligned_ic"]>0)&(hdf.get("validation_top10_excess_uew",pd.Series(np.nan,index=hdf.index))>0)
        # Candidate ranking is DEV-ONLY: validation columns are never in dev_score.
        hdf["dev_score"]=(hdf.get("development_top10_excess_uew",pd.Series(np.nan,index=hdf.index)).fillna(-9)+hdf.get("development_top10_excess_spy",pd.Series(np.nan,index=hdf.index)).fillna(-9)+hdf.get("development_top10_excess_qqq",pd.Series(np.nan,index=hdf.index)).fillna(-9))/3
        hdf["dev_rank"]=hdf["dev_score"].rank(ascending=False,method="first")
        maxc=int(cfg.p["max_candidates_per_horizon"]); hdf["recommended_for_phase2"]=hdf["development_candidate"]&(hdf["dev_rank"]<=maxc)
        all_rows.extend(hdf.to_dict(orient="records"))
    diag=pd.DataFrame(all_rows); candidates=diag[diag["recommended_for_phase2"]].copy() if len(diag) else diag.copy()
    return diag,candidates,coverage

def evaluate_gate(features: pd.DataFrame, rt: pd.DataFrame, diag: pd.DataFrame, candidates: pd.DataFrame, meta: dict, cfg: Cfg) -> tuple[pd.DataFrame,str]:
    hold=pd.Timestamp(cfg.p["holdout_start"]); hs=[int(x) for x in cfg.p["horizons"]]; rows=[]
    def add(test,ok,value,rule,blocking=True): rows.append({"test":test,"status":"PASS" if ok else "FAIL","blocking":blocking,"value":value,"rule":rule})
    add("PHASE1_NO_2025_PLUS_FEATURES",not (features["signal_date"]>=hold).any(),str(features["signal_date"].max().date()),"max feature date < 2025-01-01")
    add("PHASE1_NO_2025_PLUS_TARGETS",not (rt["signal_date"]>=hold).any(),str(rt["signal_date"].max().date()),"max target date < 2025-01-01")
    add("FEATURE_PRICE_COVERAGE",meta["price"]["research_key_coverage"]>=float(cfg.p["feature_price_coverage_required"]),meta["price"]["research_key_coverage"],f">= {cfg.p['feature_price_coverage_required']}")
    add("CANONICAL_PIT_MARKET_SOURCE",meta["price"].get("canonical_market_source") is True,meta["price"].get("canonical_market_source"),"Phase 1 market surface must come from Phase 2 canonical PIT panel")
    add("NO_DIRECT_PRICE_LEVEL_FEATURE",not any(c in {"close","adj_close","feature_price","target_total_return_price"} for c in features.columns),[c for c in features.columns if c in {"close","adj_close","feature_price","target_total_return_price"}],"no price/target level exported")
    add("UNIQUE_FEATURE_KEY",not features.duplicated(["signal_date","ticker"]).any(),int(features.duplicated(["signal_date","ticker"]).sum()),"0 duplicate keys")
    add("SIX_HORIZONS_PRESENT",set(diag["horizon_sessions"].unique())==set(hs) if len(diag) else False,sorted(diag["horizon_sessions"].unique().tolist()) if len(diag) else [],str(hs))
    usable=int((features.drop(columns=["signal_date","ticker"]).notna().mean()>=float(cfg.p["minimum_feature_coverage"])).sum())
    add("USABLE_FEATURE_BREADTH",usable>=30,usable,">=30 features with required coverage")
    cc=candidates.groupby("horizon_sessions")["feature"].nunique().reindex(hs,fill_value=0) if len(candidates) else pd.Series(0,index=hs)
    add("ALL_HORIZONS_HAVE_DEV_CANDIDATES",bool((cc>=3).all()),cc.to_dict(),">=3 DEV-only candidates per horizon",blocking=False)
    add("SIZE_NOT_TRIPLE_COUNTED",sum(c.startswith("size_") for c in features.columns)<=1,[c for c in features.columns if c.startswith("size_")],"at most one explicit size-level feature")
    gate=pd.DataFrame(rows); status="PASS" if not ((gate["blocking"]==True)&(gate["status"]=="FAIL")).any() else "FAIL"
    return gate,status

def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def _source_manifest(source: Path, cfg: Cfg) -> list[dict]:
    rels=[cfg.p["source_canonical_pit_panel"],cfg.p["source_sec_facts"],cfg.p["phase3_targets"],"data/v13/benchmarks/SPY.parquet","data/v13/benchmarks/QQQ.parquet"]
    out=[]
    for rel in rels:
        p=source/rel
        if p.exists() and p.is_file(): out.append({"path":rel,"bytes":int(p.stat().st_size),"sha256":_sha256(p)})
        else: out.append({"path":rel,"exists":False})
    return out

def _partition_manifest(rt: pd.DataFrame, cfg: Cfg) -> pd.DataFrame:
    start=pd.Timestamp(cfg.p["research_start"]); val=pd.Timestamp(cfg.p["validation_start"]); hold=pd.Timestamp(cfg.p["holdout_start"]); rows=[]
    for h in [int(x) for x in cfg.p["horizons"]]:
        for name,a,b in [("DEVELOPMENT",start,val),("VALIDATION",val,hold)]:
            x=_partition(rt,h,a,b); rows.append({"horizon_sessions":h,"partition":name,"rows":int(len(x)),"dates":int(x["signal_date"].nunique()),"first_signal_date":str(x["signal_date"].min().date()) if len(x) else "","last_signal_date":str(x["signal_date"].max().date()) if len(x) else "","max_target_end_date":str(x[f"target_end_date_{h}d"].max().date()) if len(x) else ""})
    return pd.DataFrame(rows)

def build_phase1(source: Path, workspace: Path) -> dict:
    cfg=load_cfg(workspace); p0=load_phase0(workspace)
    targets=load_target_keys_and_labels(source,cfg)
    market=load_market(source,cfg); market,price_meta=add_feature_price(market,source,cfg); bench=load_benchmarks(source,market,cfg)
    features,meta=build_feature_library(source,targets,cfg,market=market,bench=bench,price_meta=price_meta)
    # Rebuild only the aligned price key check for a transparent missing-price audit.
    research_keys=targets[["signal_date","ticker"]].drop_duplicates().rename(columns={"signal_date":"date"})
    aligned_prices=research_keys.merge(market[["date","ticker","feature_price"]],on=["date","ticker"],how="left",validate="one_to_one")
    missing_price_audit=aligned_prices.loc[aligned_prices["feature_price"].isna(),["date","ticker"]].rename(columns={"date":"signal_date"}).sort_values(["signal_date","ticker"])
    rt=build_research_targets(targets,bench,cfg)
    diag,candidates,coverage=research_diagnostics(features,rt,cfg)
    gate,status=evaluate_gate(features,rt,diag,candidates,meta,cfg)
    out=workspace/"outputs"; out.mkdir(parents=True,exist_ok=True)
    features.to_parquet(out/"v13_phase1_feature_library.parquet",index=False)
    rt.to_parquet(out/"v13_phase1_research_targets.parquet",index=False)
    diag.to_csv(out/"v13_phase1_feature_horizon_diagnostics.csv",index=False)
    candidates.to_csv(out/"v13_phase1_development_candidates.csv",index=False)
    coverage.to_csv(out/"v13_phase1_feature_coverage.csv",index=False)
    missing_price_audit.to_csv(out/"v13_phase1_missing_research_price_audit.csv",index=False)
    gate.to_csv(out/"v13_phase1_gate.csv",index=False)
    partitions=_partition_manifest(rt,cfg); partitions.to_csv(out/"v13_phase1_research_partitions.csv",index=False)
    manifest=_source_manifest(source,cfg); (out/"v13_phase1_source_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    bench_summary=pd.DataFrame([{"benchmark":sym,"rows":int(bench[sym].notna().sum()),"first_date":str(bench.loc[bench[sym].notna(),"date"].min().date()) if bench[sym].notna().any() else "","last_date":str(bench.loc[bench[sym].notna(),"date"].max().date()) if bench[sym].notna().any() else ""} for sym in ["SPY","QQQ"]]); bench_summary.to_csv(out/"v13_phase1_benchmark_summary.csv",index=False)
    fam=(candidates.groupby(["horizon_sessions","family"]).agg(candidates=("feature","nunique"),median_dev_ic=("development_mean_ic","median"),median_dev_excess_uew=("development_top10_excess_uew","median"),median_validation_excess_uew=("validation_top10_excess_uew","median")).reset_index() if len(candidates) else pd.DataFrame())
    fam.to_csv(out/"v13_phase1_family_summary.csv",index=False)
    summary={"status":status,"phase":"V13-P1","build":BUILD,"name":cfg.p["name"],"objective":cfg.p["objective"],"source_contract":p0["build"],"feature_library":{"rows":int(len(features)),"tickers":int(features["ticker"].nunique()),"first_date":str(features["signal_date"].min().date()),"last_date":str(features["signal_date"].max().date()),"feature_count":meta["feature_count"],"price_coverage":meta["price"]["research_key_coverage"],"raw_market_price_coverage":meta["price"]["raw_market_coverage"],"canonical_market_source":"outputs/phase2_canonical_pit_panel.parquet","research_key_missing_price_rows":meta["price"]["research_key_missing_rows"],"explicit_size_features":[c for c in features.columns if c.startswith("size_")]},"research":{"development_start":cfg.p["research_start"],"validation_start":cfg.p["validation_start"],"holdout_start":cfg.p["holdout_start"],"horizons":[int(x) for x in cfg.p["horizons"]],"selection_uses_2025_plus":False,"feature_admission_uses_validation":False,"candidate_counts":candidates.groupby("horizon_sessions")["feature"].nunique().reindex([int(x) for x in cfg.p["horizons"]],fill_value=0).to_dict() if len(candidates) else {}},"benchmarks":{"SPY":"adjusted future benchmark return","QQQ":"adjusted future benchmark return","UNIVERSE_EQUAL_WEIGHT":"same-date equal-weight labeled universe","daily_history":bench_summary.to_dict(orient="records")},"source_manifest":manifest,"gate":gate.to_dict(orient="records"),"next_gate":"If PASS: V13 Phase 2 trains one independent champion per horizon on DEVELOPMENT-only feature pools using purged walk-forward; no horizon is discarded. Phase 3 then learns cross-horizon conviction and dynamic cardinality/sizing from PRE-2025 net excess return."}
    (out/"v13_phase1_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8")
    return summary
