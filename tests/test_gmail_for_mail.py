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
        if url == GMAIL + '/messages/m3' and method == 'GET':  # an iPhone photo email (wizard-mail#32)
            return {'id': 'm3', 'threadId': 't3', 'labelIds': ['INBOX'], 'snippet': '',
                    'payload': {'mimeType': 'multipart/mixed', 'partId': '', 'headers': [{'name': 'Subject', 'value': 'Photo'}], 'parts': [
                        {'partId': '0', 'mimeType': 'text/html', 'filename': '', 'headers': [],
                         'body': {'size': 40, 'data': 'PGRpdj48aW1nIHNyYz0iY2lkOnBob3RvMSI-PC9kaXY-'}},
                        {'partId': '1', 'mimeType': 'image/jpeg', 'filename': 'IMG_7215.jpeg',
                         'headers': [{'name': 'Content-ID', 'value': '<photo1>'}, {'name': 'Content-Disposition', 'value': 'inline; filename=IMG_7215.jpeg'}],
                         'body': {'size': 6, 'attachmentId': 'ATT-1'}},
                        {'partId': '2', 'mimeType': 'image/png', 'filename': '',
                         'headers': [{'name': 'Content-ID', 'value': '<logo@x>'}], 'body': {'size': 3, 'data': 'UE5H'}},
                        {'partId': '3', 'mimeType': 'application/pdf', 'filename': 'big.pdf', 'headers': [],
                         'body': {'size': 26 * 1024 * 1024, 'attachmentId': 'ATT-2'}}]}}
        if url == GMAIL + '/messages/m3/attachments/ATT-1' and method == 'GET':
            return {'size': 6, 'data': 'SlBFR3h4'}
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

    def test_on_for_everyone_no_switch(self):
        # Approved at show-and-tell (#15): Gmail for Mail has no switch; an old saved "off" changes nothing.
        import server
        self.assertNotIn('gmail-for-mail', [s['id'] for s in server.SWITCHES])
        f = Path(os.environ['DATA_DIR']) / 'switches.json'
        f.write_text(json.dumps({'gmail-for-mail': False, 'google-workspace': False}))
        self.assertNotIn('on', self.req('/api/state')[1]['mail'])
        code, body, _ = self.mail('status')
        self.assertEqual(code, 200, body)
        self.assertEqual(self.req('/api/mail/access', {'level': 'read_only'})[1]['level'], 'read_only')
        server._sw_prune_retired()
        self.assertEqual(json.loads(f.read_text()), {'google-workspace': False})
        self.connect_gmail()  # Allow for Mail works with no switch
        # Calendar's plain Connect still never asks Google for Gmail.
        self.assertNotIn(GMAIL_SCOPE, self.start(False)['scope'])

    def test_grant_required_and_only_from_mail(self):
        self.assertEqual(self.mail('status', grant={'X-Wizard-Grant': 'WRONG'})[0], 403)
        calendar = self.grant(caller='wizard-calendar')
        self.assertEqual(self.req('/service/mail/v1/status', owner=False, headers={**calendar, 'X-Wizard-Owner': '1'})[0], 403)
        self.assertEqual(self.mail('status', who={'X-Other': '1'})[0], 400)  # neither owner nor agent named

    def test_owner_reads_searches_drafts_and_sends_through_connected_account(self):
        self.connect_gmail()
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
        self.connect_gmail()
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

    def test_owner_reads_one_attachment_agents_never_do(self):
        # wizard-mail#32 (contract 1.6): mail_get names each file's part and Content-ID; mail_attachment gives its bytes.
        self.connect_gmail()
        code, got, _ = self.mail('mail_get', {'id': 'm3'})
        self.assertEqual(code, 200, got)
        self.assertEqual(got['message']['attachments'], [
            {'name': 'IMG_7215.jpeg', 'mime': 'image/jpeg', 'size': 6, 'part': '1', 'content_id': 'photo1', 'inline': True},
            {'name': 'big.pdf', 'mime': 'application/pdf', 'size': 26 * 1024 * 1024, 'part': '3', 'content_id': None, 'inline': False}])
        self.assertEqual(got['message']['inline_parts'], [{'part': '2', 'mime': 'image/png', 'size': 3, 'content_id': 'logo@x'}])
        self.assertIn('mail_attachment', self.mail('status')[1]['mail_calendar']['tools'])
        code, one, _ = self.mail('mail_attachment', {'id': 'm3', 'part': '1'})
        self.assertEqual(code, 200, one)
        self.assertEqual(one['attachment'], {'name': 'IMG_7215.jpeg', 'mime': 'image/jpeg', 'size': 6, 'base64': 'SlBFR3h4'})
        code, logo, _ = self.mail('mail_attachment', {'id': 'm3', 'part': '2'})
        self.assertEqual((code, logo['attachment']['name'], logo['attachment']['base64']), (200, 'image.png', 'UE5H'))
        code, body, _ = self.mail('mail_attachment', {'id': 'm3', 'part': '9'})
        self.assertEqual((code, body['error']['code']), (404, 'not_found'))
        code, body, _ = self.mail('mail_attachment', {'id': 'm3', 'part': '3'})
        self.assertEqual((code, body['error']['code']), (413, 'attachment_too_big'))
        self.assertFalse(any('ATT-2' in c[1] for c in self.fake.gmail_calls))  # too big is known before any bytes move
        self.assertEqual(self.mail('mail_attachment', {'id': 'm3', 'part': '../1'})[0], 400)
        agent = {'X-Wizard-Agent': 'main'}
        self.assertNotIn('mail_attachment', self.mail('status', who=agent)[1]['mail_calendar']['tools'])
        code, body, _ = self.mail('mail_attachment', {'id': 'm3', 'part': '1'}, who=agent)
        self.assertEqual((code, body['error']['code']), (403, 'owner_only'))

    def test_account_without_gmail_and_missing_api_are_plain_errors(self):
        self.calendar_connect()
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

    def test_connect_from_mail_one_allow(self):
        # wizard-connectors#21: the owner's tap in Mail starts Google's sign-in with the Gmail scope, no switch to find.
        code, out, _ = self.mail('connect', {})
        self.assertEqual(code, 200, out)
        from urllib.parse import parse_qs, urlsplit
        self.assertTrue(out['authorization_url'].startswith('https://accounts.google.com/'))
        params = {k: v[0] for k, v in parse_qs(urlsplit(out['authorization_url']).query).items()}
        self.assertIn(GMAIL_SCOPE, params['scope'].split())
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

    def test_connect_from_mail_without_a_google_app(self):
        del self.config['GOOGLE_CLIENT_SECRET']
        code, body, _ = self.mail('connect', {})
        self.assertEqual((code, body['error']['code']), (409, 'google_configuration_required'))

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
