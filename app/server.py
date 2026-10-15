"""Human API and content-free MCP. Provider credentials live in a separate broker."""
import hmac
import json
import mimetypes
import os
import secrets
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from chat import THREADS, snapshot
from jobs import Jobs
from private_model import PrivateModel, Blocked
from service_rpc import RPC, RemotePrivateModel
from google_broker import Denied

ROOT = Path(__file__).resolve().parent.parent
OWNER = os.environ.get("CONNECTORS_OWNER_TOKEN", "")
MCP = os.environ.get("CONNECTORS_MCP_TOKEN", "")
HOSTS = {s.split(":")[0] for s in os.environ.get("WIZARD_TRUSTED_HOSTS", "localhost,127.0.0.1").split(",") if s}
ORIGINS = {s.rstrip("/") for s in os.environ.get("WIZARD_TRUSTED_ORIGINS", "").split(",") if s}
model = RemotePrivateModel() if os.environ.get('PRIVATE_WORKER_TOKEN') else PrivateModel(os.environ.get("TINFOIL_API_KEY", ""))
jobs = Jobs(model, os.environ.get("DATA_DIR", "/data"))
sessions = {}
broker = RPC('google-broker', 8800, os.environ.get('BROKER_TOKEN',''))

def google_status():
    try: return broker.call('status')
    except Denied:
        return {'state':'unavailable','accounts':[],'grants':[],'bindings':[],
                'blocker':'broker_unavailable','music':{'state':'unbound','playback':'separate_existing_app'}}

