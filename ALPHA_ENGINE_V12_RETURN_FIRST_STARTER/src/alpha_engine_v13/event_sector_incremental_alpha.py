from __future__ import annotations

import json, math, time, tomllib, urllib.parse, urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

BUILD = "V13_P2U_EVENT_SECTOR_INCREMENTAL_ALPHA_2026-09-12"
HORIZONS = (5,10,20,60,120,252)
FOLDS = (
    ("WF_2017_2018","2017-01-03","2019-01-02"),
    ("WF_2019_2020","2019-01-02","2021-01-04"),
    ("WF_2021_2022","2021-01-04","2023-01-03"),
    ("WF_2023_2024","2023-01-03","2025-01-01"),
)
META_EXPERTS=("BASE_OOF","RIDGE_NEWINFO","HGB_NEWINFO_RANK","HGB_NEWINFO_RETURN","HGB_NEWINFO_WINNER","HGB_NEWINFO_AVOID")
EVENT_METRICS=("eps_diluted","revenue","net_income","operating_cash_flow","operating_income")

@dataclass(frozen=True)
class Cfg:
    p: dict

def _date(s):
    return pd.to_datetime(s,errors="coerce").dt.tz_localize(None).dt.normalize().astype("datetime64[ns]")

def _ticker(s):
    return s.astype(str).str.upper().str.replace(".","-",regex=False).str.strip()

def load_cfg(workspace:Path)->Cfg:
    with (workspace/"config"/"v13_phase2u.toml").open("rb") as f:
        return Cfg(tomllib.load(f)["v13_phase2u"])

def load_contracts(workspace:Path)->tuple[dict,Path]:
    p0=workspace/"outputs"/"v13_phase0_summary.json"; p1=workspace/"outputs"/"v13_phase1_summary.json"
    if not p0.exists() or not p1.exists(): raise FileNotFoundError("Phase0/1 summaries required")
    a=json.loads(p0.read_text(encoding="utf-8")); b=json.loads(p1.read_text(encoding="utf-8"))
    if a.get("status")!="PASS" or b.get("status")!="PASS": raise RuntimeError("Phase0/1 must PASS")
    src=a.get("source_manifest",{}).get("source_v12_root")
    if not src: raise RuntimeError("source_v12_root missing from Phase0")
    return b,Path(src)

def _strict_preholdout(df:pd.DataFrame, hold:pd.Timestamp, date_col:str="signal_date", label:str="data")->pd.DataFrame:
    x=df.copy(); x[date_col]=_date(x[date_col]); x=x[x[date_col]<hold].copy()
    if (x[date_col]>=hold).any(): raise RuntimeError(f"HOLDOUT BREACH in {label}")
    return x

def load_inputs(workspace:Path,cfg:Cfg):
    hold=pd.Timestamp(cfg.p["holdout_start"])
    scores=pd.read_parquet(workspace/cfg.p["base_oof_scores"]); scores=_strict_preholdout(scores,hold,"signal_date","base OOF")
    need={"signal_date","ticker","horizon_sessions","fold","score"}
    if not need.issubset(scores.columns): raise RuntimeError(f"base OOF missing {sorted(need-set(scores.columns))}")
    scores["ticker"]=_ticker(scores["ticker"]); scores["horizon_sessions"]=pd.to_numeric(scores["horizon_sessions"],errors="raise").astype(int)
    targets=pd.read_parquet(workspace/cfg.p["research_targets"]); targets=_strict_preholdout(targets,hold,"signal_date","targets"); targets["ticker"]=_ticker(targets["ticker"])
    # Strict holdout view: any pre-2025 signal whose label matures in 2025+ is made unavailable before research code can consume it.
    for h in HORIZONS:
        ec=f"target_end_date_{h}d"; rc=f"target_resolved_{h}d"
        req=[ec,rc,f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]
        miss=[c for c in req if c not in targets.columns]
        if miss: raise RuntimeError(f"Phase1 research target schema missing for {h}D: {miss}")
        targets[ec]=_date(targets[ec]); bad=targets[ec].isna() | (targets[ec]>=hold)
        targets.loc[bad,rc]=False
        for c in [f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]: targets.loc[bad,c]=np.nan
    features=pd.read_parquet(workspace/cfg.p["feature_library"]); features=_strict_preholdout(features,hold,"signal_date","feature library"); features["ticker"]=_ticker(features["ticker"])
    if sorted(scores.horizon_sessions.unique().tolist())!=list(HORIZONS): raise RuntimeError(f"Base OOF horizons mismatch: {sorted(scores.horizon_sessions.unique().tolist())}")
    expected_folds={f[0] for f in FOLDS}
    missing_folds=expected_folds-set(scores.fold.astype(str).unique())
    if missing_folds: raise RuntimeError(f"Base OOF missing folds: {sorted(missing_folds)}")
    return scores.sort_values(["signal_date","ticker","horizon_sessions"]),targets.sort_values(["signal_date","ticker"]),features.sort_values(["signal_date","ticker"])

def load_market(source:Path,cfg:Cfg)->pd.DataFrame:
    p=source/cfg.p["canonical_panel"]; cols=["date","ticker","close","volume","research_eligible"]
    x=pd.read_parquet(p,columns=cols); x["date"]=_date(x["date"]); x["ticker"]=_ticker(x["ticker"])
    x["close"]=pd.to_numeric(x["close"],errors="coerce"); x["volume"]=pd.to_numeric(x["volume"],errors="coerce")
    x["research_eligible"]=x["research_eligible"].fillna(False).astype(bool)
    x=x[(x.date<pd.Timestamp(cfg.p["holdout_start"]))&x.close.gt(0)].copy()
    return x.drop_duplicates(["date","ticker"],keep="last").sort_values(["ticker","date"])

