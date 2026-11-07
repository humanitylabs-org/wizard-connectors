"""Fake-console browser fixture; native Chrome, real Playwright script + real intake.
Never signs into Google; synthetic credential strings only. Run on Thales with
CHROME_BINARY and a Python environment containing Playwright + app requirements.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'tests')]
from test_google_setup import script, SetupIntakeTests

AGREEMENTS = {'accepted': sorted(script.IDS), 'version': script.VERSION, 'country': 'GB'}


class FakeControl:
    """Small accessible-control model for unit tests; not browser/real Console proof."""
    def __init__(self, role, name='', **values):
        self.role, self.name = role, name
        self.values = {'checked': False, 'visible': True, **values}


class FakeLocator:
    def __init__(self, page, items): self.page, self.items = page, items
    @property
    def first(self): return self.nth(0)
    def nth(self, i): return FakeLocator(self.page, self.items[i:i+1])
    def count(self): return len(self.items)
    def is_visible(self): return bool(self.items and self.items[0] in self.page.items and self.items[0].values['visible'])
    def filter(self, has_text): return FakeLocator(self.page, [x for x in self.items if has_text.search(x.name)])
    def is_checked(self): return self.items[0].values['checked']
    def check(self): self.items[0].values['checked'] = True
    def uncheck(self): self.items[0].values['checked'] = False
    def evaluate(self, expression):
        return 'SELECT' if 'tagName' in expression else self.items[0].name
    def evaluate_all(self, expression): return [x.values['value'] for x in self.items]
    def inner_text(self): return self.items[0].name
    def get_attribute(self, key): return self.items[0].values.get(key)
    def locator(self, selector): return FakeLocator(self.page, self.items[0].values['options'])
    def select_option(self, value=None, label=None):
        self.page.country = value or next(x.values['value'] for x in self.items[0].values['options'] if x.name == label)
    def click(self):
        self.page.submitted = {x.name: x.values['checked'] for x in self.page.items if x.role == 'checkbox'}
        self.page.items = []


class FakeConsolePage:
    def __init__(self, *, labels=None, link=None, heading='Google Cloud Terms of Service', submit=True, country=True):
        self.url = 'https://console.cloud.google.com/welcome'
        self.submitted, self.country = None, None
        self.items = [FakeControl('heading', heading)]
        for label in labels if labels is not None else ['I agree to the Google Cloud Terms of Service', 'Email updates']:
            self.items.append(FakeControl('checkbox', label, checked=label == 'Email updates'))
        if link: self.items.append(FakeControl('link', 'Terms of Service', href=link))
        if submit: self.items.append(FakeControl('button', 'Agree and continue'))
        if country: self.items.append(FakeControl('combobox', 'Country', options=[FakeControl('option', 'United Kingdom', value='GB'), FakeControl('option', 'United States', value='US')]))
    def set_default_timeout(self, value): pass
    def set_default_navigation_timeout(self, value): pass
    def get_by_role(self, role, name=None, exact=False):
        return FakeLocator(self, [x for x in self.items if x.role == role and (name is None or (name.search(x.name) if hasattr(name, 'search') else x.name == name))])
    def evaluate(self, expression, code): return {'GB': 'United Kingdom', 'US': 'United States'}[code]

fixture={'project':None,'enabled':False,'branding':False,'production':False,'client':False,'creates':0}
REDIRECT='https://owner.example/connected-accounts/api/google/callback'
SECRET='GOCSPX-FAKE_CONSOLE_FIXTURE_SECRET'
ID='fake-console.apps.googleusercontent.com'

def html(body):
    return '<!doctype html><html><body><button aria-label="Google Account: Fixture Owner (owner@example.invalid)">Account</button>'+body+'</body></html>'

def button(name,action):
    return '<form action="'+action+'"><button>'+name+'</button></form>'

def handle(route):
    u=urlsplit(route.request.url);p=u.path;q=parse_qs(u.query)
    if p=='/_fixture/project':
        fixture['project']=q['projectid'][0]
        body='<p>Project creation complete</p>'
    elif p=='/apis/api/calendar-json.googleapis.com':
        fixture['enabled']=True;body=button('Manage','/apis/library/calendar-json.googleapis.com')
    elif p=='/_fixture/branding':
        fixture['branding']=True;body='<h1>OAuth overview</h1>'+button('Create OAuth client','/auth/clients')
    elif p=='/_fixture/publish':
        fixture['production']=True;body='<p>In production</p>'
    elif p=='/_fixture/client':
        fixture['client']=True;fixture['creates']+=1
        body='<div role="dialog"><h2>OAuth client created</h2><label>Client ID<input value="'+ID+'"></label><label>Client secret<input value="'+SECRET+'"></label></div>'
    elif p=='/_fixture/clientdetail':
        body='<label>Authorized redirect URI<input value="'+REDIRECT+'"></label><label>Client ID<input value="'+ID+'"></label><label>Client secret<input value="'+SECRET+'"></label>'
    elif p=='/cloud-resource-manager':
        body='<table aria-label="Projects"><tr><th>Name</th><th>Project ID</th></tr>'
        if fixture['project']:body+='<tr><td>Wizard</td><td>'+fixture['project']+'</td></tr>'
        body+='</table>'
    elif p=='/projectcreate':
        body='<form action="/_fixture/project"><label>Project name<input name="name"></label><label>Project ID<input name="projectid"></label><button>Create</button></form>'
    elif p=='/apis/library/calendar-json.googleapis.com':
        body=button('Manage' if fixture['enabled'] else 'Enable','/apis/library/calendar-json.googleapis.com' if fixture['enabled'] else '/apis/api/calendar-json.googleapis.com')
    elif p=='/auth/overview':
        body=('<h1>OAuth overview</h1>'+button('Create OAuth client','/auth/clients')) if fixture['branding'] else button('Get started','/_fixture/brandingstart')
    elif p=='/_fixture/brandingstart':
        body='''<form action="/_fixture/branding">
<div data-part="1"><label>App name<input></label><label>User support email<select><option>owner@example.invalid</option></select></label></div>
<div data-part="2" hidden><label><input type="radio" name="audience">External</label><label><input type="radio" name="audience">Internal</label></div>
<div data-part="3" hidden><label>Email addresses<input></label></div>
<div data-part="4" hidden><label><input type="checkbox" required>I agree to the Google API Services User Data Policy</label><button>Create</button></div>
<button type="button" id="next">Next</button></form><script>let step=1;document.querySelector('#next').onclick=()=>{document.querySelector('[data-part="'+step+'"]').hidden=true;step++;document.querySelector('[data-part="'+step+'"]').hidden=false;if(step===4)document.querySelector('#next').hidden=true;};</script>'''
    elif p=='/auth/audience':
        body='<p>In production</p>' if fixture['production'] else button('Publish app','/_fixture/confirm')
    elif p=='/_fixture/confirm':body=button('Confirm','/_fixture/publish')
    elif p=='/auth/clients':
        body=button('Create client','/_fixture/clientstart')+'<table><tr><th>Name</th></tr>'
        if fixture['client']:body+='<tr><td><a href="/_fixture/clientdetail">Wizard</a></td></tr>'
        body+='</table>'
    elif p=='/_fixture/clientstart':
        body='''<form action="/_fixture/client"><label>Application type<select><option>Web application</option></select></label><label>Name<input></label>
<section><h3>Authorized JavaScript origins</h3><button type="button">Add URI</button></section>
<section><h3>Authorized redirect URIs</h3><button type="button" onclick="this.nextElementSibling.hidden=false">Add URI</button><label hidden>Authorized redirect URI<input></label></section><button>Create</button></form>'''
    elif p=='/_fixture/terms':
        body='''<form action="/_fixture/termsaccepted"><h1>Google Cloud Terms of Service</h1>
<label>Country<select name="country"><option value="US">United States</option><option value="GB">United Kingdom</option></select></label>
<label><input type="checkbox" name="terms" required>I agree to the Google Cloud Terms of Service</label>
<a href="https://cloud.google.com/terms">Terms of Service</a>
<label><input type="checkbox" name="marketing" checked>Email updates</label><button>Agree and continue</button></form>'''
    elif p=='/_fixture/termsaccepted':
        fixture['terms_country']=q.get('country', [''])[0];fixture['marketing']='marketing' in q;fixture['terms']='terms' in q
        body='<h1>Dashboard</h1>'
    elif p=='/_fixture/unknownterms':body='<div role="dialog"><h1>New agreement</h1><label><input type="checkbox">I agree to a new agreement</label><button>Accept</button></div>'
    else:body='<h1>Dashboard</h1>'
    route.fulfill(status=200,content_type='text/html',body=html(body))


def main():
    from playwright.sync_api import sync_playwright
    t=SetupIntakeTests(methodName='test_script_direct_deposit_and_url_allowlist');t.setUp()
    output=io.StringIO()
    try:
        with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
            chrome=os.environ.get('CHROME_BINARY') or os.environ.get('QA_CHROME')
            browser=p.chromium.launch(headless=True,**({'executable_path':chrome} if chrome else {}))
            try:
                page=browser.new_page();page.route('https://console.cloud.google.com/**',handle)
                c=script.Console(page,agreements=AGREEMENTS)
                c.project_setup();pid=c.project
                assert fixture['project']==pid
                c.api();assert fixture['enabled']
                c.branding();assert fixture['branding']
                c.branding();c.audience_setup();assert fixture['production']
                begin=t.begin();url=t.base+'/api/google/setup/intake#'+begin['intake_url'].split('#')[1]
                with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                    creds=c.client(REDIRECT);script.deposit(url,creds);creds.clear()
                assert t.b.setup_status(REDIRECT)['configured']
                assert t.b.client()[0]['client_id']==ID
                # New process, no project file: discovers existing project/client.
                rerun=script.Console(page,agreements=AGREEMENTS);rerun.project_setup();assert rerun.project==pid
                creds=rerun.client(REDIRECT);creds.clear();assert fixture['creates']==1
                # Exercise the shipped all-step orchestrator and public-only cache.
                from argparse import Namespace
                begin=t.begin();url=t.base+'/api/google/setup/intake#'+begin['intake_url'].split('#')[1]
                statefile=Path(tmp)/'project.json'
                args=Namespace(agreements=AGREEMENTS,project=None,audience='External',state_file=statefile,dry_run=False,intake_url=url,redirect_uri=REDIRECT,step='all')
                with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):script.run(args,page)
                assert json.loads(statefile.read_text())=={'project':pid}
                assert fixture['creates']==1
                # Parse selectors in real Playwright/Chromium, not FakeLocator.
                # Every supported literal must override the initial US country,
                # including slash-bearing labels. No secret page dumps.
                country_checks = []
                for label in ('Country', 'Country/Region', 'Country or region'):
                    page.goto('https://console.cloud.google.com/_fixture/terms')
                    page.locator('select[name=country]').evaluate('(e, label) => e.parentElement.firstChild.textContent = label', label)
                    rerun.gate()
                    assert fixture['terms'] and fixture['terms_country'] == 'GB' and not fixture['marketing']
                    country_checks.append(label)
                for labels in ([], ['Country', 'Country'], ['Country', 'Country/Region'], ['Country or region changed']):
                    page.goto('https://console.cloud.google.com/_fixture/terms')
                    page.locator('label').filter(has=page.locator('select[name=country]')).evaluate('(e) => e.remove()')
                    for label in labels:
                        page.evaluate('label => { const l = document.createElement("label"); l.textContent = label; l.innerHTML += "<select><option>United States</option><option>United Kingdom</option></select>"; document.querySelector("form").prepend(l); }', label)
                    try:
                        rerun.gate()
                        raise AssertionError('changed/ambiguous country accepted')
                    except script.NeedsOwner as exc:
                        assert str(exc) == 'country_control_changed'
                    assert not page.get_by_role('checkbox', name='I agree to the Google Cloud Terms of Service', exact=True).is_checked()
                    assert page.get_by_role('checkbox', name='Email updates', exact=True).is_checked()
                    assert page.url.endswith('/_fixture/terms')
                page.goto('https://console.cloud.google.com/_fixture/terms')
                unrecorded=script.Console(page,agreements={**AGREEMENTS,'accepted':['api_terms','user_data_policy']})
                try:unrecorded.gate();raise AssertionError('unrecorded terms bypassed')
                except script.NeedsOwner:pass
                assert not page.get_by_role('checkbox',name='I agree to the Google Cloud Terms of Service',exact=True).is_checked()
                page.goto('https://console.cloud.google.com/_fixture/unknownterms')
                try:rerun.gate();raise AssertionError('unknown terms bypassed')
                except script.NeedsOwner:pass
                assert SECRET not in output.getvalue() and ID not in output.getvalue()
                print(json.dumps({'fixture':'FAKE Google Cloud console, native Chrome and real intake/RPC/store','result':'PASS','country_labels':country_checks,'country_refusals':4,'checks':['project create + existing reuse','Calendar API enable + readback','branding recorded user data policy','External audience publish + readback','Web client redirect and secret capture','direct deposit encrypted + status readback','idempotent existing client no duplicate','recorded Cloud terms and country','marketing left unticked','unrecorded and unknown terms fail closed','no credential stdout/stderr']}))
            finally:browser.close()
    finally:t.tearDown()

if __name__=='__main__':main()
