"""Google-only credential custodian. UI/MCP never receive provider credentials.
Network transport has fixed endpoints, no caller URL, no ambient proxies/cookies.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, quote
from datetime import datetime, timedelta
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError
from cryptography.fernet import Fernet
import jwt
import google_agreements as agreements

IDENTITY = frozenset({'openid', 'email'})
YOUTUBE = 'https://www.googleapis.com/auth/youtube.readonly'
CALENDAR = 'https://www.googleapis.com/auth/calendar.readonly'
# Gmail for Mail (wizard-connectors#15, switch `gmail-for-mail`): read, search, label changes and drafts. Sending
# stays the owner's tap in Mail; agents never send (mail_access.py).
GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.modify'
# Drive, Docs, Sheets and Contacts for the agent (wizard-connectors#27, switch `google-workspace`): read-only.
DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
CONTACTS_SCOPE = 'https://www.googleapis.com/auth/contacts.readonly'
WORKSPACE_SCOPES = {'drive': DRIVE_SCOPE, 'contacts': CONTACTS_SCOPE}
# Calendar edits for the agent through the Google app (wizard-connectors#29, switch google-calendar-edits): events only,
# asked per account on the owner's Allow. Who may edit is Calendar > Settings > Agent access, kept by the Google app.
CALENDAR_EDIT_SCOPE = 'https://www.googleapis.com/auth/calendar.events'
SCOPES = IDENTITY | {YOUTUBE, CALENDAR, GMAIL_SCOPE, DRIVE_SCOPE, CONTACTS_SCOPE, CALENDAR_EDIT_SCOPE}
GMAIL_API = 'https://gmail.googleapis.com/gmail/v1/users/me/'
# Fixed read-only hosts for google_workspace.py (GET only).
WORKSPACE_API = ('https://www.googleapis.com/drive/v3/files', 'https://people.googleapis.com/v1/people:searchContacts')
# The one Google Calendar path the Google app may call on an account (calendar_http): a calendar's events, or one event.
CALENDAR_EVENTS_URL = re.compile(r'https://www\.googleapis\.com/calendar/v3/calendars/([A-Za-z0-9._~%@+-]{1,900})/events(?:/([A-Za-z0-9_@.-]{1,1024}))?')
CALENDAR_QUERY = {'sendUpdates': ('all', 'externalOnly', 'none'), 'singleEvents': ('true', 'false'), 'orderBy': ('startTime', 'updated'),
                  'maxResults': None, 'timeMin': None, 'timeMax': None, 'q': None, 'pageToken': None}
MAX_CALENDAR_BODY = 64 * 1024
# Keep in step with skill/scripts/google_cloud_setup.py APIS (wizard-connectors#19, #27).
REQUIRED_APIS = ('calendar-json.googleapis.com', 'gmail.googleapis.com', 'youtube.googleapis.com',
                 'drive.googleapis.com', 'people.googleapis.com')
MAX_GMAIL_BYTES = 40 * 1024 * 1024  # a draft's attachments come back base64 (18 MB of files)
MAX_PAGES = 3
# Owners work asynchronously: a sign-in link stays usable for a day, not minutes.
SIGN_IN_WINDOW = 86400
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
AUTH = 'https://accounts.google.com/o/oauth2/v2/auth'

class Denied(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Denied('provider_redirect_denied')

class GoogleTransport:
    ENDPOINTS = {'token': 'https://oauth2.googleapis.com/token',
                 'revoke': 'https://oauth2.googleapis.com/revoke',
                 'jwks': 'https://www.googleapis.com/oauth2/v3/certs',
                 'userinfo': 'https://openidconnect.googleapis.com/v1/userinfo',
                 'catalog': 'https://www.googleapis.com/youtube/v3/videos',
                 'calendars': 'https://www.googleapis.com/calendar/v3/users/me/calendarList',
                 'events': 'https://www.googleapis.com/calendar/v3/calendars/'}
    def request(self, operation, *, form=None, token=None, query=None, calendar_id=None):
        url = self.ENDPOINTS[operation]
        if operation == 'events':
            validate_calendar_id(calendar_id)
            url += quote(calendar_id, safe='') + '/events'
        if query: url += '?' + urlencode(query)
        headers = {'Accept': 'application/json'}
        if token: headers['Authorization'] = 'Bearer ' + token
        data = urlencode(form).encode() if form is not None else None
        if data is not None: headers['Content-Type'] = 'application/x-www-form-urlencoded'
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(Request(url, data=data, headers=headers), timeout=15) as r:
                raw = r.read(MAX_OUTPUT_BYTES + 1)
                if len(raw) > MAX_OUTPUT_BYTES: raise Denied('provider_response_too_large')
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            if operation == 'token' and e.code == 400:
                raise Denied('reauth_required') from None
            if e.code == 401: raise Denied('reauth_required') from None
            if e.code == 403 and operation in ('calendars','events'): raise Denied('provider_permission_denied') from None
            if e.code == 403: raise Denied('provider_permission_denied') from None
            raise Denied('provider_unavailable') from None
        except Denied: raise
        except Exception: raise Denied('provider_unavailable') from None

    def gmail(self, method, url, token, query=None, body=None):
        """One Gmail API call on the fixed Gmail host for the signed-in account (`users/me` only)."""
        if method not in ('GET', 'POST', 'PUT') or not isinstance(url, str) or not url.startswith(GMAIL_API) \
                or '..' in url or any(c in url for c in '?#\\') or any(ord(c) < 33 for c in url):
            raise Denied('invalid_arguments')
        if query: url += '?' + urlencode(query)
        headers = {'Accept': 'application/json', 'Authorization': 'Bearer ' + token}
        data = None
        if body is not None:
            data = json.dumps(body).encode(); headers['Content-Type'] = 'application/json'
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(Request(url, data=data, headers=headers, method=method), timeout=60) as r:
                raw = r.read(MAX_GMAIL_BYTES + 1)
                if len(raw) > MAX_GMAIL_BYTES: raise Denied('provider_response_too_large')
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            code = {401: 'reauth_required', 403: 'google_permission_missing', 404: 'not_found',
                    400: 'invalid_arguments', 429: 'rate_limited'}.get(e.code, 'provider_unavailable')
            raise Denied(code) from None
        except Denied: raise
        except Exception: raise Denied('provider_unavailable') from None

    def workspace(self, url, token, query=None, raw=False):
        """One read-only Drive or People call (google_workspace.py). raw=True answers the body as text."""
        if not isinstance(url, str) or not any(url == p or (p.endswith('/files') and url.startswith(p + '/')) for p in WORKSPACE_API) \
                or '..' in url or any(c in url for c in '?#\\%') or any(ord(c) < 33 for c in url):
            raise Denied('invalid_arguments')
        if query: url += '?' + urlencode(query)
        headers = {'Accept': '*/*' if raw else 'application/json', 'Authorization': 'Bearer ' + token}
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(Request(url, headers=headers, method='GET'), timeout=60) as r:
                body = r.read(MAX_OUTPUT_BYTES + 1)
                if len(body) > MAX_OUTPUT_BYTES: raise Denied('too_large')
                if raw: return body.decode('utf-8', 'replace')
                return json.loads(body) if body else {}
        except HTTPError as e:
            code = {401: 'reauth_required', 403: 'google_permission_missing', 404: 'not_found',
                    400: 'invalid_arguments', 429: 'rate_limited'}.get(e.code, 'provider_unavailable')
            raise Denied(code) from None
        except Denied: raise
        except Exception: raise Denied('provider_unavailable') from None

    def calendar(self, method, url, token, query=None, body=None):
        """One Calendar events call (checked by calendar_request first). DELETE answers {}."""
        calendar_request(method, url, query, body)
        if query: url += '?' + urlencode(query)
        headers = {'Accept': 'application/json', 'Authorization': 'Bearer ' + token}
        data = None
        if body is not None:
            data = json.dumps(body).encode(); headers['Content-Type'] = 'application/json'
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(Request(url, data=data, headers=headers, method=method), timeout=60) as r:
                raw = r.read(MAX_OUTPUT_BYTES + 1)
                if len(raw) > MAX_OUTPUT_BYTES: raise Denied('too_large')
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            code = {401: 'reauth_required', 403: 'google_permission_missing', 404: 'not_found', 410: 'not_found',
                    400: 'invalid_arguments', 409: 'conflict', 412: 'conflict', 429: 'rate_limited'}.get(e.code, 'provider_unavailable')
            raise Denied(code) from None
        except Denied: raise
        except Exception: raise Denied('provider_unavailable') from None

    def verify(self, encoded, client_id, nonce=None):
        try:
            header = jwt.get_unverified_header(encoded)
            if header.get('alg') != 'RS256': raise ValueError()
            keys = self.request('jwks')['keys']
            key = next(k for k in keys if k.get('kid') == header.get('kid') and k.get('kty') == 'RSA')
            claims = jwt.decode(encoded, jwt.PyJWK.from_dict(key).key, algorithms=['RS256'],
                                audience=client_id, options={'require': ['exp', 'iat', 'iss', 'sub', 'aud']}, leeway=30)
            if claims['iss'] not in ('https://accounts.google.com', 'accounts.google.com'): raise ValueError()
            if claims.get('azp', client_id) != client_id: raise ValueError()
            if not isinstance(claims['sub'], str) or not 1 <= len(claims['sub']) <= 255: raise ValueError()
            if nonce is not None and not hmac.compare_digest(str(claims.get('nonce', '')), nonce): raise ValueError()
            return claims
        except Denied: raise
        except Exception: raise Denied('identity_verification_failed') from None

class Store:
    """One encrypted atomic snapshot; key is provisioned separately, never generated on restart."""
    def __init__(self, directory, key):
        self.root = Path(directory)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.path = self.root / 'google.enc'
        self.cipher = Fernet(key.encode()) if key else None
        if self.path.exists() and not self.cipher: raise RuntimeError('credential_key_required')
    def load(self):
        if not self.path.exists(): return {'accounts': {}, 'binding': None, 'revocation': 'not_applicable'}
        try: return json.loads(self.cipher.decrypt(self.path.read_bytes()))
        except Exception: raise RuntimeError('credential_store_unreadable') from None
    def save(self, value):
        if not self.cipher: raise Denied('credential_key_required')
        raw = self.cipher.encrypt(json.dumps(value).encode())
        tmp = self.path.with_suffix('.pending')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, 'wb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.path)
            fd = os.open(self.root, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            if tmp.exists(): tmp.unlink()

def store_key(config):
    if config.get('GOOGLE_STORE_KEY'): return config['GOOGLE_STORE_KEY']
    secret = config.get('GOOGLE_STORE_SECRET', '')
    if not secret: return ''
    if not isinstance(secret, str) or len(secret) < 32: raise RuntimeError('credential_secret_too_short')
    return base64.urlsafe_b64encode(HKDF(algorithm=hashes.SHA256(), length=32,
        salt=b'wizard-connectors/google-store/v1', info=b'fernet-credential-store').derive(secret.encode())).decode()


def validate_redirect(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value): raise Denied('invalid_redirect_configuration')
    try:
        u = urlsplit(value)
        _ = u.port
        if not u.hostname or u.username is not None or u.password is not None or u.query or u.fragment: raise ValueError()
        if u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ('localhost','127.0.0.1','::1')): raise ValueError()
        if not u.path.endswith('/api/google/callback'): raise ValueError()
    except ValueError: raise Denied('invalid_redirect_configuration') from None


def validate_calendar_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 300 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise Denied('invalid_calendar_id')


def calendar_request(method, url, query=None, body=None):
    """The Google app's Calendar call (calendar_http), checked before any token is used: GET/POST on one calendar's
    events, GET/PATCH/DELETE on one event, a few known query keys, a JSON object body. Nothing else at Google."""
    from urllib.parse import unquote
    m = CALENDAR_EVENTS_URL.fullmatch(url) if isinstance(url, str) else None
    if not m or method not in ('GET', 'POST', 'PATCH', 'DELETE'): raise Denied('invalid_arguments')
    calendar, event = unquote(m.group(1)), m.group(2)
    validate_calendar_id(calendar)
    # One canonical spelling only (no %2F, no dot segments): the path Google sees is the path checked here.
    if quote(calendar, safe='') != m.group(1) or any(c in calendar for c in '/\\') or '..' in calendar \
            or event in ('.', '..'): raise Denied('invalid_arguments')
    if method not in (('GET', 'POST') if event is None else ('GET', 'PATCH', 'DELETE')): raise Denied('invalid_arguments')
    if query is not None:
        if not isinstance(query, dict) or len(query) > len(CALENDAR_QUERY): raise Denied('invalid_arguments')
        for k, v in query.items():
            if k not in CALENDAR_QUERY or isinstance(v, bool) or not isinstance(v, (str, int)) or len(str(v)) > 512: raise Denied('invalid_arguments')
            if CALENDAR_QUERY[k] and str(v) not in CALENDAR_QUERY[k]: raise Denied('invalid_arguments')
    if body is not None and (method not in ('POST', 'PATCH') or not isinstance(body, dict) or len(json.dumps(body)) > MAX_CALENDAR_BODY):
        raise Denied('invalid_arguments')


def calendar_window(time_min, time_max):
    try:
        def parse(value):
            if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value): raise ValueError()
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        delta = parse(time_max) - parse(time_min)
        if not timedelta(0) < delta <= timedelta(days=400): raise ValueError()
    except (ValueError, TypeError, OverflowError): raise Denied('invalid_time_window') from None


class Broker:
    def __init__(self, config, transport=None):
        self.config = config
        self.provider = transport or GoogleTransport()
        self.store = Store(config.get('BROKER_DATA_DIR', '/data'), store_key(config))
        self.state = self.store.load()
        self.state.setdefault('client', None)
        self.state.setdefault('calendar_binding', {'app':'calendar', 'accounts':[], 'operations':['calendar.list','events.list']})
        # Pending sign-ins live in the encrypted store so an update or restart never voids a link the
        # owner has open (they work asynchronously). Verifier and nonce stay encrypted at rest.
        self.pending = {k:v for k,v in (self.state.get('pending_sign_ins') or {}).items() if v.get('expires',0) > time.time()}
        self.setup_pending = {}  # Digest-only, memory-only capabilities; restart invalidates all.
        self.lock = threading.RLock()
        # An installer replacing an env client is a replacement too. Never reuse
        # an old client's still-live access token under a different OAuth app.
        if self.state['accounts'] and self.state.get('client_fingerprint') != self._fingerprint(self.state):
            new = self._copy()
            for a in new['accounts'].values(): a.update(status='reauth_required',access_token='',refresh_token='')
            new['binding'] = None
            new['calendar_binding']['accounts'] = []
            self._commit(new)

    def _fingerprint(self, state):
        c, source = self.client()
        if source == 'owner': c = state.get('client') or {}
        return hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()

    def client(self):
        # Any environment client setting reserves configuration for the installer;
        # partial env configuration must not silently fall back to an owner secret.
        keys = ('GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_REDIRECT_URI')
        if any(self.config.get(k) for k in keys):
            return dict(zip(('client_id','client_secret','redirect_uri'), (self.config.get(k, '') for k in keys))), 'env'
        return self.state.get('client') or {}, 'owner'

    def client_status(self):
        c, source = self.client()
        return {'client_configured': bool(all(c.get(k) for k in ('client_id','client_secret','redirect_uri'))),
                'client_id': c.get('client_id', ''), 'redirect_uri': c.get('redirect_uri', ''), 'client_source': source}

    def save_client(self, client_id, client_secret, redirect_uri):
        if not isinstance(client_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com',client_id): raise Denied('invalid_client_id')
        if not isinstance(client_secret,str) or not 8 <= len(client_secret) <= 512 or any(c.isspace() for c in client_secret): raise Denied('invalid_client_secret')
        validate_redirect(redirect_uri)
        return self._set_client({'client_id':client_id,'client_secret':client_secret,'redirect_uri':redirect_uri})

    def agreement_status(self):
        saved = self.state.get('agreements') or {}
        return {'accepted': list(saved.get('agreements', [])), 'version': saved.get('version', ''),
                'country': saved.get('country', '')}

    def save_agreements(self, agreements, version, country):
        from google_agreements import IDS, VERSION, COUNTRIES
        if (not isinstance(agreements, list) or any(not isinstance(x, str) for x in agreements)
                or len(agreements) != len(IDS) or set(agreements) != IDS
                or version != VERSION or not isinstance(country, str) or country not in COUNTRIES):
            raise Denied('invalid_google_agreements')
        with self.lock:
            new = self._copy()
            new['agreements'] = {'agreements': sorted(IDS), 'version': VERSION, 'country': country,
                                 'accepted_at': datetime.now().astimezone().isoformat()}
            self._commit(new)
            self.setup_pending.clear()  # Country/acceptance changes invalidate in-flight delegated setup.
            return self.agreement_status()

    def setup_status(self, redirect_uri):
        validate_redirect(redirect_uri)
        with self.lock:
            c = self.client_status()
            # Public numeric prefix of the client ID (not a secret): the project that owns the
            # configured app, so --step api opens it without guessing by name (wizard-connectors#38).
            number = re.match(r'([1-9][0-9]{5,19})-', c['client_id'] or '') if c['client_configured'] else None
            return {'configured': c['client_configured'], 'managed': c['client_source'] == 'env',
                    'project_number': number.group(1) if number else '',
                    'redirect_uri': c['redirect_uri'] or redirect_uri,
                    # Every API this broker serves, all enabled by the agent setup in one run.
                    'required_apis': list(REQUIRED_APIS),
                    'required_scopes': sorted(IDENTITY | {CALENDAR}), 'agreements': self.agreement_status(),
                    # Asked per account only when the owner taps Allow on its Mail row.
                    'optional_scopes': [GMAIL_SCOPE, DRIVE_SCOPE, CONTACTS_SCOPE, CALENDAR_EDIT_SCOPE]}

    def setup_begin(self, redirect_uri):
        validate_redirect(redirect_uri)
        with self.lock:
            if self.client()[1] == 'env': raise Denied('client_managed_by_environment')
            if not self.store.cipher: raise Denied('credential_key_required')
            saved = self.state.get('agreements') or {}
            if (saved.get('version') != agreements.VERSION
                    or set(saved.get('agreements', [])) != agreements.IDS
                    or saved.get('country') not in agreements.COUNTRIES
                    or not saved.get('accepted_at')):
                raise Denied('google_agreements_required')
            # One active setup per owner. Reissuing supersedes the previous capability.
            token = secrets.token_urlsafe(32)
            self.setup_pending = {hashlib.sha256(token.encode()).hexdigest():
                                  {'expires': time.time() + 1800, 'redirect_uri': redirect_uri}}
            return {'token': token, 'expires_in': 1800}

    def setup_deposit(self, token, client_id, client_secret):
        with self.lock:
            if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
                raise Denied('invalid_setup_token')
            key = hashlib.sha256(token.encode()).hexdigest()
            pending = self.setup_pending.pop(key, None)  # Consume even on malformed credentials/storage failure.
            if not pending or pending['expires'] <= time.time(): raise Denied('invalid_setup_token')
            self.save_client(client_id, client_secret, pending['redirect_uri'])
            return {'ok': True}  # Never echo credentials, including the public ID.

    def clear_client(self): return self._set_client(None)

    def _set_client(self, value):
        with self.lock:
            if self.client()[1] == 'env': raise Denied('client_managed_by_environment')
            new = self._copy()
            if new['client'] != value:
                new['client'] = value
                for a in new['accounts'].values(): a.update(status='reauth_required', access_token='', refresh_token='')
                new['binding'] = None
                new['calendar_binding']['accounts'] = []
                self.pending.clear()
                self._commit(new)
            self.setup_pending.clear()
            return self.client_status()

    def gate(self):
        if self.config.get('GOOGLE_DISABLED', '').lower() == 'true': return 'google_disabled'
        if not self.client_status()['client_configured'] or not self.store.cipher: return 'google_configuration_required'
        try: validate_redirect(self.client()[0]['redirect_uri'])
        except Denied: return 'invalid_redirect_configuration'
        return None
    def _ready(self):
        if self.gate(): raise Denied(self.gate())
    def _commit(self, state):
        state['pending_sign_ins'] = self.pending
        state['client_fingerprint'] = self._fingerprint(state)
        self.store.save(state)
        self.state = state
    def _copy(self): return json.loads(json.dumps(self.state))
    def status(self):
        with self.lock:
            accounts = [{'id': aid, 'email': a.get('email', ''), 'status': a['status'],
                         'scopes': a['scopes'], 'offline': bool(a.get('refresh_token'))}
                        for aid, a in self.state['accounts'].items()]
            binding = self.state['binding']
            return {'state': 'connected' if accounts else 'not_connected', 'accounts': accounts,
                    'grants': [{'account': a['id'], 'scopes': a['scopes'], 'status': a['status']} for a in accounts],
                    'bindings': [binding] if binding else [], 'calendar_binding': self._copy()['calendar_binding'],
                    **self.client_status(), 'agreements': self.agreement_status(), 'agreement_options': agreements.options(), 'blocker': self.gate(),
                    'provider_revocation': self.state['revocation'],
                    'music': {'state': 'bound' if binding else 'unbound', 'provider': 'youtube-music',
                              'catalog': 'youtube-data-api', 'playback': 'separate_existing_app',
                              'playback_entitlement': False}}
    def start(self, browser, account=None, youtube=False, calendar=False, gmail=False, workspace=False, calendar_edits=False):
        with self.lock:
            self._ready()
            if account and account not in self.state['accounts']: raise Denied('account_not_found')
            self.pending = {k:v for k,v in self.pending.items() if v['expires'] > time.time()}
            if len(self.pending) >= 32: raise Denied('authorization_busy')
            state, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(3))
            scopes = IDENTITY | ({YOUTUBE} if youtube else set()) | ({CALENDAR} if calendar else set()) | ({GMAIL_SCOPE} if gmail is True else set())
            if workspace is True: scopes |= set(WORKSPACE_SCOPES.values())
            if calendar_edits is True: scopes |= {CALENDAR_EDIT_SCOPE}
            if account: scopes |= set(self.state['accounts'][account]['scopes'])
            self.pending[state] = {'browser': hashlib.sha256(browser.encode()).hexdigest(), 'verifier': verifier,
                                   'nonce': nonce, 'expires': time.time()+SIGN_IN_WINDOW, 'account': account, 'scopes': sorted(scopes)}
            self._commit(self._copy())
            params = {'client_id': self.client()[0]['client_id'], 'redirect_uri': self.client()[0]['redirect_uri'],
                      'response_type': 'code', 'scope': ' '.join(sorted(scopes)), 'state': state, 'nonce': nonce,
                      'access_type': 'offline', 'prompt': 'consent select_account', 'include_granted_scopes': 'true',
                      'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),
                      'code_challenge_method': 'S256'}
            return {'authorization_url': AUTH+'?'+urlencode(params), 'expires_in': SIGN_IN_WINDOW}
    def _tokens(self, value, scopes):
        if value.get('token_type', '').lower() != 'bearer' or not isinstance(value.get('access_token'), str): raise Denied('invalid_provider_grant')
        got = set(value.get('scope', '').split())
        # Google may canonicalize email to the full scope URI.
        if 'https://www.googleapis.com/auth/userinfo.email' in got:
            got.remove('https://www.googleapis.com/auth/userinfo.email'); got.add('email')
        if not got <= SCOPES or not set(scopes) <= got: raise Denied('scope_consent_required')
        expiry = value.get('expires_in')
        if not isinstance(expiry, (int,float)) or not 0 < expiry <= 86400: raise Denied('invalid_provider_grant')
        return sorted(got), time.time()+expiry
    def finish(self, state, browser, code=None, error=None):
        with self.lock:
            self._ready()
            p = self.pending.get(state)
            # The owner may tap Connect in the Wizard app and finish in their phone's own browser,
            # so the flow is bound by the owner-minted, single-use state (plus PKCE and nonce), not a cookie.
            if not p or p['expires'] <= time.time():
                raise Denied('invalid_oauth_state')
            del self.pending[state]  # one use, including denial/provider failure
            self._commit(self._copy())
            if error: raise Denied('consent_denied')
            if not isinstance(code, str) or not 1 <= len(code) <= 4096: raise Denied('invalid_authorization_code')
            value = self.provider.request('token', form={'grant_type': 'authorization_code', 'code': code,
                      'client_id': self.client()[0]['client_id'], 'client_secret': self.client()[0]['client_secret'],
                      'redirect_uri': self.client()[0]['redirect_uri'], 'code_verifier': p['verifier']})
            try: scopes, expiry = self._tokens(value, p['scopes'])
            except Denied as e:
                if p.get('account'): self._invalidate(p['account'], e)
                raise
            claims = self.provider.verify(value.get('id_token', ''), self.client()[0]['client_id'], p['nonce'])
            aid = 'google-' + hashlib.sha256(claims['sub'].encode()).hexdigest()[:32]
            if p['account'] and p['account'] != aid: raise Denied('wrong_account_reauthentication')
            new = self._copy()
            previous = new['accounts'].get(aid, {})
            if not previous and len(new['accounts']) >= 32: raise Denied('account_limit')
            refresh = value.get('refresh_token') or previous.get('refresh_token', '')
            new['accounts'][aid] = {'subject': claims['sub'], 'email': str(claims.get('email',''))[:254] if claims.get('email_verified') else '',
                                   'status': 'active', 'scopes': scopes, 'expires': expiry,
                                   'access_token': value['access_token'], 'refresh_token': refresh}
            if new['binding'] and new['binding']['account'] == aid and YOUTUBE not in scopes: new['binding'] = None
            if CALENDAR not in scopes: self._remove_calendar(new, aid)
            self._commit(new)
            return {'connected': True, 'account': aid}
    def bind(self, account, consent):
        self._ready()
        with self.lock:
            a = self.state['accounts'].get(account)
            if consent is not True: raise Denied('explicit_consent_required')
            if not a or a['status'] != 'active': raise Denied('reauth_required')
            if YOUTUBE not in a['scopes']: raise Denied('incremental_consent_required')
            new = self._copy()
            new['binding'] = {'app': 'music', 'account': account, 'operations': ['catalog.lookup']}
            self._commit(new)
            return {'bound': True, 'playback_entitlement': False}
    def unlink(self):
        with self.lock:
            new = self._copy(); new['binding'] = None; self._commit(new)
            return {'unlinked': True, 'account_preserved': True}
    def disconnect(self, account):
        with self.lock:
            a = self.state['accounts'].get(account)
            if not a: raise Denied('account_not_found')
            token = a.get('refresh_token') or a.get('access_token')
            new = self._copy(); del new['accounts'][account]
            if new['binding'] and new['binding']['account'] == account: new['binding'] = None
            self._remove_calendar(new, account)
            new['revocation'] = 'pending'; self._commit(new)
            # Generic Connect has no known subject until its callback. Cancel every
            # unidentified flow too: none begun before disconnect may resurrect this
            # account. finish/start/disconnect share this lock (including token I/O).
            self.pending = {k:v for k,v in self.pending.items()
                            if v['account'] is not None and v['account'] != account}
            new['pending_sign_ins'] = self.pending
            try:
                self.provider.request('revoke', form={'token': token})
                new['revocation'] = 'revoked'
            except Denied: new['revocation'] = 'failed_manual_revocation_required'
            self._commit(new)
            return {'local_disconnected': True, 'provider_revocation': new['revocation']}
    def catalog(self, account, video_id):
        self._ready()
        if not isinstance(video_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id): raise Denied('invalid_video_id')
        # Lock is the linearization boundary for refresh, invocation, unlink and disconnect.
        with self.lock:
            b = self.state['binding']; a = self.state['accounts'].get(account)
            if not b or b['account'] != account or not a: raise Denied('capability_denied')
            if a['status'] != 'active': raise Denied('reauth_required')
            try:
                a = self._refresh(account)
                raw = self.provider.request('catalog', token=a['access_token'], query={'part':'snippet', 'id':video_id, 'maxResults':1})
            except Denied as e:
                self._invalidate(account, e)
                raise
            items = [{'id':i['id'], 'title':str(i.get('snippet',{}).get('title',''))[:300]} for i in raw.get('items',[]) if i.get('id') == video_id]
            return {'provider':'youtube-music', 'catalog_source':'youtube-data-api', 'items':items,
                    'audio_verified':False, 'playback_entitlement':False}

    @staticmethod
    def _remove_calendar(state, account):
        state['calendar_binding']['accounts'] = [a for a in state['calendar_binding']['accounts'] if a != account]

    def calendar_bind(self, account, consent):
        with self.lock:
            if type(consent) is not bool: raise Denied('explicit_consent_required')
            new = self._copy()
            if consent:
                self._ready()
                a = new['accounts'].get(account)
                if not a or a['status'] != 'active': raise Denied('reauth_required')
                if CALENDAR not in a['scopes']: raise Denied('incremental_consent_required')
                if account not in new['calendar_binding']['accounts']: new['calendar_binding']['accounts'].append(account)
            else: self._remove_calendar(new, account)
            self._commit(new)
            return {'account':account, 'calendar_allowed':consent}

    def calendar_status(self):
        with self.lock:
            return {'client_configured':self.client_status()['client_configured'],
                    'accounts':[{'account':aid, 'email':a.get('email',''),
                                 'calendar_allowed':aid in self.state['calendar_binding']['accounts'] and CALENDAR in a['scopes'] and a['status']=='active' and not self.gate(),
                                 'status':a['status']} for aid,a in self.state['accounts'].items()],
                    'setup_url':'/connected-accounts/'}

    def _invalidate(self, account, error):
        if str(error) in ('reauth_required','scope_consent_required','provider_permission_denied'):
            new = self._copy()
            new['accounts'][account].update(status='reauth_required',access_token='',refresh_token='')
            self._remove_calendar(new, account)
            self._commit(new)

    def _refresh(self, account):
        # Called only while holding the same lock as invocation, unlink and disconnect.
        a = self.state['accounts'][account]
        if a['status'] != 'active': raise Denied('reauth_required')
        if a['expires'] > time.time()+30: return a
        if not a.get('refresh_token'): raise Denied('reauth_required')
        value = self.provider.request('token', form={'grant_type':'refresh_token', 'refresh_token':a['refresh_token'],
            'client_id':self.client()[0]['client_id'], 'client_secret':self.client()[0]['client_secret']})
        scopes, expiry = self._tokens(value, a['scopes'])
        identity = self.provider.request('userinfo', token=value['access_token'])
        if identity.get('sub') != a['subject']: raise Denied('reauth_required')
        new = self._copy(); a = new['accounts'][account]
        a.update(access_token=value['access_token'], expires=expiry, scopes=scopes)
        if value.get('refresh_token'): a['refresh_token'] = value['refresh_token']
        self._commit(new)
        return a

    def _calendar_account(self, account):
        self._ready()
        a = self.state['accounts'].get(account)
        if not a or account not in self.state['calendar_binding']['accounts']: raise Denied('capability_denied')
        if CALENDAR not in a['scopes']:
            self._invalidate(account, Denied('scope_consent_required'))
            raise Denied('incremental_consent_required')
        return self._refresh(account)

    def calendar_calendars(self):
        with self.lock:
            self._ready()
            result = []; size = 0
            # Snapshot: refresh failure may remove this binding while iterating.
            for account in list(self.state['calendar_binding']['accounts']):
                try:
                    a = self._calendar_account(account)
                    query = {'maxResults':250, 'fields':'nextPageToken,items(id,summary,backgroundColor,primary,accessRole)'}
                    page = None
                    for _ in range(MAX_PAGES):
                        raw = self.provider.request('calendars', token=a['access_token'], query=query)
                        for row in raw.get('items', [])[:250]:
                            cid = row.get('id')
                            validate_calendar_id(cid)
                            item = {'account':account, 'email':a.get('email',''), 'id':cid,
                                'name':str(row.get('summary',''))[:500], 'color':str(row.get('backgroundColor',''))[:32],
                                'primary':row.get('primary') is True, 'access_role':str(row.get('accessRole',''))[:32]}
                            size += len(json.dumps(item).encode()) + 2
                            if size > MAX_OUTPUT_BYTES - 4096: raise Denied('calendar_list_too_large')
                            result.append(item)
                        page = raw.get('nextPageToken')
                        if not page: break
                        if not isinstance(page,str) or len(page)>2048: raise Denied('invalid_provider_page')
                        query['pageToken'] = page
                    else:
                        if page: raise Denied('calendar_list_truncated')
                except Denied as e:
                    self._invalidate(account, e)
                    raise
            return {'calendars':result}

    def calendar_events(self, account, calendar_id, time_min, time_max):
        validate_calendar_id(calendar_id)
        calendar_window(time_min, time_max)
        with self.lock:
            try:
                a = self._calendar_account(account)
                query = {'timeMin':time_min, 'timeMax':time_max, 'singleEvents':'true', 'orderBy':'startTime',
                         'maxResults':2500, 'fields':'nextPageToken,items(id,summary,start,end,location,status,htmlLink,description,hangoutLink,iCalUID,attendees(self,responseStatus),conferenceData(entryPoints(entryPointType,uri)))'}
                result = []; size = 0; page = None
                for _ in range(MAX_PAGES):
                    raw = self.provider.request('events', token=a['access_token'], query=query, calendar_id=calendar_id)
                    for row in raw.get('items', [])[:2500]:
                        start, end = row.get('start', {}), row.get('end', {})
                        event = {'id':str(row.get('id',''))[:1024], 'calendar_id':calendar_id, 'account':account,
                            'title':str(row.get('summary',''))[:2000], 'start':start.get('dateTime') or start.get('date',''),
                            'end':end.get('dateTime') or end.get('date',''), 'all_day':'date' in start,
                            'location':str(row.get('location',''))[:2000], 'status':str(row.get('status',''))[:32]}
                        link = row.get('htmlLink')
                        if isinstance(link,str) and len(link)<=2048 and urlsplit(link).scheme=='https': event['html_link']=link
                        # Only bounded display details, not guest identities, cross
                        # the existing grant-scoped calendar-source boundary.
                        event['description'] = str(row.get('description') or '')[:4000]
                        if row.get('iCalUID'): event['ical_uid'] = str(row['iCalUID'])[:1024]
                        attendees = row.get('attendees') or []
                        if not isinstance(attendees, list): raise Denied('invalid_provider_event')
                        event['attendee_count'] = min(len(attendees), 10000)
                        mine = next((a for a in attendees if isinstance(a, dict) and a.get('self')), {})
                        response = mine.get('responseStatus')
                        if response in ('accepted', 'declined', 'tentative', 'needsAction'): event['self_response'] = response
                        meet = row.get('hangoutLink') or next((e.get('uri') for e in (row.get('conferenceData') or {}).get('entryPoints', []) if isinstance(e, dict) and e.get('entryPointType') == 'video'), None)
                        if isinstance(meet, str) and len(meet) <= 2000:
                            u = urlsplit(meet)
                            if u.scheme == 'https' and u.hostname and not u.username and not u.password: event['meet'] = meet
                        size += len(json.dumps(event).encode()) + 2
                        if size > MAX_OUTPUT_BYTES - 4096: return {'events':result, 'truncated':True}
                        result.append(event)
                    page = raw.get('nextPageToken')
                    if not page: break
                    if not isinstance(page,str) or len(page)>2048: raise Denied('invalid_provider_page')
                    query['pageToken'] = page
                return {'events':result, 'truncated':bool(page)}
            except Denied as e:
                self._invalidate(account, e)
                raise

    def music_catalog(self, video_id):
        # Service caller cannot select an account/grant or widen the owner binding.
        with self.lock:
            binding=self.state['binding']
            if not binding: raise Denied('capability_denied')
            return self.catalog(binding['account'],video_id)

    # ---------- Gmail for Mail (contract wizard.mail-calendar/1, mail tools; wizard-connectors#15) ----------
    def mail_status(self):
        """Accounts for Mail. An account offers mail once the owner gave this Google app Gmail access for it."""
        with self.lock:
            blocked = self.gate()
            return {'accounts': [{'email': a.get('email', ''), 'status': a['status'] if not blocked else 'reauth_required',
                                  'services': ['gmail'] if GMAIL_SCOPE in a['scopes'] else [], 'via': 'own-client'}
                                 for a in self.state['accounts'].values() if a.get('email')],
                    'blocker': blocked}

    def _mail_account(self, email):
        mail = [(aid, a) for aid, a in self.state['accounts'].items() if GMAIL_SCOPE in a['scopes'] and a.get('email')]
        if email in (None, ''):
            if len(mail) != 1: raise Denied('account_required' if mail else 'not_connected')
            return mail[0]
        if not isinstance(email, str) or len(email) > 254: raise Denied('invalid_arguments')
        found = [(aid, a) for aid, a in mail if a['email'].lower() == email.strip().lower()]
        if not found:
            known = any(a.get('email', '').lower() == email.strip().lower() for a in self.state['accounts'].values())
            raise Denied('permission_missing' if known else 'account_not_found')
        return found[0]

    def mail_call(self, tool, args):
        """Run one mail tool for one account. Access levels are checked by the caller (server, mail_access.py)."""
        import gmail_mail
        if tool not in gmail_mail.TOOLS or not isinstance(args, dict): raise Denied('invalid_arguments')
        with self.lock:
            self._ready()
            aid, a = self._mail_account(args.get('account'))
            if a['status'] != 'active': raise Denied('reauth_required')
            try: a = self._refresh(aid)
            except Denied as e:
                self._invalidate(aid, e); raise
            token, email = a['access_token'], a.get('email', '')
        # Provider I/O outside the lock: a page of mail is up to 25 calls. A disconnect meanwhile revokes the token.
        def call(method, url, query=None, body=None):
            return self.provider.gmail(method, url, token, query, body)
        rest = {k: v for k, v in args.items() if k != 'account'}
        try: result = gmail_mail.TOOLS[tool](call, rest)
        except gmail_mail.BadArgs as e: raise Denied('invalid_arguments:' + str(e)[:300]) from None
        except gmail_mail.MailFault as e: raise Denied(e.code + ':' + e.message[:300]) from None
        except Denied as e:
            if str(e) == 'reauth_required':
                with self.lock:
                    if aid in self.state['accounts']: self._invalidate(aid, e)
            raise
        return {'contract': gmail_mail.CONTRACT, 'source': 'google', 'via': 'own-client', 'account': email, **result}


    # ---------- Drive, Docs, Sheets and Contacts for the agent (wizard-connectors#27, switch google-workspace) ----------
    def workspace_status(self):
        """Accounts and which Google tools each has allowed. No content, no tokens."""
        with self.lock:
            blocked = self.gate()
            return {'accounts': [{'email': a.get('email', ''), 'status': a['status'] if not blocked else 'reauth_required',
                                  'services': [n for n, s in (('gmail', GMAIL_SCOPE), ('drive', DRIVE_SCOPE),
                                                              ('contacts', CONTACTS_SCOPE)) if s in a['scopes']]}
                                 for a in self.state['accounts'].values() if a.get('email')],
                    'blocker': blocked}

    def workspace_call(self, tool, args):
        """Run one read-only Drive/Contacts tool for one account (the agent's, through this app's MCP)."""
        import google_workspace
        if tool not in google_workspace.TOOLS or not isinstance(args, dict): raise Denied('invalid_arguments')
        scope = WORKSPACE_SCOPES[google_workspace.NEEDS[tool]]
        with self.lock:
            self._ready()
            email = args.get('account')
            have = [(aid, a) for aid, a in self.state['accounts'].items() if scope in a['scopes'] and a.get('email')]
            if email in (None, ''):
                if len(have) != 1: raise Denied('account_required' if have else 'not_connected')
                aid, a = have[0]
            else:
                if not isinstance(email, str) or len(email) > 254: raise Denied('invalid_arguments')
                found = [(i, x) for i, x in have if x['email'].lower() == email.strip().lower()]
                if not found:
                    known = any(x.get('email', '').lower() == email.strip().lower() for x in self.state['accounts'].values())
                    raise Denied('permission_missing' if known else 'account_not_found')
                aid, a = found[0]
            if a['status'] != 'active': raise Denied('reauth_required')
            try: a = self._refresh(aid)
            except Denied as e:
                self._invalidate(aid, e); raise
            token, email = a['access_token'], a.get('email', '')
        def call(url, query=None, raw=False):
            return self.provider.workspace(url, token, query, raw)
        rest = {k: v for k, v in args.items() if k != 'account'}
        try: result = google_workspace.TOOLS[tool](call, rest)
        except google_workspace.BadArgs as e: raise Denied('invalid_arguments:' + str(e)[:300]) from None
        except Denied as e:
            if str(e) == 'reauth_required':
                with self.lock:
                    if aid in self.state['accounts']: self._invalidate(aid, e)
            raise
        return {'source': 'google', 'via': 'connected-accounts', 'account': email, **result}

    # ---------- Calendar edits for the agent through the Google app (wizard-connectors#29, switch google-calendar-edits) ----------
    def calendar_edit_status(self):
        """Accounts and whether each allowed Calendar edits. No events, no tokens."""
        with self.lock:
            blocked = self.gate()
            return {'accounts': [{'email': a.get('email', ''), 'status': a['status'] if not blocked else 'reauth_required',
                                  'calendar_edits': CALENDAR_EDIT_SCOPE in a['scopes']}
                                 for a in self.state['accounts'].values() if a.get('email')],
                    'blocker': blocked}

    def calendar_http(self, method, url, account=None, query=None, body=None):
        """One Calendar events call for the Google app, on an account that allowed Calendar edits. The Google app has
        already applied the owner's Calendar > Settings > Agent access level (its agent_access.py)."""
        calendar_request(method, url, query, body)
        with self.lock:
            self._ready()
            have = [(aid, a) for aid, a in self.state['accounts'].items() if CALENDAR_EDIT_SCOPE in a['scopes'] and a.get('email')]
            if account in (None, ''):
                if len(have) != 1: raise Denied('account_required' if have else 'not_connected')
                aid, a = have[0]
            else:
                if not isinstance(account, str) or len(account) > 254: raise Denied('invalid_arguments')
                found = [(i, x) for i, x in have if x['email'].lower() == account.strip().lower()]
                if not found:
                    known = any(x.get('email', '').lower() == account.strip().lower() for x in self.state['accounts'].values())
                    raise Denied('permission_missing' if known else 'account_not_found')
                aid, a = found[0]
            if a['status'] != 'active': raise Denied('reauth_required')
            try: a = self._refresh(aid)
            except Denied as e:
                self._invalidate(aid, e); raise
            token, email = a['access_token'], a.get('email', '')
        try: value = self.provider.calendar(method, url, token, query, body)
        except Denied as e:
            if str(e) == 'reauth_required':
                with self.lock:
                    if aid in self.state['accounts']: self._invalidate(aid, e)
            raise
        return {'source': 'google', 'via': 'connected-accounts', 'account': email, 'response': value}
