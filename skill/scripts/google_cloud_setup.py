#!/usr/bin/env python3
"""Owner Google Cloud UI setup. No Google secret is ever emitted or written to disk.
Requires Playwright, a preserved Wizard Browser CDP and an MCP-minted intake URL.
Google Console changes frequently: unknown UI fails closed, never dump the page.
"""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import urlsplit, urlencode, urlunsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NeedsOwner(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise NeedsOwner('intake_redirect_refused')


def emit(step, status, reason=None, **public):
    # Only allowlisted constants/public project IDs. Never log exceptions or DOM.
    print(json.dumps(dict(step=step, status=status, **({'reason': reason} if reason else {}), **public)), flush=True)


def intake_target(value):
    u = urlsplit(value)
    if (u.scheme != 'http' or u.hostname not in ('wizard-connectors-calendar', 'localhost', '127.0.0.1')
            or u.username or u.password or u.query or u.path != '/api/google/setup/intake'
            or not re.fullmatch(r'[A-Za-z0-9_-]{43}', u.fragment)):
        raise NeedsOwner('invalid_internal_intake')
    return urlunsplit((u.scheme, u.netloc, u.path, '', '')), u.fragment


def deposit(value, credentials):
    url, token = intake_target(value)
    req = Request(url, data=json.dumps(credentials).encode(), method='POST', headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=15) as response:
            result = json.loads(response.read(1024))
            if response.status != 200 or result != {'ok': True}: raise ValueError()
    except Exception:
        raise NeedsOwner('intake_failed_get_fresh_capability_and_check_status') from None


class Console:
    def __init__(self, page, *, project=None, audience='External', base='https://console.cloud.google.com'):
        self.p, self.project, self.audience, self.base = page, project, audience, base
        page.set_default_timeout(12000)
        page.set_default_navigation_timeout(45000)

    def button(self, name):
        return self.p.get_by_role('button', name=re.compile(name, re.I))

    def visible(self, locator):
        return locator.count() > 0 and locator.first.is_visible()

    def gate(self):
        # No page dumps or field reads while the owner is authenticating.
        if urlsplit(self.p.url).hostname == 'accounts.google.com': raise NeedsOwner('sign_in_in_wizard_browser')
        for pattern, reason in [
            (r'accept.*terms|agree.*terms|terms of service', 'review_cloud_terms'),
            (r'verify (?:it.s you|your identity)|verification code|captcha', 'complete_verification'),
            (r'set up billing|enable billing|payment method|start free trial', 'billing_prompt_do_not_purchase'),
        ]:
            if self.visible(self.p.get_by_role('dialog').filter(has_text=re.compile(pattern, re.I))):
                raise NeedsOwner(reason)
        for name in [r'I agree.*(?:policy|terms)', r'accept.*terms']:
            c = self.p.get_by_role('checkbox', name=re.compile(name, re.I))
            if self.visible(c) and not c.first.is_checked(): raise NeedsOwner('review_google_data_policy_or_terms')
        # Full-page billing/terms gates as well as dialogs.
        if self.visible(self.p.get_by_role('heading', name=re.compile(r'terms of service|verify your identity|set up billing', re.I))):
            raise NeedsOwner('review_google_human_gate')

    def go(self, path):
        url = self.base + path
        if self.project: url += ('&' if '?' in url else '?') + urlencode({'project': self.project})
        self.p.goto(url, wait_until='domcontentloaded')
        self.gate()

    def click(self, pattern):
        self.gate()
        self.button(pattern).first.click()
        self.gate()

    def choose(self, label, value):
        c = self.p.get_by_role('combobox', name=re.compile(label, re.I)).first
        if c.evaluate('(e)=>e.tagName') == 'SELECT': c.select_option(label=value)
        else:
            c.click()
            self.p.get_by_role('option', name=value, exact=True).click()

    def project_setup(self):
        if self.project:
            self.go('/home/dashboard')
            return
        # Reuse an existing project, even if this process has never run before.
        self.go('/cloud-resource-manager')
        row = self.p.get_by_role('row').filter(has=self.p.get_by_text('Wizard', exact=True))
        if self.visible(row):
            if row.count() != 1: raise NeedsOwner('multiple_wizard_projects_choose_project_flag')
            text = row.inner_text()  # Project table only, never a credentials screen.
            match = re.search(r'\bwizard-[a-z0-9-]{5,28}\b', text)
            if not match: raise NeedsOwner('choose_existing_project_with_project_flag')
            self.project = match.group()
            return
        # Require the resource table to load; an empty/loading screen is not absence.
        self.p.get_by_role('table').first.wait_for()
        if self.visible(row): return self.project_setup()
        self.go('/projectcreate')
        self.p.get_by_label(re.compile(r'^Project name', re.I)).fill('Wizard')
        edit = self.button(r'^Edit$')
        if self.visible(edit): edit.first.click()
        pid = self.p.get_by_label(re.compile(r'^Project ID', re.I))
        self.project = 'wizard-' + secrets.token_hex(6)
        if not self.visible(pid): raise NeedsOwner('project_id_control_changed')
        pid.fill(self.project)
        self.click(r'^Create$')
        # Authoritative readback; Google's creation notification may take time.
        self.p.get_by_text(re.compile(r'created|creation complete', re.I)).first.wait_for(timeout=60000)
        self.go('/home/dashboard')

    def api(self):
        self.go('/apis/library/calendar-json.googleapis.com')
        enable = self.button(r'^Enable$')
        # Both states need a loaded page; wait for either action before deciding.
        enable.or_(self.button(r'^Manage$')).first.wait_for(timeout=30000)
        if self.visible(enable): self.click(r'^Enable$')
        self.button(r'^Manage$|^Disable API$').first.wait_for(timeout=60000)

    def owner_email(self):
        # Account avatar's accessible label contains the active Google email.
        labels = self.p.get_by_role('button', name=re.compile(r'Google Account', re.I))
        if not self.visible(labels): raise NeedsOwner('cannot_identify_active_google_account')
        label = labels.first.get_attribute('aria-label') or ''
        match = re.search(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', label)
        if not match: raise NeedsOwner('cannot_identify_active_google_account')
        return match.group()

    def branding(self):
        self.go('/auth/overview')
        start = self.button(r'^Get started$')
        # Wait until overview or first-run setup is rendered.
        start.or_(self.button(r'^Create (?:OAuth )?client$')).or_(self.p.get_by_role('heading', name=re.compile('OAuth overview', re.I))).first.wait_for(timeout=30000)
        if not self.visible(start): return
        email = self.owner_email()
        self.click(r'^Get started$')
        self.p.get_by_label(re.compile(r'^App name', re.I)).fill('Wizard')
        self.choose(r'User support email', email)
        self.click(r'^Next$')
        self.p.get_by_role('radio', name=self.audience, exact=True).check()
        self.click(r'^Next$')
        self.p.get_by_label(re.compile(r'^Email address', re.I)).fill(email)
        self.click(r'^Next$')
        # Legal acceptance belongs to the owner. Never check it for them.
        self.gate()
        raise NeedsOwner('review_google_data_policy_and_finish_branding_then_rerun')

    def audience_setup(self):
        self.go('/auth/audience')
        if self.audience == 'Internal':
            self.p.get_by_text('Internal', exact=True).first.wait_for()
            return
        production = self.p.get_by_text('In production', exact=True)
        publish = self.button(r'^Publish app$')
        production.or_(publish).first.wait_for(timeout=30000)
        if self.visible(production): return
        self.click(r'^Publish app$')
        # Publishing the owner's personal app is authorized by this workflow;
        # never click a legal checkbox or submit public verification.
        self.click(r'^Confirm$')
        production.first.wait_for(timeout=30000)

    def client(self, redirect):
        self.go('/auth/clients')
        create = self.button(r'^Create client$')
        create.first.wait_for(timeout=30000)
        row = self.p.get_by_role('row').filter(has=self.p.get_by_text('Wizard', exact=True))
        if self.visible(row):
            if row.count() != 1: raise NeedsOwner('multiple_wizard_clients_choose_manually')
            row.get_by_role('link', name='Wizard', exact=True).click()
            self.gate()
            uri = self.p.get_by_label(re.compile(r'^URIs?\s*1$|^Authorized redirect URI', re.I))
            if not self.visible(uri) or uri.first.input_value() != redirect:
                raise NeedsOwner('existing_client_redirect_differs_do_not_replace')
            # Google may show a secret only once. Never create/rotate a duplicate.
            return self.credentials()
        self.click(r'^Create client$')
        self.choose(r'Application type', 'Web application')
        self.p.get_by_label(re.compile(r'^Name$', re.I)).fill('Wizard')
        section = self.p.locator('section').filter(has=self.p.get_by_text('Authorized redirect URIs', exact=True))
        if section.count() == 1:
            section.get_by_role('button', name='Add URI', exact=True).click()
        else:
            # Current Console has separate origins and redirects sections. Never
            # pick the first Add URI (that would register an origin, not a callback).
            self.button(r'^Add URI$').last.click()
        self.p.get_by_label(re.compile(r'^URIs?\s*1$|^Authorized redirect URI', re.I)).last.fill(redirect)
        self.click(r'^Create$')
        self.p.get_by_role('dialog').filter(has_text=re.compile(r'OAuth client created', re.I)).wait_for(timeout=30000)
        return self.credentials()

    def credentials(self):
        # Only this isolated function handles credential-bearing UI. No DOM dumps,
        # screenshots, tracing, download files, clipboard or exception text.
        values = self.p.evaluate("""() => {
          const root = document.querySelector('[role="dialog"]') || document;
          const read = label => {
            const inputs = [...root.querySelectorAll('input')];
            const i = inputs.find(e => (e.getAttribute('aria-label') || '').toLowerCase() === label.toLowerCase()
              || [...root.querySelectorAll('label')].some(l => l.control === e && l.textContent.trim().toLowerCase() === label.toLowerCase()));
            return i?.value || '';
          };
          const text = root.innerText;
          return {client_id: read('Client ID') || text.match(/[A-Za-z0-9_-]{1,200}\\.apps\\.googleusercontent\\.com/)?.[0] || '',
            client_secret: read('Client secret') || text.match(/GOCSPX-[A-Za-z0-9_-]+/)?.[0] || ''};
        }""")
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com', values['client_id']):
            raise NeedsOwner('client_id_not_available_ui_changed')
        if not re.fullmatch(r'[^\s]{8,512}', values['client_secret']):
            raise NeedsOwner('existing_secret_not_recoverable_use_manual_form_no_rotation')
        return values


def run(args, page):
    c = Console(page, project=args.project, audience=args.audience)
    if args.state_file.exists():
        data = json.loads(args.state_file.read_text())
        c.project = c.project or data.get('project')
    if c.project and not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', c.project): raise NeedsOwner('invalid_project_id')
    if args.dry_run:
        c.go('/auth/overview')
        emit('dry_run', 'ok', project=c.project)
        return
    if not args.intake_url or not args.redirect_uri: raise NeedsOwner('get_setup_begin_from_mcp_first')
    intake_target(args.intake_url)
    if args.step == 'all' or args.step == 'project':
        emit('project', 'running')
        c.project_setup()
        args.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.state_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f: json.dump({'project': c.project}, f)
        emit('project', 'ok', project=c.project)
    if not c.project: raise NeedsOwner('run_project_step_first')
    for step, action in [('api', c.api), ('branding', c.branding), ('audience', c.audience_setup)]:
        if args.step in ('all', step):
            emit(step, 'running'); action(); emit(step, 'ok')
    if args.step in ('all', 'client'):
        emit('client', 'running')
        credentials = c.client(args.redirect_uri)
        try: deposit(args.intake_url, credentials)
        finally: credentials.clear()
        emit('deposit', 'ok')
        # Close the credential dialog without exposing it in a later agent read.
        c.go('/auth/overview')
    emit('setup', 'ok', project=c.project)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--step', choices=['all','project','api','branding','audience','client'], default='all')
    parser.add_argument('--project')
    parser.add_argument('--audience', choices=['External','Internal'], default='External')
    parser.add_argument('--redirect-uri', default=os.environ.get('GOOGLE_SETUP_REDIRECT_URI'))
    parser.add_argument('--intake-url', default=os.environ.get('GOOGLE_SETUP_INTAKE_URL'), help='MCP capability; prefer env, never put provider credentials in argv')
    parser.add_argument('--state-file', type=Path, default=Path.home()/'.cache/wizard-google-setup/project.json')
    parser.add_argument('--dry-run', action='store_true', help='Navigate/read gate only; no writes or secrets')
    args = parser.parse_args()
    # DEBUG/trace/PWDEBUG must not turn private browser values into ordinary logs.
    for key in ('DEBUG','PWDEBUG','PW_TRACE_DIR'): os.environ.pop(key, None)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            endpoint = os.environ.get('HANDOFF_CDP_URL') or os.environ.get('BROWSER_CDP_URL')
            if not endpoint: raise NeedsOwner('wizard_browser_cdp_required')
            browser = p.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0]
            pages = [p for p in context.pages if urlsplit(p.url).hostname == 'console.cloud.google.com']
            if not pages: raise NeedsOwner('open_console_and_sign_in_first')
            run(args, pages[0])
            # Do NOT close the shared handoff browser; the owner/host owns it.
        return 0
    except NeedsOwner as e:
        emit('setup', 'needs_owner', str(e)); return 2
    except Exception:
        emit('setup', 'needs_owner', 'console_ui_changed_or_timeout_no_automatic_retry'); return 2


if __name__ == '__main__': sys.exit(main())
