#!/usr/bin/env python3
"""Owner Google Cloud setup in a fresh disposable Human Handoff profile.
The owner types password/2FA during takeover with all inspection paused. The model
receives allowlisted status codes only. Persistent/shared CDP is refused by default.
Terminal exits attempt Google sign-out and verify handoff/profile removal.
Owner sign-in/verification pauses under the original TTL. Unknown UI fails closed.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import urlsplit, urlencode, urlunsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

# Keep the versioned registry beside this script so WAM can ship the skill alone.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_agreement_definitions import IDS, VERSION, COUNTRIES, DOCUMENTS


def parse_agreements(value):
    try:
        data = json.loads(value) if isinstance(value, str) else value
        if (not isinstance(data, dict) or set(data) != {'accepted', 'version', 'country'}
                or data['version'] != VERSION or data['country'] not in COUNTRIES
                or not isinstance(data['accepted'], list)
                or any(not isinstance(x, str) or x not in IDS for x in data['accepted'])
                or len(data['accepted']) != len(set(data['accepted']))):
            raise ValueError()
        return data
    except (ValueError, TypeError, KeyError):
        raise NeedsOwner('agreements_missing_or_version_changed') from None


def agreement_for_label(label):
    # Whole-label match, never a substring such as "terms" or an arbitrary link.
    text = re.sub(r'\s+', ' ', label).strip().rstrip('.')
    names = {
        r'Google Cloud(?: Platform)? Terms of Service': {'cloud_terms'},
        r'Google APIs Terms of Service': {'api_terms'},
        r'Google API Services:? User Data Policy': {'user_data_policy'},
        r'Google APIs Terms of Service and (?:the )?Google API Services:? User Data Policy': {'api_terms', 'user_data_policy'},
    }
    for name, ids in names.items():
        if re.fullmatch(r'(?:I agree to (?:the )?|I accept (?:the )?)?' + name, text, re.I): return ids
    raise NeedsOwner('unrecorded_google_agreement')


REASON_CODES = frozenset('''agreements_missing_or_version_changed branding_finish_control_changed
cannot_identify_active_google_account choose_existing_project_with_project_flag client_id_not_available_ui_changed
country_control_changed existing_client_redirect_differs_do_not_replace existing_secret_not_recoverable_use_manual_form_no_rotation
get_setup_begin_from_mcp_first google_agreement_submit_not_confirmed intake_failed_get_fresh_capability_and_check_status
intake_redirect_refused invalid_internal_intake invalid_project_id multiple_wizard_clients_choose_manually
multiple_wizard_projects_choose_project_flag open_console_and_sign_in_first project_id_control_changed
review_google_agreements_in_connected_accounts run_project_step_first sign_in_in_wizard_browser unexpected_console_origin
unrecorded_google_agreement wizard_browser_cdp_required complete_verification billing_prompt_do_not_purchase
console_ui_changed_or_timeout_no_automatic_retry fresh_disposable_handoff_required
handoff_profile_not_verified handoff_teardown_failed google_sign_out_not_verified'''.split())


class NeedsOwner(Exception):
    def __init__(self, reason):
        super().__init__(reason if reason in REASON_CODES else 'console_ui_changed_or_timeout_no_automatic_retry')


class HandoffSession:
    """Read only the selected local handoff's metadata; never its browser data."""
    def __init__(self):
        self.sid = os.environ.get('HANDOFF_SESSION_ID', '')
        self.endpoint = os.environ.get('HANDOFF_CDP_URL', '')
        if not re.fullmatch(r'hh-[0-9]{8}-[0-9]{6}-[a-f0-9]{6}', self.sid):
            raise NeedsOwner('fresh_disposable_handoff_required')
        root = Path(os.environ.get('HUMAN_HANDOFF_HOME') or
                    str(Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'hermes-human-handoff')).expanduser()
        self.directory = root/'sessions'/self.sid
        try:
            config_path = self.directory/'config.json'
            if self.directory.is_symlink() or config_path.is_symlink(): raise ValueError()
            st = config_path.stat()
            if st.st_uid != os.getuid() or st.st_mode & 0o077: raise ValueError()
            config = json.loads(config_path.read_text())
            self.mode = config.get('profile_mode')
            if self.mode != 'disposable':
                raise NeedsOwner('fresh_disposable_handoff_required')
            self.profile = self.directory/'browser-profile'
            if not self.profile.is_dir() or self.profile.is_symlink(): raise ValueError()
            status = self.command('status')
            if (status.get('status') != 'ready' or status.get('session_id') != self.sid
                    or status.get('cdp_url') != self.endpoint or not self.endpoint): raise ValueError()
            expires = datetime.fromisoformat(status['expires_at'].replace('Z', '+00:00'))
            if expires <= datetime.now(timezone.utc): raise ValueError()
            endpoint = urlsplit(self.endpoint)
            if endpoint.scheme != 'http' or endpoint.hostname not in ('localhost','127.0.0.1') or endpoint.username or endpoint.password: raise ValueError()
        except NeedsOwner: raise
        except Exception: raise NeedsOwner('handoff_profile_not_verified') from None

    def command(self, operation):
        # Capture raw CLI output locally, including cleanup errors; never print it.
        result = subprocess.run(['hermes-human-handoff', operation, self.sid], capture_output=True, text=True, timeout=25)
        if result.returncode or len(result.stdout) > 65536: raise NeedsOwner('handoff_teardown_failed')
        value = json.loads(result.stdout)
        if not isinstance(value, dict): raise NeedsOwner('handoff_teardown_failed')
        return value

    def stop_and_verify(self):
        try:
            self.command('stop')
            status = self.command('status')  # authoritative readback, not the stop response
            if (status.get('session_id') != self.sid or status.get('status') not in ('stopped', 'expired')
                    or status.get('cleanup_error') or self.profile.exists() or self.profile.is_symlink()
                    or any((self.directory/name).exists() for name in ('capability.json','config.json','vnc-passwd','webroot'))):
                raise ValueError()
        except Exception: raise NeedsOwner('handoff_teardown_failed') from None


