#!/usr/bin/env python3
"""Isolated Thales-only exact-image proof. No live deployment, no publication.
Run from a pushed source archive: python3 qa/thales_calendar_proof.py <revision>
All tokens/grants here are explicitly public FAKE test fixtures.
"""
import hashlib
import json
import os, shutil
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
if not str(root).lower().startswith('/volumes/thalesmedia/builds/'):  # APFS is case-insensitive; realpath may return Builds
    raise SystemExit('Run this proof only on the configured Thales external build volume')
revision = sys.argv[1]
env = dict(os.environ, PATH='/opt/homebrew/bin:/usr/local/bin:' + os.environ.get('PATH',''), DOCKER_CONTEXT='colima')
proof = root / 'qa-output'
proof.mkdir(exist_ok=True)
log = (proof / 'docker-proof.log').open('w')

def run(args, *, check=True):
    print('+ ' + ' '.join(args), flush=True)
    log.write('+ ' + ' '.join(args) + '\n'); log.flush()
    p = subprocess.run(args, cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(p.stdout, flush=True); log.write(p.stdout); log.flush()
    if check and p.returncode: raise RuntimeError('command_failed: ' + args[0])
    return p

run(['hostname'])
run(['docker','version'])
image = 'wizard-connectors-byo-proof:' + revision
run(['docker','build','--build-arg','SOURCE_REVISION='+revision,'-t',image,'-f','app/Dockerfile','.'])
image_id = run(['docker','image','inspect',image,'--format','{{.Id}}']).stdout.strip()
(proof/'image.json').write_text(json.dumps({'source_revision':revision,'image':image,'image_id':image_id},indent=2))
run(['docker','run','--rm',image,'python3','-m','unittest','discover','-s','tests','-v'])
# Never join a live app network. This separate network models the main network.
network = 'wcon-byo-proof-main'
run(['docker','network','inspect',network],check=False)
existing = subprocess.run(['docker','network','inspect',network],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
if existing.returncode: run(['docker','network','create',network])
# Colima shares only the macOS home into its VM; /Volumes bind mounts appear empty,
# so the read-only grants mount would fail closed. Keep this tiny fixture under ~.
data = Path.home()/'.cache'/'wcon-byo-proof'/'app-data'
(data/'wizard').mkdir(parents=True,exist_ok=True)
key = 'FAKE_CALENDAR_GRANT_FOR_ISOLATED_PROOF_ONLY'
grants = {'outgoing':{},'incoming':[{'from':'calendar','sha256':hashlib.sha256(key.encode()).hexdigest()}], 'provider_endpoints':{},'enforce':True}
(data/'wizard'/'grants.json').write_text(json.dumps(grants))
env.update({name:('FAKE_'+name+'_')*4 for name in ('CONNECTORS_OWNER_TOKEN','CONNECTORS_MCP_TOKEN','MUSIC_ADAPTER_TOKEN','BROKER_TOKEN','PRIVATE_WORKER_TOKEN','MEDIA_WORKER_TOKEN','GOOGLE_STORE_SECRET')})
env.update(APP_DATA_DIR=str(data),WIZARD_MAIN_NETWORK=network)
# JSON is valid YAML. Prebuilt image for every service; compose --no-build cannot
# accidentally rebuild another revision or touch the live install project.
services = ('ingress','wizard-connectors','google-broker','media-worker','private-worker')
override = proof/'compose-image.json'
override.write_text(json.dumps({'services':{s:{'image':image} for s in services}}))
compose = ['docker','compose','--project-directory',str(root),'-p','wcon-byo-proof','-f','runtipi/docker-compose.yml','-f',str(override)]
try:
    run(compose+['up','-d','--no-build'])
    # Readiness is checked through the consumer network, not a host-published port.
    probe = ['docker','run','--rm','--network',network,image,'python3','-c',
             "import urllib.request; q=urllib.request.Request('http://wizard-connectors-calendar:8799/service/calendar/status',headers={'X-Wizard-Grant':'FAKE_CALENDAR_GRANT_FOR_ISOLATED_PROOF_ONLY'}); print(urllib.request.urlopen(q,timeout=3).read().decode())"]
    ready=False
    for _ in range(20):
        if run(probe,check=False).returncode==0: ready=True; break
        time.sleep(1)
    if not ready: raise RuntimeError('ingress_not_ready')
    run(compose+['ps'])
    curl = ['docker','run','--rm','--network',network,'curlimages/curl:8.12.1','--silent','--show-error','--max-time','30','--write-out','\nHTTP %{http_code}\n']
    url = 'http://wizard-connectors-calendar:8799/service/calendar/status'
    yes = run(curl+['-H','X-Wizard-Grant: '+key,url]).stdout
    no = run(curl+[url]).stdout
    wrong = run(curl+['-H','X-Wizard-Grant: WRONG_FIXTURE_KEY',url]).stdout
    if 'HTTP 200' not in yes or 'HTTP 403' not in no or 'HTTP 403' not in wrong: raise RuntimeError('grant_acceptance_failed')
    (proof/'curl-results.json').write_text(json.dumps({'valid':yes,'missing':no,'wrong':wrong},indent=2))
    ids=run(compose+['ps','-q']).stdout.split()
    run(['docker','inspect',*ids,'--format','{{.Name}} image={{.Image}} networks={{json .NetworkSettings.Networks}} mounts={{json .Mounts}}'])
    # Supervised attached fixture process; always stopped in finally. This is
    # browser QA, not a detached workload or a deployment.
    support = root.parent/'wizard-connectors-byo-support'
    browser_out = proof/'browser'
    (proof/'chrome-tmp').mkdir(exist_ok=True)
    browser_env = dict(env, PLAYWRIGHT_MODULE=str(support/'node_modules/playwright/index.js'),
        CHROME_BINARY='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        QA_ROOT=str(browser_out), TMPDIR=str(proof/'chrome-tmp'))
    # Colima sees only the home share; stage the small QA tree and shared kit there.
    vm_share = Path.home()/'.cache'/'wcon-byo-proof'
    for name, src in (('qa', root/'qa'), ('support-core', support/'core'), ('support-kit', support/'kit')):
        dst = vm_share/name
        if dst.exists(): shutil.rmtree(dst)
        shutil.copytree(src, dst)
    fixture_log=(proof/'browser-fixture.log').open('w')
    fixture=subprocess.Popen(['docker','run','--rm','--name','wcon-byo-browser-proof',
        '-p','127.0.0.1:19476:8799','--tmpfs','/tmp:rw,size=64m',
        '-v',str(vm_share/'qa')+':/app/qa:ro','-v',str(vm_share/'support-core')+':/qa-support/core:ro','-v',str(vm_share/'support-kit')+':/qa-support/kit:ro',
        '-e','QA_CORE_DIR=/qa-support/core','-e','QA_KIT_DIR=/qa-support/kit',
        image,'python3','qa/byo_browser_server.py'],env=env,stdout=fixture_log,stderr=subprocess.STDOUT)
    try:
        import urllib.request
        for _ in range(30):
            if fixture.poll() is not None: raise RuntimeError('browser_fixture_exited: '+(proof/'browser-fixture.log').read_text()[-500:])
            try:
                urllib.request.urlopen('http://127.0.0.1:19476/healthz',timeout=2).close(); break
            except Exception: time.sleep(1)
        else: raise RuntimeError('browser_fixture_not_ready')
        browser_run=subprocess.run(['node','qa/byo_browser.mjs'],cwd=root,env=browser_env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240)
        print(browser_run.stdout,flush=True)
        (proof/'browser-run.log').write_text(browser_run.stdout)
        if browser_run.returncode: raise RuntimeError('browser_acceptance_failed')
    finally:
        run(['docker','stop','wcon-byo-browser-proof'],check=False)
        fixture.wait(timeout=30);fixture_log.close()
finally:
    run(compose+['logs' ,'--no-color'],check=False)
    run(compose+['down'],check=False)  # Preserve test volumes for inspection, never down -v.
    log.close()
print(json.dumps({'source_revision':revision,'image_id':image_id,'consumer_url':'http://wizard-connectors-calendar:8799','proof':'qa-output/docker-proof.log','result':'PASS'}))
