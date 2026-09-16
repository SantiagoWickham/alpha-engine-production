from __future__ import annotations
import json, time
from urllib.request import Request, urlopen
BASE='http://127.0.0.1:8765'

def get(path, timeout=40):
    with urlopen(BASE+path, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))

def post(path, obj, timeout=40):
    data=json.dumps(obj).encode('utf-8')
    req=Request(BASE+path,data=data,headers={'Content-Type':'application/json'},method='POST')
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))

j=get('/api/v4/forward/job',40)
print(f"  model session : {j.get('current_model_session')}")
print(f"  market session: {j.get('latest_completed_market_session')}")
print(f"  stale         : {j.get('stale')}")
if not j.get('stale'):
    print('  PASS forward already current')
    raise SystemExit(0)

r=post('/api/v4/forward/refresh', {'force': False}, 40)
print(f"  start status  : {r.get('status')}")
deadline=time.time()+1200
last=None
while time.time()<deadline:
    j=get('/api/v4/forward/job',40)
    state=j.get('status')
    if state!=last:
        print(f"  job           : {state}")
        last=state
    if state=='PASS':
        current=j.get('current_model_session') or j.get('after_session')
        target=j.get('latest_completed_market_session')
        print(f"  after         : {current}")
        if target and current and str(current) < str(target):
            raise SystemExit(f"FORWARD_DID_NOT_CATCH_UP current={current} target={target}")
        print('  PASS forward caught up')
        raise SystemExit(0)
    if state=='FAIL':
        print(j.get('error') or 'FORWARD_FAIL')
        print((j.get('stderr_tail') or '')[-5000:])
        raise SystemExit(2)
    time.sleep(3)
raise SystemExit('FORWARD_TIMEOUT_1200S')
