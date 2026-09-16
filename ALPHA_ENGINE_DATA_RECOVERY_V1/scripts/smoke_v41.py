from __future__ import annotations
import json, math, time, zipfile
from urllib.request import urlopen
BASE='http://127.0.0.1:8765'
XLSX=r'C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION\PRODUCT\AlphaEngine_Cartera_Real.xlsx'

def get(path, timeout=40):
    with urlopen(BASE+path, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))
last=None
for _ in range(45):
    try:
        h=get('/api/v4/health',5)
        s=get('/api/v4/summary',20)
        m=get('/api/v4/market',30)
        pulse=get('/api/v4/pulse',40)
        f=get('/api/v4/fundamentals',20)
        v=get('/api/v4/v13',20)
        j=get('/api/v4/forward/job',30)
        p=get('/api/v4/portfolio',40)
        perf=get('/api/v4/performance',20)
        assert h['status']=='PASS' and h['version']=='V4.1'
        assert len(m['rows'])==200, len(m['rows'])
        valid=[r for r in m['rows'] if r.get('ticker') and isinstance(r.get('price'),(int,float)) and math.isfinite(r['price']) and isinstance(r.get('var_1d'),(int,float))]
        assert len(valid)>=190, len(valid)
        nke=next(r for r in m['rows'] if r.get('ticker')=='NKE')
        assert nke['price']>0
        assert len(pulse['rows'])==6
        assert sum(r.get('status')=='PASS' and isinstance(r.get('price'),(int,float)) for r in pulse['rows'])>=4
        assert len(f['rows'])==187, len(f['rows'])
        assert v['status']=='PASS'
        assert v['real_orders_sent'] is False
        assert v['tuning_performed'] is False
        assert j['status'] in {'IDLE','RUNNING','PASS','FAIL'}
        assert p['status']=='PASS' and p['authority']=='MANUAL_LEDGER_V4'
        assert len(perf.get('oos_20bps') or [])>=300
        with zipfile.ZipFile(XLSX) as z:
            wb=z.read('xl/workbook.xml').decode('utf-8')
            for name in ['Operaciones','Posiciones','Resumen','Mercado','Fundamentales','Forward']:
                assert f'name="{name}"' in wb, name
        last=None
        break
    except Exception as exc:
        last=exc
        time.sleep(.8)
if last:
    raise SystemExit(f'V4_1_SMOKE_FAILED: {last}')
print('WEB VERSION         V4.1')
print('MARKET VALUES       PASS >=190/200')
print('MARKET PULSE        PASS')
print('FUNDAMENTALS        187/187')
print('FORWARD ENGINE      READY')
print('MANUAL LEDGER       PASS')
print('EXCEL MIRROR        6 SHEETS PASS')
print('OOS INTERACTIVE     READY')
print('V13 MUTATED         NO')
