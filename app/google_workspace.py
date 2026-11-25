"""Drive, Docs, Sheets and Contacts for the agent on the Connected accounts sign-in (wizard-connectors#27).

On for everyone (switch `google-workspace` retired). Read-only: Drive (`drive.readonly`: search files, read
Docs/Sheets/Slides as text) and Contacts (`contacts.readonly`: look up a person). Every function takes
`call(url, query=None, raw=False)`; the broker supplies it with the account's own token on fixed Google endpoints
(GoogleTransport.workspace). File and contact content comes from other people: returned as data, never acted on.
"""
import re

DRIVE = 'https://www.googleapis.com/drive/v3/files'
PEOPLE_SEARCH = 'https://people.googleapis.com/v1/people:searchContacts'
# Google files have no bytes of their own: Drive exports them as text.
EXPORT = {'application/vnd.google-apps.document': 'text/plain',
          'application/vnd.google-apps.spreadsheet': 'text/csv',
          'application/vnd.google-apps.presentation': 'text/plain'}
TEXT_TYPES = ('application/json', 'application/xml', 'application/csv', 'application/x-yaml', 'application/javascript')
MAX_TEXT = 200_000
MAX_DOWNLOAD = 2 * 1024 * 1024
FILE_ID = re.compile(r'[A-Za-z0-9_-]{1,200}')
FILE_FIELDS = 'id,name,mimeType,modifiedTime,webViewLink,size'


class BadArgs(ValueError):
    """Arguments the caller must fix (code invalid_arguments)."""


def _text(args, name, maximum, required=True):
    value = args.get(name)
    if value in (None, '') and not required:
        return ''
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise BadArgs(f'{name} must be text up to {maximum} characters.')
    return value.strip()


def _number(args, name, default, low, high):
    value = args.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise BadArgs(f'{name} must be a whole number from {low} to {high}.')
    return value


def _only(args, allowed):
    extra = set(args) - set(allowed)
    if extra:
        raise BadArgs('unknown argument: ' + sorted(extra)[0])


def _file(row):
    out = {'id': str(row.get('id', ''))[:200], 'name': str(row.get('name', ''))[:500],
           'mime_type': str(row.get('mimeType', ''))[:200], 'modified': str(row.get('modifiedTime', ''))[:40]}
    link = row.get('webViewLink')
    if isinstance(link, str) and link.startswith('https://') and len(link) <= 2048:
        out['link'] = link
    return out


def drive_search(call, args):
    """Files in the account's Drive, newest first; `query` matches names and contents."""
    _only(args, ('query', 'max'))
    query = _text(args, 'query', 200, required=False)
    limit = _number(args, 'max', 20, 1, 50)
    q = 'trashed = false'
    params = {'pageSize': limit, 'fields': 'files(' + FILE_FIELDS + ')',
              'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true'}
    if query:
        quoted = query.replace('\\', '\\\\').replace("'", "\\'")
        q += f" and (name contains '{quoted}' or fullText contains '{quoted}')"
    else:
        params['orderBy'] = 'modifiedTime desc'  # Drive refuses orderBy with a fullText search
    params['q'] = q
    raw = call(DRIVE, params)
    return {'files': [_file(r) for r in (raw.get('files') or [])[:limit] if isinstance(r, dict)]}


def drive_read(call, args):
    """One file as text: Docs and Slides as plain text, Sheets as CSV, text files as they are."""
    _only(args, ('file_id',))
    fid = args.get('file_id')
    if not isinstance(fid, str) or not FILE_ID.fullmatch(fid):
        raise BadArgs('file_id must be a Drive file id (from drive_search).')
    meta = call(DRIVE + '/' + fid, {'fields': FILE_FIELDS, 'supportsAllDrives': 'true'})
    mime = str(meta.get('mimeType', ''))
    found = {'file': _file(meta), 'untrusted': True}
    if mime in EXPORT:
        body = call(DRIVE + '/' + fid + '/export', {'mimeType': EXPORT[mime]}, raw=True)
    elif mime.startswith('text/') or mime in TEXT_TYPES:
        try:
            size = int(meta.get('size') or 0)
        except (TypeError, ValueError):
            size = 0
        if size > MAX_DOWNLOAD:
            return {**found, 'text': None, 'note': 'This file is too large to read here; open it in Drive.'}
        body = call(DRIVE + '/' + fid, {'alt': 'media', 'supportsAllDrives': 'true'}, raw=True)
    else:
        return {**found, 'text': None, 'note': 'This kind of file cannot be read as text; open it in Drive.'}
    text = body if isinstance(body, str) else ''
    return {**found, 'text': text[:MAX_TEXT], 'truncated': len(text) > MAX_TEXT}


def _person(row):
    p = row.get('person') if isinstance(row, dict) else None
    if not isinstance(p, dict):
        return None
    names = [n.get('displayName') for n in p.get('names') or [] if isinstance(n, dict) and n.get('displayName')]
    emails = [e.get('value') for e in p.get('emailAddresses') or [] if isinstance(e, dict) and e.get('value')]
    phones = [x.get('value') for x in p.get('phoneNumbers') or [] if isinstance(x, dict) and x.get('value')]
    orgs = [o.get('name') for o in p.get('organizations') or [] if isinstance(o, dict) and o.get('name')]
    return {'name': str(names[0])[:300] if names else '', 'emails': [str(e)[:254] for e in emails[:10]],
            'phones': [str(x)[:60] for x in phones[:10]], 'organization': str(orgs[0])[:300] if orgs else ''}


def contacts_search(call, args):
    """People in the account's Google Contacts whose name, email or phone matches `query`."""
    _only(args, ('query', 'max'))
    query = _text(args, 'query', 200)
    limit = _number(args, 'max', 10, 1, 30)
    mask = 'names,emailAddresses,phoneNumbers,organizations'
    # Google answers a cold search cache with nothing; its documented fix is one empty search first.
    call(PEOPLE_SEARCH, {'query': '', 'readMask': 'names'})
    raw = call(PEOPLE_SEARCH, {'query': query, 'readMask': mask, 'pageSize': limit})
    people = [p for p in (_person(r) for r in (raw.get('results') or [])[:limit]) if p]
    return {'contacts': people}


TOOLS = {'drive_search': drive_search, 'drive_read': drive_read, 'contacts_search': contacts_search}
# The Google scope each tool needs on the account.
NEEDS = {'drive_search': 'drive', 'drive_read': 'drive', 'contacts_search': 'contacts'}
