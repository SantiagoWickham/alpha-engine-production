from __future__ import annotations
import json, time
from urllib.request import urlopen
BASE='http://127.0.0.1:8765'

def get(path, timeout=20):
    with urlopen(BASE+path, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))
last=None
for _ in range(35):
    try:
        h=get('/api/v4/health',5)
        s=get('/api/v4/summary',15)
        m=get('/api/v4/market',20)
        f=get('/api/v4/fundamentals',20)
        v=get('/api/v4/v13',15)
        p=get('/api/v4/portfolio',30)
        perf=get('/api/v4/performance',20)
        assert h['status']=='PASS'
        assert s['status']=='PASS'
        assert s['llm']['status']=='PAUSED'
        assert len(m['rows'])==200, len(m['rows'])
        assert len(f['rows'])==187, len(f['rows'])
        assert v['status']=='PASS'
        assert v['real_orders_sent'] is False
        assert v['tuning_performed'] is False
        assert p['status']=='PASS'
        assert p['authority']=='MANUAL_LEDGER_V4'
        assert p['excel_file'].endswith('AlphaEngine_Cartera_Real.xlsx')
        assert len(perf.get('oos_20bps') or []) >= 300
        last=None
        break
    except Exception as exc:
        last=exc
        time.sleep(.7)
if last:
    raise SystemExit(f'V4_SMOKE_FAILED: {last}')
print('HEALTH             PASS')
print('PRODUCT STATE      PASS')
print('MARKET              200/200')
print('FUNDAMENTALS        187/187')
print('V13 FORWARD READ    PASS')
print('LLM                 PAUSED')
print('MANUAL LEDGER       PASS')
print('EXCEL MIRROR        PASS')
print('OOS INTERACTIVE     READY')
print('V13 MUTATED         NO')
