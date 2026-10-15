"""Isolated anonymous YouTube Music adapter; never reads browser cookie files.
Google identity/catalog authorization is deliberately NOT playback authorization.
"""
import json
import re
import subprocess
import tempfile
import os
from pathlib import Path
from google_broker import Denied

# Defense in depth; container/volume/network isolation is the credential boundary.
def process_env(tmp):
    return {'PATH':os.environ.get('PATH','/usr/local/bin:/usr/bin:/bin'),
            'HOME':tmp,'TMPDIR':tmp,'LANG':'C.UTF-8','LC_ALL':'C.UTF-8'}

class MusicAdapter:
    def probe(self, video_id):
        if not isinstance(video_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id): raise Denied('invalid_video_id')
        with tempfile.TemporaryDirectory(prefix='music-probe-') as tmp:
            # No persisted cache, no config discovery, no credential import. Fixed provider/ID.
            command = ['yt-dlp','--ignore-config','--no-cache-dir','--no-playlist','--no-progress','--no-warnings',
                       '--socket-timeout','12','--retries','0','--max-filesize','25M','-f','bestaudio',
                       '-o',str(Path(tmp)/'audio.%(ext)s'), 'https://music.youtube.com/watch?v='+video_id]
            try:
                r = subprocess.run(command, capture_output=True, timeout=55, env=process_env(tmp))
                if r.returncode:
                    message = r.stderr.decode(errors='replace').lower()
                    code = 'provider_sign_in_required' if any(x in message for x in ('sign in','bot','login','cookies')) else 'provider_audio_unavailable'
                    return {'provider':'youtube-music','video_id':video_id,'status':'blocked','error':code,'audio_verified':False,'cache':'fresh_empty','google_oauth_playback':False}
                files = list(Path(tmp).glob('audio.*'))
                if len(files)!=1: raise ValueError()
                p = subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,codec_name:format=duration','-of','json',str(files[0])],capture_output=True,timeout=10,check=True,env=process_env(tmp))
                meta=json.loads(p.stdout)
                if not any(s.get('codec_type')=='audio' for s in meta.get('streams',[])): raise ValueError()
                return {'provider':'youtube-music','video_id':video_id,'status':'fresh_audio_downloaded','audio_verified':True,
                        'bytes':files[0].stat().st_size,'duration':float(meta['format']['duration']),
                        'cache':'fresh_empty','browser_playback_verified':False,'google_oauth_playback':False}
            except subprocess.TimeoutExpired:
                return {'provider':'youtube-music','video_id':video_id,'status':'blocked','error':'provider_audio_timeout','audio_verified':False}
            except Exception: raise Denied('audio_verification_failed') from None
