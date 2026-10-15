"""Run on build worker; never writes owner/model tokens into receipts."""
import argparse
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--env-file',required=True);p.add_argument('--base',default='http://127.0.0.1:19470');p.add_argument('--output',required=True);a=p.parse_args()
env=dict(l.split('=',1) for l in Path(a.env_file).read_text().splitlines() if '=' in l)
checks=[]
def request(path,data=None,who='owner',headers=None):
    token=env.get('CONNECTORS_OWNER_TOKEN' if who=='owner' else 'CONNECTORS_MCP_TOKEN','') if who else ''
    h={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {}),**(headers or {})}
    r=urllib.request.Request(a.base+path,data=None if data is None else json.dumps(data).encode(),headers=h)
    try:
        with urllib.request.urlopen(r,timeout=120) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as e:return e.code,json.load(e)
def check(name,ok):
    if not ok:raise AssertionError(name)
    checks.append(name)
check('health',request('/healthz',who=None)[0]==200)
check('unauthenticated source denied',request('/api/conversations/garden',who=None)[0]==401)
check('MCP cannot read source',request('/api/conversations/garden',who='mcp')[0]==401)
check('foreign origin denied',request('/api/state',headers={'Origin':'https://attacker.invalid'})[0]==403)
check('foreign host denied',request('/api/state',headers={'Host':'attacker.invalid'})[0]==403)
check('Google activation gated',request('/api/google/connect',{})[1]['error']=='isolation_review_required')
check('source override rejected',request('/api/summarize',{'thread':'garden','request_id':'test-extra','classification':'public'})[0]==400)
check('unknown conversation rejected',request('/api/summarize',{'thread':'real-inbox','request_id':'test-unknown'})[0]==400)
check('private route configured',request('/api/state')[1]['private_route']['configured'])
request('/api/policy',{'enabled':True})
code,job=request('/api/summarize',{'thread':'garden','request_id':'real-canary-'+str(time.time_ns())})
check('real summary accepted',code==202)
start=time.monotonic()
while time.monotonic()-start<150:
    _,status=request('/api/jobs/'+job['id'])
    if status['status'] not in ('queued','running'):break
    time.sleep(1)
_,result=request('/api/results/'+job['id'])
receipt={'checks':checks,'job':status,'elapsed':round(time.monotonic()-start,2),'route':'tinfoil/glm-5-3','synthetic_only':True,'result_characters':len(result.get('text','')),'real_summary_complete':status['status']=='complete','result_source_ids':result.get('source_ids',[])}
Path(a.output).write_text(json.dumps(receipt,indent=2))
check('real attested summary completed',status['status']=='complete')
check('attestation proof returned to owner only',result.get('attestation',{}).get('security_verified') is True)
receipt['attestation']=result['attestation']
check('single conversation scope', 'SECOND-THREAD-CANARY' not in result['text'])
check('content-free job API', 'text' not in status and 'source_ids' not in status)
check('MCP token cannot read result', request('/api/results/'+job['id'],who='mcp')[0]==401)
_,m=request('/mcp',{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'summary_job_status','arguments':{'job_id':job['id']}}},who='mcp')
check('MCP content-free status', json.loads(m['result']['content'][0]['text'])==status)
_,denied=request('/mcp',{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'get_summary','arguments':{'job_id':job['id']}}},who='mcp')
check('MCP summary operation denied','error' in denied)
request('/api/policy',{'enabled':False})
check('disabled private blocks',request('/api/summarize',{'thread':'garden','request_id':'test-disabled'})[1]['error']=='private_route_disabled')
check('old result quarantined after policy change','text' not in request('/api/results/'+job['id'])[1])
request('/api/policy',{'enabled':True})
receipt.update(checks=checks,passed=len(checks))
Path(a.output).write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt,indent=2))
