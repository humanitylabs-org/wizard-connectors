"""Explicit FAKE provider browser fixture. Never included in runtime image.
Only loopback ephemeral test servers; real production handlers/store/verifier.
"""
import os
import sys
import threading
import tempfile
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from http.server import ThreadingHTTPServer
from cryptography.fernet import Fernet
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from test_google_http import FakeGoogle
from google_broker import Broker
from service_rpc import RPC
from services import service
with tempfile.TemporaryDirectory() as tmp:
    env=dict(l.split('=',1) for l in Path(os.environ['QA_ENV']).read_text().splitlines() if '=' in l)
    os.environ.update(env,DATA_DIR=tmp+'/ui',PORT='0',BROKER_TOKEN='f'*40,BIND_HOST='127.0.0.1')
    b=Broker({'BROKER_DATA_DIR':tmp+'/broker','GOOGLE_STORE_KEY':Fernet.generate_key().decode(),
              'GOOGLE_REVIEW_APPROVED':'true','GOOGLE_CLIENT_ID':'fixture-client','GOOGLE_CLIENT_SECRET':'FAKE_CLIENT_SECRET',
              'GOOGLE_REDIRECT_URI':'http://127.0.0.1:19476/api/google/callback'},FakeGoogle())
    original=b.start
    def start(**args):
        result=original(**args);q=parse_qs(urlsplit(result['authorization_url']).query)
        b.provider.nonce=q['nonce'][0];b.provider.scopes=set(q['scope'][0].split());return result
    b.start=start
    s=service('google',b);threading.Thread(target=s.serve_forever,daemon=True).start()
    import server
    server.broker=RPC('127.0.0.1',s.server_port,'f'*40)
    try:ThreadingHTTPServer(('127.0.0.1',19475),server.Handler).serve_forever()
    finally:s.shutdown();s.server_close()
