"""Provider-local account/grant/binding seam; no production credential loader.
Only the trusted provider adapter may register a verified identity. A caller never
gets tokens. Fixture credentials are used ONLY by tests, not the HTTP app.
"""
import threading
import time
from dataclasses import dataclass, field

class Denied(Exception):
    pass

@dataclass
class Grant:
    account: str
    scopes: frozenset
    expires: float
    token: str = field(repr=False)
    status: str = "active"
    epoch: int = 1
    lock: object = field(default_factory=threading.Lock, repr=False)

class Accounts:
    OPS = {"music": frozenset({"catalog.lookup", "playback.resolve"}),
           "test-other": frozenset({"fixture.read"})}
    def __init__(self):
        self.accounts = {}
        self.grants = {}
        self.bindings = {}
        self.lock = threading.RLock()
        self.epoch = 0

    def register_verified(self, handle, subject, grant_id, scopes, token, expires):
        with self.lock:
            if handle in self.accounts and self.accounts[handle] != subject:
                raise Denied("wrong_account_reauthentication")
            self.accounts[handle] = subject
            self.grants[grant_id] = Grant(handle, frozenset(scopes), expires, token)
            self.epoch += 1

    def bind(self, caller, account, grant_id, operations, consent=False):
        with self.lock:
            g = self.grants.get(grant_id)
            if not consent or not operations or not set(operations) <= self.OPS.get(caller, frozenset()):
                raise Denied("consent_or_operation")
            if not g or g.account != account or g.status != "active":
                raise Denied("wrong_account_or_grant")
            if not set(operations) <= g.scopes:
                raise Denied("incremental_consent_required")
            self.bindings[caller] = (account, grant_id, frozenset(operations))
            self.epoch += 1

    def _authorize(self, caller, account, operation):
        b = self.bindings.get(caller)
        if not b or b[0] != account or operation not in b[2]:
            raise Denied("capability_denied")
        g = self.grants[b[1]]
        if g.status != "active":
            raise Denied("reauth_required")
        return g

    def invoke(self, caller, account, operation, adapter, refresh):
        # Credential never returned. Adapter selected by trusted caller code,
        # not supplied through HTTP or MCP. Refresh serializes per grant.
        with self.lock:
            grant = self._authorize(caller, account, operation)
            epoch = self.epoch
        with grant.lock:
            with self.lock:
                if epoch != self.epoch:
                    raise Denied("stale_authority")
                self._authorize(caller, account, operation)
            if grant.expires <= time.time():
                try:
                    token, expires, subject = refresh(grant.token)
                    if subject != self.accounts[account] or expires <= time.time():
                        raise Denied("wrong_account_or_expired_refresh")
                except Exception:
                    self.revoke_grant(next(k for k,v in self.grants.items() if v is grant))
                    raise Denied("reauth_required") from None
                with self.lock:
                    if epoch != self.epoch:
                        raise Denied("stale_authority")
                    grant.token, grant.expires = token, expires
            result = adapter(operation, grant.token)
            with self.lock:
                if epoch != self.epoch:
                    raise Denied("stale_delivery")
            return result

    def unlink(self, caller):
        with self.lock:
            self.bindings.pop(caller, None)
            self.epoch += 1

    def revoke_grant(self, grant_id):
        with self.lock:
            self.grants[grant_id].status = "reauth_required"
            self.grants[grant_id].token = ""
            self.grants[grant_id].epoch += 1
            self.epoch += 1

    def disconnect(self, account):
        with self.lock:
            affected = [k for k,v in self.bindings.items() if v[0] == account]
            for k in affected:
                del self.bindings[k]
            for g in self.grants.values():
                if g.account == account:
                    g.status, g.token = "disconnected", ""
            self.accounts.pop(account, None)
            self.epoch += 1
            return {"affected": sorted(affected), "local_disconnected": True,
                    "provider_revocation": "not_attempted_no_live_provider"}
