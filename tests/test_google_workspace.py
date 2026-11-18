"""Google tools for the agent on the Connected accounts sign-in (wizard-connectors#27, switch google-workspace).

Real handlers, RPC and broker; fake Google (no network, no real account).
"""
import json
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_google_http import BrokerHTTPTests  # noqa: E402
from test_gmail_for_mail import FakeGmail  # noqa: E402
from google_broker import DRIVE_SCOPE, CONTACTS_SCOPE, GMAIL_SCOPE, Denied, GoogleTransport  # noqa: E402

DRIVE = 'https://www.googleapis.com/drive/v3/files'
PEOPLE = 'https://people.googleapis.com/v1/people:searchContacts'
DOC = 'application/vnd.google-apps.document'


class FakeWorkspace(FakeGmail):
    def __init__(self):
        super().__init__()
        self.workspace_calls = []
        self.workspace_error = None

    def workspace(self, url, token, query=None, raw=False):
        self.workspace_calls.append((url, query, raw, token))
        if self.workspace_error: raise Denied(self.workspace_error)
        if url == DRIVE:
            return {'files': [{'id': 'doc1', 'name': 'FAKE plan', 'mimeType': DOC, 'modifiedTime': '2026-11-18T09:00:00Z',
                               'webViewLink': 'https://docs.google.com/document/d/doc1/edit'}]}
        if url == DRIVE + '/doc1':
            return {'id': 'doc1', 'name': 'FAKE plan', 'mimeType': DOC}
        if url == DRIVE + '/doc1/export':
            assert raw and query == {'mimeType': 'text/plain'}
            return 'FAKE doc text'
        if url == DRIVE + '/pic':
            return {'id': 'pic', 'name': 'FAKE.png', 'mimeType': 'image/png'}
        if url == PEOPLE:
            if not query['query']: return {}
            return {'results': [{'person': {'names': [{'displayName': 'FAKE Ada'}],
                                            'emailAddresses': [{'value': 'ada@example.invalid'}],
                                            'phoneNumbers': [{'value': '+1 555 0100'}]}}]}
        raise AssertionError(url)


