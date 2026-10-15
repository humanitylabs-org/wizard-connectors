"""Fixed private service RPC; no generic fetch and no provider secrets in UI."""
import json
import os
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from google_broker import Denied, NoRedirect
from private_model import Blocked

class RPC:
    def __init__(self, host, port, token):
        self.url = f'http://{host}:{port}/rpc'
        self.token = token
    def call(self, operation, **args):
        if not self.token: raise Denied('service_not_configured')
        request = Request(self.url, data=json.dumps({'operation':operation,'args':args}).encode(),
                          headers={'Content-Type':'application/json', 'Authorization':'Bearer '+self.token})
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=100) as response:
                raw = response.read(65537)
                if len(raw)>65536: raise Denied('service_response_too_large')
                result = json.loads(raw)
        except HTTPError as e:
            try: error = json.loads(e.read(8192)).get('error', 'service_unavailable')
            except Exception: error = 'service_unavailable'
            raise Denied(error) from None
        except Denied: raise
        except Exception: raise Denied('service_unavailable') from None
        return result

class RemotePrivateModel:
    def __init__(self):
        self.rpc = RPC('private-worker', 8801, os.environ.get('PRIVATE_WORKER_TOKEN',''))
        self.key = os.environ.get('PRIVATE_ROUTE_CONFIGURED') == 'true'
        self.calls = 0; self.public_calls = 0; self.last_attestation = None
    def summarize(self, packet):
        # Worker selects its own immutable fictional packet by handle, never arbitrary caller text.
        from chat import THREADS, snapshot
        thread = next((k for k in THREADS if snapshot(k) == packet), None)
        if not thread: raise Blocked('synthetic_source_required')
        try:
            response = self.rpc.call('summarize', thread=thread)
            self.calls += 1; self.last_attestation = response['attestation']
            return response['text']
        except Denied as e: raise Blocked(str(e)) from None
