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
    path = os.environ.get('WIZARD_GRANTS_FILE')
    if not path: return False
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 262144: return False
        grants = json.loads(raw)
        if not isinstance(grants, dict) or type(grants.get('enforce')) is not bool: return False
        if not isinstance(grants.get('incoming'), list) or not isinstance(grants.get('outgoing', {}), dict) or not isinstance(grants.get('provider_endpoints', {}), dict): return False
        for row in grants['incoming']:
            if not isinstance(row, dict) or not isinstance(row.get('from'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', row['from']): return False
            if not isinstance(row.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', row['sha256']): return False
        key = headers.get('X-Wizard-Grant', '')
        if not key or len(key) > 4096: return False
        digest = hashlib.sha256(key.encode()).hexdigest()
        allowed = any(row['from']=='calendar' and hmac.compare_digest(digest, row['sha256']) for row in grants['incoming'])
        if not allowed and not grants['enforce']:
            logging.getLogger('calendar-grants').warning('Calendar grant denied despite report-only mode (private calendar data)')
        return allowed
    except (OSError, ValueError, TypeError):
        return False
