"""wizard-os#774: the Agent Service gateway reaches /mcp with X-Wizard-Grant only, and a
host:agent-service row in grants.json no longer makes every other app's grant fail."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_google_http import BrokerHTTPTests  # noqa: E402


def _digest(key):
    return hashlib.sha256(key.encode()).hexdigest()


class GatewayGrantTests(BrokerHTTPTests):
    def write_rows(self, rows, enforce=True):
        self.grant()  # sets WIZARD_GRANTS_FILE in the temp dir
        self.grants.write_text(json.dumps({'outgoing': {}, 'provider_endpoints': {}, 'enforce': enforce,
                                           'incoming': [{'from': f, 'sha256': _digest(k)} for f, k in rows]}))

    def mcp_list(self, headers):
        return self.req('/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, owner=False, headers=headers)

    def test_gateway_grant_lists_tools(self):
        self.write_rows([('host:agent-service', 'GATEWAY_KEY_FIXTURE'), ('wizard-calendar', 'CAL_KEY_FIXTURE')])
        code, out, _ = self.mcp_list({'X-Wizard-Grant': 'GATEWAY_KEY_FIXTURE', 'X-Wizard-Agent': 'main'})
        self.assertEqual(code, 200)
        self.assertIn('connector_status', {t['name'] for t in out['result']['tools']})
        call = self.req('/mcp', {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                 'params': {'name': 'connector_status', 'arguments': {}}},
                        owner=False, headers={'X-Wizard-Grant': 'GATEWAY_KEY_FIXTURE'})
        self.assertEqual(call[0], 200)
        self.assertNotIn('error', call[1])

    def test_bearer_still_works_and_wrong_callers_refused(self):
        self.write_rows([('host:agent-service', 'GATEWAY_KEY_FIXTURE'), ('wizard-calendar', 'CAL_KEY_FIXTURE')])
        self.assertEqual(self.mcp_list({'Authorization': 'Bearer ' + 'm' * 40})[0], 200)
        self.assertEqual(self.mcp_list({})[0], 401)
        self.assertEqual(self.mcp_list({'X-Wizard-Grant': 'WRONG_KEY'})[0], 401)
        # Another app's key is not the gateway's key.
        self.assertEqual(self.mcp_list({'X-Wizard-Grant': 'CAL_KEY_FIXTURE'})[0], 401)
        # Report-only mode does not open /mcp either.
        self.write_rows([('host:agent-service', 'GATEWAY_KEY_FIXTURE')], enforce=False)
        self.assertEqual(self.mcp_list({'X-Wizard-Grant': 'WRONG_KEY'})[0], 401)
        self.assertEqual(self.mcp_list({'X-Wizard-Grant': 'GATEWAY_KEY_FIXTURE'})[0], 200)

    def test_host_row_keeps_calendar_grant_working(self):
        self.write_rows([('host:agent-service', 'GATEWAY_KEY_FIXTURE'), ('wizard-calendar', 'CAL_KEY_FIXTURE')])
        path = '/service/calendar/status'
        self.assertEqual(self.req(path, owner=False, headers={'X-Wizard-Grant': 'CAL_KEY_FIXTURE'})[0], 200)
        # The gateway key is not a Calendar grant.
        self.assertEqual(self.req(path, owner=False, headers={'X-Wizard-Grant': 'GATEWAY_KEY_FIXTURE'})[0], 403)
        # Malformed rows still fail the file closed.
        for bad in ('host:', 'Host:agent-service', 'host:host:x', 'other:agent-service'):
            self.write_rows([(bad, 'GATEWAY_KEY_FIXTURE'), ('wizard-calendar', 'CAL_KEY_FIXTURE')])
            self.assertEqual(self.req(path, owner=False, headers={'X-Wizard-Grant': 'CAL_KEY_FIXTURE'})[0], 403, bad)


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name in loader.getTestCaseNames(GatewayGrantTests):
        if name in GatewayGrantTests.__dict__:
            suite.addTest(GatewayGrantTests(name))
    return suite
