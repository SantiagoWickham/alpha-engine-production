import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from alpha_engine_v13 import sheets_shadow_bridge as b


def test_env_parser(tmp_path):
    p=tmp_path/'.env';p.write_text('MMM_SHEET_API_URL="https://example.test/exec"\nMMM_SHEET_API_TOKEN=abc123\n',encoding='utf-8')
    d=b._parse_env(p); assert d['MMM_SHEET_API_URL']=='https://example.test/exec'; assert d['MMM_SHEET_API_TOKEN']=='abc123'


def test_alert_mapping():
    c={'asof':'2026-09-11','rows':[{'ticker':'msft','effective_horizon_sessions':60,'model_intent':'ELIGIBLE_ENTRY','expected_active_total':.03,'model_target_weight':.1}]}
    z=b._alert_rows(c); assert z[0]['ticker']=='MSFT'; assert z[0]['action']=='ELIGIBLE_ENTRY'; assert z[0]['model_weight']==.1


def test_contract_payload_digest_stable_and_compact():
    s={'holdout_verdict':'STRONG_CONFIRMATION'}
    rows=[{'ticker':f'T{i:03d}','score_5d':i/1000,'score_10d':i/900,'score_20d':i/800,'score_60d':i/700,'score_120d':i/600,'score_252d':i/500,'blob':'x'*700} for i in range(183)]
    c={'asof':'2026-09-11','input_fingerprint':'x','rows':rows}
    a=b._payload(s,c); bb=b._payload(s,c)
    assert a['contract_digest']==bb['contract_digest']; assert a['seal_id']==b.EXPECTED_SEAL
    assert 'rows' not in a
    assert a['advisor_rows']==183
    assert len(json.dumps(a,separators=(',',':'))) < 50000


def test_safe_url_redacts_token():
    x=b._safe_url('https://example.test/exec?action=health&token=secret'); assert 'secret' not in x and '%2A%2A%2A' in x


def test_local_e2e_bridge(tmp_path, monkeypatch):
    state={'decision':None,'alerts':[]}
    class H(BaseHTTPRequestHandler):
        def log_message(self,*a): pass
        def _send(self,obj):
            raw=json.dumps(obj).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query); a=q.get('action',['health'])[0]
            if q.get('token',[''])[0] != 'tok': return self._send({'ok':False,'error':'UNAUTHORIZED'})
            if a=='health': return self._send({'ok':True,'api_version':'V9.1-FORWARD-CLOUD','model_version':'V10.4_FROZEN','validation_status':'PASS'})
            if a=='positions': return self._send({'ok':True,'headers':['Ticker','Cantidad','Valor Mercado USD Eq.','Peso Actual'],'rows':[['MSFT',1,100,1.0]],'returned':1})
            if a=='cash': return self._send({'ok':True,'headers':['Moneda','Saldo','Actualizado','Fuente'],'rows':[['USD',10,'x','x']], 'returned':1})
            if a=='mandate': return self._send({'ok':True,'headers':['Campo','Valor'],'rows':[['Perfil','Test']], 'returned':1})
            if a=='decision_state':
                rows=[] if state['decision'] is None else [['latest_runtime',json.dumps(state['decision']),'x']]
                return self._send({'ok':True,'headers':['key','json','updated_at'],'rows':rows,'returned':len(rows)})
            if a=='alert_state':
                headers=['ticker','action','severity','signal','event','alpha','alpha_percentile','current_weight','model_weight','updated_at']
                rows=[[r.get(h,'') for h in headers] for r in state['alerts']]
                return self._send({'ok':True,'headers':headers,'rows':rows,'returned':len(rows)})
            return self._send({'ok':False,'error':'UNKNOWN_ACTION'})
        def do_POST(self):
            q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query); a=q.get('action',[''])[0]
            n=int(self.headers.get('Content-Length','0')); body=json.loads(self.rfile.read(n) or b'{}')
            if a=='decision_state_replace':
                raw=json.dumps(body['payload'],separators=(',',':'))
                if len(raw)>50000: return self._send({'ok':False,'error':'API_POST_ERROR','message':'cell > 50000'})
                state['decision']=body['payload']; return self._send({'ok':True,'saved':True})
            if a=='alert_state_replace': state['alerts']=body['rows']; return self._send({'ok':True,'saved_rows':len(state['alerts'])})
            return self._send({'ok':False,'error':'UNKNOWN_POST_ACTION'})
    srv=ThreadingHTTPServer(('127.0.0.1',0),H); th=threading.Thread(target=srv.serve_forever,daemon=True); th.start()
    try:
        os.environ['MMM_SHEET_API_URL']=f'http://127.0.0.1:{srv.server_port}/exec'; os.environ['MMM_SHEET_API_TOKEN']='tok'
        d=tmp_path/'outputs'/'live_shadow'; d.mkdir(parents=True)
        (d/'v13_live_shadow_summary.json').write_text(json.dumps({'status':'PASS','seal_id':b.EXPECTED_SEAL,'shadow_only':True,'real_orders_sent':False,'tuning_performed':False,'holdout_verdict':'STRONG_CONFIRMATION','latest_completed_session':'2026-09-11'}))
        rows=[{'ticker':'MSFT','effective_horizon_sessions':60,'model_intent':'ELIGIBLE_ENTRY','expected_active_total':.03,'model_target_weight':.1}]
        (d/'v13_live_shadow_contract_latest.json').write_text(json.dumps({'seal_id':b.EXPECTED_SEAL,'asof':'2026-09-11','input_fingerprint':'fp','shadow_only':True,'real_orders_sent':False,'rows':rows}))
        out=b.build_sheet_shadow_bridge(tmp_path); assert out['status']=='PASS'; assert out['full_contract_rows_authoritative_local']==1; assert all(out['readback_parity'].values()); assert out['operation_append_called'] is False
    finally:
        srv.shutdown(); srv.server_close(); os.environ.pop('MMM_SHEET_API_URL',None); os.environ.pop('MMM_SHEET_API_TOKEN',None)
