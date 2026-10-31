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
from playwright.sync_api import sync_playwright

fixture={'project':None,'enabled':False,'branding':False,'production':False,'client':False,'creates':0}
REDIRECT='https://owner.example/wizard-connectors/api/google/callback'
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
    elif p=='/_fixture/enable':
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
        body=button('Manage' if fixture['enabled'] else 'Enable','/apis/library/calendar-json.googleapis.com' if fixture['enabled'] else '/_fixture/enable')
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
    elif p=='/_fixture/terms':body='<div role="dialog"><h1>Terms of service</h1><button>Accept</button></div>'
    else:body='<h1>Dashboard</h1>'
    route.fulfill(status=200,content_type='text/html',body=html(body))


def main():
    t=SetupIntakeTests(methodName='test_script_direct_deposit_and_url_allowlist');t.setUp()
    output=io.StringIO()
    try:
        with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
            browser=p.chromium.launch(executable_path=os.environ['CHROME_BINARY'],headless=True)
            try:
                page=browser.new_page();page.route('https://console.cloud.google.com/**',handle)
                c=script.Console(page)
                c.project_setup();pid=c.project
                assert fixture['project']==pid
                c.api();assert fixture['enabled']
                try:c.branding();raise AssertionError('legal gate was bypassed')
                except script.NeedsOwner as e:assert str(e) in ('review_google_data_policy_or_terms','review_google_data_policy_and_finish_branding_then_rerun')
                assert not page.get_by_role('checkbox').is_checked()
                # Explicit OWNER simulation, not a step in the automation script.
                page.get_by_role('checkbox').check();page.get_by_role('button',name='Create',exact=True).click()
                c.branding();c.audience_setup();assert fixture['production']
                begin=t.begin();url=t.base+'/api/google/setup/intake#'+begin['intake_url'].split('#')[1]
                with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                    creds=c.client(REDIRECT);script.deposit(url,creds);creds.clear()
                assert t.b.setup_status(REDIRECT)['configured']
                assert t.b.client()[0]['client_id']==ID
                # New process, no project file: discovers existing project/client.
                rerun=script.Console(page);rerun.project_setup();assert rerun.project==pid
                creds=rerun.client(REDIRECT);creds.clear();assert fixture['creates']==1
                # Exercise the shipped all-step orchestrator and public-only cache.
                from argparse import Namespace
                begin=t.begin();url=t.base+'/api/google/setup/intake#'+begin['intake_url'].split('#')[1]
                statefile=Path(tmp)/'project.json'
                args=Namespace(project=None,audience='External',state_file=statefile,dry_run=False,intake_url=url,redirect_uri=REDIRECT,step='all')
                with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):script.run(args,page)
                assert json.loads(statefile.read_text())=={'project':pid}
                assert fixture['creates']==1
                page.goto('https://console.cloud.google.com/_fixture/terms')
                try:rerun.gate();raise AssertionError('terms bypassed')
                except script.NeedsOwner:pass
                assert SECRET not in output.getvalue() and ID not in output.getvalue()
                print(json.dumps({'fixture':'FAKE Google Cloud console, native Chrome and real intake/RPC/store','result':'PASS','checks':['project create + existing reuse','Calendar API enable + readback','branding owner legal gate','External audience publish + readback','Web client redirect and secret capture','direct deposit encrypted + status readback','idempotent existing client no duplicate','terms fail closed','no credential stdout/stderr']}))
            finally:browser.close()
    finally:t.tearDown()

if __name__=='__main__':main()
