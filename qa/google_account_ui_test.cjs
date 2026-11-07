/* Dependency-free DOM contract tests; not a replacement for forum screenshots. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
class Node {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.attrs={};this.dataset={};this._text='';this.isConnected=true;}
 set textContent(v){this._text=String(v);this.children=[];}
 get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
 append(...children){this.children.push(...children);}
 replaceChildren(){this._text='';this.children=[];}
 setAttribute(k,v){this.attrs[k]=String(v);}
 getAttribute(k){return this.attrs[k]??null;}
 removeAttribute(k){delete this.attrs[k];}
 addEventListener(){}
 showModal(){this.open=true;}
 close(){this.open=false;}
}
const nodes={},document={getElementById:id=>nodes[id]??=new Node(),createElement:t=>new Node(t),createTextNode:t=>{const n=new Node('text');n.textContent=t;return n;},body:new Node('body'),addEventListener(){},querySelectorAll(){return [];}};
const context=vm.createContext({document,window:{addEventListener(){}},confirm:()=>true,console,clearInterval,setInterval,URL,Intl,navigator:{language:'en-GB'},scrollTo(){}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8'),context);
const run=s=>vm.runInContext(s,context),all=n=>[n,...n.children.flatMap(all)];
const account={id:'test-account',email:'calendar-demo@example.invalid',status:'active',offline:true,scopes:['openid','email','https://www.googleapis.com/auth/calendar.readonly']};
const google={client_configured:true,accounts:[account],calendar_binding:{accounts:[account.id]},bindings:[],music:{state:'unbound'},blocker:null};
context.fixture=google;
run("state={google:fixture};view='google';renderGoogle()");
let tree=all(nodes.detail);
assert(tree.some(n=>n.className==='google-status-pill'&&n.textContent==='Connected'));
assert(!nodes.detail.textContent.includes('needs attention'));
assert(tree.some(n=>n.attrs.role==='switch'&&n.attrs['aria-checked']==='true'));
assert.equal(tree.filter(n=>n.tagName==='article').length,1);
assert.equal(tree.filter(n=>n.tagName==='summary'&&n.textContent==='More').length,1);
assert(!tree.some(n=>n.open));
for(const status of ['active','connected']){context.testStatus=status;assert.equal(run('googleAccountStatus({status:testStatus})'),'Connected');}
assert.equal(run("googleAccountStatus({status:'reauth_required'})"),'Sign in again');
run('renderRootGoogle()');assert.equal(nodes['google-summary'].textContent,account.email+' · Calendar on');
google.accounts.push({...account,id:'second'});run('renderRootGoogle()');assert.equal(nodes['google-summary'].textContent,'2 accounts · Calendar on');google.accounts.pop();
google.client_configured=false;run('renderRootGoogle()');assert.equal(nodes['google-summary'].textContent,'Google app not set up');google.client_configured=true;
google.accounts=[];run('renderRootGoogle()');assert.equal(nodes['google-summary'].textContent,'Not connected');google.accounts=[account];
account.scopes=[];run('detail.replaceChildren();renderGoogleAccounts(fixture)');tree=all(nodes.detail);assert(!tree.some(n=>n.attrs.role==='switch'));assert(tree.some(n=>n.attrs['aria-label']==='Allow Calendar'));
account.scopes=['https://www.googleapis.com/auth/calendar.readonly'];
context.WizardApp={back:{push:()=>({release(){}})}};
(async()=>{
 const docs=[['cloud_terms','Google Cloud Terms of Service','https://cloud.google.com/terms'],['api_terms','Google APIs Terms of Service','https://developers.google.com/terms'],['user_data_policy','Google API Services User Data Policy','https://developers.google.com/terms/api-services-user-data-policy']].map(([id,title,url])=>({id,title,url}));
 google.agreement_options={version:'google-2026-11',countries:['GB','US'],documents:docs};google.agreements={accepted:[],version:'',country:''};
 google.client_configured=false;google.accounts=[];run('startGoogleSetup()');
 let agreementTree=all(nodes.detail),agree=agreementTree.find(n=>n.tagName==='button'&&n.textContent==='Agree and continue');
 const boxes=agreementTree.filter(n=>n.type==='checkbox'),country=agreementTree.find(n=>n.tagName==='select');
 assert.equal(boxes.length,3);assert(boxes.every(c=>!c.checked));assert.equal(agree.disabled,true);assert.equal(country.value,'GB');
 assert.deepEqual(agreementTree.filter(n=>n.tagName==='a').map(n=>n.href),docs.map(d=>d.url));
 for(const c of boxes){c.checked=true;c.onchange();}assert.equal(agree.disabled,false);country.value='';country.onchange();assert.equal(agree.disabled,true);country.value='GB';country.onchange();
 let agreementPayload;context.saveAgreements=data=>{agreementPayload=data;return {accepted:data.agreements,version:data.version,country:data.country};};
 run('api=async(path,data)=>saveAgreements(data)');await agreementTree.find(n=>n.tagName==='form').onsubmit({preventDefault(){}});
 assert.equal(agreementPayload.version,'google-2026-11');assert.equal(agreementPayload.country,'GB');assert.equal(agreementPayload.agreements.length,3);
 assert.equal(run('googleSetup'),'agent');run('back()');assert.equal(run('googleSetup'),'agreements');
 run('googleSetup="agent";manualGoogle();back()');assert.equal(run('googleSetup'),'agent');
 run('googleSetup=null');google.client_configured=true;google.accounts=[account];
 const toggle=new Node('button');context.control=toggle;context.a=account;
 let release,writes=[];context.writeGate=new Promise(r=>release=r);
 context.record=d=>writes.push(d);
 run("api=async(path,data)=>{record({path,...data});await writeGate};refresh=async()=>{};");
 const task=run('toggleCalendar(control,a,true)');
 assert.equal(toggle.attrs['aria-checked'],'false');assert.equal(toggle.attrs['aria-busy'],'true');assert.equal(toggle.disabled,true);
 assert.equal(writes.length,1);assert.equal(writes[0].consent,false);release();await task;assert.equal(toggle.disabled,false);
 context.confirm=()=>false;await run('toggleCalendar(control,a,false)');assert.equal(writes.length,1);
 context.confirm=()=>true;run("api=async()=>{throw Error('fixture')}");await run('toggleCalendar(control,a,false)');assert.equal(toggle.attrs['aria-checked'],'false');assert.equal(nodes['dialog-title'].textContent,'Could not update Calendar');
 const home=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');
 for(const removed of ['Practice a private summary','Try it out','chat-row','google-manage'])assert(!home.includes(removed));
 console.log('PASS active/connected status, agreements checklist/country/save/Back, reauthentication, account cards, root states, permissions, immediate toggle feedback, consent cancellation, failure rollback, no practice UI');
})().catch(e=>{console.error(e);process.exitCode=1;});
