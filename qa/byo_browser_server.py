"""Thales QA ONLY: real ingress/UI/RPC/store, explicitly FAKE Google transport.
Mounted into the proof image, never copied to the production image. Shared
WizardApp resources come from QA_CORE_DIR, not a duplicate app implementation.
"""
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'tests'), str(Path(__file__).resolve().parents[1]/'app')]
from test_google_http import FakeGoogle
from google_broker import Broker
from services import service
from service_rpc import RPC

os.environ.update(DATA_DIR='/tmp/byo-ui-fixture',PORT='0',BIND_HOST='127.0.0.1',BROKER_TOKEN='FAKE_BROKER_TOKEN_'*4,
                  UI_HOST='127.0.0.1',UI_PORT='8888',CONNECTORS_OWNER_TOKEN='FAKE_OWNER_TOKEN_'*4,
                  WIZARD_TRUSTED_ORIGINS='https://owner.example',WIZARD_GRANTS_FILE='/tmp/byo-fixture-grants.json')
import hashlib
import json
Path(os.environ['WIZARD_GRANTS_FILE']).write_text(json.dumps({'outgoing':{},'provider_endpoints':{},'incoming':[{'from':'calendar','sha256':hashlib.sha256(b'FAKE_BROWSER_CALENDAR_GRANT').hexdigest()}],'enforce':True}))

with tempfile.TemporaryDirectory() as tmp:
    broker=Broker({'BROKER_DATA_DIR':tmp,'GOOGLE_STORE_SECRET':'FAKE_BROWSER_STORE_SECRET_'*4},FakeGoogle())
    original=broker.start
    counter=[0]
    def start(**args):
        if args.get('account'):broker.provider.subject=broker.state['accounts'][args['account']]['subject']
        else:
            counter[0]+=1;broker.provider.subject='fixture-subject-'+str(counter[0])
        result=original(**args);q=parse_qs(urlsplit(result['authorization_url']).query)
        broker.provider.nonce=q['nonce'][0];broker.provider.scopes=set(q['scope'][0].split());return result
    broker.start=start
    rpc=service('google',broker)
    threading.Thread(target=rpc.serve_forever,daemon=True).start()
    import server
    server.broker=RPC('127.0.0.1',rpc.server_port,os.environ['BROKER_TOKEN'])
    class UI(server.Handler):
        def do_GET(self):
            name=urlsplit(self.path).path
            if name.startswith('/wizard-os-home/core/'):
                part=name.removeprefix('/wizard-os-home/core/')
                if '/' in part or '..' in part:return self.send(404,{'error':'not_found'})
                path=Path(os.environ['QA_CORE_DIR'])/part
                if not path.is_file():return self.send(404,{'error':'not_found'})
                return self.send(200,path.read_bytes(),'text/javascript' if part.endswith('.js') else 'text/css')
            if name.startswith('/wizard-os-home/kit/'):
                part=name.removeprefix('/wizard-os-home/kit/')
                path=Path(os.environ['QA_KIT_DIR'])/part
                if '/' in part or '..' in part or not path.is_file():return self.send(404,{'error':'not_found'})
                return self.send(200,path.read_bytes(),'text/css')
            if name=='/_qa/host.js':
                return self.send(200,b'window.WizAppServices={connect:(w,c)=>{window.__qaBack=c.back;return null;}};', 'text/javascript')
            if name=='/_qa/host.css':
                # App CSP forbids inline styles, so the mock host's frame sizing is a stylesheet.
                return self.send(200,b'html,body{margin:0;height:100%}iframe{border:0;display:block;width:100%;height:100dvh}','text/css')
            if name=='/_qa/host':
                return self.send(200,b'<!doctype html><html><meta name="viewport" content="width=device-width,initial-scale=1"><title>Explicit mock Appearance host</title><link rel="stylesheet" href="/_qa/host.css"><script src="/_qa/host.js"></script><body><iframe title="Connected accounts QA" src="/"></iframe></body></html>','text/html')
            return super().do_GET()
    ui=ThreadingHTTPServer(('127.0.0.1',8888),UI)
    threading.Thread(target=ui.serve_forever,daemon=True).start()
    import http.client, types, ingress
    # Real ingress relay code; only its fixed upstream host maps to this in-process UI.
    class _Upstream(http.client.HTTPConnection):
        def __init__(self,host,port,**kw):super().__init__('127.0.0.1',8888,**kw)
    ingress.http=types.SimpleNamespace(client=types.SimpleNamespace(HTTPConnection=_Upstream))
    try:ThreadingHTTPServer(('0.0.0.0',8799),ingress.Ingress).serve_forever()
    finally:
        ui.shutdown();ui.server_close();rpc.shutdown();rpc.server_close()