def sign_out_google(page):
    """Fixed logout, provider UI confirmation and local cookie check; no values emitted."""
    try:
        page.goto('https://accounts.google.com/Logout', wait_until='domcontentloaded')
        signout = page.get_by_role('button', name=re.compile(r'^Sign out(?: of all accounts)?$', re.I))
        if signout.count() == 1 and signout.first.is_visible(): signout.first.click()
        # Never inspect password, email or 2FA field values, even after the logout.
        signed_out = page.get_by_role('heading', name=re.compile(r'^Sign in$|signed out', re.I)).or_(page.locator('#identifierId'))
        signed_out.first.wait_for(state='visible', timeout=15000)
        auth_cookies = {'SID','HSID','SSID','APISID','SAPISID','__Secure-1PSID','__Secure-3PSID'}
        if any(c['name'] in auth_cookies and (c['domain'].lstrip('.') == 'google.com' or c['domain'].endswith('.google.com')) for c in page.context.cookies()):
            raise ValueError()
    except Exception: raise NeedsOwner('google_sign_out_not_verified') from None


def finish_handoff(handoff, page):
    # Profile deletion is mandatory even if provider logout or setup failed.
    signout_error = None
    try:
        if page is None: raise NeedsOwner('google_sign_out_not_verified')
        sign_out_google(page)
        emit('sign_out', 'ok')
    except Exception: signout_error = 'google_sign_out_not_verified'
    try: handoff.stop_and_verify()
    except Exception: raise NeedsOwner('handoff_teardown_failed') from None
    emit('teardown', 'ok')
    if signout_error: raise NeedsOwner(signout_error)


OWNER_RESUMABLE = frozenset({'open_console_and_sign_in_first', 'sign_in_in_wizard_browser', 'complete_verification'})


