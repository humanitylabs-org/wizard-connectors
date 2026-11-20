"""Agent access in one place (wizard-connectors#49, switch grants-panel), as rescoped by Miguel on 20 Nov 2026.

The panel stores no grants: it reads and sets the Agent Service's agent.json ticks (GET/PUT
/wizard/v1/apps/<app>/agents) from the page, and Mail's level stays this app's own. Real handlers with a fake Google;
web/connections.js runs under Node against a fake Agent Service.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_google_http import BrokerHTTPTests  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SVC = {'Host': 'wizard-connectors-calendar:8799'}


class ConnectionsPanelTests(BrokerHTTPTests):
    def setUp(self):
        super().setUp()
        Path(os.environ['DATA_DIR']).mkdir(parents=True, exist_ok=True)

    def switch(self, on):
        (Path(os.environ['DATA_DIR']) / 'switches.json').write_text(json.dumps({'grants-panel': on}))

    def test_switch_off_by_default_and_linked(self):
        self.assertFalse(self.req('/api/state')[1]['grants_panel']['on'])
        import server
        sw = next(s for s in server.SWITCHES if s['id'] == 'grants-panel')
        self.assertFalse(sw['default'])
        self.assertEqual(sw['issues'], ['humanitylabs-org/wizard-connectors#49'])
        self.switch(True)
        self.assertTrue(self.req('/api/state')[1]['grants_panel']['on'])

    def test_no_second_grants_store(self):
        self.switch(True)
        self.assertFalse((ROOT / 'app/agent_grants.py').exists())
        self.assertNotEqual(self.req('/api/grants')[0], 200)
        self.assertNotEqual(self.req('/api/grants', {'account': 'x', 'agent': 'main', 'level': 'read'})[0], 200)
        h = {**self.grant(caller='wizard-mail'), **SVC}
        code, _, _ = self.req('/service/grants/v1/check', {'agent': 'main', 'account': 'x', 'action': 'read'}, owner=False, headers=h)
        self.assertNotEqual(code, 200)
        self.assertFalse(any(p.name.startswith('agent-grants') for p in Path(os.environ['DATA_DIR']).iterdir()))

    def test_page_script_is_served(self):
        code, body, _ = self.req('/connections.js')
        self.assertEqual(code, 200)
        self.assertIn('/wizard/v1/apps/', body if isinstance(body, str) else body.decode() if isinstance(body, bytes) else json.dumps(body))
        self.assertIn('src="connections.js"', (ROOT / 'web/index.html').read_text())


NODE_CHECK = r"""
const C = require(process.argv[1]);
const calls = [];
const store = {
  'connected-accounts': [{id:'hermes',label:'Hermes',enabled:true},{id:'oscar',label:'Oscar',enabled:false}],
  'messenger': [{id:'hermes',label:'Hermes',enabled:false},{id:'oscar',label:'Oscar',enabled:true,privacy:'private'}],
};
const reply = (status, body) => ({status, ok: status >= 200 && status < 300, json: async () => body});
async function fake(url, init) {
  calls.push([init.method, url, init.body || '']);
  const id = decodeURIComponent(url.split('/')[4]);
  if (init.credentials !== 'same-origin') throw new Error('credentials');
  if (!store[id]) return reply(404, {error: 'app_not_found', check: 'app.id'});
  if (init.method === 'PUT') {
    if (init.headers['Content-Type'] !== 'application/json') return reply(415, {error: 'json_required'});
    const want = new Set(JSON.parse(init.body).agents);
    store[id] = store[id].map(a => ({...a, enabled: want.has(a.id)}));
  }
  return reply(200, {app_id: id, kind: 'wizard_apps', agents: store[id]});
}
(async () => {
  const out = {};
  const view = await C.load(fake);
  out.reachable = view.reachable;
  out.apps = view.apps.map(a => [a.id, a.state, (a.agents || []).map(x => x.id + ':' + x.enabled + ':' + x.privacy)]);
  const msg = view.apps.find(a => a.id === 'messenger');
  out.put = await C.setAgents(fake, 'messenger', C.toggled(msg.agents, 'hermes', true));
  out.putBody = calls.filter(c => c[0] === 'PUT').map(c => [c[1], c[2]]);
  out.off = C.toggled(view.apps[0].agents, 'hermes', false);
  const down = await C.load(async () => { throw new TypeError('Failed to fetch'); });
  out.down = [down.reachable, down.apps.map(a => a.id + ':' + a.state)];
  const html = await C.load(async () => ({status: 200, ok: true, json: async () => { throw new SyntaxError('html'); }}));
  out.html = [html.reachable, html.apps.map(a => a.id + ':' + a.state)];
  try { await C.setAgents(async () => reply(403, {error: 'access_required'}), 'messenger', []); out.refused = 'no'; }
  catch (e) { out.refused = e.message; }
  console.log(JSON.stringify(out));
})();
"""


LEVEL_CHECK = r"""
const C = require(process.argv[1]);
const calls = [];
let google = {mail: 'draft_only', calendar: 'suggest_only'};
const levels = ids => ids.map(id => ({id, label: id}));
const doc = () => ({app: 'wizard-google', accounts: [{name: 'me@example.com'}, {name: 'work@example.com'}], applies_to: 'every_agent',
  agent_access: {mail: google.mail, what: 'w', levels: levels(['no_access', 'read_only', 'draft_only']),
                 calendar: google.calendar, calendar_what: 'c', calendar_levels: levels(['no_access', 'read_only', 'suggest_only', 'can_edit'])}});
