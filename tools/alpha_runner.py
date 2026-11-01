#!/usr/bin/env python3
"""Native staged-source Alpha packaging; never installs or deploys an app."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import signal
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--arch', choices=('amd64', 'arm64'), default=os.environ.get('ARCH'))
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    native = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine())
    if native != args.arch: parser.error('native architecture must match ARCH; never emulate')
    source = args.source.resolve(strict=True)
    out = (args.evidence or source.parent/'evidence').resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out/('release-'+args.arch+'.json')).unlink(missing_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if not re.fullmatch('[0-9a-f]{40}', revision): raise SystemExit('full source revision required')
    if os.environ.get('SOURCE_REVISION', revision) != revision: raise SystemExit('staged revision mismatch')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True).strip(): raise SystemExit('source must be clean')
    config = json.loads((source/'runtipi/config.json').read_text())
    version = config['version']
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-alpha\.[0-9]+', version): raise SystemExit('expected fixed Alpha version')
    tag = 'wizard-connectors:' + version
    compose = (source/'runtipi/docker-compose.yml').read_text()
    assert compose.count('image: ' + tag + '\n') == 5 and compose.count('pull_policy: never') == 5
    assert 'version: ' + version + '\n' in (source/'wizard.md').read_text()
    assert json.loads((source/'openapi.json').read_text())['info']['version'] == version
    docker = shlex.split(os.environ.get('DOCKER_CMD', 'docker --context colima' if platform.system() == 'Darwin' else 'docker'))
    if not docker: raise SystemExit('empty DOCKER_CMD')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')

    def run(argv, name, timeout=300):
        with (out/(name+'-'+args.arch+'.log')).open('w') as log:
            proc = subprocess.run(argv, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        print(name, 'exit', proc.returncode, flush=True)
        if proc.returncode: raise SystemExit(proc.returncode)

    pins = json.loads((source/'tools/browser_versions.json').read_text())
    uv = ['uv', 'run', '-q', '--python', '3.12', '--managed-python', '--with-requirements', 'requirements.lock']
    run(uv+['python', '-m', 'unittest', 'discover', '-s', 'tests'], 'unit-tests')
    for file in [source/'web/app.js', *sorted((source/'qa').glob('*.cjs'))]:
        run(['node', '--check', str(file)], 'syntax-'+file.stem, 30)
    run(['node', 'qa/google_account_ui_test.cjs'], 'ui-dom-contracts', 30)
    # Browser phase is independent of Docker image availability.
    browser = {'executed': False, 'reason': 'arm64 packaging; browser QA is amd64-only'}
    if args.arch == 'amd64':
        run(['node', 'qa/google_connect_ux.cjs', str(source), str(out/'browser')], 'browser-qa', 240)
        receipt = json.loads((out/'browser/browser-receipt.json').read_text())
        assert receipt['mode'] == 'standalone-candidate-synthetic-api-and-skins'
        assert receipt['liveOwnerWrites'] == 0 and not receipt['errors']
        expected = {screen+'-'+skin+'.png' for screen in ('home-connected', 'google-calendar-on', 'google-agreements', 'google-connected', 'google-error') for skin in ('nebula', 'light')}
        assert expected <= set(receipt['screenshots'])
        assert all((out/'browser'/name).stat().st_size > 0 for name in expected)
        run(uv+['--with', 'playwright=='+pins['python'], 'python', 'qa/google_console_fixture.py'], 'console-fixture', 240)
        browser = {'executed': True, 'screenshots': sorted(expected), 'checks': len(receipt['checks']), 'coverage': 'synthetic standalone skins and fake Console; not live shell/Google/physical phone'}
    daemon_arch = subprocess.check_output(docker+['info','--format','{{.Architecture}}'],cwd=source,env=env,text=True).strip()
    if {'x86_64':'amd64','amd64':'amd64','aarch64':'arm64','arm64':'arm64'}.get(daemon_arch) != args.arch:
        raise SystemExit('Docker daemon must be native; never emulate')
    run(docker+['build', '--pull=false', '--platform', 'linux/'+args.arch,
                '--build-arg', 'SOURCE_REVISION='+revision, '--label', 'org.opencontainers.image.revision='+revision,
                '-f', 'app/Dockerfile', '-t', tag, '.'], 'image-build', 1200)
    info = json.loads(subprocess.check_output(docker+['image', 'inspect', tag], cwd=source, env=env))[0]
    assert info['Architecture'] == args.arch
    assert info['Config']['Labels']['org.opencontainers.image.revision'] == revision
    run(uv+['python', 'qa/alpha_smoke.py'], 'hardened-recipe-smoke', 360)
    archive = out/('connected-accounts-'+args.arch+'.tar.gz')
    partial = archive.with_suffix(archive.suffix+'.partial')
    with partial.open('wb') as stream, (out/('image-save-'+args.arch+'.log')).open('wb') as log:
        save = subprocess.Popen(docker+['save', tag], cwd=source, env=env, stdout=subprocess.PIPE, stderr=log)
        try:
            gzip = subprocess.Popen(['gzip', '-n'], stdin=save.stdout, stdout=stream, stderr=log)
            save.stdout.close()
            try:
                zipped = gzip.wait(timeout=900)
                saved = save.wait(timeout=30)
            finally:
                if gzip.poll() is None: gzip.kill(); gzip.wait()
            if saved or zipped: raise SystemExit('docker save / gzip failed; archive not released')
        finally:
            if save.poll() is None: save.kill(); save.wait()
    partial.replace(archive)
    with archive.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (out/(archive.name+'.sha256')).write_text(digest+'  '+archive.name+'\n')
    evidence = {'version': version, 'revision': revision, 'arch': args.arch, 'tag': tag, 'image_id': info['Id'],
                'archive': archive.name, 'sha256': digest, 'browser': browser, 'hardened_smoke': True, 'deployed': False,
                'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out/('release-'+args.arch+'.json')).write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(evidence), flush=True)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    main()
