"""Synthetic Human Handoff metadata/teardown tests. No browser is launched."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch
from test_google_setup import script


class DisposableHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.sid='hh-20261101-120000-abcdef';self.directory=self.root/'sessions'/self.sid
        self.directory.mkdir(parents=True)
        self.profile=self.directory/'browser-profile';self.profile.mkdir()
        self.config=self.directory/'config.json'
        self.write_config('disposable')
        self.status={'session_id':self.sid,'status':'ready','cdp_url':'http://127.0.0.1:9222','cleanup_error':None,'expires_at':'2999-01-01T00:00:00Z'}
        self.env=patch.dict(os.environ,{'HUMAN_HANDOFF_HOME':str(self.root),'HANDOFF_SESSION_ID':self.sid,'HANDOFF_CDP_URL':self.status['cdp_url']})
        self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def write_config(self, mode):
        self.config.write_text(json.dumps({'profile_mode':mode,'profile_path':str(self.profile)}));self.config.chmod(0o600)
    def handoff(self, **kw):
        with patch.object(script.HandoffSession,'command',return_value=self.status):return script.HandoffSession(**kw)

    def test_shipped_skill_scripts_are_portable_without_source_checkout(self):
        import subprocess
        import sys
        source=Path(script.__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            dest=Path(directory)
            for name in ('google_cloud_setup.py','google_agreement_definitions.py'):
                shutil.copyfile(source/name,dest/name)
            result=subprocess.run([sys.executable,str(dest/'google_cloud_setup.py'),'--help'],cwd=dest,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn('--allow-persistent-profile',result.stdout)
            self.assertNotIn('Traceback',result.stderr)

    def test_persistent_and_clone_refused_before_any_browser_inspection(self):
        for mode in ('persistent','clone',None):
            self.write_config(mode)
            with self.assertRaisesRegex(script.NeedsOwner,'fresh_disposable_handoff_required'):self.handoff()
        self.write_config('persistent')
        with self.assertRaises(TypeError):self.handoff(allow_persistent=True)
        with patch.dict(os.environ,{'HANDOFF_SESSION_ID':'','BROWSER_CDP_URL':'http://127.0.0.1:9222'}):
            with self.assertRaises(script.NeedsOwner):script.HandoffSession()

    def test_fresh_profile_endpoint_binding_and_private_metadata_required(self):
        self.assertEqual(self.handoff().mode,'disposable')
        with patch.dict(os.environ,{'HANDOFF_CDP_URL':'http://127.0.0.1:9999'}):
            with self.assertRaises(script.NeedsOwner):self.handoff()
        self.config.chmod(0o644)
        with self.assertRaises(script.NeedsOwner):self.handoff()

    def test_teardown_requires_readback_stopped_and_actual_removal(self):
        h=self.handoff();calls=[]
        def command(op):
            calls.append(op)
            if op=='stop':shutil.rmtree(self.profile);self.config.unlink()
            return {**self.status,'status':'stopped'}
        with patch.object(h,'command',side_effect=command):h.stop_and_verify()
        self.assertEqual(calls,['stop','status'])
        self.assertFalse(self.profile.exists())

    def test_teardown_failure_cannot_be_reported_as_success(self):
        h=self.handoff()
        # A lying successful stop response does not erase the actual profile.
        with patch.object(h,'command',return_value={**self.status,'status':'stopped'}):
            with self.assertRaisesRegex(script.NeedsOwner,'handoff_teardown_failed'):h.stop_and_verify()
        shutil.rmtree(self.profile);self.config.unlink()
        for result in ({**self.status,'status':'ready'}, {**self.status,'status':'stopped','cleanup_error':'FAKE_PRIVATE_TEXT'}):
            with patch.object(h,'command',return_value=result):
                with self.assertRaisesRegex(script.NeedsOwner,'handoff_teardown_failed'):h.stop_and_verify()

    def test_signout_failure_still_destroys_profile_and_needs_owner(self):
        h=Mock();page=object()
        with patch.object(script,'sign_out_google',side_effect=RuntimeError('FAKE_PRIVATE_CONTENT')):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(script.NeedsOwner,'google_sign_out_not_verified'):script.finish_handoff(h,page)
        h.stop_and_verify.assert_called_once()

    def test_signout_checks_signed_out_ui_and_rejects_remaining_auth_cookie(self):
        page=Mock();page.get_by_role.return_value.count.return_value=0
        page.context.cookies.return_value=[]
        script.sign_out_google(page)
        page.goto.assert_called_once_with('https://accounts.google.com/Logout',wait_until='domcontentloaded')
        page.context.cookies.return_value=[{'name':'SID','domain':'.google.com','value':'FAKE_COOKIE_SECRET'}]
        with self.assertRaisesRegex(script.NeedsOwner,'google_sign_out_not_verified'):script.sign_out_google(page)

    def test_main_emits_success_only_after_verified_finalization(self):
        import types
        session=Mock();session.endpoint=self.status['cdp_url']
        page=Mock();page.url='https://console.cloud.google.com/auth/overview'
        browser=Mock();browser.contexts=[types.SimpleNamespace(pages=[page])]
        manager=Mock();p=manager.__enter__=Mock();manager.__exit__=Mock(return_value=False)
        p.return_value.chromium.connect_over_cdp.return_value=browser
        module=types.ModuleType('playwright.sync_api');module.sync_playwright=lambda:manager
        for failure in (False,True):
            output=io.StringIO()
            def finalizer(h,p):
                if failure:raise script.NeedsOwner('handoff_teardown_failed')
                script.emit('sign_out','ok');script.emit('teardown','ok')
            with patch.dict('sys.modules',{'playwright.sync_api':module}),patch.object(script.sys,'argv',['google_cloud_setup.py']),patch.object(script,'HandoffSession',return_value=session) as factory,patch.object(script,'run',side_effect=lambda a,p:script.emit('deposit','ok')),patch.object(script,'finish_handoff',side_effect=finalizer),contextlib.redirect_stdout(output):
                self.assertEqual(script.main(),2 if failure else 0)
                factory.assert_called_once_with()
            codes=[json.loads(x) for x in output.getvalue().splitlines()]
            self.assertEqual(codes[-1],{'step':'setup','status':'needs_owner','reason':'handoff_teardown_failed'} if failure else {'step':'setup','status':'ok'})
            if not failure:self.assertEqual([x['step'] for x in codes],['deposit','sign_out','teardown','setup'])

    def test_finalizer_order_and_allowlisted_output_only(self):
        actions=[];h=Mock();h.stop_and_verify.side_effect=lambda:actions.append('stop_and_verify')
        output=io.StringIO()
        with patch.object(script,'sign_out_google',side_effect=lambda p:actions.append('sign_out')),contextlib.redirect_stdout(output):
            script.finish_handoff(h,object())
            script.emit('setup','needs_owner','FAKE_PRIVATE_PAGE_CONTENT',project='FAKE_EMAIL_OR_PROJECT')
        self.assertEqual(actions,['sign_out','stop_and_verify'])
        self.assertNotIn('FAKE_',output.getvalue())
        codes=[json.loads(x) for x in output.getvalue().splitlines()]
        self.assertEqual(codes[0],{'step':'sign_out','status':'ok'})
        self.assertEqual(codes[1],{'step':'teardown','status':'ok'})

    def test_expired_ready_session_is_refused_before_inspection(self):
        self.status['expires_at']='2000-01-01T00:00:00Z'
        with self.assertRaisesRegex(script.NeedsOwner,'handoff_profile_not_verified'):self.handoff()

    def test_owner_auth_gate_preserves_only_active_expiring_disposable_session(self):
        h=self.handoff()
        for reason in script.OWNER_RESUMABLE:
            with patch.object(h,'command',return_value=self.status),patch.object(h,'stop_and_verify') as stop,patch.object(script,'finish_handoff') as finish,contextlib.redirect_stdout(io.StringIO()):
                script.finalize_attempt(h,None,script.NeedsOwner(reason))
                stop.assert_not_called();finish.assert_not_called()
        with patch.object(script,'finish_handoff') as finish:
            script.finalize_attempt(h,None,script.NeedsOwner('unrecorded_google_agreement'))
            finish.assert_called_once_with(h,None)

    def test_resumable_gate_never_keeps_expired_session(self):
        h=self.handoff()
        with patch.object(h,'command',return_value={**self.status,'expires_at':'2000-01-01T00:00:00Z'}),patch.object(h,'stop_and_verify') as stop:
            with self.assertRaises(script.NeedsOwner):script.finalize_attempt(h,None,script.NeedsOwner('complete_verification'))
            stop.assert_called_once()
