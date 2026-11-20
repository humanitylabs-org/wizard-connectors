"""Layer-2 app grants; Calendar is stricter than transitional report-only mode.
Read on EVERY request (including atomic file replacement/revocation). No cache
or caller-supplied identity; no configured file means no Calendar service access.
"""
import hashlib
import hmac
import json
import logging
import os
import re
from pathlib import Path


def calendar_caller(headers):
    return app_caller(headers, 'wizard-calendar')


def app_caller(headers, app_id):
    """True when X-Wizard-Grant matches an incoming row from app_id (Calendar, or Mail for Gmail)."""
    return _matching(headers, app_id) == app_id


def any_app_caller(headers):
    """The app id whose incoming grant row X-Wizard-Grant matches (any app with a grant to this one), or None.
    Used by wizard.app-grants/1 (wizard-connectors#49): every app and the MCP gateway may ask a grant question."""
    return _matching(headers, None)


def _matching(headers, app_id):
    path = os.environ.get('WIZARD_GRANTS_FILE') or '/wizard/grants.json'
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 262144: return None
        grants = json.loads(raw)
        if not isinstance(grants, dict) or type(grants.get('enforce')) is not bool: return None
        if not isinstance(grants.get('incoming'), list) or not isinstance(grants.get('outgoing', {}), dict) or not isinstance(grants.get('provider_endpoints', {}), dict): return None
        for row in grants['incoming']:
            if not isinstance(row, dict) or not isinstance(row.get('from'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', row['from']): return None
            if not isinstance(row.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', row['sha256']): return None
        key = headers.get('X-Wizard-Grant', '')
        if not key or len(key) > 4096: return None
        digest = hashlib.sha256(key.encode()).hexdigest()
        found = None
        for row in grants['incoming']:
            if (app_id is None or row['from'] == app_id) and hmac.compare_digest(digest, row['sha256']) and found is None:
                found = row['from']
        if found is None and not grants['enforce']:
            logging.getLogger('app-grants').warning('%s grant denied despite report-only mode (private data)', app_id or 'app')
        return found
    except (OSError, ValueError, TypeError):
        return None
