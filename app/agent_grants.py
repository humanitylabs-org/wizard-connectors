"""What each agent may do with each connected account (wizard-connectors#49, switch grants-panel).

Contract wizard.app-grants/1 (docs/APP_GRANTS.md). The grants live here, on the box, outside the agent and outside the
Agent Service, so an agent can't grant itself access: only the owner's tap in Connected accounts changes them. Apps and
the MCP gateway ask "may agent X do Y on account Z?" with POST /service/grants/v1/check and get a yes or no; every
answer goes to a content-free audit log.

Levels, lowest first: none, read, draft, send. A new agent gets none on every account until the owner grants it.
Messenger accounts show Draft as the recommended level (not granted by itself). A grant is per account and agent,
optionally narrowed per app (the `app` field): an app-specific row wins over the account-wide one.

Files (DATA_DIR): agent-grants.json (accounts other apps registered, agents seen, grants), grants-audit.jsonl.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

CONTRACT = 'wizard.app-grants/1'
LEVELS = ('none', 'read', 'draft', 'send')
RANK = {level: n for n, level in enumerate(LEVELS)}
LABELS = {'none': 'No access', 'read': 'Read', 'draft': 'Draft', 'send': 'Send'}
# The highest level that means something per kind of account. Google mail and Microsoft mail are draft-only for
# agents (only the owner sends, from Mail); bank and health accounts are sources to read.
KINDS = {'google': 'draft', 'microsoft': 'draft', 'messenger': 'send', 'bank': 'read', 'health': 'read',
         'ai': 'send', 'other': 'send'}
KIND_NAMES = {'google': 'Google', 'microsoft': 'Microsoft', 'messenger': 'Messenger', 'bank': 'Bank',
              'health': 'Health', 'ai': 'AI account', 'other': 'Account'}
RECOMMENDED = {'messenger': 'draft'}
DEFAULT_AGENT = 'main'
NAME = re.compile(r'[a-z0-9][a-z0-9_-]{0,62}')
ACCOUNT_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,63}:[A-Za-z0-9._@+-]{1,128}')
MAX_AGENTS, MAX_REGISTERED, AUDIT_KEEP = 32, 64, 500
_lock = threading.Lock()


class Invalid(ValueError):
    pass


def _dir():
    return Path(os.environ.get('DATA_DIR') or '/data')


def _load():
    try:
        saved = json.loads((_dir() / 'agent-grants.json').read_text())
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict): saved = {}
    accounts = saved.get('accounts') if isinstance(saved.get('accounts'), dict) else {}
    agents = [a for a in saved.get('agents', []) if isinstance(a, str) and NAME.fullmatch(a)] \
        if isinstance(saved.get('agents'), list) else []
    grants = saved.get('grants') if isinstance(saved.get('grants'), dict) else {}
    return {'accounts': accounts, 'agents': agents, 'grants': grants}


def _save(doc):
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / 'agent-grants.json.tmp'
    tmp.write_text(json.dumps(doc))
    os.replace(tmp, d / 'agent-grants.json')


def agent_name(value):
    """A caller-named agent ('Main', ' ops ') as its stored id, or Invalid."""
    name = value.strip().lower() if isinstance(value, str) else ''
    if not NAME.fullmatch(name): raise Invalid('invalid_agent')
    return name


def all_accounts(google_accounts, doc=None):
    """Every connected account: Google ones from this app's own sign-in, then those other connector apps registered."""
    doc = doc or _load()
    rows = [{'id': 'google:' + a['id'], 'kind': 'google', 'label': a.get('email') or 'Google account',
             'source': 'connected-accounts', 'status': a.get('status', 'active')}
            for a in google_accounts if isinstance(a, dict) and isinstance(a.get('id'), str)]
    for aid, a in sorted(doc['accounts'].items()):
        if isinstance(a, dict) and ACCOUNT_ID.fullmatch(aid):
            rows.append({'id': aid, 'kind': a.get('kind') if a.get('kind') in KINDS else 'other',
                         'label': str(a.get('label') or aid)[:120], 'source': str(a.get('from', '')), 'status': 'active',
                         **({'max': a['max']} if a.get('max') in LEVELS else {})})
    for row in rows:
        cap = KINDS[row['kind']]
        if RANK.get(row.get('max'), 99) < RANK[cap]: cap = row['max']
        row['max'] = cap
        row['levels'] = [x for x in LEVELS if RANK[x] <= RANK[cap]]
        if row['kind'] in RECOMMENDED: row['recommended'] = RECOMMENDED[row['kind']]
    return rows


def _level(doc, account, agent, app=None):
    rows = doc['grants'].get(account, {}).get(agent, {})
    if not isinstance(rows, dict): return 'none'
    value = rows.get(app) if app and app in rows else rows.get('*')
    return value if value in LEVELS else 'none'


def agents(doc=None):
    doc = doc or _load()
    return [DEFAULT_AGENT] + [a for a in doc['agents'] if a != DEFAULT_AGENT]