const reply = (status, body) => ({status, ok: status >= 200 && status < 300, json: async () => body});
async function fake(url, init) {
  calls.push([init.method, url, init.headers['X-Wizard-Agent-Access'] || '', init.body || '']);
  if (url.startsWith('/wizard/v1/apps/')) {
    const id = decodeURIComponent(url.split('/')[4]);
    if (id !== 'wizard-google') return reply(404, {error: 'app_not_found'});
    return reply(200, {agents: [{id: 'hermes', label: 'Hermes', enabled: true}]});
  }
  if (url !== '/wizard-google/api/panel/agent-access' || init.credentials !== 'same-origin') return reply(404, {});
  if (init.headers['X-Wizard-Agent-Access'] !== '1') return reply(403, {error: {code: 'owner_only'}});
  if (init.method === 'POST') {
    const b = JSON.parse(init.body);
    if (b.mail === 'send') return reply(400, {error: {code: 'invalid_level'}});
    google = {...google, ...b};
  }
  return reply(200, doc());
}
(async () => {
  const out = {};
  const view = await C.load(fake);
  const g = view.apps.find(a => a.id === 'wizard-google');
  out.google = [g.state, g.own_level.accounts, g.own_level.kinds.map(k => k.kind + ':' + k.level)];
  out.set = (await C.setLevel(fake, g, 'calendar', 'can_edit')).kinds.map(k => k.kind + ':' + k.level);
  out.kept = google;
  try { await C.setLevel(fake, g, 'mail', 'send'); out.bad = 'no'; } catch (e) { out.bad = e.message; }
  out.posts = calls.filter(c => c[0] === 'POST').map(c => [c[1], c[2], c[3]]);
  // Google's switch off (404), an older Google, or the browser boundary: no level, the note stays "set in Google".
  const off = await C.load(async (url, init) => url.startsWith('/wizard/v1/') ? fake(url, init) : reply(404, {error: {code: 'not_found'}}));
  out.off = off.apps.filter(a => a.id === 'wizard-google').map(a => [a.state, a.own_level]);
  // Agent Service out of reach but Google answers: Google's accounts and level are still shown.
  const down = await C.load(async (url, init) => { if (url.startsWith('/wizard/v1/')) throw new TypeError('x'); return fake(url, init); });
  out.down = [down.reachable, down.apps.map(a => a.id + ':' + a.state + ':' + !!a.own_level)];
  console.log(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class GoogleLevelScriptTests(unittest.TestCase):
    def test_reads_and_sets_googles_own_level_in_google(self):
        # wizard-google#30: Google's accounts (names only) and its agent level, read from and set in the Google app.
        run = subprocess.run(['node', '-e', LEVEL_CHECK, str(ROOT / 'web/connections.js')], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        self.assertEqual(out['google'], ['ok', ['me@example.com', 'work@example.com'], ['mail:draft_only', 'calendar:suggest_only']])
        self.assertEqual(out['set'], ['mail:draft_only', 'calendar:can_edit'])
        self.assertEqual(out['kept'], {'mail': 'draft_only', 'calendar': 'can_edit'})
        self.assertEqual(out['bad'], 'invalid_level')
        self.assertEqual(out['posts'][0], ['/wizard-google/api/panel/agent-access', '1', '{"calendar":"can_edit"}'])
        self.assertEqual(out['off'], [['ok', None]])
        self.assertEqual(out['down'], [False, ['connected-accounts:unavailable:false', 'wizard-google:unavailable:true']])


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class ConnectionsScriptTests(unittest.TestCase):
    def test_reads_and_sets_the_agent_service_ticks(self):
        run = subprocess.run(['node', '-e', NODE_CHECK, str(ROOT / 'web/connections.js')], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        self.assertTrue(out['reachable'])
        # Only installed account apps are shown (the others answer app_not_found).
        self.assertEqual(out['apps'], [
            ['connected-accounts', 'ok', ['hermes:true:standard', 'oscar:false:standard']],
            ['messenger', 'ok', ['hermes:false:standard', 'oscar:true:private']],
        ])
        # Turning Hermes on for Messenger PUTs the full set to the Agent Service and shows what it stored.
        self.assertEqual(out['putBody'], [['/wizard/v1/apps/messenger/agents', '{"agents":["hermes","oscar"]}']])
        self.assertEqual([a['enabled'] for a in out['put']], [True, True])
        self.assertEqual(out['off'], [])
        # Agent Service out of reach (another box, the browser boundary): still lists this app's own accounts.
        self.assertEqual(out['down'], [False, ['connected-accounts:unavailable']])
        self.assertEqual(out['html'], [False, ['connected-accounts:unavailable']])
        self.assertEqual(out['refused'], 'access_required')


def load_tests(loader, tests, pattern):
    # Only this file's own tests: the BrokerHTTPTests base would otherwise run every one of its tests again here.
    suite = unittest.TestSuite()
    for case in (ConnectionsPanelTests, ConnectionsScriptTests, GoogleLevelScriptTests):
        for name in loader.getTestCaseNames(case):
            if name in case.__dict__:
                suite.addTest(case(name))
    return suite


if __name__ == '__main__':
    unittest.main()
