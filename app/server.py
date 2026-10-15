"""Synthetic-only preview. Authenticated human API and content-free MCP.
No Google credential reader, login side effect or broad agent result endpoint.
"""
import hmac
import json
import mimetypes
import os
import secrets
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from chat import THREADS, snapshot
from jobs import Jobs
from private_model import PrivateModel, Blocked

ROOT = Path(__file__).resolve().parent.parent
OWNER = os.environ.get("CONNECTORS_OWNER_TOKEN", "")
MCP = os.environ.get("CONNECTORS_MCP_TOKEN", "")
HOSTS = {s.split(":")[0] for s in os.environ.get("WIZARD_TRUSTED_HOSTS", "localhost,127.0.0.1").split(",") if s}
ORIGINS = {s.rstrip("/") for s in os.environ.get("WIZARD_TRUSTED_ORIGINS", "").split(",") if s}
model = PrivateModel(os.environ.get("TINFOIL_API_KEY", ""))
jobs = Jobs(model, os.environ.get("DATA_DIR", "/data"))
sessions = {}
GOOGLE = {"state": "not_connected", "accounts": [], "grants": [], "bindings": [],
          "blocker": "isolation_review_required", "provider_revocation": "not_applicable",
          "music": {"state": "unbound", "provider": "youtube-music", "playback": "separate_existing_app"}}

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

    def trusted(self):
        host = self.headers.get("Host", "").split(":")[0]
        if host not in HOSTS:
            self.send(403, {"error": "host_denied"}); return False
        origin = self.headers.get("Origin")
        allowed = ORIGINS | {"http://" + self.headers.get("Host", ""), "https://" + self.headers.get("Host", "")}
        if origin and origin not in allowed:
            self.send(403, {"error": "origin_denied"}); return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
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
        if not self.trusted(): return
        path = urlsplit(self.path).path
        if path == "/healthz":
            return self.send(200, {"ok": True, "app": "wizard-connectors", "synthetic_only": True})
        static = {"/": "index.html", "/app.js":"app.js", "/boot.js":"boot.js", "/styles.css":"styles.css", "/wizard-ui.css":"wizard-ui.css"}
        if path in static:
            p = ROOT / "web" / static[path]
            return self.send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "text/plain")
        if not self.human(): return self.send(401, {"error":"owner_auth_required"})
        try:
            if path == "/api/state":
                return self.send(200, {"google":GOOGLE, "synthetic_only":True,
                    "private_route":{"model":"tinfoil/glm-5-3", "enabled":jobs.enabled, "configured":bool(model.key), "fallback":False, "tools":False},
                    "assurance":{"real_data_eligible":False,"host_admin_isolation":False,"network_confinement":False},
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
            if path == "/api/policy" and set(data) == {"enabled"}:
                jobs.policy(data["enabled"])
                return self.send(200,{"enabled":jobs.enabled,"epoch":jobs.epoch})
            if path == "/api/summarize" and set(data) == {"thread","request_id"}:
                return self.send(202,jobs.create(data["thread"],data["request_id"]))
            if path.startswith("/api/cancel/") and not data:
                return self.send(200,jobs.cancel(path.rsplit("/",1)[1]))
            if path in ("/api/google/connect","/api/google/reconnect","/api/music/bind"):
                return self.send(409,{"error":"isolation_review_required", "message":"Google sign-in is disabled pending credential-custody and host-isolation review. No Google credentials were loaded by this app; nothing was sent to Google."})
            if path in ("/api/music/unlink", "/api/google/disconnect"):
                return self.send(409,{"error":"no_connected_account"})
            return self.send(400,{"error":"unsupported_operation"})
        except Blocked as exc:
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
                content = {"synthetic_only":True,"google":"not_connected","private_enabled":jobs.enabled,"real_data_eligible":False}
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
    ThreadingHTTPServer(("0.0.0.0",int(os.environ.get("PORT","8799"))),Handler).serve_forever()