def view(google_accounts):
    doc = _load()
    names = agents(doc)
    accounts = []
    for row in all_accounts(google_accounts, doc):
        apps = {}
        for agent in names:
            rows = doc['grants'].get(row['id'], {}).get(agent, {})
            if isinstance(rows, dict):
                narrowed = {k: v for k, v in rows.items() if k != '*' and v in LEVELS}
                if narrowed: apps[agent] = narrowed
        accounts.append({**row, 'agents': {agent: _level(doc, row['id'], agent) for agent in names},
                         **({'apps': apps} if apps else {})})
    return {'contract': CONTRACT, 'agents': names, 'accounts': accounts,
            'levels': [{'id': x, 'label': LABELS[x]} for x in LEVELS]}


def set_level(google_accounts, account, agent, level, app=None):
    """The owner's tap: agent's level on account (optionally for one app only). Returns the new view."""
    agent = agent_name(agent)
    if level not in LEVELS: raise Invalid('invalid_level')
    if app is not None and (not isinstance(app, str) or not NAME.fullmatch(app)): raise Invalid('invalid_app')
    with _lock:
        doc = _load()
        row = next((a for a in all_accounts(google_accounts, doc) if a['id'] == account), None)
        if not row: raise Invalid('account_unknown')
        if RANK[level] > RANK[row['max']]: raise Invalid('level_not_offered')
        if agent not in agents(doc):
            if len(doc['agents']) >= MAX_AGENTS: raise Invalid('too_many_agents')
            doc['agents'].append(agent)
        per = doc['grants'].setdefault(account, {}).setdefault(agent, {})
        per[app or '*'] = level
        _save(doc)
    return view(google_accounts)


def add_agent(google_accounts, agent):
    agent = agent_name(agent)
    with _lock:
        doc = _load()
        if agent not in agents(doc):
            if len(doc['agents']) >= MAX_AGENTS: raise Invalid('too_many_agents')
            doc['agents'].append(agent)
            _save(doc)
    return view(google_accounts)


def register(app, accounts):
    """A connector app (by its own grant) lists the accounts it holds; replaces that app's earlier list."""
    if not isinstance(accounts, list) or len(accounts) > MAX_REGISTERED: raise Invalid('invalid_accounts')
    rows = {}
    for a in accounts:
        if not isinstance(a, dict) or not set(a) <= {'id', 'kind', 'label', 'max'} or not isinstance(a.get('id'), str):
            raise Invalid('invalid_accounts')
        if a.get('kind', 'other') not in KINDS or a.get('kind') == 'google' or ('max' in a and a['max'] not in LEVELS):
            raise Invalid('invalid_accounts')
        aid = app + ':' + a['id']
        if not ACCOUNT_ID.fullmatch(aid) or not isinstance(a.get('label', ''), str): raise Invalid('invalid_accounts')
        rows[aid] = {'from': app, 'kind': a.get('kind', 'other'), 'label': a.get('label', '')[:120] or a['id'],
                     **({'max': a['max']} if 'max' in a else {})}
    with _lock:
        doc = _load()
        doc['accounts'] = {k: v for k, v in doc['accounts'].items() if not (isinstance(v, dict) and v.get('from') == app)}
        doc['accounts'].update(rows)
        _save(doc)
    return sorted(rows)


def check(google_accounts, by, agent, account, action, app=None):
    """May agent do action (read/draft/send) on account, for app? Always answers; always audited."""
    if action not in LEVELS[1:]: raise Invalid('invalid_action')
    if app is not None and (not isinstance(app, str) or not NAME.fullmatch(app)): raise Invalid('invalid_app')
    if not isinstance(account, str) or len(account) > 200: raise Invalid('invalid_account')
    agent = agent_name(agent)
    with _lock:
        doc = _load()
        row = next((a for a in all_accounts(google_accounts, doc) if a['id'] == account), None)
        if agent not in agents(doc) and len(doc['agents']) < MAX_AGENTS:
            doc['agents'].append(agent)   # the owner sees every agent that asked, with No access, and can grant it
            _save(doc)
        level = _level(doc, account, agent, app) if row else 'none'
        if not row: reason = 'account_unknown'
        elif RANK[action] > RANK[row['max']]: reason = 'not_offered'
        elif RANK[level] >= RANK[action]: reason = 'granted'
        else: reason = 'not_granted'
        allowed = reason == 'granted'
        _audit({'at': int(time.time()), 'by': by, 'agent': agent, 'account': account if row else '?',
                'action': action, **({'app': app} if app else {}), 'allowed': allowed, 'reason': reason})
    return {'contract': CONTRACT, 'allowed': allowed, 'level': level, 'need': action, 'reason': reason}


def _audit(entry):
    f = _dir() / 'grants-audit.jsonl'
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open('a') as out:
        out.write(json.dumps(entry) + '\n')
    try:
        lines = f.read_text().splitlines()
    except OSError:
        return
    if len(lines) > AUDIT_KEEP * 2:
        tmp = f.with_name(f.name + '.tmp')
        tmp.write_text('\n'.join(lines[-AUDIT_KEEP:]) + '\n')
        os.replace(tmp, f)


def audit(limit=50):
    try:
        lines = (_dir() / 'grants-audit.jsonl').read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try: out.append(json.loads(line))
        except ValueError: continue
        if len(out) >= limit: break
    return out
