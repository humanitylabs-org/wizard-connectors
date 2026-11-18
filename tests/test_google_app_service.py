"""The Google app (wizard-google) on the Connected accounts sign-in: /service/google/v1 (wizard-google#20).

Real handlers, RPC and broker; fake Google (no network, no real account).
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_google_workspace import GoogleWorkspaceTests  # noqa: E402


class GoogleAppServiceTests(GoogleWorkspaceTests):
    def google(self, tool, data=None, agent='main', grant=None):
        h = {**(grant or self.grant(caller='wizard-google')), 'Host': 'wizard-connectors-calendar:8799'}
        if agent is not None: h['X-Wizard-Agent'] = agent
        if tool == 'status':
            return self.req('/service/google/v1/status', owner=False, headers=h)
        return self.req('/service/google/v1/' + tool, data if data is not None else {}, owner=False, headers=h)

    def test_only_the_google_app_and_only_while_the_switch_is_on(self):
        self.assertEqual(self.google('status', grant={'X-Wizard-Grant': 'WRONG'})[0], 403)
        mail = self.grant(caller='wizard-mail')
        self.assertEqual(self.google('drive_search', grant=mail)[1]['error']['code'], 'google_grant_required')
        code, res, _ = self.google('drive_search')
        self.assertEqual((code, res['error']['code']), (409, 'service_off'))
        self.switch(True)
        self.assertEqual(self.google('status', agent=None)[1]['error']['code'], 'caller_unknown')
        self.assertEqual(self.google('mail_send', {'draft_id': 'd1'})[0], 404)  # agents never send
        self.assertEqual(self.google('google_accounts')[0], 404)

    def test_google_app_lists_drive_reads_doc_finds_contact_and_drafts(self):
        # wizard-google#20 done-when, on this side: only a Connected accounts sign-in, no Google app sign-in.
        self.switch(True)
        self.allow(workspace=True, gmail=True)
        code, status, _ = self.google('status')
        self.assertEqual(code, 200, status)
        self.assertEqual(status['accounts'][0]['services'], ['gmail', 'drive', 'contacts'])
        self.assertNotIn('FAKE_ACCESS_SECRET', json.dumps(status))
        files = self.google('drive_search', {'query': 'plan'})[1]
        self.assertEqual((files['files'][0]['id'], files['via']), ('doc1', 'connected-accounts'))
        self.assertEqual(self.google('drive_read', {'file_id': 'doc1'})[1]['text'], 'FAKE doc text')
        self.assertEqual(self.google('contacts_search', {'query': 'Ada'})[1]['contacts'][0]['name'], 'FAKE Ada')
        draft = self.google('mail_draft', {'to': ['a@example.invalid'], 'subject': 'Hi', 'body': 'Hello'})[1]
        self.assertEqual((draft['sent'], draft['draft']['id']), (False, 'd1'))
        self.assertIn('messages', self.google('mail_search', {})[1])

    def test_owner_mail_level_and_plain_errors(self):
        self.switch(True)
        self.allow(workspace=True, gmail=True)
        self.assertEqual(self.req('/api/mail/access', {'level': 'read_only'})[1]['level'], 'read_only')
        code, res, _ = self.google('mail_draft', {'to': ['a@example.invalid'], 'subject': 'Hi'}, agent='Helper')
        self.assertEqual((code, res['error']['code']), (403, 'agent_access_denied'))
        code, res, _ = self.google('drive_read', {'file_id': '../x'})
        self.assertEqual((code, res['error']['code']), (400, 'invalid_arguments'))
        code, res, _ = self.google('drive_search', {'account': 'nobody@example.invalid'})
        self.assertEqual((code, res['error']['code']), (404, 'account_not_found'))


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name in loader.getTestCaseNames(GoogleAppServiceTests):
        if name in GoogleAppServiceTests.__dict__:
            suite.addTest(GoogleAppServiceTests(name))
    return suite


if __name__ == '__main__':
    unittest.main()