class GoogleWorkspaceTests(BrokerHTTPTests):
    def setUp(self):
        super().setUp()
        self.fake = FakeWorkspace()
        self.b.provider = self.fake
        Path(os.environ['DATA_DIR']).mkdir(parents=True, exist_ok=True)

    def switch(self, on):
        (Path(os.environ['DATA_DIR']) / 'switches.json').write_text(json.dumps({'google-workspace': on}))

    def allow(self, **flags):
        code, res, h = self.req('/api/google/connect', flags)
        self.assertEqual(code, 200, res)
        self.cookie = h['Set-Cookie'].split(';')[0]
        params = {k: v[0] for k, v in parse_qs(urlsplit(res['authorization_url']).query).items()}
        self.fake.nonce = params['nonce']; self.fake.scopes = set(params['scope'].split())
        self.assertEqual(self.finish(params)[0], 200)
        return params['scope'].split()

    def mcp(self, name, args=None, method='tools/call'):
        body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': {'name': name, 'arguments': args or {}}}
        code, res, _ = self.req('/mcp', body, owner=False, headers={'Authorization': 'Bearer ' + 'm' * 40})
        self.assertEqual(code, 200, res)
        if method != 'tools/call': return res['result']
        if 'error' in res: return res['error']
        return json.loads(res['result']['content'][0]['text'])

    def tool_names(self):
        return [t['name'] for t in self.mcp(None, method='tools/list')['tools']]

    def test_off_by_default_no_tools_no_scopes(self):
        self.assertFalse(self.req('/api/state')[1]['workspace']['on'])
        self.assertNotIn('google_drive_search', self.tool_names())
        self.assertEqual(self.mcp('google_drive_search')['error']['code'], 'service_off')
        self.assertEqual(self.req('/api/google/connect', {'workspace': True})[1]['error'], 'service_off')
        self.assertNotIn(DRIVE_SCOPE, self.start(False)['scope'])

    def test_one_allow_then_agent_lists_drive_reads_doc_finds_contact_and_drafts(self):
        # The issue's acceptance, on a box with only a Connected accounts sign-in and fake Google.
        self.switch(True)
        self.assertIn('google_drive_read', self.tool_names())
        scopes = self.allow(workspace=True, gmail=True)
        self.assertTrue({DRIVE_SCOPE, CONTACTS_SCOPE, GMAIL_SCOPE} <= set(scopes))
        accounts = self.mcp('google_accounts')
        self.assertEqual(accounts['accounts'][0]['services'], ['gmail', 'drive', 'contacts'])
        self.assertNotIn('FAKE_ACCESS_SECRET', json.dumps(accounts))
        files = self.mcp('google_drive_search', {'query': "it's"})
        self.assertEqual(files['files'][0]['name'], 'FAKE plan')
        q = self.fake.workspace_calls[0][1]['q']
        self.assertIn("name contains 'it\\'s'", q)
        self.assertNotIn('orderBy', self.fake.workspace_calls[0][1])
        self.assertEqual(self.fake.workspace_calls[0][3], 'FAKE_ACCESS_SECRET')  # broker's own token
        doc = self.mcp('google_drive_read', {'file_id': 'doc1'})
        self.assertEqual((doc['text'], doc['untrusted'], doc['truncated']), ('FAKE doc text', True, False))
        self.assertIsNone(self.mcp('google_drive_read', {'file_id': 'pic'})['text'])
        people = self.mcp('google_contacts_search', {'query': 'Ada'})
        self.assertEqual(people['contacts'][0]['emails'], ['ada@example.invalid'])
        self.assertEqual(self.fake.workspace_calls[-2][1]['query'], '')  # warm-up search first
        draft = self.mcp('google_mail_draft', {'to': ['a@example.invalid'], 'subject': 'Hi', 'body': 'Hello'})
        self.assertEqual((draft['sent'], draft['draft']['id']), (False, 'd1'))
        self.assertNotIn('google_mail_send', self.tool_names())  # agents never send

    def test_mail_keeps_the_owners_level_and_missing_allow_is_plain(self):
        self.switch(True)
        self.allow(calendar=True)
        self.assertEqual(self.mcp('google_drive_search')['error']['code'], 'not_connected')
        self.assertEqual(self.mcp('google_drive_search', {'account': 'fixture@example.invalid'})['error']['code'],
                         'permission_missing')
        self.allow(workspace=True, gmail=True)
        self.assertEqual(self.req('/api/mail/access', {'level': 'read_only'})[1]['level'], 'read_only')
        self.assertEqual(self.mcp('google_mail_draft', {'to': ['a@example.invalid'], 'subject': 'Hi'})['error']['code'],
                         'agent_access_denied')
        self.assertIn('messages', self.mcp('google_mail_search', {}))
        self.assertEqual(self.mcp('google_drive_read', {'file_id': '../x'})['error']['code'], 'invalid_arguments')
        self.assertEqual(self.mcp('google_drive_search', {'nope': 1})['error']['code'], 'invalid_arguments')
        self.fake.workspace_error = 'google_permission_missing'
        err = self.mcp('google_drive_search')['error']
        self.assertEqual(err['code'], 'google_permission_missing')
        self.assertIn('Drive API', err['message'])
        self.assertEqual(self.b.status()['accounts'][0]['status'], 'active')  # API off is not a sign-out

    def test_transport_stays_on_fixed_read_only_endpoints(self):
        t = GoogleTransport()
        for url in ('https://evil.invalid/drive/v3/files', DRIVE + '/../x', DRIVE + '/a?x=1', DRIVE + 'x',
                    'https://people.googleapis.com/v1/people/me', PEOPLE + '/x', DRIVE + '/a%2F..'):
            with self.assertRaises(Denied): t.workspace(url, 'tok')


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name in loader.getTestCaseNames(GoogleWorkspaceTests):
        if name in GoogleWorkspaceTests.__dict__:
            suite.addTest(GoogleWorkspaceTests(name))
    return suite


if __name__ == '__main__':
    unittest.main()
