"""Fixed upstream ingress. No auth injection, cookies/logging, arbitrary URL or credentials."""
import http.client
import os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

HOP={'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade'}
class Ingress(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def relay(self):
        connection=None
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<=size<=8192 or not self.path.startswith('/') or self.path.startswith('//'):
                self.send_error(400);return
            headers={k:v for k,v in self.headers.items() if k.lower() not in HOP}
            connection=http.client.HTTPConnection('wizard-connectors',8799,timeout=110)
            connection.request(self.command,self.path,body=self.rfile.read(size) if size else None,headers=headers)
            response=connection.getresponse();body=response.read(2*1024*1024+1)
            if len(body)>2*1024*1024:raise ValueError()
            self.send_response(response.status)
            for k,v in response.getheaders():
                if k.lower() not in HOP|{'content-length','server','date'}:self.send_header(k,v)
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        except Exception:self.send_error(502)
        finally:
            if connection:connection.close()
    do_GET=relay
    do_POST=relay
    do_DELETE=relay
if __name__=='__main__':ThreadingHTTPServer((os.environ.get('BIND_HOST','0.0.0.0'),8799),Ingress).serve_forever()