def _yahoo_raw_close(symbol:str,start="2013-01-01",end="2025-01-02")->pd.DataFrame:
    p1=int(pd.Timestamp(start,tz="UTC").timestamp()); p2=int(pd.Timestamp(end,tz="UTC").timestamp()); q=urllib.parse.quote(symbol,safe="")
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?period1={p1}&period2={p2}&interval=1d&events=history&includeAdjustedClose=false"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 AlphaEngineV13/1.0"}); last=None
    for k in range(3):
        try:
            with urllib.request.urlopen(req,timeout=25) as r: payload=json.loads(r.read().decode("utf-8"))
            res=payload["chart"]["result"][0]; ts=res.get("timestamp",[]); close=((res.get("indicators",{}).get("quote") or [{}])[0].get("close") or [])
            if not ts or len(ts)!=len(close): raise RuntimeError("raw close history missing")
            x=pd.DataFrame({"date":pd.to_datetime(ts,unit="s",utc=True).tz_convert(None).normalize(),symbol:pd.to_numeric(pd.Series(close),errors="coerce")})
            return x.dropna().drop_duplicates("date",keep="last").sort_values("date")
        except Exception as e:
            last=e; time.sleep(1+k)
    raise RuntimeError(f"Yahoo raw-close download failed {symbol}: {last}")

def load_rotation_sources(workspace:Path,cfg:Cfg)->tuple[pd.DataFrame,pd.DataFrame]:
    cache=workspace/cfg.p["sector_cache_dir"]; cache.mkdir(parents=True,exist_ok=True); hold=pd.Timestamp(cfg.p["holdout_start"])
    frames=[]; aud=[]
    for sym in list(cfg.p["sector_symbols"])+list(cfg.p["macro_symbols"]):
        p=cache/f"{sym}.parquet"; src="CACHE"; x=None
        if p.exists():
            try:
                x=pd.read_parquet(p); x["date"]=_date(x["date"]); x[sym]=pd.to_numeric(x[sym],errors="coerce")
                if sym not in x or len(x)<int(cfg.p["minimum_source_rows"]): x=None
            except Exception: x=None
        if x is None:
            src="YAHOO_RAW_CLOSE"; x=_yahoo_raw_close(sym); x=x[x.date<hold].copy(); x.to_parquet(p,index=False)
        else: x=x[x.date<hold].copy()
        frames.append(x[["date",sym]]); aud.append({"symbol":sym,"source":src,"rows":len(x),"first_date":str(x.date.min().date()) if len(x) else "","last_date":str(x.date.max().date()) if len(x) else ""})
    z=frames[0]
    for x in frames[1:]: z=z.merge(x,on="date",how="outer",validate="one_to_one")
    z=z.sort_values("date").reset_index(drop=True)
    if (z.date>=hold).any(): raise RuntimeError("HOLDOUT BREACH rotation source")
    return z,pd.DataFrame(aud)

def rotation_daily_features(raw:pd.DataFrame,cfg:Cfg)->tuple[pd.DataFrame,list[str],pd.DataFrame]:
    x=raw.sort_values("date").copy(); sectors=list(cfg.p["sector_symbols"]); macros=list(cfg.p["macro_symbols"]); out=pd.DataFrame({"signal_date":x.date})
    r1={}
    for s in sectors+macros:
        p=pd.to_numeric(x[s],errors="coerce"); r1[s]=p.pct_change(fill_method=None); out[f"rot_{s.lower()}_r1"]=r1[s]
        for h in (20,60,120): out[f"rot_{s.lower()}_ret{h}"]=p/p.shift(h)-1
    # Common regime features; stock-specific beta interactions are built separately.
    for h in (20,60,120):
        sec=np.column_stack([out[f"rot_{s.lower()}_ret{h}"].to_numpy(float) for s in sectors])
        out[f"rot_sector_dispersion_{h}"]=pd.DataFrame(sec).std(axis=1,skipna=True).to_numpy()
        out[f"rot_xle_xlk_{h}"]=out.get(f"rot_xle_ret{h}",np.nan)-out.get(f"rot_xlk_ret{h}",np.nan)
        out[f"rot_xlf_xlk_{h}"]=out.get(f"rot_xlf_ret{h}",np.nan)-out.get(f"rot_xlk_ret{h}",np.nan)
        out[f"rot_ief_shy_{h}"]=out.get(f"rot_ief_ret{h}",np.nan)-out.get(f"rot_shy_ret{h}",np.nan)
        out[f"rot_tip_ief_{h}"]=out.get(f"rot_tip_ret{h}",np.nan)-out.get(f"rot_ief_ret{h}",np.nan)
        out[f"rot_dbc_gld_{h}"]=out.get(f"rot_dbc_ret{h}",np.nan)-out.get(f"rot_gld_ret{h}",np.nan)
    cols=[c for c in out.columns if c!="signal_date" and not c.endswith("_r1")]
    # trailing PIT z-scores for stable scale
    zcols={}
    for c in cols:
        s=pd.to_numeric(out[c],errors="coerce"); mu=s.rolling(252,min_periods=63).mean(); sd=s.rolling(252,min_periods=63).std().replace(0,np.nan); zcols[c+"_z252"]=((s-mu)/sd).clip(-5,5)
    out=pd.concat([out,pd.DataFrame(zcols,index=out.index)],axis=1)
    return out,[c for c in out.columns if c!="signal_date" and not c.endswith("_r1")],pd.DataFrame({"sector_symbol":sectors})

