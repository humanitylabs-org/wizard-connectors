"""The owner's level for agents' mail through Connected accounts (wizard-connectors#15, switch gmail-for-mail).

Same levels and meaning as wizard-google / wizard-microsoft `agent_access.py` (contract wizard.mail-calendar/1):
No access, Read-only, Draft only (recommended, the default). Agents never send: `mail_send` is the owner's tap in
Mail. Mail proves a request is the owner's own tap with its App Manager grant plus `X-Wizard-Owner: 1`; anything it
sends for an agent carries `X-Wizard-Agent`. Kept in DATA_DIR/mail-access.json on the box.
"""
import json
import os
import threading
from pathlib import Path

LEVELS = ('no_access', 'read_only', 'draft_only')
DEFAULT = 'draft_only'
LABELS = {'no_access': 'No access', 'read_only': 'Read-only', 'draft_only': 'Draft only'}
WHAT = {'no_access': "Agents can't read your mail.",
        'read_only': "Agents read and search your mail. They can't draft or send.",
        'draft_only': 'Agents read, sort and write drafts. Only you send, from Mail.'}
RANK = {level: n for n, level in enumerate(LEVELS)}
# What each mail tool needs from an agent. None: agents never get it.
NEEDS = {'mail_search': 'read_only', 'mail_get': 'read_only', 'mail_update': 'draft_only',
         'mail_update_bulk': 'draft_only', 'mail_draft': 'draft_only', 'mail_send': None}
SEND_REFUSED = ("Agents can't send mail on this Wizard. Write it with mail_draft; the owner reads and sends it "
                'from Mail.')
_lock = threading.Lock()


class Refused(Exception):
    def __init__(self, code, message):
        super().__init__(code)
        self.code, self.message = code, message


def _file():
    return Path(os.environ.get('DATA_DIR') or '/data') / 'mail-access.json'


def level():
    try:
        value = json.loads(_file().read_text()).get('mail')
    except (OSError, ValueError, AttributeError):
        return DEFAULT
    return value if value in LEVELS else DEFAULT


def view():
    current = level()
    return {'level': current, 'label': LABELS[current], 'what': WHAT[current],
            'levels': [{'id': x, 'label': LABELS[x], 'what': WHAT[x]} for x in LEVELS]}


def set_level(value):
    if value not in LEVELS:
        raise ValueError('invalid_level')
    with _lock:
        f = _file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + '.tmp')
        tmp.write_text(json.dumps({'mail': value}))
        os.replace(tmp, f)
    return view()


def check(caller, tool):
    """Raise Refused unless caller ('owner' or 'agent:<name>') may run tool."""
    if tool not in NEEDS:
        raise Refused('not_found', 'Unknown mail tool.')
    if caller == 'owner':
        return
    need = NEEDS[tool]
    if need is None:
        raise Refused('agent_send_refused', SEND_REFUSED)
    if RANK[level()] < RANK[need]:
        raise Refused('agent_access_denied', f"The owner set agents' mail to {LABELS[level()]}"
                      ' (Connected accounts or Mail > Settings > Agent access).')
