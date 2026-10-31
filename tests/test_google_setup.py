"""Single-use setup: real HTTP/RPC/encrypted store, no real Google credentials."""
import concurrent.futures
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import test_google_http as fixtures

spec = importlib.util.spec_from_file_location('google_cloud_setup', Path(__file__).resolve().parents[1]/'skill/scripts/google_cloud_setup.py')
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


class SetupIntakeTests(unittest.TestCase):
    setUp = fixtures.BrokerHTTPTests.setUp
    tearDown = fixtures.BrokerHTTPTests.tearDown
    req = fixtures.BrokerHTTPTests.req

    def owner_client(self):
        for k in ('GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_REDIRECT_URI'): self.config.pop(k, None)
        self.payload = {'client_id':'fake-setup.apps.googleusercontent.com','client_secret':'FAKE_INTAKE_SECRET'}

    def mcp(self, name, args=None, auth='m'):
        return self.req('/mcp', {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args or {}}},
                        owner=False, headers={'Authorization':'Bearer '+auth*40})

    def begin(self):
        self.owner_client()
        data = self.mcp('google_app_setup_begin')[1]
        return json.loads(data['result']['content'][0]['text'])

    def post(self, token, data=None, **kw):
        return self.req('/api/google/setup/intake', self.payload if data is None else data, owner=False,
                        headers={'Authorization':'Bearer '+token, **kw})

    def test_mcp_auth_status_no_credentials_and_no_arg_widening(self):
        for auth in ('o','x'):
            self.assertEqual(self.mcp('google_app_setup_begin', auth=auth)[0],401)
        raw=json.dumps(self.mcp('google_app_setup_status')[1])
        for value in ('FAKE_CLIENT_SECRET','fixture-client','client_secret','client_id'): self.assertNotIn(value,raw)
        self.assertIn('calendar-json.googleapis.com',raw)
        self.assertIn('operation_denied',json.dumps(self.mcp('google_app_setup_begin', {'redirect_uri':'https://evil.invalid'})[1]))
        self.assertIn('client_managed_by_environment',json.dumps(self.mcp('google_app_setup_begin')[1]))

    def test_deposit_once_encrypts_no_echo_and_status_readback(self):
        begin=self.begin();token=begin['intake_url'].split('#')[1]
        self.assertEqual(begin['expires_in'],1800)
        self.assertNotIn(token,json.dumps(self.b.setup_pending))
        self.assertEqual(self.post(token)[:2],(200,{'ok':True}))
        self.assertTrue(self.b.setup_status(begin['redirect_uri'])['configured'])
        self.assertNotIn(self.payload['client_secret'].encode(),self.b.store.path.read_bytes())
        self.assertEqual(self.post(token)[0],403)
        for method in ('google_app_setup_status','google_app_setup_begin'):
            raw=json.dumps(self.mcp(method)[1]);self.assertNotIn(self.payload['client_secret'],raw);self.assertNotIn(self.payload['client_id'],raw)

    def test_expired_wrong_reissued_restart_and_concurrent_single_use(self):
        begin=self.begin();token=begin['intake_url'].split('#')[1]
        self.assertEqual(self.post('x'*43)[0],403)
        self.b.setup_pending[hashlib.sha256(token.encode()).hexdigest()]['expires']=0
        self.assertEqual(self.post(token)[0],403)
        old=self.begin()['intake_url'].split('#')[1];new=self.begin()['intake_url'].split('#')[1]
        self.assertEqual(self.post(old)[0],403)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            codes=list(ex.map(lambda _:self.post(new)[0],range(2)))
        self.assertEqual(sorted(codes),[200,403])
        from google_broker import Broker,Denied
        restored=Broker(self.config,self.fake)
        with self.assertRaises(Denied):restored.setup_deposit(new,**self.payload)

    def test_malformed_credentials_consumed_no_secret_in_responses_or_logs(self):
        for invalid in ({'client_id':'malformed'},{'client_secret':'bad secret'},{'client_secret':None}):
            token=self.begin()['intake_url'].split('#')[1]
            logs=io.StringIO()
            with contextlib.redirect_stderr(logs),contextlib.redirect_stdout(logs):
                code,body,_=self.post(token,{**self.payload,**invalid})
            self.assertEqual(code,400);self.assertEqual(self.post(token)[0],403)
            self.assertNotIn('FAKE_INTAKE_SECRET',json.dumps(body)+logs.getvalue())
            self.assertNotIn('bad secret',json.dumps(body)+logs.getvalue())
        token=self.begin()['intake_url'].split('#')[1]
        self.assertEqual(self.post(token,{**self.payload,'redirect_uri':'https://evil.invalid'})[0],400)
        self.assertEqual(self.post(token,Origin='https://console.cloud.google.com')[0],403)
        self.assertEqual(self.post(token,**{'X-Forwarded-Host':'owner.example'})[0],403)
        self.assertEqual(self.post('o'*40)[0],403)  # Owner/MCP token is not an intake capability.
        self.assertEqual(self.post('m'*40)[0],403)

    def test_storage_failure_no_success_and_no_capability_replay(self):
        token=self.begin()['intake_url'].split('#')[1]
        with patch.object(self.b.store,'save',side_effect=OSError('FAKE failure')):
            self.assertEqual(self.post(token)[0],400)  # RPC reports safe storage failure.
        self.assertEqual(self.post(token)[0],403)
        self.assertFalse(self.b.client_status()['client_configured'])

    def test_script_direct_deposit_and_url_allowlist(self):
        token=self.begin()['intake_url'].split('#')[1]
        url=self.base+'/api/google/setup/intake#'+token
        script.deposit(url,self.payload)
        self.assertTrue(self.b.client_status()['client_configured'])
        for bad in ('https://evil.invalid/api/google/setup/intake#'+token,
                    'http://localhost/api/google/setup/intake?token='+token,
                    'http://localhost@evil.invalid/api/google/setup/intake#'+token):
            with self.assertRaises(script.NeedsOwner):script.intake_target(bad)

    def test_public_ingress_blocks_intake_even_with_valid_capability(self):
        import ingress
        s=ThreadingHTTPServer(('127.0.0.1',0),ingress.Ingress)
        threading.Thread(target=s.serve_forever,daemon=True).start()
        try:
            old=self.base;self.base='http://127.0.0.1:'+str(s.server_port)
            self.owner_client()
            self.assertEqual(self.post('x'*43,Host='owner.example')[0],403)
            self.assertEqual(self.post('x'*43,**{'X-Forwarded-Host':'owner.example'})[0],403)
        finally:self.base=old;s.shutdown();s.server_close()
