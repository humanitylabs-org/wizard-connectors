#!/usr/bin/env python3
"""Disposable native image/recipe smoke; synthetic secrets, no owner endpoints.
Uses only owned Compose resources, no source/host bind mounts or published ports.
WAM grant injection is simulated with an empty named-volume mount: real WAM
admission and cross-app grants are separate acceptance gates.
"""
import json
import os
from pathlib import Path
import secrets
import shlex
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    docker = shlex.split(os.environ.get('DOCKER_CMD', 'docker'))
    project = 'connected-alpha-smoke-' + secrets.token_hex(6)
    # The recipe joins no shared main network; the probe uses the project's own edge network,
    # where the ingress service name is the advertised consumer host (WAM link nets do the same).
    network = project + '_edge'
    env = dict(os.environ)
    fields = json.loads((ROOT/'runtipi/config.json').read_text())['form_fields']
    for field in fields:
        if field.get('required'):
            assert field['type'] == 'password'
            env[field['env_variable']] = secrets.token_urlsafe(48)
    # No inherited real account/key values, route pins, or private provider access.
    for key in ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'GOOGLE_REDIRECT_URI', 'GOOGLE_STORE_KEY', 'TINFOIL_API_KEY', 'WIZARD_TRUSTED_HOSTS', 'WIZARD_TRUSTED_ORIGINS'):
        env[key] = ''
    env.update(PRIVATE_ROUTE_CONFIGURED='false', GOOGLE_DISABLED='false')
    def run(args, **kw):
        return subprocess.check_output(docker+args, cwd=ROOT, env=env, text=True, stderr=subprocess.STDOUT, timeout=120, **kw)
    checks = []
    cleanup_errors = []
    with tempfile.TemporaryDirectory(prefix=project+'-', dir=ROOT.parent) as tmp:
        override = Path(tmp)/'override.json'
        override.write_text(json.dumps({'services': {'wizard-connectors': {'volumes': ['smoke-grants:/wizard:ro']}}, 'volumes': {'smoke-grants': {}}}))
        compose = ['compose', '-p', project, '-f', str(ROOT/'runtipi/docker-compose.yml'), '-f', str(override)]
        try:
            run(compose+['up', '-d', '--pull', 'never', '--no-build'])
            ids = run(compose+['ps', '-aq']).split()
            assert len(ids) == 5
            for cid in ids:
                row = json.loads(run(['inspect', cid]))[0]
                assert row['Config']['Labels']['com.docker.compose.project'] == project
                assert row['HostConfig']['ReadonlyRootfs'] and row['Config']['User'] == '1000:1000'
                assert row['HostConfig']['CapDrop'] == ['ALL']
                assert 'no-new-privileges:true' in row['HostConfig']['SecurityOpt']
                assert all(m['Type'] == 'volume' or m['Type'] == 'tmpfs' and m['Destination'] == '/tmp' for m in row['Mounts']), 'No host or source binds'
            checks.append('five recipe services non-root/read-only/ALL caps dropped; no host binds')
            probe = r'''import json,time,urllib.request,urllib.error
base='http://wizard-connectors-calendar:8799'
for _ in range(100):
 try:
  with urllib.request.urlopen(base+'/healthz',timeout=2) as r: assert json.load(r)['ok'];break
 except (OSError,AssertionError):time.sleep(.2)
else:raise AssertionError('ingress health timeout')
for path in ('/api/state','/service/calendar/status'):
 try:urllib.request.urlopen(base+path,timeout=3);raise AssertionError('unauthorized read')
 except urllib.error.HTTPError as e:assert e.code in (401,403)
req=urllib.request.Request(base+'/api/google/setup/intake',data=b'{}',headers={'Host':'public.example.invalid','Content-Type':'application/json'})
try:urllib.request.urlopen(req,timeout=3);raise AssertionError('public intake')
except urllib.error.HTTPError as e:assert e.code==403
print('PASS ingress health, owner/grant denial, public intake denial')'''
            run(['run', '--rm', '--network', network, '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--user', '1000:1000', 'wizard-connectors:0.2.0-alpha.1', 'python', '-c', probe])
            checks.append('real image ingress health; owner/grant/public intake deny')
        finally:
            try: run(compose+['down', '--volumes', '--remove-orphans', '--timeout', '10'])
            except Exception: cleanup_errors.append('compose_down_failed')
            if cleanup_errors: raise RuntimeError(','.join(cleanup_errors))
        assert not run(['ps', '-aq', '--filter', 'label=com.docker.compose.project='+project]).strip()
        assert not run(['volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project='+project]).strip()
    print(json.dumps({'ok': True, 'checks': checks, 'cleanup_verified': True, 'live_owner_writes': 0}))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    main()
