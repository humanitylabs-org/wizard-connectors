"""Gmail for Mail (wizard-connectors#15): real handlers, RPC and broker; fake Google (no network, no real account)."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_google_http import BrokerHTTPTests, FakeGoogle  # noqa: E402
from google_broker import GMAIL_SCOPE, Denied, GoogleTransport  # noqa: E402

GMAIL = 'https://gmail.googleapis.com/gmail/v1/users/me'


class FakeGmail(FakeGoogle):
    def __init__(self):
        super().__init__()
        self.gmail_calls = []
        self.gmail_error = None

    def gmail(self, method, url, token, query=None, body=None):
        self.gmail_calls.append((method, url, query, body, token))
        if self.gmail_error: raise Denied(self.gmail_error)
        if url == GMAIL + '/messages' and method == 'GET':
            return {'messages': [{'id': 'm1'}], 'nextPageToken': None}
        if url == GMAIL + '/messages/m1' and method == 'GET':
            return {'id': 'm1', 'threadId': 't1', 'labelIds': ['INBOX', 'UNREAD'], 'snippet': 'FAKE hello',
                    'payload': {'headers': [{'name': 'From', 'value': 'Fake <fake@example.invalid>'},
                                            {'name': 'Subject', 'value': 'FAKE subject'}]}}
        if url == GMAIL + '/drafts' and method == 'POST':
            return {'id': 'd1', 'message': {'id': 'm2', 'threadId': 't2'}}
        if url == GMAIL + '/drafts/send':
            return {'id': 'm2', 'threadId': 't2'}
        raise AssertionError((method, url))


class GmailForMailTests(BrokerHTTPTests):
    def setUp(self):
        super().setUp()
        self.fake = FakeGmail()
        self.b.provider = self.fake
        Path(os.environ['DATA_DIR']).mkdir(parents=True, exist_ok=True)

    def switch(self, on):
        (Path(os.environ['DATA_DIR']) / 'switches.json').write_text(json.dumps({'gmail-for-mail': on}))

    def connect_gmail(self):
        code, res, h = self.req('/api/google/connect', {'gmail': True})
        self.assertEqual(code, 200, res)
        self.cookie = h['Set-Cookie'].split(';')[0]
        from urllib.parse import parse_qs, urlsplit
        params = {k: v[0] for k, v in parse_qs(urlsplit(res['authorization_url']).query).items()}
        self.assertIn(GMAIL_SCOPE, params['scope'].split())
        self.fake.nonce = params['nonce']; self.fake.scopes = set(params['scope'].split())
        self.assertEqual(self.finish(params)[0], 200)

    def mail(self, tool, data=None, who=None, grant=None):
        h = {**(grant or self.grant(caller='wizard-mail')), **(who or {'X-Wizard-Owner': '1'}),
             'Host': 'wizard-connectors-calendar:8799'}
        if data is None and tool == 'status':
            return self.req('/service/mail/v1/status', owner=False, headers=h)
        return self.req('/service/mail/v1/' + tool, data if data is not None else {}, owner=False, headers=h)

    def test_off_by_default_no_gmail_scope_no_service(self):
        self.assertFalse(self.req('/api/state')[1]['mail']['on'])
        self.assertEqual(self.req('/api/google/connect', {'gmail': True})[1]['error'], 'service_off')
        code, body, _ = self.mail('status')
        self.assertEqual((code, body['error']['code']), (409, 'service_off'))
        # Off: Calendar's plain Connect never asks Google for Gmail.
        self.assertNotIn(GMAIL_SCOPE, self.start(False)['scope'])

    def test_grant_required_and_only_from_mail(self):
        self.switch(True)
        self.assertEqual(self.mail('status', grant={'X-Wizard-Grant': 'WRONG'})[0], 403)
        calendar = self.grant(caller='wizard-calendar')
        self.assertEqual(self.req('/service/mail/v1/status', owner=False, headers={**calendar, 'X-Wizard-Owner': '1'})[0], 403)
        self.assertEqual(self.mail('status', who={'X-Other': '1'})[0], 400)  # neither owner nor agent named

    def test_owner_reads_searches_drafts_and_sends_through_connected_account(self):
        self.switch(True); self.connect_gmail()
        code, status, _ = self.mail('status')
        self.assertEqual(code, 200)
        self.assertEqual(status['accounts'], [{'email': 'fixture@example.invalid', 'status': 'active', 'services': ['gmail'], 'via': 'own-client'}])
        self.assertIn('mail_send', status['mail_calendar']['tools'])
        self.assertEqual(status['mail_access']['level'], 'draft_only')
        self.assertNotIn('FAKE_ACCESS_SECRET', json.dumps(status))
        code, found, _ = self.mail('mail_search', {'account': 'fixture@example.invalid', 'folder': 'inbox', 'max': 5})
        self.assertEqual(code, 200, found)
        self.assertEqual(found['messages'][0]['subject'], 'FAKE subject')
        self.assertEqual((found['contract'], found['source'], found['via']), ('wizard.mail-calendar/1', 'google', 'own-client'))
        self.assertEqual(self.fake.gmail_calls[0][2]['q'], 'in:inbox')
        self.assertEqual(self.fake.gmail_calls[0][4], 'FAKE_ACCESS_SECRET')  # the broker's own token, never the caller's
        code, draft, _ = self.mail('mail_draft', {'to': ['a@example.invalid'], 'subject': 'Hi', 'body': 'Hello'})
        self.assertEqual((code, draft['sent'], draft['draft']['id']), (200, False, 'd1'))
        self.assertEqual(self.mail('mail_send', {'draft_id': 'd1'})[1]['sent'], True)

    def test_agents_keep_the_owner_level_and_never_send(self):
        self.switch(True); self.connect_gmail()
        agent = {'X-Wizard-Agent': 'main'}
        self.assertNotIn('mail_send', self.mail('status', who=agent)[1]['mail_calendar']['tools'])
        code, body, _ = self.mail('mail_send', {'draft_id': 'd1'}, who=agent)
        self.assertEqual((code, body['error']['code']), (403, 'agent_send_refused'))
        self.assertEqual(self.mail('mail_draft', {'to': ['a@example.invalid'], 'subject': 'Hi'}, who=agent)[0], 200)
        self.assertEqual(self.mail('agent_access', {'mail': 'no_access'}, who=agent)[0], 403)
        self.assertEqual(self.req('/api/mail/access', {'level': 'read_only'})[1]['level'], 'read_only')
        self.assertEqual(self.mail('mail_draft', {'to': ['a@example.invalid'], 'subject': 'Hi'}, who=agent)[1]['error']['code'], 'agent_access_denied')
        self.assertEqual(self.mail('mail_search', {}, who=agent)[0], 200)
        self.assertEqual(self.mail('agent_access', {'mail': 'no_access'})[1]['agent_access']['level'], 'no_access')
        self.assertEqual(self.mail('mail_search', {}, who=agent)[1]['error']['code'], 'agent_access_denied')

    def test_account_without_gmail_and_missing_api_are_plain_errors(self):
        self.switch(True); self.calendar_connect()
        status = self.mail('status')[1]
        self.assertEqual(status['accounts'][0]['services'], [])
        self.assertEqual(self.mail('mail_search', {'account': 'fixture@example.invalid'})[1]['error']['code'], 'permission_missing')
        self.assertEqual(self.mail('mail_search', {})[1]['error']['code'], 'not_connected')
        self.connect_gmail()
        self.fake.gmail_error = 'google_permission_missing'
        code, body, _ = self.mail('mail_search', {})
        self.assertEqual((code, body['error']['code']), (403, 'google_permission_missing'))
        self.assertEqual(self.b.status()['accounts'][0]['status'], 'active')  # Gmail API off is not a sign-out
        self.fake.gmail_error = None
        code, body, _ = self.mail('mail_search', {'max': 99})
        self.assertEqual((code, body['error']['code']), (400, 'invalid_arguments'))
        self.assertIn('max', body['error']['message'])

    def test_connect_from_mail_one_allow_turns_gmail_for_mail_on(self):
        # wizard-connectors#21: the owner's tap in Mail starts Google's sign-in with the Gmail scope, no switch to find.
        self.assertFalse(self.req('/api/state')[1]['mail']['on'])
        code, out, _ = self.mail('connect', {})
        self.assertEqual(code, 200, out)
        from urllib.parse import parse_qs, urlsplit
        self.assertTrue(out['authorization_url'].startswith('https://accounts.google.com/'))
        params = {k: v[0] for k, v in parse_qs(urlsplit(out['authorization_url']).query).items()}
        self.assertIn(GMAIL_SCOPE, params['scope'].split())
        self.assertTrue(self.req('/api/state')[1]['mail']['on'])  # the tap turned Gmail for Mail on
        self.fake.nonce = params['nonce']; self.fake.scopes = set(params['scope'].split())
        self.cookie = ''  # finished in another window: the single-use state binds it, not a cookie
        self.assertEqual(self.finish(params)[0], 200)  # Google's Allow: the owner's only step
        status = self.mail('status')[1]
        self.assertEqual(status['accounts'][0]['services'], ['gmail'])
        self.assertEqual(self.mail('mail_search', {})[0], 200)

    def test_connect_from_mail_is_the_owners_tap_only(self):
        self.assertEqual(self.mail('connect', {}, grant={'X-Wizard-Grant': 'WRONG'})[0], 403)
        calendar = self.grant(caller='wizard-calendar')
        self.assertEqual(self.req('/service/mail/v1/connect', {}, owner=False, headers={**calendar, 'X-Wizard-Owner': '1'})[0], 403)
        code, body, _ = self.mail('connect', {}, who={'X-Wizard-Agent': 'main'})
        self.assertEqual((code, body['error']['code']), (403, 'owner_only'))
        self.assertEqual(self.mail('connect', {}, who={'X-Wizard-Agent': 'main', 'X-Wizard-Owner': '1'})[0], 403)
        self.assertEqual(self.mail('connect', {'account': 'x'})[0], 400)
        self.assertFalse(self.req('/api/state')[1]['mail']['on'])  # none of these turned anything on

    def test_connect_from_mail_without_a_google_app_turns_nothing_on(self):
        del self.config['GOOGLE_CLIENT_SECRET']
        code, body, _ = self.mail('connect', {})
        self.assertEqual((code, body['error']['code']), (409, 'google_configuration_required'))
        self.assertFalse(self.req('/api/state')[1]['mail']['on'])

    def test_transport_stays_on_gmail_users_me(self):
        t = GoogleTransport()
        for url in ('https://evil.invalid/gmail/v1/users/me/messages', GMAIL + '/../x', GMAIL + '/messages?x=1',
                    'https://gmail.googleapis.com/gmail/v1/users/other/messages'):
            with self.assertRaises(Denied): t.gmail('GET', url, 'tok')
        with self.assertRaises(Denied): t.gmail('DELETE', GMAIL + '/messages/m1', 'tok')


def load_tests(loader, tests, pattern):
    # Only this file's tests (the base class's own tests run in test_google_http).
    suite = unittest.TestSuite()
    for name in loader.getTestCaseNames(GmailForMailTests):
        if name in GmailForMailTests.__dict__:
            suite.addTest(GmailForMailTests(name))
    return suite


if __name__ == '__main__':
    unittest.main()
