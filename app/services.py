"""One image, two non-public service roles. Only fixed typed RPC operations."""
import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from google_broker import Broker, Denied
from private_model import PrivateModel, Blocked
from chat import snapshot
from music_adapter import MusicAdapter

class ServiceHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send(self, status, data):
        body=json.dumps(data).encode(); self.send_response(status)
        self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        token=self.headers.get('Authorization','').removeprefix('Bearer ')
        if self.path!='/rpc' or not hmac.compare_digest(token,self.server.token): return self.send(401,{'error':'service_auth_required'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=8192: raise ValueError()
            data=json.loads(self.rfile.read(size))
            if set(data)!={'operation','args'} or not isinstance(data['args'],dict): raise ValueError()
            if data['operation'] not in self.server.operations: raise Denied('operation_denied')
            result=self.server.operations[data['operation']](**data['args'])
            return self.send(200,result)
        except (Denied,Blocked) as e: return self.send(409,{'error':str(e)})
        except (ValueError,KeyError,TypeError): return self.send(400,{'error':'invalid_request'})
        except OSError: return self.send(503,{'error':'local_storage_unavailable'})
        except Exception: return self.send(503,{'error':'service_unavailable'})

def service(role, broker=None):
    if role=='google':
        b=broker or Broker(dict(os.environ)); music=MusicAdapter(); mutex=threading.Lock()
        def probe(video_id):
            if not mutex.acquire(blocking=False): raise Denied('worker_busy')
            try: return music.probe(video_id)
            finally: mutex.release()
        operations={'status':b.status,'start':b.start,'finish':b.finish,'bind':b.bind,'unlink':b.unlink,
                    'disconnect':b.disconnect,'catalog':b.catalog,'audio_probe':probe}
        port,token=8800,os.environ.get('BROKER_TOKEN','')
    elif role=='private':
        model=PrivateModel(os.environ.get('TINFOIL_API_KEY','')); mutex=threading.Lock()
        def summarize(thread):
            if not mutex.acquire(blocking=False): raise Blocked('worker_busy')
            try:
                text=model.summarize(snapshot(thread))
                return {'text':text,'attestation':model.last_attestation}
            finally: mutex.release()
        operations={'summarize':summarize}; port,token=8801,os.environ.get('PRIVATE_WORKER_TOKEN','')
    else: raise RuntimeError('unknown_service_role')
    if len(token)<32: raise RuntimeError('service_token_required')
    s=ThreadingHTTPServer((os.environ.get('BIND_HOST','127.0.0.1'),int(os.environ.get('PORT',port))),ServiceHandler)
    s.token=token; s.operations=operations
    return s

if __name__=='__main__': service(os.environ['SERVICE_ROLE']).serve_forever()