def stock_sector_features(market:pd.DataFrame,raw:pd.DataFrame,keys:pd.DataFrame,cfg:Cfg)->pd.DataFrame:
    sectors=list(cfg.p["sector_symbols"]); rr=raw.sort_values("date").copy()
    for s in sectors: rr[f"{s}_r1"]=pd.to_numeric(rr[s],errors="coerce").pct_change(fill_method=None)
    retcols=[f"{s}_r1" for s in sectors]; momcols=[]
    for s in sectors:
        for h in (20,60,120): rr[f"{s}_m{h}"]=pd.to_numeric(rr[s],errors="coerce")/pd.to_numeric(rr[s],errors="coerce").shift(h)-1; momcols.append(f"{s}_m{h}")
    z=market.merge(rr[["date"]+retcols+momcols],on="date",how="left")
    win=int(cfg.p["beta_window"]); mp=int(cfg.p["beta_min_periods"]); frames=[]
    for _,g in z.groupby("ticker",sort=False):
        g=g.sort_values("date").copy(); sr=g.close.pct_change(fill_method=None); o=g[["date","ticker"]].copy(); betas=[]
        for s in sectors:
            mr=pd.to_numeric(g[f"{s}_r1"],errors="coerce"); var=mr.rolling(win,min_periods=mp).var().replace(0,np.nan); b=(sr.rolling(win,min_periods=mp).cov(mr)/var).clip(-1,4); o[f"beta_{s.lower()}_60"]=b; betas.append(b.to_numpy(float))
        B=np.column_stack(betas); bp=np.where(np.isfinite(B)&(B>0),B,0.0); den=bp.sum(axis=1)
        bf=pd.DataFrame(B); o["sector_beta_max"]=bf.max(axis=1,skipna=True).to_numpy(); o["sector_beta_dispersion"]=bf.std(axis=1,skipna=True).to_numpy()
        for h in (20,60,120):
            M=np.column_stack([pd.to_numeric(g[f"{s}_m{h}"],errors="coerce").to_numpy(float) for s in sectors]); num=np.nansum(bp*M,axis=1); o[f"sector_implied_mom_{h}"]=np.divide(num,den,out=np.full(len(g),np.nan),where=den>0)
        frames.append(o)
    b=pd.concat(frames,ignore_index=True); k=keys.rename(columns={"signal_date":"date"})[["date","ticker"]].drop_duplicates(); return k.merge(b,on=["date","ticker"],how="left",validate="one_to_one").rename(columns={"date":"signal_date"})

def _next_session(dates:pd.Series,calendar:pd.DatetimeIndex)->pd.Series:
    cal=calendar.to_numpy(dtype="datetime64[ns]"); v=pd.to_datetime(dates).to_numpy(dtype="datetime64[ns]"); idx=np.searchsorted(cal,v,side="right"); out=np.full(len(v),np.datetime64("NaT"),dtype="datetime64[ns]"); ok=idx<len(cal); out[ok]=cal[idx[ok]]; return pd.Series(out,index=dates.index)

def sec_event_table(source:Path,market:pd.DataFrame,cfg:Cfg)->tuple[pd.DataFrame,pd.DataFrame]:
    p=source/cfg.p["source_sec_facts"]; x=pd.read_parquet(p)
    req={"ticker","canonical_metric","value","end","filed"}
    if not req.issubset(x.columns): raise RuntimeError(f"SEC facts missing {sorted(req-set(x.columns))}")
    x=x[x.canonical_metric.isin(EVENT_METRICS)].copy(); x["ticker"]=_ticker(x.ticker); x["filed"]=_date(x.filed); x["period_end"]=_date(x.end); x["value"]=pd.to_numeric(x.value,errors="coerce")
    if "form" in x.columns: x=x[x["form"].astype(str).str.upper().isin(["10-Q","10-K","10-Q/A","10-K/A"])|x["form"].isna()].copy()
    x=x.dropna(subset=["ticker","canonical_metric","filed","period_end","value"]); x=x[x.filed<pd.Timestamp(cfg.p["holdout_start"])].copy()
    cal=pd.DatetimeIndex(sorted(market.date.unique())); x["available_date"]=_next_session(x.filed,cal); x=x.dropna(subset=["available_date"])
    # One observation per metric and availability date. Latest period_end wins; no future filing is used.
    x=x.sort_values(["ticker","canonical_metric","available_date","period_end"]).drop_duplicates(["ticker","canonical_metric","available_date"],keep="last")
    groups=[]
    for (_,metric),g in x.groupby(["ticker","canonical_metric"],sort=False):
        g=g.sort_values(["available_date","period_end"]).copy(); prev=g.value.shift(1); delta=(g.value-prev)/prev.abs().replace(0,np.nan); delta=delta.clip(-10,10)
        prior_med=delta.shift(1).rolling(4,min_periods=2).median(); prior_sd=delta.shift(1).rolling(8,min_periods=3).std().replace(0,np.nan); surprise=((delta-prior_med)/prior_sd).clip(-6,6)
        # Prefer same fiscal-period YoY when available in source.
        if "fp" in g.columns and g["fp"].notna().any():
            gg=g.copy(); gg["_fp"]=gg["fp"].astype(str); same=gg.groupby("_fp",sort=False).value.shift(1); yoy=(gg.value-same)/same.abs().replace(0,np.nan); yoy=yoy.clip(-10,10)
        else: yoy=delta
        g["event_delta"]=delta; g["event_surprise_z"]=surprise; g["event_growth"]=yoy; groups.append(g)
    e=pd.concat(groups,ignore_index=True) if groups else x.assign(event_delta=np.nan,event_surprise_z=np.nan,event_growth=np.nan)
    piv=[]
    for c in ["event_surprise_z","event_growth"]:
        q=e.pivot_table(index=["ticker","available_date"],columns="canonical_metric",values=c,aggfunc="last"); q.columns=[f"earn_{c}_{m}" for m in q.columns]; piv.append(q.reset_index())
    ev=piv[0]
    for q in piv[1:]: ev=ev.merge(q,on=["ticker","available_date"],how="outer",validate="one_to_one")
    s_cols=[c for c in ev.columns if c.startswith("earn_event_surprise_z_")]; g_cols=[c for c in ev.columns if c.startswith("earn_event_growth_")]
    ev["earn_surprise_composite"]=ev[s_cols].mean(axis=1); ev["earn_surprise_dispersion"]=ev[s_cols].std(axis=1); ev["earn_positive_breadth"]=(ev[s_cols]>0).mean(axis=1); ev["earn_growth_composite"]=ev[g_cols].mean(axis=1); ev["earn_metric_count"]=ev[s_cols].notna().sum(axis=1)
    aud=pd.DataFrame({"metric":["sec_rows","sec_tickers","event_rows","event_tickers"],"value":[len(x),x.ticker.nunique(),len(ev),ev.ticker.nunique()]})
    return ev.sort_values(["ticker","available_date"]),aud