def finalize_attempt(handoff, page, error):
    # Authentication/verification is an owner-only takeover, not a failed setup.
    # Do not navigate/logout/delete the page while the owner is using it. The
    # existing CLI TTL still retires the disposable session; no extension here.
    if isinstance(error, NeedsOwner) and str(error) in OWNER_RESUMABLE:
        try:
            status = handoff.command('status')
            expires = datetime.fromisoformat(status['expires_at'].replace('Z', '+00:00'))
            valid = (status.get('status') == 'ready' and status.get('session_id') == handoff.sid
                     and expires > datetime.now(timezone.utc))
        except Exception:
            valid = False
        if not valid:
            handoff.stop_and_verify()
            raise NeedsOwner('handoff_teardown_failed')
        emit('teardown', 'needs_owner', str(error))
        return
    finish_handoff(handoff, page)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise NeedsOwner('intake_redirect_refused')


def emit(step, status, reason=None, **public):
    # Only allowlisted constants/public project IDs. Never log exceptions or DOM.
    if step not in {'project','api','branding','audience','client','deposit','setup','dry_run','sign_out','teardown'} or status not in {'running','ok','needs_owner'}:
        step, status, reason = 'setup', 'needs_owner', 'console_ui_changed_or_timeout_no_automatic_retry'
    if reason and reason not in REASON_CODES: reason = 'console_ui_changed_or_timeout_no_automatic_retry'
    print(json.dumps(dict(step=step, status=status, **({'reason': reason} if reason else {}))), flush=True)


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
    def __init__(self, page, *, project=None, audience='External', base='https://console.cloud.google.com', agreements=None, allow_accept=True):
        self.p, self.project, self.audience, self.base = page, project, audience, base
        self.agreements, self.allow_accept = agreements, allow_accept
        self.legal_checked = False
        page.set_default_timeout(12000)
        page.set_default_navigation_timeout(45000)

    def button(self, name):
        return self.p.get_by_role('button', name=re.compile(name, re.I))

    def visible(self, locator):
        return locator.count() > 0 and locator.first.is_visible()

    def checkbox_label(self, checkbox):
        # Read only this control's accessible label, never a page/credential dump.
        return checkbox.evaluate("""e => e.getAttribute('aria-label') ||
          (e.getAttribute('aria-labelledby') || '').split(/\\s+/).map(id => document.getElementById(id)?.textContent || '').join(' ').trim() ||
          [...(e.labels || [])].map(l => l.textContent).join(' ') || e.textContent || ''""")

    def gate(self):
        if urlsplit(self.p.url).hostname == 'accounts.google.com': raise NeedsOwner('sign_in_in_wizard_browser')
        if urlsplit(self.p.url).hostname != urlsplit(self.base).hostname: raise NeedsOwner('unexpected_console_origin')
        # Human gates win BEFORE any agreement checkbox is changed.
        for pattern, reason in [
            (r'verify|verification|captcha|confirm.*(?:identity|you)|two.step|2.step', 'complete_verification'),
            (r'billing|payment|credit card|free trial', 'billing_prompt_do_not_purchase'),
        ]:
            for role in ('dialog', 'heading'):
                loc = self.p.get_by_role(role)
                loc = loc.filter(has_text=re.compile(pattern, re.I)) if role == 'dialog' else self.p.get_by_role(role, name=re.compile(pattern, re.I))
                if self.visible(loc): raise NeedsOwner(reason)
        self.accept_recorded_agreements()

    def accept_recorded_agreements(self):
        boxes = self.p.get_by_role('checkbox')
        visible_boxes = [boxes.nth(i) for i in range(boxes.count()) if boxes.nth(i).is_visible()]
        labels = [(c, self.checkbox_label(c)) for c in visible_boxes]
        marketing_label = re.compile(r'(?:(?:Send me |I would like to receive )?(?:marketing emails|email updates|updates and offers)(?: about Google Cloud)?|I would like to receive periodic emails on news, product updates, and special offers from Google Cloud)[.]?', re.I)
        agree = self.button(r'^Agree and continue$')
        legal_dialog = self.p.get_by_role('dialog').filter(has_text=re.compile(r'terms|policy|agreement', re.I))
        legal = self.visible(agree) or self.visible(legal_dialog) or any(re.search(r'agree|accept|terms|policy', label, re.I) for _, label in labels)
        if not legal:
            if self.allow_accept:
                for c, label in labels:
                    if marketing_label.fullmatch(label.strip()): c.uncheck()
            return
        recorded = parse_agreements(self.agreements)
        if not self.allow_accept: raise NeedsOwner('review_google_agreements_in_connected_accounts')
        accepted = set(recorded['accepted'])
        tasks, marketing, legal_ids = [], [], set()
        # Classify the ENTIRE form before doing any legal write (no partial acceptance).
        for c, label in labels:
            if marketing_label.fullmatch(label.strip()):
                marketing.append(c); continue
            ids = agreement_for_label(label)
            if not ids <= accepted: raise NeedsOwner('unrecorded_google_agreement')
            legal_ids.update(ids)
            tasks.append(c)
        links = self.p.get_by_role('link')
        linked_ids = set()
        urls = {d['url']: d['id'] for d in DOCUMENTS}
        for i in range(links.count()):
            link = links.nth(i)
            if not link.is_visible(): continue
            href = link.get_attribute('href') or ''
            # Only legal links are inspected; a new legal document must fail closed.
            name = link.inner_text()
            if not re.search(r'terms|policy|agreement', name + ' ' + href, re.I): continue
            ident = urls.get(href)
            if not ident or ident not in accepted: raise NeedsOwner('unrecorded_google_agreement')
            linked_ids.add(ident)
        if self.visible(agree) and not tasks:
            # First Cloud welcome form may bind the terms to its submit button.
            if linked_ids != {'cloud_terms'}: raise NeedsOwner('unrecorded_google_agreement')
        elif not tasks:
            raise NeedsOwner('unrecorded_google_agreement')
        # Literal role names avoid Python regexes being serialized as invalid JS
        # regex literals (notably the slash in Country/Region). Count every known
        # label before selection so two different country labels also fail closed.
        countries = [self.p.get_by_role('combobox', name=name, exact=True)
                     for name in ('Country', 'Country/Region', 'Country or region')]
        matches = [c for c in countries if c.count()]
        if sum(c.count() for c in matches) > 1: raise NeedsOwner('country_control_changed')
        country = matches[0] if matches else None
        if self.visible(agree) and 'cloud_terms' in (legal_ids | linked_ids) and (country is None or not self.visible(country)):
            raise NeedsOwner('country_control_changed')
        if country is not None and self.visible(country):
            code = recorded['country']
            country_name = self.p.evaluate("code => new Intl.DisplayNames(['en'], {type:'region'}).of(code)", code)
            if country.first.evaluate('(e)=>e.tagName') == 'SELECT':
                options = country.first.locator('option')
                values = options.evaluate_all('(es)=>es.map(e=>e.value)')
                if code in values: country.first.select_option(value=code)
                else: country.first.select_option(label=country_name)
            else:
                country.first.click()
                self.p.get_by_role('option', name=country_name, exact=True).click()
        for c in marketing: c.uncheck()
        for c in tasks: c.check()
        self.legal_checked = True
        if self.visible(agree):
            agree.first.click()
            # Read back after submit; no recursive retry or repeated acceptance.
            if self.visible(agree): raise NeedsOwner('google_agreement_submit_not_confirmed')
            self.gate()

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
        # Real Console renders the resource list as bare rows (no table/grid role).
        self.p.get_by_role('table').or_(self.p.get_by_role('row')).first.wait_for()
        if self.visible(row): return self.project_setup()
        self.go('/projectcreate')
        self.p.get_by_label(re.compile(r'^Project name', re.I)).or_(self.p.locator('input[id$="-name-input"]')).first.fill('Wizard')
        edit = self.button(r'^Edit\b')  # Real Console: "Edit the project id."
        if self.visible(edit): edit.first.click()
        pid = self.p.get_by_label(re.compile(r'^Project ID', re.I)).or_(self.p.locator('input[id$="-id-input"]'))  # real Console labels lack accessible names
        self.project = 'wizard-' + secrets.token_hex(6)
        if not self.visible(pid): raise NeedsOwner('project_id_control_changed')
        pid.first.fill(self.project)
        self.click(r'^Create$')
        # Authoritative readback; Google's creation notification may take time.
        self.p.get_by_text(re.compile(r'created|creation complete', re.I)).first.wait_for(timeout=60000)
        self.go('/home/dashboard')

    def api(self):
        self.go('/apis/library/calendar-json.googleapis.com')
        enable = self.button(r'^Enable(?: this API)?$')
        # Both states need a loaded page; wait for either action before deciding.
        enable.or_(self.button(r'^Manage(?: this API)?$')).first.wait_for(timeout=30000)
        # Real Console ignores clicks until the product page hydrates; then Enable navigates to /apis/api/.
        if self.visible(enable):
            self.p.wait_for_timeout(4000)
            self.click(r'^Enable(?: this API)?$')
            self.p.wait_for_url(re.compile(r'/apis/api/'), timeout=90000)
        self.button(r'^Manage(?: this API)?$|^Disable API$').first.wait_for(timeout=60000)

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
        # gate checks only the agreements recorded in Connected accounts.
        self.legal_checked = False
        self.gate()
        if not self.legal_checked: raise NeedsOwner('unrecorded_google_agreement')
        finish = self.button(r'^(?:Create|Finish)$')
        if finish.count() != 1 or not self.visible(finish): raise NeedsOwner('branding_finish_control_changed')
        self.click(r'^(?:Create|Finish)$')
        self.p.get_by_role('heading', name=re.compile('OAuth overview', re.I)).first.wait_for(timeout=30000)

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
        # never submit public verification.
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
    recorded = parse_agreements(args.agreements)
    if set(recorded['accepted']) != IDS: raise NeedsOwner('review_google_agreements_in_connected_accounts')
    c = Console(page, project=args.project, audience=args.audience, agreements=recorded, allow_accept=not args.dry_run)
    if args.state_file.exists():
        data = json.loads(args.state_file.read_text())
        c.project = c.project or data.get('project')
    if c.project and not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', c.project): raise NeedsOwner('invalid_project_id')
    if args.dry_run:
        c.go('/auth/overview')
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
    # Final setup success is emitted by main only after sign-out and teardown.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--step', choices=['all','project','api','branding','audience','client'], default='all')
    parser.add_argument('--project')

    parser.add_argument('--agreements', default=os.environ.get('GOOGLE_SETUP_AGREEMENTS'), help='JSON agreements object from MCP status/begin')
    parser.add_argument('--audience', choices=['External','Internal'], default='External')
    parser.add_argument('--redirect-uri', default=os.environ.get('GOOGLE_SETUP_REDIRECT_URI'))
    parser.add_argument('--intake-url', default=os.environ.get('GOOGLE_SETUP_INTAKE_URL'), help='MCP capability; prefer env, never put provider credentials in argv')
    parser.add_argument('--state-file', type=Path, default=Path.home()/'.cache/wizard-google-setup/project.json')
    parser.add_argument('--dry-run', action='store_true', help='No setup writes; still signs out and deletes the disposable session')
    args = parser.parse_args()
    # DEBUG/trace/PWDEBUG must not turn private browser values into ordinary logs.
    for key in ('DEBUG','PWDEBUG','PW_TRACE_DIR'): os.environ.pop(key, None)
    handoff, teardown_attempted = None, False
    try:
        handoff = HandoffSession()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            page, attempt_error = None, None
            try:
                browser = p.chromium.connect_over_cdp(handoff.endpoint)
                context = browser.contexts[0]
                pages = [p for p in context.pages if urlsplit(p.url).hostname == 'console.cloud.google.com']
                if not pages: raise NeedsOwner('open_console_and_sign_in_first')
                page = pages[0]
                run(args, page)
            except BaseException as error:
                attempt_error = error
                raise
            finally:
                teardown_attempted = True
                finalize_attempt(handoff, page, attempt_error)
        emit('dry_run' if args.dry_run else 'setup' if args.step in ('all','client') else args.step, 'ok')
        return 0
    except NeedsOwner as e:
        emit('setup', 'needs_owner', str(e)); return 2
    except Exception:
        emit('setup', 'needs_owner', 'console_ui_changed_or_timeout_no_automatic_retry'); return 2
    finally:
        if handoff and not teardown_attempted:
            try: handoff.stop_and_verify()
            except Exception: emit('setup', 'needs_owner', 'handoff_teardown_failed')


if __name__ == '__main__': sys.exit(main())
