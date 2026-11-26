"""Agent access in one place (wizard-connectors#49; its grants-panel switch removed after show-and-tell), as rescoped by Miguel on 20 Nov 2026.

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

    def test_switch_removed_and_stored_value_cleared(self):
        # Approved at show-and-tell: Agent access is on for everyone, no grants-panel switch left.
        import server
        self.assertNotIn('grants-panel', [s['id'] for s in server.SWITCHES])
        self.assertNotIn('grants_panel', self.req('/api/state')[1])
        f = Path(os.environ['DATA_DIR']) / 'switches.json'
        f.write_text(json.dumps({'grants-panel': False, 'future-switch': True}))
        self.assertNotIn('grants-panel', [s['id'] for s in server.switches_doc()['switches']])
        server._sw_prune_retired()
        self.assertEqual(json.loads(f.read_text()), {'future-switch': True})

    def test_no_second_grants_store(self):
        self.assertFalse((ROOT / 'app/agent_grants.py').exists())
        self.assertNotEqual(self.req('/api/grants')[0], 200)
        self.assertNotEqual(self.req('/api/grants', {'account': 'x', 'agent': 'main', 'level': 'read'})[0], 200)
        h = {**self.grant(caller='wizard-mail'), **SVC}
        code, _, _ = self.req('/service/grants/v1/check', {'agent': 'main', 'account': 'x', 'action': 'read'}, owner=False, headers=h)
        self.assertNotEqual(code, 200)
        self.assertFalse(any(p.name.startswith('agent-grants') for p in Path(os.environ['DATA_DIR']).iterdir()))

    def test_sandboxed_page_loads_its_own_files(self):
        # Browser boundary on (wizard-ux#1668): the page runs in a sandboxed frame, so its own scripts and styles arrive
        # as Sec-Fetch-Site: cross-site with no Origin (or Origin: null). Those public files are served; nothing else is.
        x = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'no-cors'}
        for f in ('/boot.js', '/app.js', '/connections.js', '/styles.css', '/wizard-ui.css'):
            code, _, h = self.req(f, owner=False, headers=x)
            self.assertEqual(code, 200, f)
            self.assertEqual(h['Access-Control-Allow-Origin'], '*', f)
            self.assertIsNone(h.get('Access-Control-Allow-Credentials'), f)
            self.assertEqual(self.req(f, owner=False, headers={**x, 'Origin': 'null', 'Sec-Fetch-Mode': 'cors'})[0], 200, f)
            # Another site's page asking with its own Origin is still refused.
            self.assertEqual(self.req(f, owner=False, headers={**x, 'Origin': 'https://evil.example'})[0], 403, f)
        # The page itself, the API and other paths stay same-site only, also for a sandboxed page.
        for path in ('/', '/api/state', '/healthz', '/privacy.html'):
            self.assertEqual(self.req(path, headers=x)[0], 403, path)
            self.assertEqual(self.req(path, headers={**x, 'Origin': 'null'})[0], 403, path)
        # The Host check still applies to the files.
        self.assertEqual(self.req('/app.js', owner=False, headers={**x, 'Host': 'evil.example'})[0], 403)
        # A same-site load is unchanged (no CORS header on the page).
        code, _, h = self.req('/', owner=False)
        self.assertEqual(code, 200)
        self.assertIsNone(h.get('Access-Control-Allow-Origin'))

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
// Messenger's own levels (wizard-messenger#342): the only copy, kept in "Messenger".
const messenger = {on: true, agents: [{id:'hermes',label:'Your Wizard agent',main:true,level:'no_access'},{id:'oscar',label:'Oscar',main:false,level:'read_only'}]};
const levels = () => ({app:'messenger', accounts:[{network:'whatsapp',label:'WhatsApp',name:'Sam Example'}],
  agents: messenger.agents, levels:[{id:'no_access',label:'No access',recommended:false},{id:'read_only',label:'Read-only',recommended:false},{id:'draft_only',label:'Draft-only',recommended:true}]});
async function fake(url, init) {
  calls.push([init.method, url, init.body || '']);
  if (url === '/messenger/api/agent-levels') {
    if (!messenger.on) return reply(404, {error: 'No such route', code: 'not_found'});
    if (init.method === 'POST') {
      if (init.headers['X-Wizard-Agent-Level'] !== '1' || init.headers['Content-Type'] !== 'application/json') return reply(403, {code: 'level_header_required'});
      const {agent, level} = JSON.parse(init.body);
      if (!['no_access','read_only','draft_only'].includes(level)) return reply(400, {code: 'invalid_level'});
      messenger.agents = messenger.agents.map(a => a.id === agent ? {...a, level} : a);
    }
    return reply(200, levels());
  }
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
  out.levels = msg.ownLevels;
  out.noLevelsElsewhere = view.apps.filter(a => a.id !== 'messenger').map(a => a.ownLevels === undefined);
  out.set = (await C.setLevel(fake, msg.levels, 'hermes', 'draft_only')).agents.map(a => a.id + ':' + a.level);
  out.post = calls.filter(c => c[0] === 'POST').map(c => [c[1], c[2]]);
  messenger.agents[1].level = 'no_access';  // changed in Messenger: the panel shows it on its next read
  out.reread = (await C.load(fake)).apps.find(a => a.id === 'messenger').ownLevels.agents.map(a => a.id + ':' + a.level);
  try { await C.setLevel(fake, msg.levels, 'hermes', 'draft_and_send'); out.badLevel = 'no'; } catch (e) { out.badLevel = e.message; }
  messenger.on = false;  // Messenger's switch off (or an older Messenger): "set in Messenger" as before
  out.offState = (await C.load(fake)).apps.find(a => a.id === 'messenger').ownLevels.state;
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
  out.google = [g.state, g.appLevelView.accounts, g.appLevelView.kinds.map(k => k.kind + ':' + k.level)];
  out.set = (await C.setAppLevel(fake, g, 'calendar', 'can_edit')).kinds.map(k => k.kind + ':' + k.level);
  out.kept = google;
  try { await C.setAppLevel(fake, g, 'mail', 'send'); out.bad = 'no'; } catch (e) { out.bad = e.message; }
  out.posts = calls.filter(c => c[0] === 'POST').map(c => [c[1], c[2], c[3]]);
  // Google's switch off (404), an older Google, or the browser boundary: no level, the note stays "set in Google".
  const off = await C.load(async (url, init) => url.startsWith('/wizard/v1/') ? fake(url, init) : reply(404, {error: {code: 'not_found'}}));
  out.off = off.apps.filter(a => a.id === 'wizard-google').map(a => [a.state, a.appLevelView]);
  // Agent Service out of reach but Google answers: Google's accounts and level are still shown.
  const down = await C.load(async (url, init) => { if (url.startsWith('/wizard/v1/')) throw new TypeError('x'); return fake(url, init); });
  out.down = [down.reachable, down.apps.map(a => a.id + ':' + a.state + ':' + !!a.appLevelView)];
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


MS_LEVEL_CHECK = LEVEL_CHECK.replace('wizard-google', 'wizard-microsoft').replace('me@example.com', 'me@outlook.com')


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class MicrosoftLevelScriptTests(unittest.TestCase):
    def test_reads_and_sets_microsofts_own_level_in_microsoft(self):
        # wizard-microsoft#10: Microsoft's accounts (names only) and its agent level, read from and set in Microsoft.
        run = subprocess.run(['node', '-e', MS_LEVEL_CHECK, str(ROOT / 'web/connections.js')], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        self.assertEqual(out['google'], ['ok', ['me@outlook.com', 'work@example.com'], ['mail:draft_only', 'calendar:suggest_only']])
        self.assertEqual(out['set'], ['mail:draft_only', 'calendar:can_edit'])
        self.assertEqual(out['kept'], {'mail': 'draft_only', 'calendar': 'can_edit'})
        self.assertEqual(out['bad'], 'invalid_level')
        self.assertEqual(out['posts'][0], ['/wizard-microsoft/api/panel/agent-access', '1', '{"calendar":"can_edit"}'])
        self.assertEqual(out['off'], [['ok', None]])
        self.assertEqual(out['down'], [False, ['connected-accounts:unavailable:false', 'wizard-microsoft:unavailable:true']])


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

    def test_reads_and_sets_messengers_own_level_in_messenger(self):
        run = subprocess.run(['node', '-e', NODE_CHECK, str(ROOT / 'web/connections.js')], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        # wizard-messenger#342: the Messenger card reads Messenger's accounts (names only) and per-agent level.
        self.assertEqual(out['levels']['state'], 'ok')
        self.assertEqual(out['levels']['accounts'], [{'label': 'WhatsApp', 'name': 'Sam Example'}])
        self.assertEqual([(a['id'], a['main'], a['level']) for a in out['levels']['agents']],
                         [('hermes', True, 'no_access'), ('oscar', False, 'read_only')])
        self.assertEqual([l['id'] for l in out['levels']['levels'] if l['recommended']], ['draft_only'])
        self.assertEqual(out['noLevelsElsewhere'], [True])
        # A change here is a POST to Messenger itself (the only store), and the answer is what Messenger now holds.
        self.assertEqual(out['post'], [['/messenger/api/agent-levels', '{"agent":"hermes","level":"draft_only"}']])
        self.assertEqual(out['set'], ['hermes:draft_only', 'oscar:read_only'])
        # A change made in Messenger shows on the next read.
        self.assertEqual(out['reread'], ['hermes:draft_only', 'oscar:no_access'])
        self.assertEqual(out['badLevel'], 'invalid_level')
        self.assertEqual(out['offState'], 'off')

    def test_messenger_card_draws_its_levels(self):
        app_js = (ROOT / 'web/app.js').read_text()
        self.assertIn("app.ownLevels?.state==='ok'", app_js)
        self.assertIn('WizConnections.setLevel(', app_js)


BOXED_CHECK = r"""
// Browser boundary on (wizard-ux#1668): this page is sandboxed (origin 'null') and its own owner call carries no token,
// so the shell reads and sets the ticks (WizardApp.agentAccess). When the shell does not offer it (its switch off), the
// owner route is tried as before.
const C = require(process.argv[1]);
const fetched = [], asked = [];
let shellOn = true;
const store = {'connected-accounts': [{id:'hermes',label:'Hermes',enabled:true,privacy:'standard'}], 'messenger': [{id:'hermes',label:'Hermes',enabled:false,privacy:'standard'},{id:'oscar',label:'Oscar',enabled:true,privacy:'private'}]};
globalThis.origin = 'null';
globalThis.WizardApp = {agentAccess: {
  read: async id => { asked.push(['read', id]); if (!shellOn) throw new Error('Agent access is not available here'); return store[id] ? {state:'ok', agents: store[id]} : {state:'absent'}; },
  set: async (id, ids) => { asked.push(['set', id, ids.join()]); if (!shellOn) throw new Error('Agent access is not available here'); store[id] = store[id].map(a => ({...a, enabled: ids.includes(a.id)})); return {state:'ok', agents: store[id]}; },
}};
// The page's own owner call under the boundary: refused (no token).
const own = async (url, init) => { fetched.push([init.method, url]); return {status: 401, ok: false, json: async () => ({error: 'owner_auth_required'})}; };
(async () => {
  const out = {};
  const view = await C.load(own);
  out.reachable = view.reachable;
  out.apps = view.apps.map(a => [a.id, a.state, (a.agents || []).map(x => x.id + ':' + x.enabled + ':' + x.privacy)]);
  out.fetchedAgents = fetched.filter(c => c[1].startsWith('/wizard/v1/')).length;
  out.set = (await C.setAgents(own, 'messenger', ['hermes', 'oscar'])).map(a => a.id + ':' + a.enabled);
  out.asked = asked.filter(a => a[0] === 'set');
  shellOn = false; fetched.length = 0;
  const off = await C.load(own);
  out.off = [off.reachable, off.apps.map(a => a.id + ':' + a.state)];
  out.offFetched = fetched.filter(c => c[1].startsWith('/wizard/v1/')).length;
  try { await C.setAgents(own, 'messenger', []); out.offSet = 'no'; } catch (e) { out.offSet = e.message; }
  console.log(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which('node'), 'node not installed')
class BoundaryScriptTests(unittest.TestCase):
    def test_sandboxed_page_asks_the_shell(self):
        run = subprocess.run(['node', '-e', BOXED_CHECK, str(ROOT / 'web/connections.js')], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        # The shell answered every app: ticks shown, no owner call from the page for them.
        self.assertTrue(out['reachable'])
        self.assertEqual(out['apps'], [
            ['connected-accounts', 'ok', ['hermes:true:standard']],
            ['messenger', 'ok', ['hermes:false:standard', 'oscar:true:private']],
        ])
        self.assertEqual(out['fetchedAgents'], 0)
        # A change goes to the shell, which answers what the Agent Service now keeps.
        self.assertEqual(out['set'], ['hermes:true', 'oscar:true'])
        self.assertEqual(out['asked'], [['set', 'messenger', 'hermes,oscar']])
        # The shell's switch off: the page tries its own owner call as before and shows the fallback.
        self.assertEqual(out['off'], [False, ['connected-accounts:unavailable']])
        self.assertGreater(out['offFetched'], 0)
        self.assertEqual(out['offSet'], 'owner_auth_required')


def load_tests(loader, tests, pattern):
    # Only this file's own tests: the BrokerHTTPTests base would otherwise run every one of its tests again here.
    suite = unittest.TestSuite()
    for case in (ConnectionsPanelTests, ConnectionsScriptTests, GoogleLevelScriptTests, MicrosoftLevelScriptTests, BoundaryScriptTests):
        for name in loader.getTestCaseNames(case):
            if name in case.__dict__:
                suite.addTest(case(name))
    return suite


if __name__ == '__main__':
    unittest.main()
