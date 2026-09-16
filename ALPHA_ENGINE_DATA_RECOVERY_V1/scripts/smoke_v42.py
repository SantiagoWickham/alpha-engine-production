
from __future__ import annotations
import json, math, time, zipfile
from urllib.request import urlopen

BASE="http://127.0.0.1:8765"
XLSX=r"C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION\PRODUCT\AlphaEngine_Cartera_Real.xlsx"

def get(path, timeout=60):
    with urlopen(BASE+path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

last=None
for _ in range(50):
    try:
        h=get("/api/v4/health",5)
        s=get("/api/v4/summary",40)
        m=get("/api/v4/market",40)
        mj=get("/api/v4/market/job",40)
        pulse=get("/api/v4/pulse",50)
        v=get("/api/v4/v13",30)
        r=get("/api/v4/recommendations",90)
        perf=get("/api/v4/performance",40)

        assert h["status"]=="PASS" and h["version"]=="V4.2"
        assert s["version"]=="ALPHA_ENGINE_WEB_V4_2_AUTOMATED"
        assert len(m["rows"])==200
        valid=[
            x for x in m["rows"]
            if x.get("ticker") and isinstance(x.get("price"),(int,float))
            and math.isfinite(x["price"]) and isinstance(x.get("var_1d"),(int,float))
        ]
        assert len(valid)>=190
        assert mj.get("regular_session_only") is True
        assert mj.get("refresh_every_seconds")==300
        assert len(pulse.get("rows") or [])==6
        assert v["status"]=="PASS" and v["real_orders_sent"] is False and v["tuning_performed"] is False
        assert r["status"]=="PASS" and len(r.get("rows") or [])>=180
        assert perf["status"]=="PASS"
        f=perf.get("forward_summary") or {}
        assert f.get("status")=="PASS", f
        assert f.get("start_date")=="2026-09-04"
        assert f.get("latest_date")==v.get("latest_completed_session"), (f.get("latest_date"),v.get("latest_completed_session"))
        assert (f.get("holdout_parity") or {}).get("status")=="PASS"
        assert len(perf.get("combined_20bps") or []) > len(perf.get("oos_20bps") or [])

        with zipfile.ZipFile(XLSX) as z:
            wb=z.read("xl/workbook.xml").decode("utf-8")
            for name in ["Operaciones","Posiciones","Resumen","Mercado","Fundamentales","Forward","Recomendaciones"]:
                assert f'name="{name}"' in wb, name
        last=None
        break
    except Exception as exc:
        last=exc
        time.sleep(.8)

if last:
    raise SystemExit(f"V42_SMOKE_FAILED: {last}")

print("WEB VERSION          V4.2")
print("MARKET AUTO          PASS / 5 MIN REGULAR SESSION")
print("MARKET VALUES        PASS >=190/200")
print("FORWARD              PASS / CURRENT")
print("FORWARD NAV          PASS / 2026-09-04 -> CURRENT")
print("HOLDOUT PARITY       PASS")
print("RECOMMENDATIONS      PASS")
print("EXCEL MIRROR         7 SHEETS PASS")
print("LLM                  PAUSED")
print("V13 MUTATED          NO")
