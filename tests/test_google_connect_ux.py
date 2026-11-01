"""Google connect UX contract: real HTTP and broker, fake provider only."""
import unittest
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import test_google_http as fixtures


class GoogleConnectUXTests(unittest.TestCase):
    setUp = fixtures.BrokerHTTPTests.setUp
    tearDown = fixtures.BrokerHTTPTests.tearDown
    req = fixtures.BrokerHTTPTests.req
    start = fixtures.BrokerHTTPTests.start
    finish = fixtures.BrokerHTTPTests.finish

    def test_exact_browser_payload_calendar_read_without_service_binding(self):
        status, result, headers = self.req('/api/google/connect', {'account': None, 'youtube': False, 'calendar': True})
        self.assertEqual(status, 200)
        query = parse_qs(urlsplit(result['authorization_url']).query)
        self.assertEqual(urlsplit(result['authorization_url']).netloc, 'accounts.google.com')
        self.assertIn('https://www.googleapis.com/auth/calendar.readonly', query['scope'][0].split())
        self.assertNotIn('https://www.googleapis.com/auth/youtube.readonly', query['scope'][0].split())
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', headers['Set-Cookie'])
        self.assertEqual(self.b.status()['accounts'], [])
        self.assertFalse(self.b.status()['calendar_binding']['accounts'])

    def test_payload_rejects_untyped_permissions_and_bad_accounts(self):
        for data in ({'calendar': 'true'}, {'youtube': 1}, {'account': []}, {'account': 42}, {'redirect_uri': 'https://wrong.invalid'}):
            with self.subTest(data=data):
                self.assertEqual(self.req('/api/google/connect', data)[0], 400)

    def test_success_is_skinned_html_without_oauth_echo_and_clears_cookie(self):
        p = self.start(False)
        status, page, headers = self.finish(p)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), 'text/html')
        self.assertIn('Google connected', page)
        self.assertIn('../../wizard-ui.css', page)
        self.assertNotIn('google-callback.js', page)
        self.assertNotIn('<button', page)
        self.assertNotIn('window.close', page)
        self.assertNotIn('<a ', page)
        self.assertIn('Go back to the Wizard app to finish. You can close this tab.', page)
        self.assertNotIn('Music playback', page)
        for value in (p['state'], p['nonce'], 'FAKE_CODE', 'FAKE_ACCESS_SECRET', 'FAKE_REFRESH_SECRET'):
            self.assertNotIn(value, page)
        self.assertIn('Max-Age=0', headers['Set-Cookie'])
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])

    def test_cancel_is_skinned_error_and_cannot_replay(self):
        p = self.start(False)
        status, page, headers = self.finish(p, error='access_denied')
        self.assertEqual(status, 400)
        self.assertIn('sign-in wasn’t completed', page)
        self.assertIn('../../styles.css', page)
        self.assertIn(self.ui.CALLBACK_REASONS['consent_denied'], page)
        self.assertNotIn('{{REASON}}', page)
        self.assertIn('Go back to the Wizard app and tap Connect again.', page)
        self.assertNotIn('<a ', page)
        self.assertNotIn('<button', page)
        self.assertIn('{{REASON}}', (Path(__file__).resolve().parents[1] / 'web/google-error.html').read_text())
        self.assertNotIn(p['state'], page)
        self.assertIsNone(headers.get('Set-Cookie'))  # binding kept for other open sign-in windows
        self.assertEqual(self.finish(p)[0], 400)
        self.assertEqual(self.b.status()['accounts'], [])

    def test_privacy_is_public_but_state_remains_private(self):
        status, page, headers = self.req('/privacy', owner=False)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), 'text/html')
        self.assertIn('stored encrypted on your Wizard server', page)
        self.assertIn('server administrator remains trusted', page)
        self.assertEqual(self.req('/api/state', owner=False)[0], 401)
        self.assertEqual(self.req('/privacy', owner=False, headers={'Host': 'evil.invalid'})[0], 403)


class GoogleWebUIContractTests(unittest.TestCase):
    def test_home_has_one_provider_card_and_no_practice_entry(self):
        root = Path(__file__).resolve().parents[1]
        home = (root / 'web/index.html').read_text()
        app = (root / 'web/app.js').read_text()
        self.assertEqual(home.count('id="google-row"'), 1)
        for removed in ('Practice a private summary', 'Try it out', 'chat-row', 'google-manage'):
            self.assertNotIn(removed, home)
        self.assertNotIn('function renderChat', app)
        self.assertNotIn('function renderSummary', app)

    @unittest.skipUnless(shutil.which('node'), 'Node DOM contracts run separately on the forum host')
    def test_rendered_active_status_and_calendar_switch_contract(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', 'qa/google_account_ui_test.cjs'], cwd=root,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS active/connected status', result.stdout)


if __name__ == '__main__':
    unittest.main()