class Handler(BaseHTTPRequestHandler):
    server_version = "ConnectedAccounts"
    def log_message(self, *args):
        pass # No paths, payloads or provider exceptions in ordinary logs.

    def send(self, status, value, kind="application/json", cookie=None):
        body = json.dumps(value).encode() if kind == "application/json" else value
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def trusted(self, callback=False):
        host = self.headers.get("Host", "").split(":")[0]
        if host not in HOSTS:
            self.send(403, {"error": "host_denied"}); return False
        origin = self.headers.get("Origin")
        allowed = ORIGINS | {"http://" + self.headers.get("Host", ""), "https://" + self.headers.get("Host", "")}
        if origin and origin not in allowed:
            self.send(403, {"error": "origin_denied"}); return False
        if not callback and self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send(403, {"error": "cross_site_denied"}); return False
        return True

    def human(self):
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if OWNER and hmac.compare_digest(token, OWNER):
            return True
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
            sid = cookies.get("connectors_session")
            return bool(sid and sessions.get(sid.value, 0) > time.time())
        except Exception:
            return False

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.trusted(callback=path == '/api/google/callback'): return
        if path == '/api/google/callback':
            # Google redirects use a separate Lax CSRF cookie, never the Strict owner session.
            try:
                q=parse_qs(urlsplit(self.path).query, max_num_fields=12)
                if any(len(v)!=1 for v in q.values()): raise ValueError()
                cookies=SimpleCookie(); cookies.load(self.headers.get('Cookie',''))
                binding=cookies.get('connectors_oauth')
                if not binding: raise Denied('invalid_oauth_state')
                broker.call('finish', state=q.get('state',[''])[0],browser=binding.value,
                            code=q.get('code',[None])[0],error=q.get('error',[None])[0])
                message='Google account connected. Close this tab and refresh Connected accounts.'
                status=200
            except (Denied,ValueError):
                message='Google authorization did not complete. Return to Connected accounts and try again.'
                status=400
            return self.send(status, message.encode(), 'text/plain',cookie='connectors_oauth=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0')
        if path == "/healthz":
            return self.send(200, {"ok": True, "app": "wizard-connectors", "synthetic_only": True})
        static = {"/": "index.html", "/app.js":"app.js", "/boot.js":"boot.js", "/styles.css":"styles.css", "/wizard-ui.css":"wizard-ui.css"}
        if path in static:
            p = ROOT / "web" / static[path]
            return self.send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "text/plain")
        if not self.human(): return self.send(401, {"error":"owner_auth_required"})
        try:
            if path == "/api/state":
                return self.send(200, {"google":google_status(), "synthetic_only":True,
                    "private_route":{"model":"tinfoil/glm-5-3", "enabled":jobs.enabled, "configured":bool(model.key), "fallback":False, "tools":False},
                    "assurance":{"real_data_eligible":False,"host_admin_isolation":False,"network_confinement":os.environ.get('ISOLATED_PACKAGE') == 'true'},
                    "threads":[{"id":k,"title":v["title"],"count":len(v["messages"])} for k,v in THREADS.items()]})
            if path.startswith("/api/conversations/"):
                return self.send(200, snapshot(path.rsplit("/",1)[1]))
            if path.startswith("/api/results/"):
                return self.send(200, jobs.get(path.rsplit("/",1)[1], human=True))
            if path.startswith("/api/jobs/"):
                return self.send(200, jobs.get(path.rsplit("/",1)[1]))
            return self.send(404, {"error":"not_found"})
        except KeyError:
            return self.send(404, {"error":"not_found"})

    def do_POST(self):
        if not self.trusted(): return
        path = urlsplit(self.path).path
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 8192: raise ValueError()
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415,{"error":"json_required"})
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict): raise ValueError()
        except Exception:
            return self.send(400, {"error":"invalid_request"})
        if path == "/api/session":
            token = data.get("token")
            if not OWNER or not isinstance(token,str) or not hmac.compare_digest(token, OWNER):
                return self.send(401,{"error":"owner_auth_required"})
            for k,v in list(sessions.items()):
                if v <= time.time(): sessions.pop(k,None)
            if len(sessions) >= 64:
                return self.send(429,{"error":"session_limit"})
            sid = secrets.token_urlsafe(32)
            sessions[sid] = time.time()+3600
            secure = "; Secure" if any(o.startswith("https:") for o in ORIGINS) else ""
            return self.send(200,{"ok":True}, cookie=f"connectors_session={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600{secure}")
        if path == "/mcp":
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if not MCP or not hmac.compare_digest(token, MCP):
                return self.send(401,{"error":"mcp_auth_required"})
            return self.mcp(data)
        if not self.human(): return self.send(401,{"error":"owner_auth_required"})
        try:
            if path == '/api/session/logout' and not data:
                cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
                if cookies.get('connectors_session'): sessions.pop(cookies['connectors_session'].value,None)
                return self.send(200,{'logged_out':True},cookie='connectors_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if path == "/api/policy" and set(data) == {"enabled"}:
                jobs.policy(data["enabled"])
                return self.send(200,{"enabled":jobs.enabled,"epoch":jobs.epoch})
            if path == "/api/summarize" and set(data) == {"thread","request_id"}:
                return self.send(202,jobs.create(data["thread"],data["request_id"]))
            if path.startswith("/api/cancel/") and not data:
                return self.send(200,jobs.cancel(path.rsplit("/",1)[1]))
            if path in ('/api/google/connect','/api/google/reconnect') and set(data) <= {'account','youtube'}:
                if 'youtube' in data and not isinstance(data['youtube'],bool): raise ValueError()
                browser=secrets.token_urlsafe(32)
                value=broker.call('start', browser=browser,account=data.get('account'),youtube=data.get('youtube',False))
                secure='; Secure' if any(o.startswith('https:') for o in ORIGINS) else ''
                return self.send(200,value,cookie=f'connectors_oauth={browser}; HttpOnly; SameSite=Lax; Path=/; Max-Age=600{secure}')
            operations={'/api/music/bind':('bind',{'account','consent'}),'/api/music/unlink':('unlink',set()),
                        '/api/google/disconnect':('disconnect',{'account'}),'/api/music/catalog':('catalog',{'account','video_id'}),
                        '/api/music/audio-probe':('audio_probe',{'video_id'})}
            if path in operations:
                operation,keys=operations[path]
                if set(data)!=keys: raise ValueError()
                return self.send(200,broker.call(operation,**data))
            return self.send(400,{"error":"unsupported_operation"})
        except (Blocked,Denied) as exc:
            return self.send(409,{"error":str(exc)})
        except OSError:
            return self.send(503,{"error":"local_storage_unavailable"})
        except (ValueError,KeyError,TypeError):
            return self.send(400,{"error":"invalid_request"})

    def mcp(self, request):
        ident, method, params = request.get("id"), request.get("method"), request.get("params",{})
        if method == "initialize":
            result = {"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"wizard-connectors","version":"0.1.0"}}
        elif method == "tools/list":
            result = {"tools":[{"name":"connector_status","description":"Content-free connector readiness. No private sources or results.","inputSchema":{"type":"object","properties":{},"additionalProperties":False}},
                               {"name":"summary_job_status","description":"Content-free status for an owner-issued job handle.","inputSchema":{"type":"object","properties":{"job_id":{"type":"string"}},"required":["job_id"],"additionalProperties":False}}]}
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments",{})
            if name == "connector_status" and not args:
                content = {"synthetic_only":True,"google":google_status()['state'],"private_enabled":jobs.enabled,"real_data_eligible":False}
            elif name == "summary_job_status" and isinstance(args,dict) and set(args) == {"job_id"}:
                try: content = jobs.get(args["job_id"])
                except (KeyError,TypeError): content = {"error":"not_found"}
            else:
                return self.send(200,{"jsonrpc":"2.0","id":ident,"error":{"code":-32601,"message":"operation_denied"}})
            result = {"content":[{"type":"text","text":json.dumps(content)}],"isError":False}
        elif method == "notifications/initialized":
            return self.send(202,{})
        else:
            return self.send(200,{"jsonrpc":"2.0","id":ident,"error":{"code":-32601,"message":"method_not_found"}})
        return self.send(200,{"jsonrpc":"2.0","id":ident,"result":result})

if __name__ == "__main__":
    if not OWNER or OWNER == MCP:
        raise SystemExit("Configure distinct human and MCP authentication; startup refused")
    ThreadingHTTPServer((os.environ.get("BIND_HOST","127.0.0.1"),int(os.environ.get("PORT","8799"))),Handler).serve_forever()
