"""Credential-free media role: real RPC/auth with mocked media binaries only."""
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from services import service
from service_rpc import RPC
from google_broker import Denied
from music_adapter import MusicAdapter

class MediaIsolationTests(unittest.TestCase):
    def test_media_rpc_cannot_call_broker_operations(self):
        with patch.dict(os.environ,{'PORT':'0','MEDIA_WORKER_TOKEN':'z'*40}):
            s=service('media')
        self.addCleanup(s.server_close)
        threading.Thread(target=s.serve_forever,daemon=True).start()
        self.addCleanup(s.shutdown)
        rpc=RPC('127.0.0.1',s.server_port,'z'*40)
        self.assertEqual(set(s.operations),{'audio_probe'})
        for op in ('status','start','finish','bind','unlink','disconnect','catalog','music_catalog'):
            with self.assertRaisesRegex(Denied,'operation_denied'):
                rpc.call(op)
        with self.assertRaisesRegex(Denied,'service_auth_required'):
            RPC('127.0.0.1',s.server_port,'b'*40).call('audio_probe',video_id='W8VdVY8diqs')
        with patch.object(MusicAdapter,'probe',return_value={'fixture':True}):
            # The bound method is invoked by the closure, so the mock reaches it.
            self.assertEqual(rpc.call('audio_probe',video_id='W8VdVY8diqs'),{'fixture':True})

    def test_both_media_processes_get_only_allowlisted_environment(self):
        observed=[]
        def run(command,**kw):
            observed.append(kw['env'])
            self.assertEqual(set(kw['env']),{'PATH','HOME','TMPDIR','LANG','LC_ALL'})
            self.assertNotIn('FAKE_CREDENTIAL',json.dumps(kw['env']))
            if command[0]=='yt-dlp':
                Path(command[command.index('-o')+1].replace('%(ext)s','m4a')).write_bytes(b'fixture')
                return SimpleNamespace(returncode=0,stderr=b'')
            self.assertEqual(command[0],'ffprobe')
            return SimpleNamespace(stdout=b'{"streams":[{"codec_type":"audio"}],"format":{"duration":"1"}}')
        with patch.dict(os.environ,{'GOOGLE_CLIENT_SECRET':'FAKE_CREDENTIAL','GOOGLE_STORE_KEY':'FAKE_CREDENTIAL',
                                     'BROKER_TOKEN':'FAKE_CREDENTIAL','TINFOIL_API_KEY':'FAKE_CREDENTIAL'}),patch('music_adapter.subprocess.run',side_effect=run):
            result=MusicAdapter().probe('W8VdVY8diqs')
        self.assertTrue(result['audio_verified'])
        self.assertEqual(len(observed),2)
        self.assertFalse(result['google_oauth_playback'])


if __name__=='__main__':unittest.main()
