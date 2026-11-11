"""Human API and content-free MCP. Provider credentials live in a separate broker."""
import hashlib
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
from grants import calendar_caller
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
OWNER = os.environ.get("CONNECTORS_OWNER_TOKEN", "")
MCP = os.environ.get("CONNECTORS_MCP_TOKEN", "")
MUSIC = os.environ.get('MUSIC_ADAPTER_TOKEN','')
LOCAL_HOSTS = {'localhost', '127.0.0.1', 'wizard-connectors', 'wizard-connectors-calendar'}
HOSTS = {s.split(":")[0] for s in os.environ.get("WIZARD_TRUSTED_HOSTS", "").split(",") if s} | LOCAL_HOSTS
ORIGINS = {s.rstrip("/") for s in os.environ.get("WIZARD_TRUSTED_ORIGINS", "").split(",") if s}
model = RemotePrivateModel() if os.environ.get('PRIVATE_WORKER_TOKEN') else PrivateModel(os.environ.get("TINFOIL_API_KEY", ""))
jobs = Jobs(model, os.environ.get("DATA_DIR", "/data"))
sessions = {}
broker = RPC('google-broker', 8800, os.environ.get('BROKER_TOKEN',''))
media = RPC('media-worker', 8802, os.environ.get('MEDIA_WORKER_TOKEN',''))

def google_status():
    try: return broker.call('status')
    except Denied:
        return {'state':'unavailable','accounts':[],'grants':[],'bindings':[],
                'blocker':'broker_unavailable','music':{'state':'unbound','playback':'separate_existing_app'}}

