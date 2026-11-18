"""Calendar edits for the agent through the Google app on the Connected accounts sign-in (wizard-connectors#29,
switch google-calendar-edits). Real handlers, RPC and broker; fake Google (no network, no real account).
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_google_app_service import GoogleAppServiceTests  # noqa: E402
from google_broker import CALENDAR_EDIT_SCOPE, Denied, GoogleTransport, calendar_request  # noqa: E402

EVENTS = 'https://www.googleapis.com/calendar/v3/calendars/primary/events'


class CalendarEditTests(GoogleAppServiceTests):
    def setUp(self):
        super().setUp()
        self.calendar_calls = []
        self.calendar_error = None

        def calendar(method, url, token, query=None, body=None):
            calendar_request(method, url, query, body)  # the real transport checks this too
            self.calendar_calls.append((method, url, query, body, token))
            if self.calendar_error: raise Denied(self.calendar_error)
            if method == 'POST': return {'id': 'ev1', 'summary': body.get('summary'), **body}
            if method == 'PATCH': return {'id': url.rsplit('/', 1)[1], **body}
            if method == 'DELETE': return {}
            return {'items': [{'id': 'ev1', 'summary': 'FAKE standup'}]}
        self.fake.calendar = calendar

    def edits(self, on=True):
        (Path(os.environ['DATA_DIR']) / 'switches.json').write_text(json.dumps({'google-calendar-edits': on}))

    def cal(self, tool, data=None, agent='main', owner=False):
        h = {**self.grant(caller='wizard-google'), 'Host': 'wizard-connectors-calendar:8799'}
        if agent is not None: h['X-Wizard-Agent'] = agent
        if owner: h['X-Wizard-Owner'] = '1'
        if tool == 'calendar_status':
            return self.req('/service/google/v1/calendar_status', owner=False, headers=h)
        return self.req('/service/google/v1/' + tool, data if data is not None else {}, owner=False, headers=h)

    def test_off_by_default_no_scope_and_refused(self):
        state = self.req('/api/state')[1]
        self.assertFalse(state['calendar_edits']['on'])
        self.assertEqual(self.req('/api/google/connect', {'calendar_edits': True})[1]['error'], 'service_off')
        self.assertNotIn(CALENDAR_EDIT_SCOPE, self.start(False)['scope'])
        code, res, _ = self.cal('calendar_http', {'method': 'POST', 'url': EVENTS, 'body': {'summary': 'x'}})
        self.assertEqual((code, res['error']['code']), (409, 'service_off'))
        self.assertEqual(self.calendar_calls, [])

    def test_allow_then_google_app_creates_moves_and_deletes_an_event(self):
        # The issue's done-when on this side: only a Connected accounts sign-in, the switch on, the owner's Allow.
        self.edits(True)
        code, res, _ = self.cal('calendar_http', {'method': 'POST', 'url': EVENTS, 'body': {'summary': 'x'}})
        self.assertEqual((code, res['error']['code']), (409, 'not_connected'))
        scopes = self.allow(calendar_edits=True)
        self.assertIn(CALENDAR_EDIT_SCOPE, scopes)
        status = self.cal('calendar_status')[1]
        self.assertEqual(status['accounts'][0]['calendar_edits'], True)
        self.assertNotIn('FAKE_ACCESS_SECRET', json.dumps(status))
        body = {'summary': 'Dentist', 'start': {'dateTime': '2026-11-20T10:00:00+01:00'}, 'end': {'dateTime': '2026-11-20T11:00:00+01:00'}}
        code, made, _ = self.cal('calendar_http', {'method': 'POST', 'url': EVENTS, 'query': {'sendUpdates': 'all'}, 'body': body})
        self.assertEqual(code, 200, made)
        self.assertEqual((made['response']['id'], made['via'], made['account']), ('ev1', 'connected-accounts', 'fixture@example.invalid'))
        self.assertEqual(self.calendar_calls[-1][4], 'FAKE_ACCESS_SECRET')  # broker's own token, never sent back
        self.assertNotIn('FAKE_ACCESS_SECRET', json.dumps(made))
        moved = {'start': {'dateTime': '2026-11-20T14:00:00+01:00'}, 'end': {'dateTime': '2026-11-20T15:00:00+01:00'}}
        code, res, _ = self.cal('calendar_http', {'method': 'PATCH', 'url': EVENTS + '/ev1', 'body': moved})
        self.assertEqual((code, res['response']['start']), (200, moved['start']))
        listed = self.cal('calendar_http', {'method': 'GET', 'url': EVENTS, 'query': {'singleEvents': 'true', 'maxResults': 25}})[1]
        self.assertEqual(listed['response']['items'][0]['id'], 'ev1')
        code, res, _ = self.cal('calendar_http', {'method': 'DELETE', 'url': EVENTS + '/ev1'}, agent=None, owner=True)
        self.assertEqual((code, res['response']), (200, {}))

    def test_only_the_google_app_says_who_and_stays_on_the_events_path(self):
        self.edits(True)
        self.allow(calendar_edits=True)
        mail = self.grant(caller='wizard-mail')
        h = {**mail, 'Host': 'wizard-connectors-calendar:8799', 'X-Wizard-Agent': 'main'}
        self.assertEqual(self.req('/service/google/v1/calendar_status', owner=False, headers=h)[0], 403)
        self.assertEqual(self.cal('calendar_status', agent=None)[1]['error']['code'], 'caller_unknown')
        for bad in ({'method': 'PUT', 'url': EVENTS + '/ev1'}, {'method': 'POST', 'url': EVENTS + '/ev1'},
                    {'method': 'DELETE', 'url': EVENTS}, {'method': 'GET', 'url': 'https://www.googleapis.com/calendar/v3/users/me/calendarList'},
                    {'method': 'GET', 'url': EVENTS + '/../acl'}, {'method': 'GET', 'url': EVENTS + '?x=1'},
                    {'method': 'GET', 'url': 'https://www.googleapis.com/calendar/v3/calendars/a%2F..%2Facl/events'},
                    {'method': 'GET', 'url': 'https://www.googleapis.com/calendar/v3/calendars/a@b.c/events'},
                    {'method': 'GET', 'url': EVENTS, 'query': {'fields': '*'}},
                    {'method': 'GET', 'url': EVENTS, 'query': {'sendUpdates': 'everyone'}},
                    {'method': 'PATCH', 'url': EVENTS + '/ev1', 'body': ['x']},
                    {'method': 'GET', 'url': EVENTS, 'token': 'x'}):
            code, res, _ = self.cal('calendar_http', bad)
            self.assertEqual((code, res['error']['code']), (400, 'invalid_arguments'), bad)
        self.assertEqual(self.calendar_calls, [])
        ok = 'https://www.googleapis.com/calendar/v3/calendars/a%40b.c/events'
        self.assertEqual(self.cal('calendar_http', {'method': 'GET', 'url': ok})[0], 200)

    def test_account_choice_and_google_errors_keep_the_sign_in(self):
        self.edits(True)
        self.allow(calendar=True)
        code, res, _ = self.cal('calendar_http', {'method': 'GET', 'url': EVENTS, 'account': 'fixture@example.invalid'})
        self.assertEqual(res['error']['code'], 'permission_missing')
        self.assertEqual(self.cal('calendar_http', {'method': 'GET', 'url': EVENTS, 'account': 'nobody@example.invalid'})[1]['error']['code'],
                         'account_not_found')
        self.allow(calendar_edits=True)
        self.calendar_error = 'google_permission_missing'
        code, res, _ = self.cal('calendar_http', {'method': 'GET', 'url': EVENTS})
        self.assertEqual((code, res['error']['code']), (403, 'google_permission_missing'))
        self.assertEqual(self.b.status()['accounts'][0]['status'], 'active')  # no edit rights is not a sign-out
        self.calendar_error = 'conflict'
        self.assertEqual(self.cal('calendar_http', {'method': 'PATCH', 'url': EVENTS + '/ev1', 'body': {}})[0], 409)

    def test_setup_lists_the_optional_scope_and_transport_checks_first(self):
        self.assertIn(CALENDAR_EDIT_SCOPE, self.b.setup_status('https://box.example.invalid/connected-accounts/api/google/callback')['optional_scopes'])
        with self.assertRaises(Denied):
            GoogleTransport().calendar('GET', 'https://evil.invalid/calendar/v3/calendars/primary/events', 'tok')


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name in loader.getTestCaseNames(CalendarEditTests):
        if name in CalendarEditTests.__dict__:
            suite.addTest(CalendarEditTests(name))
    return suite


if __name__ == '__main__':
    unittest.main()
