"""Worker-local preview transport, not an App Manager registration.
Supply the reviewed shared core directory. It is never bundled into app source.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--env-file',required=True);p.add_argument('--data-dir',required=True);p.add_argument('--core-dir',required=True);p.add_argument('--port',type=int,default=19471);p.add_argument('--backend-port',type=int,default=19470);a=p.parse_args()
env=dict(os.environ)
env.update(dict(l.split('=',1) for l in Path(a.env_file).read_text().splitlines() if '=' in l))
env.update(DATA_DIR=a.data_dir,PORT=str(a.backend_port),PYTHONDONTWRITEBYTECODE='1')
proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1]/'app/server.py')],env=env)
class Proxy(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def relay(self):
        if self.path.startswith('/wizard-os-home/core/'):
            name=self.path.removeprefix('/wizard-os-home/core/')
            if '/' in name or '..' in name or not name.endswith('.js'):
                self.send_error(404);return
            file=Path(a.core_dir)/name
            if not file.is_file():self.send_error(404);return
            b=file.read_bytes();self.send_response(200);self.send_header('Content-Type','text/javascript');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        size=int(self.headers.get('Content-Length','0'))
        if size>8192:self.send_error(413);return
        data=self.rfile.read(size) if size else None
        headers={k:v for k,v in self.headers.items() if k.lower() not in ('host','connection','accept-encoding')}
        # Preserve the browser origin via Host; never inject owner authorization.
        headers['Host']=self.headers.get('Host')
        req=urllib.request.Request('http://127.0.0.1:'+str(a.backend_port)+self.path,data=data,headers=headers,method=self.command)
        try:r=urllib.request.urlopen(req,timeout=120)
        except urllib.error.HTTPError as e:r=e
        except Exception:self.send_error(502);return
        with r:
            b=r.read();self.send_response(r.status)
            for k,v in r.headers.items():
                if k.lower() not in ('server','date','connection','transfer-encoding','content-length'):self.send_header(k,v)
            self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    do_GET=relay
    do_POST=relay
try:ThreadingHTTPServer(('127.0.0.1',a.port),Proxy).serve_forever()
finally:proc.terminate();proc.wait(timeout=10)