def attach_event_features(keys:pd.DataFrame,events:pd.DataFrame,market:pd.DataFrame)->pd.DataFrame:
    base=keys[["signal_date","ticker"]].drop_duplicates().sort_values(["signal_date","ticker"]).copy(); e=events.copy()
    cols=[c for c in e.columns if c not in {"ticker","available_date"}]
    if e.empty:
        for c in cols+['earn_days_since_event','earn_event_return','earn_event_volume_ratio','earn_event_decay_5','earn_event_decay_20','earn_event_decay_60']: base[c]=np.nan
        return base
    # merge_asof requires global sort by time then by; this order is robust across pandas versions.
    b=base.sort_values(["signal_date","ticker"]); ee=e.sort_values(["available_date","ticker"])
    out=pd.merge_asof(b,ee,left_on="signal_date",right_on="available_date",by="ticker",direction="backward",allow_exact_matches=True)
    # session age and post-event reaction from observable closes only.
    cal=pd.DatetimeIndex(sorted(market.date.unique())); pos=pd.Series(np.arange(len(cal)),index=cal)
    sp=out.signal_date.map(pos); ep=out.available_date.map(pos); out["earn_days_since_event"]=(sp-ep).astype(float)
    px=market[["date","ticker","close","volume"]].copy(); px["vol60"]=px.groupby("ticker",sort=False).volume.transform(lambda s:s.rolling(60,min_periods=30).mean())
    cur=out.merge(px.rename(columns={"date":"signal_date","close":"_cur_close","volume":"_cur_vol","vol60":"_cur_vol60"}),on=["signal_date","ticker"],how="left",validate="one_to_one")
    epm=px[["date","ticker","close"]].rename(columns={"date":"available_date","close":"_event_close"}); cur=cur.merge(epm,on=["available_date","ticker"],how="left",validate="many_to_one")
    cur["earn_event_return"]=(cur._cur_close/cur._event_close-1).where(cur.earn_days_since_event.between(0,60)); cur["earn_event_volume_ratio"]=(cur._cur_vol/cur._cur_vol60-1).where(cur.earn_days_since_event.between(0,20))
    for h in (5,20,60): cur[f"earn_event_decay_{h}"]=cur.earn_surprise_composite*np.exp(-cur.earn_days_since_event.clip(lower=0)/h)
    return cur.drop(columns=[c for c in ["_cur_close","_event_close","_cur_vol","_cur_vol60"] if c in cur])

def build_newinfo_surface(workspace:Path,source:Path,scores:pd.DataFrame,features:pd.DataFrame,market:pd.DataFrame,cfg:Cfg):
    keys=scores[["signal_date","ticker"]].drop_duplicates(); raw,src_audit=load_rotation_sources(workspace,cfg); daily,_,_=rotation_daily_features(raw,cfg); ss=stock_sector_features(market,raw,keys,cfg); events,event_audit=sec_event_table(source,market,cfg); ef=attach_event_features(keys,events,market)
    # small subset of existing stock state for interactions; new sources remain the core incremental information.
    state=[c for c in ["mom_5d","mom_20d","mom_60d","mom_120d","rel_mom_spy_20","rel_mom_qqq_20","downside_vol_20","downside_vol_60","size_log_market_cap","earnings_yield","cash_assets","fundamental_freshness_mean_days"] if c in features.columns]
    z=keys.merge(features[["signal_date","ticker"]+state],on=["signal_date","ticker"],how="left",validate="one_to_one").merge(daily,on="signal_date",how="left",validate="many_to_one").merge(ss,on=["signal_date","ticker"],how="left",validate="one_to_one").merge(ef,on=["signal_date","ticker"],how="left",validate="one_to_one")
    for h in (20,60,120):
        if f"mom_{h}d" in z and f"sector_implied_mom_{h}" in z: z[f"sector_residual_mom_{h}"]=pd.to_numeric(z[f"mom_{h}d"],errors="coerce")-pd.to_numeric(z[f"sector_implied_mom_{h}"],errors="coerce")
    if "earn_surprise_composite" in z and "sector_residual_mom_20" in z: z["ix_earn_surprise_sector_resid20"]=z.earn_surprise_composite*z.sector_residual_mom_20
    if "earn_surprise_composite" in z and "downside_vol_20" in z: z["ix_earn_surprise_downvol20"]=z.earn_surprise_composite*pd.to_numeric(z.downside_vol_20,errors="coerce")
    if "available_date" in z.columns: z=z.drop(columns=["available_date"])
    newcols=[c for c in z.columns if c not in {"signal_date","ticker"}]
    for c in newcols: z[c]=pd.to_numeric(z[c],errors="coerce").replace([np.inf,-np.inf],np.nan)
    return z.sort_values(["signal_date","ticker"]),src_audit,event_audit

