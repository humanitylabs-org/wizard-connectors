"""Agent access in one place (wizard-connectors#49, switch grants-panel, contract wizard.app-grants/1).

Real handlers, RPC and broker; fake Google (no network, no real account).
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_google_http import BrokerHTTPTests  # noqa: E402

SVC = {'Host': 'wizard-connectors-calendar:8799'}


class AgentGrantsTests(BrokerHTTPTests):
    def setUp(self):
        super().setUp()
        Path(os.environ['DATA_DIR']).mkdir(parents=True, exist_ok=True)

    def switch(self, on):
        (Path(os.environ['DATA_DIR']) / 'switches.json').write_text(json.dumps({'grants-panel': on}))

    def ask(self, tool, data=None, caller='wizard-mail'):
        h = {**self.grant(caller=caller), **SVC}
        return self.req('/service/grants/v1/' + tool, data, owner=False, headers=h)

    def check(self, account, action, agent='main', app=None, caller='wizard-mail'):
        body = {'agent': agent, 'account': account, 'action': action, **({'app': app} if app else {})}
        code, res, _ = self.ask('check', body, caller)
        self.assertEqual(code, 200, res)
        return res

    def test_off_by_default_everywhere(self):
        self.assertFalse(self.req('/api/state')[1]['grants_panel']['on'])
        self.assertEqual(self.req('/api/grants')[0], 409)
        self.assertEqual(self.req('/api/grants', {'account': 'x', 'agent': 'main', 'level': 'read'})[0], 409)
        code, res, _ = self.ask('check', {'agent': 'main', 'account': 'x', 'action': 'read'})
        self.assertEqual((code, res['error']['code']), (409, 'service_off'))
        import server
        sw = next(s for s in server.SWITCHES if s['id'] == 'grants-panel')
        self.assertFalse(sw['default'])
        self.assertEqual(sw['issues'], ['humanitylabs-org/wizard-connectors#49'])

    def test_owner_grants_and_apps_only_ask(self):
        self.switch(True)
        aid = 'google:' + self.connect()
        view = self.req('/api/grants')[1]
        self.assertEqual(view['contract'], 'wizard.app-grants/1')
        self.assertEqual(view['agents'], ['main'])
        google = next(a for a in view['accounts'] if a['id'] == aid)
        self.assertEqual((google['label'], google['kind'], google['agents']), ('fixture@example.invalid', 'google', {'main': 'none'}))
        self.assertEqual(google['levels'], ['none', 'read', 'draft'])  # agents never send mail
        # Nothing until granted.
        res = self.check(aid, 'read')
        self.assertEqual((res['allowed'], res['reason'], res['level']), (False, 'not_granted', 'none'))
        self.assertEqual(self.req('/api/grants', {'account': aid, 'agent': 'main', 'level': 'read'})[0], 200)
        self.assertTrue(self.check(aid, 'read')['allowed'])
        self.assertFalse(self.check(aid, 'draft')['allowed'])
        self.assertEqual(self.check(aid, 'send')['reason'], 'not_offered')
        self.assertEqual(self.req('/api/grants', {'account': aid, 'agent': 'main', 'level': 'send'})[1]['error'], 'level_not_offered')
        # Narrowed for one app: wins over the account-wide level for that app only.
        self.req('/api/grants', {'account': aid, 'agent': 'main', 'level': 'none', 'app': 'wizard-mail'})
        self.assertFalse(self.check(aid, 'read', app='wizard-mail')['allowed'])
        self.assertTrue(self.check(aid, 'read', app='wizard-calendar')['allowed'])
        # Audit: allowed and refused, who asked, no content.
        entries = self.req('/api/grants/audit')[1]['entries']
        self.assertEqual(len(entries), 6)
        self.assertEqual(entries[0], {**entries[0], 'by': 'wizard-mail', 'agent': 'main', 'action': 'read',
                                      'app': 'wizard-calendar', 'allowed': True, 'reason': 'granted'})
        self.assertEqual(sum(not e['allowed'] for e in entries), 4)
        # Unknown account is a no, not an error.
        self.assertEqual(self.check('google:nope', 'read')['reason'], 'account_unknown')

    def test_new_agent_starts_with_nothing_and_shows_up(self):
        self.switch(True)
        aid = 'google:' + self.connect()
        self.req('/api/grants', {'account': aid, 'agent': 'main', 'level': 'draft'})
        self.assertFalse(self.check(aid, 'read', agent='Ops')['allowed'])
        view = self.req('/api/grants')[1]
        self.assertEqual(view['agents'], ['main', 'ops'])
        self.assertEqual(view['accounts'][0]['agents'], {'main': 'draft', 'ops': 'none'})
        self.assertEqual(self.req('/api/grants/agents', {'agent': 'helper'})[1]['agents'], ['main', 'ops', 'helper'])
        self.assertEqual(self.req('/api/grants/agents', {'agent': '../x'})[0], 400)

    def test_connector_apps_list_their_accounts(self):
        self.switch(True)
        code, res, _ = self.ask('accounts', {'accounts': [{'id': 'whatsapp', 'kind': 'messenger', 'label': 'WhatsApp'},
                                                          {'id': 'acct-1', 'kind': 'bank', 'label': 'Checking'}]}, 'wizard-messenger')
        self.assertEqual((code, res['registered']), (200, ['wizard-messenger:acct-1', 'wizard-messenger:whatsapp']), res)
        view = self.req('/api/grants')[1]
        chat = next(a for a in view['accounts'] if a['id'] == 'wizard-messenger:whatsapp')
        self.assertEqual((chat['recommended'], chat['levels'][-1], chat['agents']['main']), ('draft', 'send', 'none'))
        bank = next(a for a in view['accounts'] if a['id'] == 'wizard-messenger:acct-1')
        self.assertEqual(bank['levels'], ['none', 'read'])
        self.req('/api/grants', {'account': chat['id'], 'agent': 'main', 'level': 'draft'})
        self.assertTrue(self.check(chat['id'], 'draft', caller='wizard-calendar')['allowed'])
        self.assertFalse(self.check(chat['id'], 'send')['allowed'])
        # A re-list replaces only that app's accounts; an app can't list Google accounts or another app's ids.
        self.ask('accounts', {'accounts': []}, 'wizard-messenger')
        self.assertEqual([a['id'] for a in self.req('/api/grants')[1]['accounts']], [])
        self.assertEqual(self.ask('accounts', {'accounts': [{'id': 'x', 'kind': 'google'}]}, 'wizard-messenger')[0], 400)
        self.assertEqual(self.ask('accounts', {'accounts': [{'id': 'a/b'}]}, 'wizard-messenger')[0], 400)

    def test_only_apps_ask_and_nobody_but_the_owner_changes(self):
        self.switch(True)
        self.grant(caller='wizard-mail')
        code, res, _ = self.req('/service/grants/v1/check', {'agent': 'main', 'account': 'x', 'action': 'read'},
                                owner=False, headers={'X-Wizard-Grant': 'WRONG', **SVC})
        self.assertEqual((code, res['error']['code']), (403, 'app_grant_required'))
        self.assertEqual(self.req('/service/grants/v1/status', owner=False, headers=SVC)[0], 403)
        # The service API has no route that sets a level.
        self.assertEqual(self.ask('set', {'account': 'x', 'agent': 'main', 'level': 'send'})[0], 404)
        self.assertEqual(self.ask('check', {'agent': 'main', 'account': 'x', 'action': 'delete'})[0], 400)
        self.assertEqual(self.ask('check', {'agent': 'main', 'account': 'x'})[0], 400)
        self.assertEqual(self.req('/api/grants', owner=False)[0], 401)
        self.assertEqual(self.req('/api/grants', {'account': 'x', 'agent': 'main', 'level': 'read'}, owner=False)[0], 401)
        # The agent's MCP has no grant tool.
        body = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
        tools = self.req('/mcp', body, owner=False, headers={'Authorization': 'Bearer ' + 'm' * 40})[1]['result']['tools']
        self.assertFalse([t for t in tools if 'grant' in t['name']])
        code, status, _ = self.ask('status')
        self.assertEqual((code, status['contract'], status['levels']), (200, 'wizard.app-grants/1', ['none', 'read', 'draft', 'send']))


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name in loader.getTestCaseNames(AgentGrantsTests):
        if name in AgentGrantsTests.__dict__:
            suite.addTest(AgentGrantsTests(name))
    return suite


if __name__ == '__main__':
    unittest.main()
