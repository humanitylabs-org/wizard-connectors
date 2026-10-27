"""REAL HTTP handlers/RPC/store, FAKE Google transport only. No real credentials.
Fake ID tokens are signed with a per-test RSA key and checked by production verifier.
"""
import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit,parse_qs,urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from google_broker import Broker,GoogleTransport,Denied,IDENTITY,SCOPES,YOUTUBE,CALENDAR,MAX_PAGES,store_key
from services import service
from service_rpc import RPC

class FakeGoogle(GoogleTransport):
    def __init__(self):
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()));self.jwk['kid']='fixture'
        self.calendar_pages=1;self.event_pages=1;self.calendar_calls=[];self.event_calls=[];self.calendar_error=None
        self.nonce='';self.subject='fixture-subject-a';self.scopes=IDENTITY
        self.refreshes=0;self.revoked=False;self.fail_revoke=False;self.bad={};self.forms=[];self.forge=False
    def request(self,operation,*,form=None,token=None,query=None,calendar_id=None):
        if operation in ('calendars','events'):
            if self.calendar_error: raise Denied(self.calendar_error)
            calls=self.calendar_calls if operation=='calendars' else self.event_calls
            calls.append(dict(query));page=int(query.get('pageToken','0'))
            row=({'id':'primary@example.invalid','summary':'FAKE calendar','backgroundColor':'FAKE_COLOR','primary':True,'accessRole':'owner'}
                 if operation=='calendars' else {'id':'fake-event-'+str(page),'summary':'FAKE event','start':{'date':'2026-10-24'},'end':{'date':'2026-10-25'},'status':'confirmed','location':'FAKE room','htmlLink':'https://calendar.google.com/fixture','description':'FAKE notes','iCalUID':'fake-uid@google.com','hangoutLink':'https://meet.google.com/fak-efak-efa','attendees':[{'self':True,'responseStatus':'declined','email':'fake@example.invalid'},{'email':'other@example.invalid'}]})
            result={'items':[row]}
            pages=self.calendar_pages if operation=='calendars' else self.event_pages
            if page+1 < pages:result['nextPageToken']=str(page+1)
            return result
        if operation=='jwks':return {'keys':[self.jwk]}
        if operation=='userinfo':return {'sub':self.subject}
        if operation=='revoke':
            self.revoked=True
            if self.fail_revoke:raise Denied('provider_unavailable')
            return {}
        if operation=='catalog':return {'items':[{'id':query['id'],'snippet':{'title':'FAKE catalog fixture'}}]}
        if operation=='token':
            self.forms.append(form)
            claims={'iss':'https://accounts.google.com','aud':form['client_id'],'sub':self.subject,'nonce':self.nonce,
                    'iat':int(time.time()),'exp':int(time.time())+3600,'email':'fixture@example.invalid','email_verified':True,**self.bad}
            if form['grant_type']=='refresh_token': self.refreshes+=1;time.sleep(.02)
            return {'access_token':'FAKE_ACCESS_SECRET','refresh_token':'FAKE_REFRESH_SECRET','token_type':'Bearer','expires_in':3600,
                    'scope':' '.join(self.scopes),'id_token':jwt.encode(claims,rsa.generate_private_key(public_exponent=65537,key_size=2048) if self.forge else self.key,algorithm='RS256',headers={'kid':'fixture'})}
        raise AssertionError(operation)

class BrokerHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.fake=FakeGoogle()
        self.config={'BROKER_DATA_DIR':self.tmp.name+'/broker','GOOGLE_STORE_KEY':Fernet.generate_key().decode(),
                     'GOOGLE_CLIENT_ID':'fixture-client','GOOGLE_CLIENT_SECRET':'FAKE_CLIENT_SECRET',
                     'GOOGLE_REDIRECT_URI':'http://127.0.0.1/api/google/callback'}
        self.b=Broker(self.config,self.fake)
        self.env=patch.dict(os.environ,{'PORT':'0','BROKER_TOKEN':'b'*40,'DATA_DIR':self.tmp.name+'/ui','CONNECTORS_OWNER_TOKEN':'o'*40,'CONNECTORS_MCP_TOKEN':'m'*40})
        self.env.start()
        self.s=service('google',self.b);threading.Thread(target=self.s.serve_forever,daemon=True).start()
        import server
        self.ui=server
        self.ui.OWNER='o'*40;self.ui.MCP='m'*40;self.ui.MUSIC='s'*40
        self.ui.broker=RPC('127.0.0.1',self.s.server_port,'b'*40)
        self.web=ThreadingHTTPServer(('127.0.0.1',0),self.ui.Handler);threading.Thread(target=self.web.serve_forever,daemon=True).start()
        self.base='http://127.0.0.1:'+str(self.web.server_port);self.cookie=''
    def tearDown(self):
        self.web.shutdown();self.web.server_close();self.s.shutdown();self.s.server_close();self.env.stop();self.tmp.cleanup()
    def req(self,path,data=None,owner=True,cookie=None,headers=None,method=None):
        h={'Content-Type':'application/json',**({'Authorization':'Bearer '+'o'*40} if owner else {}),**(headers or {})}
        if cookie is not None:h['Cookie']=cookie
        q=Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers=h,method=method)
        try:r=urlopen(q,timeout=5)
        except HTTPError as e:r=e
        with r:
            raw=r.read();body=json.loads(raw) if r.headers.get_content_type()=='application/json' else raw.decode()
            return r.status,body,r.headers
    def start(self,youtube=True,account=None):
        code,res,h=self.req('/api/google/connect',{'youtube':youtube,'account':account});self.assertEqual(code,200)
        self.cookie=h['Set-Cookie'].split(';')[0]
        params={k:v[0] for k,v in parse_qs(urlsplit(res['authorization_url']).query).items()}
        self.fake.nonce=params['nonce'];self.fake.scopes=set(params['scope'].split());return params
    def finish(self,p,**kw):
        return self.req('/api/google/callback?'+urlencode({'state':p['state'],'code':'FAKE_CODE',**kw}),owner=False,cookie=self.cookie,headers={'Sec-Fetch-Site':'cross-site'})
    def connect(self,youtube=True):
        p=self.start(youtube);self.assertEqual(self.finish(p)[0],200)
        return self.b.status()['accounts'][0]['id']
    def test_full_http_flow_persistence_binding_unlink_disconnect(self):
        p=self.start();self.assertEqual(p['code_challenge_method'],'S256');self.assertEqual(self.finish(p)[0],200)
        form=self.fake.forms[0];self.assertIn('code_verifier',form);self.assertNotEqual(form['code_verifier'],p['code_challenge'])
        state=self.req('/api/state')[1]['google'];aid=state['accounts'][0]['id']
        self.assertNotIn('FAKE_ACCESS_SECRET',json.dumps(state));self.assertNotIn('FAKE_REFRESH_SECRET',json.dumps(state))
        self.assertEqual(self.req('/api/music/bind',{'account':aid,'consent':True})[0],200)
        restored=Broker(self.config,self.fake);self.assertEqual(restored.status()['bindings'][0]['account'],aid)
        raw=(Path(self.config['BROKER_DATA_DIR'])/'google.enc').read_bytes();self.assertNotIn(b'FAKE_REFRESH_SECRET',raw)
        self.assertEqual((Path(self.config['BROKER_DATA_DIR'])/'google.enc').stat().st_mode & 0o777,0o600)
        result=self.req('/api/music/catalog',{'account':aid,'video_id':'W8VdVY8diqs'})[1]
        self.assertEqual(result['items'][0]['title'],'FAKE catalog fixture');self.assertFalse(result['audio_verified'])
        self.assertEqual(self.req('/api/music/unlink',{})[0],200);self.assertEqual(len(Broker(self.config,self.fake).status()['accounts']),1)
        self.assertEqual(self.req('/api/music/catalog',{'account':aid,'video_id':'W8VdVY8diqs'})[1]['error'],'capability_denied')
        self.assertEqual(self.req('/api/google/disconnect',{'account':aid})[1]['provider_revocation'],'revoked')
        self.assertTrue(self.fake.revoked);self.assertEqual(Broker(self.config,self.fake).status()['accounts'],[])
    def test_state_browser_expiry_replay_denial(self):
        p=self.start();self.assertEqual(self.req('/api/google/callback?state='+p['state']+'&code=x',owner=False,cookie='connectors_oauth=wrong')[0],400)
        self.assertEqual(self.finish(p)[0],200);self.assertEqual(self.finish(p)[0],400)
        p=self.start();self.b.pending[p['state']]['expires']=0;self.assertEqual(self.finish(p)[0],400)
        p=self.start();self.assertEqual(self.finish(p,error='access_denied')[0],400);self.assertEqual(self.finish(p)[0],400)
    def test_nonce_issuer_audience_signature_and_subject_checks(self):
        for bad in ({'nonce':'wrong'},{'iss':'https://attacker.invalid'},{'aud':'wrong'},{'azp':'wrong'},{'exp':1},{'sub':''}):
            with self.subTest(bad=bad):
                self.fake.bad=bad;p=self.start();self.assertEqual(self.finish(p)[0],400)
        self.assertEqual(self.b.status()['accounts'],[])
    def test_scope_and_wrong_account_reconnect(self):
        aid=self.connect(False)
        self.assertEqual(self.req('/api/music/bind',{'account':aid,'consent':True})[1]['error'],'incremental_consent_required')
        p=self.start(True,aid);self.fake.subject='different-subject';self.assertEqual(self.finish(p)[0],400)
        self.assertEqual(self.b.status()['accounts'][0]['id'],aid)
        self.fake.subject='fixture-subject-a';p=self.start(True,aid);self.fake.scopes=IDENTITY;self.assertEqual(self.finish(p)[0],400)
        p=self.start(True,aid);self.fake.scopes=SCOPES|{'https://mail.google.com/'};self.assertEqual(self.finish(p)[0],400)
    def test_forged_signature_and_atomic_storage_failure(self):
        self.fake.forge=True;p=self.start();self.assertEqual(self.finish(p)[0],400)
        self.assertFalse(self.b.status()['accounts']);self.fake.forge=False
        p=self.start()
        with patch.object(self.b.store,'save',side_effect=OSError('fixture disk failure')):
            self.assertEqual(self.finish(p)[0],400)
        self.assertFalse(self.b.status()['accounts'])
        self.assertFalse(Broker(self.config,self.fake).status()['accounts'])
    def test_refresh_serialized_wrong_subject_revocation_and_gate(self):
        aid=self.connect();self.b.bind(aid,True);self.b.state['accounts'][aid]['expires']=0
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            result=list(ex.map(lambda _:self.req('/api/music/catalog',{'account':aid,'video_id':'W8VdVY8diqs'})[0],range(6)))
        self.assertEqual(result,[200]*6);self.assertEqual(self.fake.refreshes,1)
        self.b.state['accounts'][aid]['expires']=0;self.fake.subject='wrong'
        self.assertEqual(self.req('/api/music/catalog',{'account':aid,'video_id':'W8VdVY8diqs'})[1]['error'],'reauth_required')
        self.assertEqual(Broker(self.config,self.fake).status()['accounts'][0]['status'],'reauth_required')
        self.fake.fail_revoke=True;self.assertEqual(self.req('/api/google/disconnect',{'account':aid})[1]['provider_revocation'],'failed_manual_revocation_required')
        self.assertFalse(self.b.status()['accounts'])
        self.config['GOOGLE_DISABLED']='true';self.assertEqual(self.req('/api/google/connect',{})[1]['error'],'google_disabled')
        self.config['GOOGLE_DISABLED']='false';del self.config['GOOGLE_CLIENT_SECRET'];self.assertEqual(self.req('/api/google/connect',{})[1]['error'],'google_configuration_required')
    def test_agent_cannot_connect_read_accounts_or_fetch(self):
        for path in ('/api/google/connect','/api/music/bind','/api/music/audio-probe'):
            self.assertEqual(self.req(path,{},owner=False,headers={'Authorization':'Bearer '+'m'*40})[0],401)
        self.assertEqual(self.req('/api/state',owner=False,headers={'Authorization':'Bearer '+'m'*40})[0],401)
        self.assertEqual(self.req('/api/google/connect',{},headers={'Origin':'https://evil.invalid'})[0],403)
        self.assertEqual(self.req('/api/google/connect',{'url':'https://evil.invalid'})[0],400)
        with self.assertRaisesRegex(Denied,'operation_denied'): self.ui.broker.call('fetch',url='https://evil.invalid')
    def test_key_loss_and_corruption_fail_closed(self):
        self.connect()
        with self.assertRaises(RuntimeError):Broker({**self.config,'GOOGLE_STORE_KEY':''},self.fake)
        with self.assertRaises(RuntimeError):Broker({**self.config,'GOOGLE_STORE_KEY':Fernet.generate_key().decode()},self.fake)
    def test_typed_music_service_uses_only_persisted_owner_binding(self):
        headers={'Authorization':'Bearer '+'s'*40};payload={'video_id':'W8VdVY8diqs'}
        self.assertEqual(self.req('/service/music/catalog',payload,owner=False,headers=headers)[1]['error'],'capability_denied')
        aid=self.connect();self.b.bind(aid,True)
        self.assertEqual(self.req('/service/music/catalog',payload,owner=False,headers=headers)[0],200)
        self.assertEqual(self.req('/service/music/catalog',{**payload,'account':'wrong'},owner=False,headers=headers)[0],400)
        self.assertEqual(self.req('/service/music/catalog',payload,owner=False,headers={'Authorization':'Bearer '+'m'*40})[0],401)
        self.assertEqual(self.req('/api/state',owner=False,headers=headers)[0],401)
        self.assertEqual(self.req('/api/google/connect',{},owner=False,headers=headers)[0],401)
        self.b.unlink();self.assertEqual(self.req('/service/music/catalog',payload,owner=False,headers=headers)[1]['error'],'capability_denied')
    def test_disconnect_cancels_pending_reconnect(self):
        aid=self.connect();p=self.start(True,aid);self.req('/api/google/disconnect',{'account':aid})
        self.assertEqual(self.finish(p)[0],400);self.assertEqual(self.b.status()['accounts'],[])
    def test_owner_session_logout(self):
        status,_,headers=self.req('/api/session',{'token':'o'*40},owner=False);self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.req('/api/state',owner=False,cookie=cookie)[0],200)
        self.assertEqual(self.req('/api/session/logout',{},owner=False,cookie=cookie)[0],200)
        self.assertEqual(self.req('/api/state',owner=False,cookie=cookie)[0],401)

    def test_disconnect_cancels_unidentified_connect_before_callback(self):
        aid=self.connect();p=self.start(True)  # generic Connect, account=None
        self.assertIn(p['state'],self.b.pending)
        self.assertEqual(self.req('/api/google/disconnect',{'account':aid})[0],200)
        self.assertNotIn(p['state'],self.b.pending)
        calls=len(self.fake.forms)
        self.assertEqual(self.finish(p)[0],400)
        self.assertEqual(len(self.fake.forms),calls)
        self.assertEqual(self.b.status()['accounts'],[])
        self.assertEqual(Broker(self.config,self.fake).status()['accounts'],[])
        # Reconnecting intentionally AFTER disconnect remains supported.
        fresh=self.start(True);self.assertEqual(self.finish(fresh)[0],200)
        self.assertEqual(self.b.status()['accounts'][0]['id'],aid)

    def test_owner_audio_uses_separate_media_rpc(self):
        from music_adapter import MusicAdapter
        self.assertNotIn('audio_probe',self.s.operations)
        with patch.dict(os.environ,{'MEDIA_WORKER_TOKEN':'z'*40}):
            media=service('media')
        threading.Thread(target=media.serve_forever,daemon=True).start()
        try:
            with patch.object(self.ui,'media',RPC('127.0.0.1',media.server_port,'z'*40)),patch.object(MusicAdapter,'probe',return_value={'fixture':True}):
                self.assertEqual(self.req('/api/music/audio-probe',{'video_id':'W8VdVY8diqs'})[:2],(200,{'fixture':True}))
                self.assertEqual(self.req('/api/music/audio-probe',{'video_id':'W8VdVY8diqs'},owner=False)[0],401)
            with self.assertRaisesRegex(Denied,'operation_denied'):
                self.ui.broker.call('audio_probe',video_id='W8VdVY8diqs')
        finally:
            media.shutdown();media.server_close()

    def calendar_connect(self, subject='fixture-subject-a', account=None, youtube=False):
        self.fake.subject=subject
        code,res,h=self.req('/api/google/connect',{'account':account,'calendar':True,'youtube':youtube})
        self.assertEqual(code,200)
        self.cookie=h['Set-Cookie'].split(';')[0]
        params={k:v[0] for k,v in parse_qs(urlsplit(res['authorization_url']).query).items()}
        self.assertEqual(params['include_granted_scopes'],'true')
        self.fake.nonce=params['nonce'];self.fake.scopes=set(params['scope'].split())
        self.assertEqual(self.finish(params)[0],200)
        return self.b.status()['accounts'][-1]['id']

    def grant(self, enforce=True, caller='wizard-calendar', key='FAKE_GRANT_KEY'):
        import hashlib
        self.grants=Path(self.tmp.name)/'grants.json'
        self.grants.write_text(json.dumps({'outgoing':{},'provider_endpoints':{},'incoming':[{'from':caller,'sha256':hashlib.sha256(key.encode()).hexdigest()}],'enforce':enforce}))
        os.environ['WIZARD_GRANTS_FILE']=str(self.grants)
        return {'X-Wizard-Grant':key}

    def event_body(self, aid):
        return {'account':aid,'calendar_id':'primary@example.invalid','time_min':'2026-10-01T00:00:00Z','time_max':'2026-11-01T00:00:00+00:00'}

    def test_owner_client_save_replace_clear_and_validation(self):
        aid=self.connect();self.b.bind(aid,True)
        # Environment client takes precedence; owner cannot override it.
        payload={'client_id':'123-fixture.apps.googleusercontent.com','client_secret':'FAKE_OWNER_CLIENT_SECRET','redirect_uri':'https://owner.example/wizard-connectors/api/google/callback'}
        self.assertEqual(self.req('/api/google/client',payload)[1]['error'],'client_managed_by_environment')
        for k in ('GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','GOOGLE_REDIRECT_URI'):self.config.pop(k)
        self.assertEqual(self.req('/api/google/client',payload,owner=False)[0],401)
        self.assertEqual(self.req('/api/google/client',payload,headers={'Origin':'https://evil.invalid'})[0],403)
        for bad in ({'client_id':'not-a-client'},{'client_secret':'short'},{'redirect_uri':'http://evil.invalid/api/google/callback'},{'redirect_uri':'https://x.invalid/wrong'},{'redirect_uri':'https://x.invalid/api/google/callback?x=1'}):
            self.assertEqual(self.req('/api/google/client',{**payload,**bad})[0],409)
        result=self.req('/api/google/client',payload)
        self.assertEqual(result[0],200);self.assertTrue(result[1]['client_configured']);self.assertEqual(result[1]['client_source'],'owner')
        self.assertNotIn(payload['client_secret'],json.dumps(self.req('/api/state')[1]))
        self.assertEqual(self.b.status()['accounts'][0]['status'],'reauth_required')
        self.assertEqual(self.b.status()['bindings'],[])
        self.assertNotIn(payload['client_secret'].encode(),self.b.store.path.read_bytes())
        restored=Broker(self.config,self.fake);self.assertEqual(restored.client()[0],payload)
        self.calendar_connect(account=aid);self.b.calendar_bind(aid,True)
        payload['client_secret']='FAKE_REPLACEMENT_SECRET'
        self.assertEqual(self.req('/api/google/client',payload)[0],200)
        self.assertEqual(self.b.status()['calendar_binding']['accounts'],[])
        self.assertEqual(self.b.state['accounts'][aid]['refresh_token'],'')
        self.assertEqual(self.req('/api/google/client',owner=False,method='DELETE')[0],401)
        self.assertEqual(self.req('/api/google/client',method='DELETE')[0],200)
        self.assertFalse(Broker(self.config,self.fake).client_status()['client_configured'])
        self.assertEqual(self.req('/api/google/connect',{})[1]['error'],'google_configuration_required')

    def test_hkdf_deterministic_legacy_precedence_wrong_key_refusal(self):
        config={'BROKER_DATA_DIR':self.tmp.name+'/derived','GOOGLE_STORE_SECRET':'FAKE_STORE_SECRET_'*4}
        self.assertEqual(store_key(config),store_key(dict(config)))
        self.assertEqual(store_key({**config,'GOOGLE_STORE_KEY':self.config['GOOGLE_STORE_KEY']}),self.config['GOOGLE_STORE_KEY'])
        b=Broker(config,self.fake);b.save_client('test.apps.googleusercontent.com','FAKE_SECRET','http://localhost/api/google/callback')
        self.assertTrue(Broker(config,self.fake).client_status()['client_configured'])
        for changed in ('OTHER_FAKE_STORE_SECRET_'*4,''):
            with self.assertRaises(RuntimeError):Broker({**config,'GOOGLE_STORE_SECRET':changed},self.fake)
        with self.assertRaises(RuntimeError):Broker({**config,'GOOGLE_STORE_SECRET':'short'},self.fake)

    def test_calendar_incremental_union_multiaccount_and_binding(self):
        aid=self.connect(True);self.b.bind(aid,True)
        self.assertEqual(self.req('/api/calendar/bind',{'account':aid,'consent':True})[1]['error'],'incremental_consent_required')
        self.calendar_connect(account=aid)
        self.assertEqual(set(self.b.state['accounts'][aid]['scopes']),SCOPES)
        self.assertEqual(self.b.status()['bindings'][0]['account'],aid)
        self.assertEqual(self.req('/api/calendar/bind',{'account':aid,'consent':True})[0],200)
        other=self.calendar_connect('fixture-subject-b')
        self.assertNotEqual(aid,other)
        self.assertEqual(self.req('/api/calendar/bind',{'account':other,'consent':'true'})[0],409)
        self.b.calendar_bind(other,True)
        self.assertEqual(set(Broker(self.config,self.fake).state['calendar_binding']['accounts']),{aid,other})
        # Reverse incremental direction: Calendar first, then YouTube.
        p=self.start(True,other);self.assertIn(CALENDAR,p['scope']);self.assertEqual(self.finish(p)[0],200)
        h=self.grant()
        calendars=self.req('/service/calendar/calendars',{},owner=False,headers=h)
        self.assertEqual(calendars[0],200);self.assertEqual(len(calendars[1]['calendars']),2)
        self.b.calendar_bind(aid,False)
        self.assertEqual(self.req('/service/calendar/events',self.event_body(aid),owner=False,headers=h)[1]['error'],'capability_denied')
        self.assertEqual(self.b.status()['bindings'][0]['account'],aid)
        self.b.disconnect(other);self.assertEqual(self.b.status()['calendar_binding']['accounts'],[])

    def test_calendar_grants_fail_closed_report_only_rotation_and_mcp(self):
        path='/service/calendar/status'
        os.environ.pop('WIZARD_GRANTS_FILE',None)
        self.assertEqual(self.req(path,owner=False)[0],403)
        h=self.grant()
        status=self.req(path,owner=False,headers={**h,'Host':'wizard-connectors-calendar:8799'})
        self.assertEqual(status[0],200);self.assertEqual(status[1],{'client_configured':True,'accounts':[],'setup_url':'/wizard-connectors/'})
        for suffix,body in [('status',None),('calendars',{}),('events',self.event_body('wrong'))]:
            self.assertEqual(self.req('/service/calendar/'+suffix,body,headers={'X-Wizard-Grant':'WRONG'})[0],403)
        self.grant(enforce=False)
        self.assertEqual(self.req(path,owner=False)[0],403)
        self.assertEqual(self.req(path,owner=False,headers={'X-Wizard-App':'calendar'})[0],403)
        self.assertEqual(self.req(path,owner=False,headers=h)[0],200)
        # Canonical package id only; the old launcher/handwritten bridge id is not authority.
        self.grant(caller='calendar');self.assertEqual(self.req(path,owner=False,headers=h)[0],403)
        self.grant(caller='music');self.assertEqual(self.req(path,owner=False,headers=h)[0],403)
        self.grant(key='ROTATED_KEY');self.assertEqual(self.req(path,owner=False,headers=h)[0],403)
        self.grants.write_text('{broken');self.assertEqual(self.req(path,owner=False,headers=h)[0],403)
        self.grants.unlink();self.assertEqual(self.req(path,owner=False,headers=h)[0],403)
        h=self.grant();self.assertEqual(self.req('/api/state',owner=False,headers=h)[0],401)
        data={'jsonrpc':'2.0','id':1,'method':'tools/list'}
        tools=self.req('/mcp',data,owner=False,headers={'Authorization':'Bearer '+'m'*40})[1]['result']['tools']
        self.assertEqual({t['name'] for t in tools},{'connector_status','summary_job_status'})

    def test_calendar_events_refresh_window_pagination_bound(self):
        aid=self.calendar_connect();self.b.calendar_bind(aid,True);h=self.grant();body=self.event_body(aid)
        self.b.state['accounts'][aid]['expires']=0
        self.fake.event_pages=2
        code,out,_=self.req('/service/calendar/events',body,owner=False,headers=h)
        self.assertEqual(code,200);self.assertEqual(len(out['events']),2);self.assertFalse(out['truncated'])
        self.assertEqual(self.fake.refreshes,1);self.assertTrue(out['events'][0]['all_day'])
        self.assertEqual(out['events'][0]['start'],'2026-10-24');self.assertIn('html_link',out['events'][0])
        e=out['events'][0];self.assertEqual((e['description'],e['ical_uid'],e['attendee_count'],e['self_response'],e['meet']),('FAKE notes','fake-uid@google.com',2,'declined','https://meet.google.com/fak-efak-efa'))
        self.assertNotIn('other@example.invalid',json.dumps(out));self.assertNotIn('fake@example.invalid',json.dumps(out))
        query=self.fake.event_calls[0];self.assertEqual(query['maxResults'],2500);self.assertEqual(query['singleEvents'],'true');self.assertIn('fields',query)
        self.fake.event_calls=[];self.fake.event_pages=99
        self.assertTrue(self.req('/service/calendar/events',body,owner=False,headers=h)[1]['truncated'])
        self.assertEqual(len(self.fake.event_calls),MAX_PAGES)
        before=len(self.fake.event_calls)
        for bad in ({'time_min':'2026-01-01'},{'time_max':'2028-01-01T00:00:00Z'},{'time_max':body['time_min']},{'calendar_id':''},{'calendar_id':'x'*301}):
            self.assertEqual(self.req('/service/calendar/events',{**body,**bad},owner=False,headers=h)[0],409)
        self.assertEqual(len(self.fake.event_calls),before)
        self.fake.calendar_pages=99
        self.assertEqual(self.req('/service/calendar/calendars',{},owner=False,headers=h)[1]['error'],'calendar_list_truncated')
        self.assertEqual(len(self.fake.calendar_calls),MAX_PAGES)
        self.fake.subject='wrong';self.b.state['accounts'][aid]['expires']=0
        self.assertEqual(self.req('/service/calendar/events',body,owner=False,headers=h)[1]['error'],'reauth_required')
        self.assertEqual(Broker(self.config,self.fake).state['calendar_binding']['accounts'],[])

    def test_legacy_review_flag_no_longer_blocks(self):
        self.config['GOOGLE_REVIEW_APPROVED']='false'
        self.assertIsNone(self.b.gate())
        self.connect()

    def test_calendar_scope_loss_and_disabled(self):
        aid=self.calendar_connect();self.b.calendar_bind(aid,True);h=self.grant();body=self.event_body(aid)
        self.config['GOOGLE_DISABLED']='true'
        self.assertFalse(self.req('/service/calendar/status',owner=False,headers=h)[1]['accounts'][0]['calendar_allowed'])
        self.assertEqual(self.req('/service/calendar/events',body,owner=False,headers=h)[1]['error'],'google_disabled')
        self.config['GOOGLE_DISABLED']='false'
        self.fake.scopes=IDENTITY;self.b.state['accounts'][aid]['expires']=0
        self.assertEqual(self.req('/service/calendar/events',body,owner=False,headers=h)[1]['error'],'scope_consent_required')
        self.assertEqual(Broker(self.config,self.fake).state['calendar_binding']['accounts'],[])

    def test_calendar_callback_scope_loss_removes_binding(self):
        aid=self.calendar_connect();self.b.calendar_bind(aid,True)
        p=self.start(account=aid)
        self.fake.scopes=IDENTITY
        self.assertEqual(self.finish(p)[0],400)
        self.assertEqual(self.b.status()['calendar_binding']['accounts'],[])
        self.assertEqual(self.b.state['accounts'][aid]['status'],'reauth_required')

    def test_env_client_replacement_requires_reauth_on_restart(self):
        aid=self.calendar_connect();self.b.calendar_bind(aid,True)
        b=Broker({**self.config,'GOOGLE_CLIENT_SECRET':'FAKE_CHANGED_ENV_SECRET'},self.fake)
        self.assertEqual(b.status()['accounts'][0]['status'],'reauth_required')
        self.assertEqual(b.state['calendar_binding']['accounts'],[])
        self.assertEqual(b.state['accounts'][aid]['access_token'],'')

    def test_calendar_transport_fixed_endpoint_and_encoded_path(self):
        from unittest.mock import MagicMock
        opener=MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value=b'{"items":[]}'
        with patch('google_broker.build_opener',return_value=opener):
            GoogleTransport().request('events',token='FAKE_ACCESS',calendar_id='x@example.invalid/?evil=https://evil.invalid',query={'singleEvents':'true'})
        request=opener.open.call_args.args[0]
        u=urlsplit(request.full_url)
        self.assertEqual(u.netloc,'www.googleapis.com')
        self.assertEqual(u.path,'/calendar/v3/calendars/x%40example.invalid%2F%3Fevil%3Dhttps%3A%2F%2Fevil.invalid/events')
        self.assertEqual(parse_qs(u.query),{'singleEvents':['true']})
        self.assertEqual(request.get_header('Authorization'),'Bearer FAKE_ACCESS')
        self.assertEqual(GoogleTransport.ENDPOINTS['calendars'],'https://www.googleapis.com/calendar/v3/users/me/calendarList')

    def test_calendar_permission_loss_removes_binding(self):
        aid=self.calendar_connect();self.b.calendar_bind(aid,True);h=self.grant()
        self.fake.calendar_error='provider_permission_denied'
        self.assertEqual(self.req('/service/calendar/calendars',{},owner=False,headers=h)[1]['error'],'provider_permission_denied')
        self.assertEqual(self.b.status()['calendar_binding']['accounts'],[])
        self.assertEqual(self.b.state['accounts'][aid]['status'],'reauth_required')

    def test_callback_guess_trusted_origin_and_prefix(self):
        with patch.object(self.ui,'ORIGINS',{'https://owner.example'}):
            g=self.req('/api/state',headers={'X-Forwarded-Prefix':'/wizard-connectors/'})[1]['google']
            self.assertEqual(g['suggested_redirect_uri'],'https://owner.example/wizard-connectors/api/google/callback')
            g=self.req('/api/state',headers={'X-Forwarded-Prefix':'//evil.invalid'})[1]['google']
            self.assertEqual(g['suggested_redirect_uri'],'https://owner.example/wizard-connectors/api/google/callback')

if __name__=='__main__':unittest.main()