def horizon_frame(scores:pd.DataFrame,targets:pd.DataFrame,newinfo:pd.DataFrame,h:int)->pd.DataFrame:
    sc=scores[scores.horizon_sessions.eq(h)][["signal_date","ticker","fold","score"]].rename(columns={"score":"base_score"})
    cols=["signal_date","ticker",f"target_end_date_{h}d",f"target_resolved_{h}d",f"fwd_return_{h}d",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]
    miss=[c for c in cols if c not in targets.columns]
    if miss: raise RuntimeError(f"Phase1 research target schema missing for {h}D: {miss}")
    t=targets[cols].copy(); t[f"target_end_date_{h}d"]=_date(t[f"target_end_date_{h}d"]); t[f"target_resolved_{h}d"]=t[f"target_resolved_{h}d"].fillna(False).astype(bool)
    z=sc.merge(t,on=["signal_date","ticker"],how="inner",validate="one_to_one").merge(newinfo,on=["signal_date","ticker"],how="left",validate="one_to_one")
    e=np.column_stack([pd.to_numeric(z[f"excess_spy_{h}d"],errors="coerce"),pd.to_numeric(z[f"excess_qqq_{h}d"],errors="coerce"),pd.to_numeric(z[f"excess_uew_{h}d"],errors="coerce")]); z["_robust_alpha"]=np.nanmin(e,axis=1)
    z["_alpha_rank"]=z.groupby("signal_date",observed=True)["_robust_alpha"].rank(method="average",pct=True); z["_winner"]=(z._alpha_rank>=.90).astype(int); z["_loser"]=(z._alpha_rank<=.20).astype(int)
    return z

def fold_order(name:str)->int:
    names=[f[0] for f in FOLDS]; return names.index(name)

def meta_train_test(df:pd.DataFrame,h:int,fold:str)->tuple[pd.DataFrame,pd.DataFrame]:
    i=fold_order(fold); ifold={f[0]:(pd.Timestamp(f[1]),pd.Timestamp(f[2])) for f in FOLDS}; ts,te=ifold[fold]
    prior={f[0] for f in FOLDS[:i]}; ec=f"target_end_date_{h}d"; rc=f"target_resolved_{h}d"
    tr=df[df.fold.isin(prior)&df[rc]&df[ec].notna()&(df[ec]<ts)&df._robust_alpha.notna()].copy(); va=df[df.fold.eq(fold)&df[rc]&df[ec].notna()&(df[ec]<te)&df._robust_alpha.notna()].copy()
    if len(tr) and not (tr[ec]<ts).all(): raise RuntimeError("META PURGE BREACH")
    return tr,va

def _rz(x):
    x=np.asarray(x,float); med=np.nanmedian(x); mad=np.nanmedian(np.abs(x-med)); return np.clip((x-med)/max(1.4826*mad,1e-9),-4,4)

def select_features(train:pd.DataFrame,candidates:list[str],cfg:Cfg)->list[str]:
    y=pd.to_numeric(train._alpha_rank,errors="coerce").to_numpy(float); rows=[]
    for c in candidates:
        x=pd.to_numeric(train[c],errors="coerce").to_numpy(float); ok=np.isfinite(x)&np.isfinite(y); cc=float(np.corrcoef(x[ok],y[ok])[0,1]) if ok.sum()>=300 else 0.0; rows.append((c,abs(cc) if np.isfinite(cc) else 0.0))
    ranked=[r[0] for r in sorted(rows,key=lambda q:(-q[1],q[0]))]; pre=ranked[:max(int(cfg.p["max_selected_features"])*2,int(cfg.p["minimum_selected_features"]))]; keep=[]
    if pre:
        sample=train[pre]
        if len(sample)>int(cfg.p["correlation_sample_rows"]): sample=sample.sample(int(cfg.p["correlation_sample_rows"]),random_state=int(cfg.p["random_state"]))
        corr=sample.corr().abs()
        for c in pre:
            if not keep or all((not np.isfinite(corr.loc[c,k])) or corr.loc[c,k]<float(cfg.p["correlation_prune_threshold"]) for k in keep): keep.append(c)
            if len(keep)>=int(cfg.p["max_selected_features"]): break
    for must in ["base_score","earn_surprise_composite","sector_residual_mom_20","sector_residual_mom_60"]:
        if must in candidates and must not in keep: keep.append(must)
    return keep[:int(cfg.p["max_selected_features"])]

def _mat(df,cols):
    x=df[cols].to_numpy(np.float32); med=np.nanmedian(x,axis=0); med=np.where(np.isfinite(med),med,.0); return np.where(np.isfinite(x),x,med).astype(np.float32)