CALLBACK_REASONS = {
    'consent_denied': 'You cancelled on Google’s screen, so nothing was connected. That’s fine: tap Connect again whenever you’re ready.',
    'invalid_oauth_state': 'This sign-in link was already used, is more than a day old, or was started before Connected accounts was updated. Tap Connect again for a fresh one.',
    'scope_consent_required': 'Google didn’t pass on Calendar access. Tap Connect again and leave “See your calendars” ticked on Google’s screen.',
    'reauth_required': 'Google didn’t confirm this sign-in. Tap Connect again; if it happens twice, tell your wizard.',
    '_': 'Something went wrong while finishing the sign-in. Tap Connect again; if it happens twice, tell your wizard.',
}

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
        if host not in HOSTS or not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?', self.headers.get('Host', '')):
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

    def callback_guess(self):
        # Same-host HTTPS by default, or a configured trusted origin; never a forwarded host.
        origin = next(iter(sorted(o for o in ORIGINS if o.startswith('https://'))), '')
        request_origin = 'https://' + self.headers.get('Host', '')
        if request_origin in ORIGINS: origin = request_origin
        if not origin:
            host = self.headers.get('Host', 'localhost')
            origin = ('http://' if host.split(':')[0] in ('localhost', '127.0.0.1') else 'https://') + host
        prefix = self.headers.get('X-Forwarded-Prefix', '/connected-accounts').rstrip('/')
        if not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)*', prefix): prefix = '/connected-accounts'
        return origin + prefix + '/api/google/callback'

    def calendar_service(self, path, data=None):
        if not calendar_caller(self.headers): return self.send(403, {'error':'calendar_grant_required'})
        try:
            if path == '/service/calendar/status' and self.command == 'GET':
                return self.send(200, broker.call('calendar_status'))
            if path == '/service/calendar/calendars' and self.command == 'POST' and data == {}:
                return self.send(200, broker.call('calendar_calendars'))
            if path == '/service/calendar/events' and self.command == 'POST' and set(data) == {'account','calendar_id','time_min','time_max'}:
                return self.send(200, broker.call('calendar_events', **data))
            return self.send(400, {'error':'invalid_operation'})
        except Denied as e: return self.send(409, {'error':str(e)})

    def do_DELETE(self):
        if not self.trusted(): return
        if not self.human(): return self.send(401, {'error':'owner_auth_required'})
        if urlsplit(self.path).path != '/api/google/client': return self.send(404, {'error':'not_found'})
        try: return self.send(200, broker.call('clear_client'))
        except Denied as e: return self.send(409, {'error':str(e)})

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/service/calendar/'):
            return self.calendar_service(path)
        if not self.trusted(callback=path in ('/api/google/callback','/privacy')): return
        if path == '/privacy':
            return self.send(200,(ROOT/'web/privacy.html').read_bytes(),'text/html; charset=utf-8')
        if path == '/api/google/callback':
            # Google redirects use a separate Lax CSRF cookie, never the Strict owner session.
            try:
                q=parse_qs(urlsplit(self.path).query, max_num_fields=12)
                if any(len(v)!=1 for v in q.values()): raise ValueError()
                cookies=SimpleCookie(); cookies.load(self.headers.get('Cookie',''))
                binding=cookies.get('connectors_oauth')
                broker.call('finish', state=q.get('state',[''])[0],browser=binding.value if binding else '',
                            code=q.get('code',[None])[0],error=q.get('error',[None])[0])
            except (Denied,ValueError) as e:
                reason=str(e) if isinstance(e,Denied) else 'invalid_callback'
                # Reason code only: never the state, code or cookie.
                ref=hashlib.sha256(q.get('state',[''])[0].encode()).hexdigest()[:8] if q.get('state') else '-'
                print(f'google_callback_denied reason={reason} sign_in={ref}',file=sys.stderr,flush=True)
                body=(ROOT/'web/google-error.html').read_text().replace('{{REASON}}',CALLBACK_REASONS.get(reason,CALLBACK_REASONS['_']))
                # Keep the browser binding: another sign-in window from this browser may still be open.
                return self.send(400,body.encode(),'text/html; charset=utf-8')
            return self.send(200,(ROOT/'web/google-connected.html').read_bytes(),'text/html; charset=utf-8',cookie='connectors_oauth=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0')
        if path == "/healthz":
            return self.send(200, {"ok": True, "app": "wizard-connectors", "synthetic_only": True})
        static = {"/": "index.html", "/app.js":"app.js", "/boot.js":"boot.js", "/styles.css":"styles.css", "/wizard-ui.css":"wizard-ui.css", "/google-callback.js":"google-callback.js"}
        if path in static:
            p = ROOT / "web" / static[path]
            return self.send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "text/plain")
        if not self.human(): return self.send(401, {"error":"owner_auth_required"})
        try:
            if path == "/api/state":
                return self.send(200, {"google":{**google_status(), 'suggested_redirect_uri':self.callback_guess()}, "synthetic_only":True,
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
        path = urlsplit(self.path).path
        is_calendar = path.startswith('/service/calendar/')
        if is_calendar:
            if not calendar_caller(self.headers): return self.send(403, {'error':'calendar_grant_required'})
        elif path == '/api/google/setup/intake':
            # Direct internal service/loopback only; ingress rejects public/proxied requests.
            if (self.headers.get('Host', '').split(':')[0] not in ('wizard-connectors','127.0.0.1','localhost')
                or any(k.lower().startswith(('x-forwarded-', 'tailscale-')) or k.lower() in ('forwarded','via','origin','cookie') for k in self.headers)):
                return self.send(403, {'error':'internal_intake_required'})
        elif not self.trusted(): return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 8192: raise ValueError()
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415,{"error":"json_required"})
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict): raise ValueError()
        except Exception:
            return self.send(400, {"error":"invalid_request"})
        if is_calendar: return self.calendar_service(path, data)
        if path == '/api/google/setup/intake':
            if set(data) != {'client_id','client_secret'}: return self.send(400, {'error':'invalid_request'})
            try:
                value = broker.call('setup_deposit', token=self.headers.get('Authorization','').removeprefix('Bearer '), **data)
                return self.send(200, value)
            except Denied as e:
                return self.send(403 if str(e) == 'invalid_setup_token' else 400, {'error': str(e)})
            except OSError: return self.send(503, {'error':'local_storage_unavailable'})
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
        if path == '/service/music/catalog':
            token=self.headers.get('Authorization','').removeprefix('Bearer ')
            if not MUSIC or not hmac.compare_digest(token,MUSIC): return self.send(401,{'error':'music_service_auth_required'})
            if set(data)!={'video_id'}: return self.send(400,{'error':'invalid_operation'})
            try: return self.send(200,broker.call('music_catalog',video_id=data['video_id']))
            except Denied as e: return self.send(409,{'error':str(e)})
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
            if path == '/api/google/agreements':
                if set(data) != {'agreements', 'version', 'country'}: raise ValueError()
                return self.send(200,broker.call('save_agreements', **data))
            if path == '/api/google/client' and set(data) == {'client_id','client_secret','redirect_uri'}:
                return self.send(200,broker.call('save_client',**data))
            if path in ('/api/google/connect','/api/google/reconnect') and set(data) <= {'account','youtube','calendar'}:
                if any(k in data and type(data[k]) is not bool for k in ('youtube','calendar')): raise ValueError()
                if data.get('account') is not None and not isinstance(data['account'],str): raise ValueError()
                # Reuse this browser's binding so overlapping sign-in windows all stay valid;
                # a fresh value per tap would orphan any window opened earlier.
                jar=SimpleCookie();jar.load(self.headers.get('Cookie',''))
                prior=jar.get('connectors_oauth')
                browser=prior.value if prior and re.fullmatch(r'[A-Za-z0-9_-]{43}',prior.value) else secrets.token_urlsafe(32)
                value=broker.call('start', browser=browser,account=data.get('account'),youtube=data.get('youtube',False),calendar=data.get('calendar',False))
                started=parse_qs(urlsplit(value['authorization_url']).query).get('state',[''])[0]
                print(f'google_sign_in_started sign_in={hashlib.sha256(started.encode()).hexdigest()[:8]}',file=sys.stderr,flush=True)
                secure='; Secure' if any(o.startswith('https:') for o in ORIGINS) else ''
                return self.send(200,value,cookie=f'connectors_oauth={browser}; HttpOnly; SameSite=Lax; Path=/; Max-Age=86400{secure}')
            operations={'/api/calendar/bind':('calendar_bind',{'account','consent'}),'/api/music/bind':('bind',{'account','consent'}),'/api/music/unlink':('unlink',set()),
                        '/api/google/disconnect':('disconnect',{'account'}),'/api/music/catalog':('catalog',{'account','video_id'}),
                        '/api/music/audio-probe':('audio_probe',{'video_id'})}
            if path in operations:
                operation,keys=operations[path]
                if set(data)!=keys: raise ValueError()
                target = media if operation == 'audio_probe' else broker
                return self.send(200,target.call(operation,**data))
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
            result = {"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"wizard-connectors","version":"0.2.0"}}
        elif method == "tools/list":
            empty = {"type":"object","properties":{},"additionalProperties":False}
            result = {"tools":[{"name":"connector_status","description":"Content-free connector readiness. No private sources or results.","inputSchema":empty},
                               {"name":"google_app_setup_status","description":"Google app configured flag, exact redirect URI and required APIs/scopes. No credentials.","inputSchema":empty},
                               {"name":"google_app_setup_begin","description":"Owner-authorized Google app setup: mint a single-use internal intake capability, valid 30 minutes. No provider secrets. Reissuing invalidates the previous capability.","inputSchema":empty},
                               {"name":"summary_job_status","description":"Content-free status for an owner-issued job handle.","inputSchema":{"type":"object","properties":{"job_id":{"type":"string"}},"required":["job_id"],"additionalProperties":False}}]}
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments",{})
            if name == "connector_status" and not args:
                content = {"synthetic_only":True,"google":google_status()['state'],"private_enabled":jobs.enabled,"real_data_eligible":False}
            elif name in ('google_app_setup_status', 'google_app_setup_begin') and args == {}:
                try:
                    content = broker.call('setup_status', redirect_uri=self.callback_guess())
                    if name == 'google_app_setup_begin':
                        intake = broker.call('setup_begin', redirect_uri=content['redirect_uri'])
                        content = {'intake_url': 'http://wizard-connectors-calendar:8799/api/google/setup/intake#' + intake['token'],
                                   'expires_in': intake['expires_in'], 'redirect_uri': content['redirect_uri'], 'agreements': content['agreements']}
                except Denied as e: content = {'error': str(e)}
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

# ---- wizard.app-switches/1 ------------------------------------------------------------------------------------------
# Owner feature switches for the Tracker's Try it (wizard-os docs/APP_SWITCHES.md). Shared block: the same text ships in
# every Wizard app (template: wizard-app-manager templates/hello-wizard). Every new feature ships behind a switch, off by
# default: append it to SWITCHES with the issue it delivers, e.g.
#   {'id': 'compact-header', 'name': 'Compact top bar', 'description': '...', 'default': False,
#    'issues': ['humanitylabs-org/<repo>#20']}
# and gate the feature on switch_on('compact-header'). State lives on the box (DATA_DIR/switches.json), so the app's
# page, the Tracker (through the App Manager) and the agent see one state. GET/POST /api/switches, owner only: the
# box's Tailscale Serve owner login with X-Wizard-Switch: 1; never a bearer, agent grant or box-local host.
import json as _sw_json
import os as _sw_os
import re as _sw_re
import threading as _sw_threading
from pathlib import Path as _SwPath
from urllib.parse import urlsplit as _sw_urlsplit

SWITCHES = []
_SW_CONTRACT = 'wizard.app-switches/1'
_SW_ROUTE = _sw_re.compile(r'(?:/[a-z0-9][a-z0-9-]{0,62})?/api/switches/?')
_SW_LOCAL = {'localhost', '127.0.0.1', '::1', '[::1]', '0.0.0.0'}
_sw_lock = _sw_threading.Lock()


def _sw_file():
    return _SwPath(_sw_os.environ.get('WIZARD_SWITCHES_DIR') or _sw_os.environ.get('DATA_DIR') or '/data') / 'switches.json'


def _sw_saved():
    try:
        saved = _sw_json.loads(_sw_file().read_text())
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def switches_doc():
    saved = _sw_saved()
    return {'contract': _SW_CONTRACT, 'switches': [
        dict(s, on=saved[s['id']] if isinstance(saved.get(s['id']), bool) else bool(s.get('default'))) for s in SWITCHES]}


def switch_on(switch_id):
    return next((s['on'] for s in switches_doc()['switches'] if s['id'] == switch_id), False)


def _sw_set(switch_id, on):
    with _sw_lock:
        ids = {s['id'] for s in SWITCHES}
        saved = {k: v for k, v in _sw_saved().items() if k in ids and isinstance(v, bool)}
        saved[switch_id] = on
        f = _sw_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + '.tmp')
        tmp.write_text(_sw_json.dumps(saved))
        _sw_os.replace(tmp, f)
    return switches_doc()


