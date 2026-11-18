import io
import contextlib
import json
import unittest
from argparse import Namespace
from pathlib import Path
import tempfile

from test_google_setup import script

AGREEMENTS = {'accepted': sorted(script.IDS), 'version': script.VERSION, 'country': 'GB'}


class RecordingConsole(script.Console):
    """No browser: records which Console pages the setup would open."""
    def __init__(self, *a, **kw):
        self.opened, self.lookups = [], []
        super().__init__(FakePage(), *a, **kw)
    def go(self, path): self.opened.append(path)
    def enable_api(self, name): self.opened.append('/apis/library/' + name)
    def project_setup(self, create=True):
        self.lookups.append(create)
        if not create: self.project = 'wizard-existing1'
        else: raise AssertionError('api step must never create a project')


class FakePage:
    url = 'https://console.cloud.google.com/'
    def set_default_timeout(self, v): pass
    def set_default_navigation_timeout(self, v): pass


class GmailApiSetupTests(unittest.TestCase):
    """wizard-connectors#19: the agent setup turns on every API the broker serves."""

    def test_setup_script_enables_calendar_gmail_and_youtube(self):
        self.assertEqual(script.APIS, ('calendar-json.googleapis.com', 'gmail.googleapis.com', 'youtube.googleapis.com',
                                       'drive.googleapis.com', 'people.googleapis.com'))
        c = RecordingConsole(agreements=AGREEMENTS)
        c.api()
        self.assertEqual(c.opened, ['/apis/library/' + a for a in script.APIS])

    def test_api_step_alone_needs_no_intake_and_never_creates_a_project(self):
        made = []
        orig = script.Console
        script.Console = lambda *a, **kw: made.append(RecordingConsole(*a[1:], **kw)) or made[-1]
        try:
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
                args = Namespace(agreements=AGREEMENTS, project=None, audience='External', state_file=Path(tmp) / 'p.json',
                                 dry_run=False, intake_url=None, redirect_uri=None, step='api')
                script.run(args, FakePage())
        finally:
            script.Console = orig
        c = made[0]
        self.assertEqual(c.lookups, [False])
        self.assertEqual(c.project, 'wizard-existing1')
        self.assertEqual(c.opened, ['/apis/library/' + a for a in script.APIS])
        self.assertEqual([json.loads(l)['step'] for l in out.getvalue().splitlines()], ['api', 'api'])

    def test_other_steps_still_require_the_intake_capability(self):
        for step in ('all', 'client', 'project', 'branding'):
            args = Namespace(agreements=AGREEMENTS, project='wizard-existing1', audience='External', state_file=Path('/nonexistent/p.json'),
                             dry_run=False, intake_url=None, redirect_uri=None, step=step)
            with self.assertRaises(script.NeedsOwner) as e:
                script.run(args, FakePage())
            self.assertEqual(str(e.exception), 'get_setup_begin_from_mcp_first')

    def test_broker_status_lists_gmail_api_as_required(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
        import google_broker
        self.assertEqual(google_broker.REQUIRED_APIS, script.APIS)


if __name__ == '__main__':
    unittest.main()