def daily_rank(df:pd.DataFrame,raw)->np.ndarray:
    q=pd.DataFrame({"d":df.signal_date.to_numpy(),"x":np.asarray(raw,float)}); return q.groupby("d",observed=True).x.rank(method="average",pct=True).to_numpy(float)

def fit_meta_experts(train:pd.DataFrame,test:pd.DataFrame,cols:list[str],cfg:Cfg)->dict[str,np.ndarray]:
    xt=_mat(train,cols); xv=_mat(test,cols); yr=pd.to_numeric(train._alpha_rank,errors="coerce").to_numpy(float); ya=pd.to_numeric(train._robust_alpha,errors="coerce").clip(train._robust_alpha.quantile(.01),train._robust_alpha.quantile(.99)).to_numpy(float); win=train._winner.to_numpy(int); lose=train._loser.to_numpy(int)
    out={"BASE_OOF":pd.to_numeric(test.base_score,errors="coerce").to_numpy(float)}
    mu=np.nanmean(xt,axis=0); sd=np.nanstd(xt,axis=0); sd=np.where(sd>1e-6,sd,1.0); rg=Ridge(alpha=float(cfg.p["ridge_alpha"])); rg.fit((xt-mu)/sd,yr); out["RIDGE_NEWINFO"]=rg.predict((xv-mu)/sd)
    hp=dict(loss="squared_error",learning_rate=float(cfg.p["hgb_learning_rate"]),max_iter=int(cfg.p["hgb_max_iter"]),max_leaf_nodes=int(cfg.p["hgb_max_leaf_nodes"]),min_samples_leaf=int(cfg.p["hgb_min_samples_leaf"]),l2_regularization=float(cfg.p["hgb_l2"]),random_state=int(cfg.p["random_state"]))
    for name,y in [("HGB_NEWINFO_RANK",yr),("HGB_NEWINFO_RETURN",ya)]: m=HistGradientBoostingRegressor(**hp); m.fit(xt,y); out[name]=m.predict(xv)
    cp={k:v for k,v in hp.items() if k!="loss"}; cw=HistGradientBoostingClassifier(**cp); cw.fit(xt,win); out["HGB_NEWINFO_WINNER"]=cw.predict_proba(xv)[:,1]; cd=HistGradientBoostingClassifier(**cp); cd.fit(xt,lose); out["HGB_NEWINFO_AVOID"]=1-cd.predict_proba(xv)[:,1]
    return out