def _sw_owner(h, write):
    hd = h.headers
    if hd.get('Authorization') or hd.get('X-Wizard-Switch') != '1':
        return False
    if (hd.get('Sec-Fetch-Site') or 'same-origin').lower() not in ('same-origin', 'none'):
        return False
    host = (hd.get('Host') or '').strip().lower()
    name = host.split(']')[0] + ']' if host.startswith('[') else host.rsplit(':', 1)[0]
    if not name or name in _SW_LOCAL or '.' not in name:      # box-local and container hosts never prove the owner
        return False
    origin = hd.get('Origin')
    trusted = {o.strip() for o in (_sw_os.environ.get('WIZARD_TRUSTED_ORIGINS') or '').split(',') if o.strip()}
    if origin and _sw_urlsplit(origin).netloc.lower() != host and origin not in trusted:
        return False
    if write and not origin:
        return False
    logins = [x.strip() for x in (hd.get_all('Tailscale-User-Login') or [])]
    owners = {x.strip().lower() for x in (_sw_os.environ.get('WIZARD_OWNER_LOGINS') or '').split(',') if x.strip()}
    return len(logins) == 1 and '@' in logins[0] and (not owners or logins[0].lower() in owners)


def _sw_send(h, code, doc):
    body = _sw_json.dumps(doc).encode()
    h.send_response(code)
    h.send_header('Content-Type', 'application/json')
    h.send_header('Cache-Control', 'no-store')
    h.send_header('Content-Length', str(len(body)))
    h.end_headers()
    if h.command != 'HEAD':
        h.wfile.write(body)


