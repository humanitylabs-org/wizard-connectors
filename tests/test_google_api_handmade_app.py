"""wizard-connectors#38: `--step api` for a Google app the owner set up by hand.

No recorded agreements, a project not named Wizard, and the skill's scripts missing
beside the host copy of SKILL.md must not stop "connect my Gmail to Mail"."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import test_google_http as fixtures
from test_google_api_step import RecordingConsole, FakePage
from test_google_setup import script

ROOT = Path(__file__).resolve().parents[1]
# What google_app_setup_status returns for an app saved by hand (James's box).
NO_AGREEMENTS = {'accepted': [], 'version': '', 'country': ''}


def run_api(agreements, **kw):
    made = []
    orig = script.Console
    script.Console = lambda *a, **k: made.append(RecordingConsole(*a[1:], **k)) or made[-1]
    try:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            args = Namespace(agreements=agreements, project=None, audience='External', state_file=Path(tmp) / 'p.json',
                             dry_run=False, intake_url=None, redirect_uri=None, step='api', **kw)
            script.run(args, FakePage())
    finally:
        script.Console = orig
    return made[0], [json.loads(line) for line in out.getvalue().splitlines()]


class Loc:
    def __init__(self, n=0): self.n = n
    def count(self): return self.n
    @property
    def first(self): return self
    def is_visible(self): return self.n > 0
    def filter(self, **kw): return self
    def nth(self, i): return self


class TermsPage(FakePage):
    """A Google page that shows an "Agree and continue" terms screen."""
    def get_by_role(self, role, name=None, **kw):
        return Loc(1 if role == 'button' and name is not None and name.search('Agree and continue') else 0)


class HandMadeAppApiStepTests(unittest.TestCase):
    def test_api_step_runs_without_recorded_agreements(self):
        for agreements in (NO_AGREEMENTS, json.dumps(NO_AGREEMENTS), None):
            c, out = run_api(agreements, project_number='123456789012')
            self.assertEqual(c.opened, ['/apis/library/' + a for a in script.APIS])
            self.assertEqual([(o['step'], o['status']) for o in out], [('api', 'running'), ('api', 'ok')])

    def test_project_number_opens_the_apps_own_project_without_a_name_lookup(self):
        c, _ = run_api(NO_AGREEMENTS, project_number='123456789012')
        self.assertEqual(c.project, '123456789012')
        self.assertEqual(c.lookups, [])  # never searched for a project named "Wizard"

    def test_without_a_number_it_still_falls_back_to_the_name_lookup(self):
        c, _ = run_api(NO_AGREEMENTS)
        self.assertEqual(c.lookups, [False])

    def test_bad_project_number_stops(self):
        for bad in ('12ab', '0123456789', '1/../x', 12345678):
            with self.assertRaises(script.NeedsOwner) as e: run_api(NO_AGREEMENTS, project_number=bad)
            self.assertEqual(str(e.exception), 'invalid_project_id')

    def test_a_terms_screen_still_stops_with_needs_owner(self):
        c = script.Console(TermsPage(), project='123456789012', agreements=dict(script.NO_AGREEMENTS))
        with self.assertRaises(script.NeedsOwner) as e: c.accept_recorded_agreements()
        self.assertEqual(str(e.exception), 'agreements_missing_or_version_changed')

    def test_setting_up_a_new_app_still_needs_all_recorded_agreements(self):
        for step in ('all', 'project', 'branding', 'client'):
            args = Namespace(agreements=NO_AGREEMENTS, project=None, project_number=None, audience='External',
                             state_file=Path('/nonexistent/p.json'), dry_run=False, intake_url=None, redirect_uri=None, step=step)
            with self.assertRaises(script.NeedsOwner) as e: script.run(args, FakePage())
            self.assertEqual(str(e.exception), 'agreements_missing_or_version_changed')


class HandMadeAppStatusTests(unittest.TestCase):
    setUp = fixtures.BrokerHTTPTests.setUp
    tearDown = fixtures.BrokerHTTPTests.tearDown
    req = fixtures.BrokerHTTPTests.req

    def status(self):
        data = self.req('/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                 'params': {'name': 'google_app_setup_status', 'arguments': {}}},
                        owner=False, headers={'Authorization': 'Bearer ' + 'm' * 40})[1]
        return json.loads(data['result']['content'][0]['text'])

    def test_status_returns_the_project_number_of_a_hand_saved_client(self):
        for k in ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REDIRECT_URI'): self.config.pop(k, None)
        self.assertEqual(self.status()['project_number'], '')
        self.b.save_client('123456789012-abc123def456.apps.googleusercontent.com', 'FIXTURE_SECRET',
                           'https://box.example.invalid/connected-accounts/api/google/callback')
        status = self.status()
        self.assertTrue(status['configured'])
        self.assertEqual(status['project_number'], '123456789012')
        self.assertEqual(status['agreements'], NO_AGREEMENTS)
        raw = json.dumps(status)
        self.assertNotIn('abc123def456', raw)
        self.assertNotIn('FIXTURE_SECRET', raw)

    def test_scripts_are_served_for_the_host_copy_of_the_skill(self):
        listed = {s['path']: s['sha256'] for s in self.status()['scripts']}
        self.assertEqual(set(listed), {'/skill/scripts/google_cloud_setup.py', '/skill/scripts/google_agreement_definitions.py'})
        for path, digest in listed.items():
            code, body, headers = self.req(path, owner=False)
            self.assertEqual(code, 200)
            local = (ROOT / 'skill/scripts' / path.rsplit('/', 1)[1]).read_bytes()
            self.assertEqual(body.encode(), local)
            self.assertEqual(hashlib.sha256(local).hexdigest(), digest)
        for path in ('/skill/scripts/../../app/server.py', '/skill/scripts/', '/skill/SKILL.md', '/skill/scripts/x.py'):
            self.assertNotEqual(self.req(path, owner=False)[0], 200, path)


if __name__ == '__main__':
    unittest.main()
