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
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import HTTPError
from cryptography.fernet import Fernet
import jwt

IDENTITY = frozenset({'openid', 'email'})
YOUTUBE = 'https://www.googleapis.com/auth/youtube.readonly'
SCOPES = IDENTITY | {YOUTUBE}
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
                 'catalog': 'https://www.googleapis.com/youtube/v3/videos'}
    def request(self, operation, *, form=None, token=None, query=None):
        url = self.ENDPOINTS[operation]
        if query: url += '?' + urlencode(query)
        headers = {'Accept': 'application/json'}
        if token: headers['Authorization'] = 'Bearer ' + token
        data = urlencode(form).encode() if form is not None else None
        if data is not None: headers['Content-Type'] = 'application/x-www-form-urlencoded'
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(Request(url, data=data, headers=headers), timeout=15) as r:
                raw = r.read(262145)
                if len(raw) > 262144: raise Denied('provider_response_too_large')
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            if operation == 'token' and e.code == 400:
                raise Denied('reauth_required') from None
            if e.code == 401: raise Denied('reauth_required') from None
            if e.code == 403: raise Denied('provider_permission_denied') from None
            raise Denied('provider_unavailable') from None
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

class Broker:
    def __init__(self, config, transport=None):
        self.config = config
        self.provider = transport or GoogleTransport()
        self.store = Store(config.get('BROKER_DATA_DIR', '/data'), config.get('GOOGLE_STORE_KEY', ''))
        self.state = self.store.load()
        self.pending = {}
        self.lock = threading.RLock()
    def gate(self):
        if self.config.get('GOOGLE_REVIEW_APPROVED') != 'true': return 'isolation_review_required'
        if not all(self.config.get(k) for k in ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REDIRECT_URI', 'GOOGLE_STORE_KEY')):
            return 'google_configuration_required'
        u = urlsplit(self.config['GOOGLE_REDIRECT_URI'])
        if u.query or u.fragment or u.username or (u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ('localhost', '127.0.0.1'))):
            return 'invalid_redirect_configuration'
        if not u.path.endswith('/api/google/callback'): return 'invalid_redirect_configuration'
        return None
    def _ready(self):
        if self.gate(): raise Denied(self.gate())
    def _commit(self, state):
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
                    'bindings': [binding] if binding else [], 'blocker': self.gate(),
                    'provider_revocation': self.state['revocation'],
                    'music': {'state': 'bound' if binding else 'unbound', 'provider': 'youtube-music',
                              'catalog': 'youtube-data-api', 'playback': 'separate_existing_app',
                              'playback_entitlement': False}}
    def start(self, browser, account=None, youtube=False):
        self._ready()
        with self.lock:
            if account and account not in self.state['accounts']: raise Denied('account_not_found')
            self.pending = {k:v for k,v in self.pending.items() if v['expires'] > time.time()}
            if len(self.pending) >= 32: raise Denied('authorization_busy')
            state, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(3))
            scopes = SCOPES if youtube else IDENTITY
            self.pending[state] = {'browser': hashlib.sha256(browser.encode()).hexdigest(), 'verifier': verifier,
                                   'nonce': nonce, 'expires': time.time()+600, 'account': account, 'scopes': sorted(scopes)}
            params = {'client_id': self.config['GOOGLE_CLIENT_ID'], 'redirect_uri': self.config['GOOGLE_REDIRECT_URI'],
                      'response_type': 'code', 'scope': ' '.join(sorted(scopes)), 'state': state, 'nonce': nonce,
                      'access_type': 'offline', 'prompt': 'consent select_account', 'include_granted_scopes': 'false',
                      'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),
                      'code_challenge_method': 'S256'}
            return {'authorization_url': AUTH+'?'+urlencode(params), 'expires_in': 600}
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
        self._ready()
        with self.lock:
            p = self.pending.get(state)
            if not p or p['expires'] <= time.time() or not hmac.compare_digest(p['browser'], hashlib.sha256(browser.encode()).hexdigest()):
                raise Denied('invalid_oauth_state')
            del self.pending[state]  # one use, including denial/provider failure
            if error: raise Denied('consent_denied')
            if not isinstance(code, str) or not 1 <= len(code) <= 4096: raise Denied('invalid_authorization_code')
            value = self.provider.request('token', form={'grant_type': 'authorization_code', 'code': code,
                      'client_id': self.config['GOOGLE_CLIENT_ID'], 'client_secret': self.config['GOOGLE_CLIENT_SECRET'],
                      'redirect_uri': self.config['GOOGLE_REDIRECT_URI'], 'code_verifier': p['verifier']})
            scopes, expiry = self._tokens(value, p['scopes'])
            claims = self.provider.verify(value.get('id_token', ''), self.config['GOOGLE_CLIENT_ID'], p['nonce'])
            aid = 'google-' + hashlib.sha256(claims['sub'].encode()).hexdigest()[:32]
            if p['account'] and p['account'] != aid: raise Denied('wrong_account_reauthentication')
            new = self._copy()
            previous = new['accounts'].get(aid, {})
            refresh = value.get('refresh_token') or previous.get('refresh_token', '')
            new['accounts'][aid] = {'subject': claims['sub'], 'email': str(claims.get('email',''))[:254] if claims.get('email_verified') else '',
                                   'status': 'active', 'scopes': scopes, 'expires': expiry,
                                   'access_token': value['access_token'], 'refresh_token': refresh}
            if new['binding'] and new['binding']['account'] == aid and YOUTUBE not in scopes: new['binding'] = None
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
            new['revocation'] = 'pending'; self._commit(new)
            # Also cancel outstanding reconnects, so a late callback cannot resurrect it.
            self.pending = {k:v for k,v in self.pending.items() if v['account'] != account}
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
                if a['expires'] <= time.time()+30:
                    if not a.get('refresh_token'): raise Denied('reauth_required')
                    value = self.provider.request('token', form={'grant_type': 'refresh_token', 'refresh_token': a['refresh_token'],
                                      'client_id': self.config['GOOGLE_CLIENT_ID'], 'client_secret': self.config['GOOGLE_CLIENT_SECRET']})
                    scopes, expiry = self._tokens(value, a['scopes'])
                    identity = self.provider.request('userinfo', token=value['access_token'])
                    if identity.get('sub') != a['subject']: raise Denied('reauth_required')
                    new = self._copy(); a = new['accounts'][account]
                    a.update(access_token=value['access_token'], expires=expiry, scopes=scopes)
                    if value.get('refresh_token'): a['refresh_token'] = value['refresh_token']
                    self._commit(new)
                raw = self.provider.request('catalog', token=a['access_token'], query={'part':'snippet', 'id':video_id, 'maxResults':1})
            except Denied as e:
                if str(e) in ('reauth_required','scope_consent_required'):
                    new = self._copy(); new['accounts'][account].update(status='reauth_required',access_token='',refresh_token='')
                    self._commit(new)
                raise
            items = [{'id':i['id'], 'title':str(i.get('snippet',{}).get('title',''))[:300]} for i in raw.get('items',[]) if i.get('id') == video_id]
            return {'provider':'youtube-music', 'catalog_source':'youtube-data-api', 'items':items,
                    'audio_verified':False, 'playback_entitlement':False}

    def music_catalog(self, video_id):
        # Service caller cannot select an account/grant or widen the owner binding.
        with self.lock:
            binding=self.state['binding']
            if not binding: raise Denied('capability_denied')
            return self.catalog(binding['account'],video_id)