def _sw_handle(h):
    """Serve /api/switches (or /<app>/api/switches) and return True; False for every other request."""
    if not _SW_ROUTE.fullmatch(_sw_urlsplit(h.path).path):
        return False
    if h.command in ('GET', 'HEAD'):
        if not _sw_owner(h, False):
            _sw_send(h, 403, {'error': "Only this Wizard's owner can see these switches.", 'code': 'owner_only'})
        else:
            _sw_send(h, 200, switches_doc())
        return True
    if not _sw_owner(h, True):
        _sw_send(h, 403, {'error': "Only this Wizard's owner can change these switches.", 'code': 'owner_only'})
        return True
    try:
        if (h.headers.get('Content-Type') or '').split(';')[0].strip() != 'application/json':
            raise ValueError
        size = int(h.headers.get('Content-Length') or '0')
        if size <= 0 or size > 4096:
            raise ValueError
        body = _sw_json.loads(h.rfile.read(size))
        if not isinstance(body, dict) or not isinstance(body.get('id'), str) or not isinstance(body.get('on'), bool) \
                or set(body) - {'id', 'on'}:
            raise ValueError
    except (ValueError, TypeError):
        _sw_send(h, 400, {'error': 'Send JSON {"id": "...", "on": true|false}', 'code': 'invalid_input'})
        return True
    if body['id'] not in {s['id'] for s in SWITCHES}:
        _sw_send(h, 404, {'error': 'No such switch', 'code': 'unknown_switch'})
        return True
    try:
        _sw_send(h, 200, _sw_set(body['id'], body['on']))
    except OSError:
        _sw_send(h, 500, {'error': 'storage_failure'})
    return True


def wizard_switches_install(handler_cls):
    """Route the switch endpoint ahead of the app's own GET/HEAD/POST handlers."""
    for method in ('do_GET', 'do_HEAD', 'do_POST'):
        orig = getattr(handler_cls, method, None)
        if getattr(orig, '_wizard_switches', False):
            continue

        def wrapped(self, _orig=orig):
            if _sw_handle(self):
                return None
            if _orig is None:
                return self.send_error(501)
            return _orig(self)
        wrapped._wizard_switches = True
        setattr(handler_cls, method, wrapped)
    return handler_cls
# ---- end wizard.app-switches/1 ---------------------------------------------------------------------------------------

wizard_switches_install(Handler)


if __name__ == "__main__":
    if not OWNER or OWNER == MCP:
        raise SystemExit("Configure distinct human and MCP authentication; startup refused")
    ThreadingHTTPServer((os.environ.get("BIND_HOST","127.0.0.1"),int(os.environ.get("PORT","8799"))),Handler).serve_forever()
