"""Owner agreements: HTTP/RPC/encrypted persistence + FAKE Console controls (no browser)."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_google_http as fixtures
from test_google_setup import script
from google_agreements import IDS, VERSION

spec = importlib.util.spec_from_file_location('console_fixture', Path(__file__).resolve().parents[1]/'qa/google_console_fixture.py')
fake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fake)


class AgreementsHTTPTests(unittest.TestCase):
    setUp = fixtures.BrokerHTTPTests.setUp
    tearDown = fixtures.BrokerHTTPTests.tearDown
    req = fixtures.BrokerHTTPTests.req

    def payload(self): return {'agreements': sorted(IDS), 'version': VERSION, 'country': 'GB'}

    def test_owner_auth_origin_and_cross_site_checks(self):
        path='/api/google/agreements'
        self.assertEqual(self.req(path,self.payload(),owner=False)[0],401)
        self.assertEqual(self.req(path,self.payload(),owner=False,headers={'Authorization':'Bearer '+'m'*40})[0],401)
        for headers in ({'Origin':'https://evil.invalid'}, {'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.req(path,self.payload(),headers=headers)[0],403)
        self.assertEqual(self.b.agreement_status()['accepted'],[])
        self.assertEqual(self.req(path,self.payload(),headers={'Origin':self.base})[0],200)

    def test_validation_no_partial_unknown_version_country_or_extra_fields(self):
        bad=[{'agreements':['cloud_terms']}, {'agreements':list(IDS)+['new_terms']},
             {'agreements':['cloud_terms']*3}, {'agreements':'all'}, {'agreements':[{}, 'api_terms','user_data_policy']},
             {'version':'google-next'}, {'country':''}, {'country':'ZZ'}, {'country':'gb'}, {'country':[]},
             {'accepted_at':'2020-01-01'}, {'marketing':True}]
        for change in bad:
            with self.subTest(change=change):
                self.assertIn(self.req('/api/google/agreements',{**self.payload(),**change})[0],(400,409))
                self.assertEqual(self.b.agreement_status()['accepted'],[])

    def test_encrypted_persistence_restart_readback_mcp_and_client_clear(self):
        code,result,_=self.req('/api/google/agreements',self.payload());self.assertEqual(code,200)
        self.assertEqual(result,{'accepted':sorted(IDS),'version':VERSION,'country':'GB'})
        restored=fixtures.Broker(self.config,self.fake)
        self.assertEqual(restored.agreement_status(),result)
        self.assertIn('accepted_at',restored.state['agreements'])
        self.assertNotIn(VERSION.encode(),restored.store.path.read_bytes())
        self.assertEqual(self.req('/api/state')[1]['google']['agreements'],result)
        for k in ('GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_REDIRECT_URI'): self.config.pop(k,None)
        for tool in ('google_app_setup_status','google_app_setup_begin'):
            data=self.req('/mcp',{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':tool,'arguments':{}}},owner=False,headers={'Authorization':'Bearer '+'m'*40})[1]
            self.assertEqual(json.loads(data['result']['content'][0]['text'])['agreements'],result)
        self.assertEqual(self.req('/api/google/client',method='DELETE')[0],200)
        self.assertEqual(self.b.agreement_status(),result)

    def test_failed_storage_is_not_accepted(self):
        with patch.object(self.b.store,'save',side_effect=OSError('fixture failure')):
            self.assertNotEqual(self.req('/api/google/agreements',self.payload())[0],200)
        self.assertEqual(self.b.agreement_status()['accepted'],[])

    def test_fresh_same_host_redirect_prefix_and_existing_saved_redirect(self):
        for k in ('GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_REDIRECT_URI'): self.config.pop(k,None)
        with patch.object(self.ui,'HOSTS',{'box.example.invalid'}),patch.object(self.ui,'ORIGINS',set()):
            state=self.req('/api/state',headers={'Host':'box.example.invalid','Origin':'https://box.example.invalid'})[1]
            self.assertEqual(state['google']['suggested_redirect_uri'],'https://box.example.invalid/connected-accounts/api/google/callback')
            state=self.req('/api/state',headers={'Host':'box.example.invalid','X-Forwarded-Prefix':'/custom-route'})[1]
            self.assertEqual(state['google']['suggested_redirect_uri'],'https://box.example.invalid/custom-route/api/google/callback')
        legacy='https://box.example.invalid/wizard-connectors/api/google/callback'
        self.b.save_client('fixture.apps.googleusercontent.com','FIXTURE_SECRET',legacy)
        self.assertEqual(self.b.setup_status('https://box.example.invalid/connected-accounts/api/google/callback')['redirect_uri'],legacy)
        self.assertEqual(fixtures.Broker(self.config,self.fake).client_status()['redirect_uri'],legacy)

    def test_matching_attacker_host_origin_and_empty_allowlist_fail_closed(self):
        for hosts in (set(), self.ui.LOCAL_HOSTS):
            with patch.object(self.ui,'HOSTS',hosts),patch.object(self.ui,'ORIGINS',set()):
                for path in ('/api/state','/api/google/agreements'):
                    body=self.payload() if path.endswith('/agreements') else None
                    code,result,_=self.req(path,body,headers={'Host':'rebinding.example.invalid','Origin':'http://rebinding.example.invalid'})
                    self.assertEqual((code,result),(403,{'error':'host_denied'}))


class ConsoleAgreementTests(unittest.TestCase):
    def console(self, page, data=None, **kw): return script.Console(page,agreements=copy.deepcopy(fake.AGREEMENTS if data is None else data),**kw)

    def test_recorded_cloud_terms_country_marketing_declined(self):
        page=fake.FakeConsolePage(link='https://cloud.google.com/terms')
        self.console(page).gate()
        self.assertEqual(page.country,'GB')
        self.assertTrue(page.submitted['I agree to the Google Cloud Terms of Service'])
        self.assertFalse(page.submitted['Email updates'])

    def test_api_terms_and_user_data_policy_exact_checkbox_labels(self):
        for name in ('I agree to the Google APIs Terms of Service','I agree to the Google API Services: User Data Policy.',
                     'I agree to the Google APIs Terms of Service and the Google API Services User Data Policy'):
            page=fake.FakeConsolePage(labels=[name],submit=False,country=False)
            self.console(page).gate();self.assertTrue(page.items[1].values['checked'])

    def test_unrecorded_unknown_and_changed_documents_stop_before_any_acceptance(self):
        cases=[(fake.FakeConsolePage(),{**fake.AGREEMENTS,'accepted':['api_terms','user_data_policy']}),
               (fake.FakeConsolePage(labels=['I agree to the Google Cloud Terms of Service','I agree to New Terms']),fake.AGREEMENTS),
               (fake.FakeConsolePage(link='https://cloud.google.com/new-terms'),fake.AGREEMENTS),
               (fake.FakeConsolePage(labels=['I agree to the Google Cloud Terms of Service and pay a fee']),fake.AGREEMENTS)]
        for page,data in cases:
            with self.assertRaises(script.NeedsOwner):self.console(page,data).gate()
            self.assertIsNone(page.submitted)
            self.assertFalse(page.get_by_role('checkbox').first.is_checked())

    def test_no_checkbox_cloud_form_requires_exact_document_link(self):
        page=fake.FakeConsolePage(labels=['Email updates'],link='https://cloud.google.com/terms')
        self.console(page).gate();self.assertFalse(page.submitted['Email updates'])
        page=fake.FakeConsolePage(labels=['Email updates'])
        with self.assertRaises(script.NeedsOwner):self.console(page).gate()
        self.assertIsNone(page.submitted)

    def test_missing_cloud_country_stops_and_marketing_is_declined_without_legal_submit(self):
        page=fake.FakeConsolePage(country=False)
        with self.assertRaisesRegex(script.NeedsOwner,'country_control_changed'):self.console(page).gate()
        self.assertFalse(page.get_by_role('checkbox').first.is_checked())
        page=fake.FakeConsolePage(labels=['Email updates'],submit=False,country=False,heading='Google Cloud')
        self.console(page).gate()
        self.assertFalse(page.get_by_role('checkbox').first.is_checked())
        self.assertIsNone(page.submitted)

    def test_missing_wrong_version_or_malformed_records_stop(self):
        for data in ({},'not-json', {**fake.AGREEMENTS,'version':'google-old'},
                     {**fake.AGREEMENTS,'country':'ZZ'}, {**fake.AGREEMENTS,'accepted':['cloud_terms']*2}):
            page=fake.FakeConsolePage()
            with self.assertRaises(script.NeedsOwner):self.console(page,data).gate()
            self.assertIsNone(page.submitted)

    def test_identity_billing_unknown_origin_and_dry_run_never_accept(self):
        for heading in ('Verify your identity','Set up billing','Start free trial'):
            page=fake.FakeConsolePage(heading=heading)
            with self.assertRaises(script.NeedsOwner):self.console(page).gate()
            self.assertFalse(page.get_by_role('checkbox').first.is_checked())
        for url in ('https://accounts.google.com/signin','https://evil.invalid/console'):
            page=fake.FakeConsolePage();page.url=url
            with self.assertRaises(script.NeedsOwner):self.console(page).gate()
            self.assertIsNone(page.submitted)
        page=fake.FakeConsolePage()
        with self.assertRaises(script.NeedsOwner):self.console(page,allow_accept=False).gate()
        self.assertIsNone(page.submitted)