def evaluate(test:pd.DataFrame,score:np.ndarray,h:int,cfg:Cfg)->dict:
    z=test[["signal_date","ticker",f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d","_alpha_rank"]].copy(); z["score"]=score; z=z[np.isfinite(z.score)&z._alpha_rank.notna()].copy()
    if z.empty:return {"economic_score":np.nan,"worst_cut_robust_excess":np.nan,"positive_cut_share":0.0,"winner_lift":np.nan,"mean_rank_ic":np.nan}
    cuts=[]
    for q in [float(v) for v in cfg.p["evaluation_cutoffs"]]:
        s=z[z.score>=1-q]
        if len(s):
            d=s.groupby("signal_date",observed=True)[[f"excess_spy_{h}d",f"excess_qqq_{h}d",f"excess_uew_{h}d"]].mean(); cuts.append(min(float(d[c].mean()) for c in d.columns))
    ics=[]
    for _,g in z.groupby("signal_date",observed=True):
        if len(g)>=20 and g.score.nunique()>1: ics.append(g.score.corr(g._alpha_rank))
    top=z[z.score>=.90]; base=float((z._alpha_rank>=.90).mean()); hit=float((top._alpha_rank>=.90).mean()) if len(top) else np.nan
    return {"economic_score":float(np.mean(cuts)) if cuts else np.nan,"worst_cut_robust_excess":float(np.min(cuts)) if cuts else np.nan,"positive_cut_share":float(np.mean(np.array(cuts)>0)) if cuts else 0.0,"winner_lift":float(hit/base) if np.isfinite(hit) and base>0 else np.nan,"mean_rank_ic":float(np.nanmean(ics)) if ics else np.nan}

def expert_weights(prior:pd.DataFrame,cfg:Cfg)->dict[str,float]:
    if prior.empty:
        # Preserve the strong base predictor while allowing genuinely new information to contribute immediately.
        w={e:.12 for e in META_EXPERTS}; w["BASE_OOF"]=.40; s=sum(w.values()); return {k:v/s for k,v in w.items()}
    a=prior.groupby("expert",as_index=False).agg(econ=("economic_score","mean"),worst=("worst_cut_robust_excess","min"),winner=("winner_lift","mean"),ic=("mean_rank_ic","mean")).set_index("expert").reindex(META_EXPERTS)
    skill=.55*_rz(a.econ)+.20*_rz(a.worst)+.15*_rz(a.winner)+.10*_rz(a.ic); q=np.asarray(skill,float)/max(float(cfg.p["expert_weight_temperature"]),1e-6); q-=np.nanmax(q); w=np.exp(np.nan_to_num(q,nan=-5)); w/=w.sum(); floor=float(cfg.p["expert_weight_floor"]); w=np.maximum(w,floor); w/=w.sum(); return {e:float(v) for e,v in zip(META_EXPERTS,w)}

def blend(sf:pd.DataFrame,w:dict[str,float])->np.ndarray:
    a=np.column_stack([sf[e].to_numpy(float) for e in META_EXPERTS]); ww=np.array([w[e] for e in META_EXPERTS]); ok=np.isfinite(a); den=(ok*ww).sum(1); num=np.nansum(a*ww,axis=1); return np.divide(num,den,out=np.full(len(a),np.nan),where=den>0)

def run_horizon(df:pd.DataFrame,h:int,cfg:Cfg,candidates:list[str]):
    prior=[]; evrows=[]; oof=[]; wrows=[]; selrows=[]
    # First fold is base OOF only; it supplies causal training rows to the first new-info meta prediction.
    first=FOLDS[0][0]; base0=df[df.fold.eq(first)].copy(); base0=base0[base0[f"target_resolved_{h}d"]&base0[f"target_end_date_{h}d"].notna()&(base0[f"target_end_date_{h}d"]<pd.Timestamp(FOLDS[0][2]))]
    if len(base0):
        s=daily_rank(base0,base0.base_score); o=base0[["signal_date","ticker"]].copy(); o["horizon_sessions"]=h; o["fold"]=first; o["score"]=s; oof.append(o)
    for fold,ts,te in FOLDS[1:]:
        tr,va=meta_train_test(df,h,fold)
        if len(tr)<5000 or len(va)<1000: raise RuntimeError(f"Insufficient meta rows h={h} {fold}: {len(tr)}/{len(va)}")
        cols=select_features(tr,candidates,cfg); selrows.extend([{"horizon_sessions":h,"fold":fold,"feature":c} for c in cols])
        pred=fit_meta_experts(tr,va,cols,cfg); sf=va[["signal_date","ticker"]].copy(); foldrows=[]
        for e,r in pred.items():
            s=daily_rank(va,r); sf[e]=s; z=evaluate(va,s,h,cfg); row={"horizon_sessions":h,"fold":fold,"expert":e,**z}; evrows.append(row); foldrows.append(row)
        w=expert_weights(pd.DataFrame(prior),cfg); wrows.extend([{"horizon_sessions":h,"fold":fold,"expert":e,"weight":v} for e,v in w.items()]); sc=daily_rank(va,blend(sf,w)); z=evaluate(va,sc,h,cfg)
        out=va[["signal_date","ticker"]].copy(); out["horizon_sessions"]=h; out["fold"]=fold; out["score"]=sc; oof.append(out); evrows.append({"horizon_sessions":h,"fold":fold,"expert":"META_BLEND",**z}); prior.extend(foldrows)
    return pd.DataFrame(evrows),pd.concat(oof,ignore_index=True),pd.DataFrame(wrows),pd.DataFrame(selrows)

def build_phase2u(workspace:Path)->dict:
    cfg=load_cfg(workspace); p1,source=load_contracts(workspace); scores,targets,features=load_inputs(workspace,cfg); market=load_market(source,cfg)
    out=workspace/"outputs"; out.mkdir(parents=True,exist_ok=True); cp=out/"v13_phase2u_newinfo_surface.parquet"; sa=out/"v13_phase2u_rotation_source_audit.csv"; ea=out/"v13_phase2u_event_source_audit.csv"
    use_cache=False
    if cp.exists() and sa.exists() and ea.exists():
        try:
            info=pd.read_parquet(cp); info["signal_date"]=_date(info["signal_date"]); info["ticker"]=_ticker(info["ticker"]); source_audit=pd.read_csv(sa); event_audit=pd.read_csv(ea)
            use_cache=bool(len(info)>1000 and info.signal_date.max()<pd.Timestamp(cfg.p["holdout_start"]) and {"earn_surprise_composite","sector_implied_mom_20"}.issubset(info.columns))
        except Exception: use_cache=False
    if not use_cache:
        info,source_audit,event_audit=build_newinfo_surface(workspace,source,scores,features,market,cfg); info.to_parquet(cp,index=False); source_audit.to_csv(sa,index=False); event_audit.to_csv(ea,index=False)
    evall=[]; oofall=[]; wall=[]; sall=[]; base_compare=[]
    info_cols=[c for c in info.columns if c not in {"signal_date","ticker"}]; candidates=["base_score"]+info_cols
    for h in HORIZONS:
        print(f"Phase2U horizon {h}D ...",flush=True); d=horizon_frame(scores,targets,info,h); ev,o,w,s=run_horizon(d,h,cfg,candidates); evall.append(ev); oofall.append(o); wall.append(w); sall.append(s)
        for fold in ["WF_2019_2020","WF_2021_2022","WF_2023_2024"]:
            va=d[d.fold.eq(fold)&d[f"target_resolved_{h}d"]&d[f"target_end_date_{h}d"].notna()].copy(); meta=o[(o.horizon_sessions.eq(h))&(o.fold.eq(fold))]
            va=va.merge(meta[["signal_date","ticker","score"]],on=["signal_date","ticker"],how="inner",validate="one_to_one"); b=evaluate(va,daily_rank(va,va.base_score),h,cfg); m=evaluate(va,va.score.to_numpy(float),h,cfg); base_compare.append({"horizon_sessions":h,"fold":fold,"base_economic_score":b["economic_score"],"newinfo_economic_score":m["economic_score"],"incremental_economic_score":m["economic_score"]-b["economic_score"]})
    evidence=pd.concat(evall,ignore_index=True); oof=pd.concat(oofall,ignore_index=True); weights=pd.concat(wall,ignore_index=True); selected=pd.concat(sall,ignore_index=True); comp=pd.DataFrame(base_compare)
    meta=evidence[evidence.expert.eq("META_BLEND")].copy(); byh=meta.groupby("horizon_sessions",as_index=False).agg(economic_score=("economic_score","mean"),worst_fold=("economic_score","min"),worst_cut=("worst_cut_robust_excess","min"),positive_cut_share=("positive_cut_share","mean"),winner_lift=("winner_lift","mean"),mean_ic=("mean_rank_ic","mean")); r21=meta[meta.fold.eq("WF_2021_2022")]; r23=meta[meta.fold.eq("WF_2023_2024")]; c21=comp[comp.fold.eq("WF_2021_2022")]
    rows=[]
    def add(t,ok,val,rule,blocking=True): rows.append({"test":t,"status":"PASS" if ok else "FAIL","blocking":blocking,"value":val,"rule":rule})
    hold=pd.Timestamp(cfg.p["holdout_start"]); maxd=max(scores.signal_date.max(),targets.signal_date.max(),features.signal_date.max(),info.signal_date.max()); add("FINAL_HOLDOUT_NOT_LOADED",maxd<hold,str(maxd.date()),"all loaded research dates < 2025-01-01")
    src_ok=bool((source_audit.rows>=int(cfg.p["minimum_source_rows"])).all()); add("ROTATION_SOURCES_READY",src_ok,source_audit[["symbol","rows","last_date"]].to_dict(orient="records"),"all sector/rates/commodity sources have adequate pre-2025 history")
    event_ok=bool(float(event_audit.loc[event_audit.metric.eq("event_rows"),"value"].iloc[0])>1000 if (event_audit.metric.eq("event_rows")).any() else False); add("PIT_EARNINGS_EVENTS_READY",event_ok,event_audit.to_dict(orient="records"),"SEC filing event surface has material historical breadth")
    add("ALL_SIX_HORIZONS_RETAINED",sorted(byh.horizon_sessions.astype(int).tolist())==list(HORIZONS),byh.horizon_sessions.astype(int).tolist(),str(list(HORIZONS)))
    add("PRE2025_NEWINFO_ALPHA",int((byh.economic_score>0).sum())>=4 and float(byh.economic_score.median())>0,{"positive_horizons":int((byh.economic_score>0).sum()),"median_economic_score":float(byh.economic_score.median())},">=4/6 positive and median >0")
    add("2021_2022_NEWINFO_RECOVERY",int((r21.economic_score>0).sum())>=3 and float(r21.economic_score.median())>0,{"positive_horizons":int((r21.economic_score>0).sum()),"median_economic_score":float(r21.economic_score.median())},">=3/6 positive and median >0")
    add("2023_2024_NEWINFO_CONFIRMATION",int((r23.economic_score>0).sum())>=3 and float(r23.economic_score.median())>0,{"positive_horizons":int((r23.economic_score>0).sum()),"median_economic_score":float(r23.economic_score.median())},">=3/6 positive and median >0")
    add("NEW_INFORMATION_INCREMENTAL_2021_2022",int((c21.incremental_economic_score>0).sum())>=4 and float(c21.incremental_economic_score.median())>0,{"improved_horizons":int((c21.incremental_economic_score>0).sum()),"median_incremental_score":float(c21.incremental_economic_score.median())},"new event/sector information improves >=4/6 horizons and median improvement >0")
    gate=pd.DataFrame(rows); status="PASS" if not ((gate.blocking)&gate.status.eq("FAIL")).any() else "FAIL"
    evidence.to_csv(out/"v13_phase2u_expert_evidence.csv",index=False); byh.to_csv(out/"v13_phase2u_horizon_summary.csv",index=False); r21.to_csv(out/"v13_phase2u_2021_2022_evidence.csv",index=False); r23.to_csv(out/"v13_phase2u_2023_2024_evidence.csv",index=False); comp.to_csv(out/"v13_phase2u_incremental_vs_base.csv",index=False); weights.to_csv(out/"v13_phase2u_nested_expert_weights.csv",index=False); selected.to_csv(out/"v13_phase2u_selected_features.csv",index=False); oof.to_parquet(out/"v13_phase2u_oof_scores.parquet",index=False); gate.to_csv(out/"v13_phase2u_gate.csv",index=False)
    summary={"status":status,"phase":"V13-P2U","build":BUILD,"name":cfg.p["name"],"objective":cfg.p["objective"],"research_contract":{"research":"pre-2025 OOF stacking only","holdout_start":cfg.p["holdout_start"],"holdout_used":False,"portfolio_run":False},"new_information":{"earnings_events":"SEC filing-date PIT surprise/growth/recency/post-event reaction","rotation":"sector ETFs + rates/inflation/commodity ETFs with stock-specific rolling sector betas","base_predictor":"Phase2R OOF score; no base-model retraining","newinfo_cache_reused":bool(use_cache)},"horizon_summary":byh.to_dict(orient="records"),"regime_2021_2022":r21.to_dict(orient="records"),"recent_2023_2024":r23.to_dict(orient="records"),"incremental_vs_base":comp.to_dict(orient="records"),"gate":gate.to_dict(orient="records"),"readiness":"READY_FOR_ONE_CACHED_PORTFOLIO_BLOCK" if status=="PASS" else "NEW_INFORMATION_DID_NOT_RECOVER_ALPHA","next":"If PASS, build one cached portfolio block from v13_phase2u_oof_scores. If FAIL, stop adding architecture and decide whether to source true analyst-estimate/revision data before opening 2025+."}
    (out/"v13_phase2u_summary.json").write_text(json.dumps(summary,indent=2,default=str),encoding="utf-8"); return summary
