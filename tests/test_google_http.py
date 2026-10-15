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
from google_broker import Broker,GoogleTransport,Denied,IDENTITY,SCOPES,YOUTUBE
from services import service
from service_rpc import RPC

class FakeGoogle(GoogleTransport):
    def __init__(self):
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()));self.jwk['kid']='fixture'
        self.nonce='';self.subject='fixture-subject-a';self.scopes=IDENTITY
        self.refreshes=0;self.revoked=False;self.fail_revoke=False;self.bad={};self.forms=[];self.forge=False
    def request(self,operation,*,form=None,token=None,query=None):
        if operation=='jwks':return {'keys':[self.jwk]}
        if operation=='userinfo':return {'sub':self.subject}
        if operation=='revoke':
            self.revoked=True
            if self.fail_revoke:raise Denied('provider_unavailable')
            return {}
        if operation=='catalog':return {'items':[{'id':query['id'],'snippet':{'title':'FAKE catalog fixture'}}]}
        if operation=='token':
            self.forms.append(form)
            claims={'iss':'https://accounts.google.com','aud':'fixture-client','sub':self.subject,'nonce':self.nonce,
                    'iat':int(time.time()),'exp':int(time.time())+3600,'email':'fixture@example.invalid','email_verified':True,**self.bad}
            if form['grant_type']=='refresh_token': self.refreshes+=1;time.sleep(.02)
            return {'access_token':'FAKE_ACCESS_SECRET','refresh_token':'FAKE_REFRESH_SECRET','token_type':'Bearer','expires_in':3600,
                    'scope':' '.join(self.scopes),'id_token':jwt.encode(claims,rsa.generate_private_key(public_exponent=65537,key_size=2048) if self.forge else self.key,algorithm='RS256',headers={'kid':'fixture'})}
        raise AssertionError(operation)

class BrokerHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.fake=FakeGoogle()
        self.config={'BROKER_DATA_DIR':self.tmp.name+'/broker','GOOGLE_STORE_KEY':Fernet.generate_key().decode(),
                     'GOOGLE_REVIEW_APPROVED':'true','GOOGLE_CLIENT_ID':'fixture-client','GOOGLE_CLIENT_SECRET':'FAKE_CLIENT_SECRET',
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
    def req(self,path,data=None,owner=True,cookie=None,headers=None):
        h={'Content-Type':'application/json',**({'Authorization':'Bearer '+'o'*40} if owner else {}),**(headers or {})}
        if cookie is not None:h['Cookie']=cookie
        q=Request(self.base+path,data=None if data is None else json.dumps(data).encode(),headers=h)
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
        self.config['GOOGLE_REVIEW_APPROVED']='false';self.assertEqual(self.req('/api/google/connect',{})[1]['error'],'isolation_review_required')
        self.config['GOOGLE_REVIEW_APPROVED']='true';del self.config['GOOGLE_CLIENT_SECRET'];self.assertEqual(self.req('/api/google/connect',{})[1]['error'],'google_configuration_required')
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

if __name__=='__main__':unittest.main()
