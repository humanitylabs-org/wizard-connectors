/* Forum worker only. Standalone candidate pages + synthetic API/skin fixtures.
 * Every request is fulfilled or aborted: no live shell, Google, or owner writes.
 * Run: node qa/google_connect_ux.cjs <source> <evidence-dir>
 */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
let playwright;try{playwright=require('playwright');}catch{playwright=require('/srv/work/provider-signin-browser/node_modules/playwright');}
const {chromium,devices}=playwright;
const source=path.resolve(process.argv[2]||'.'),out=path.resolve(process.argv[3]||'evidence');
const origin='https://connected-accounts.fixture.invalid',base=origin+'/connected-accounts/';
const checks=[],errors=[],writes=[],blocked=[],screenshots=[];
const read=name=>fs.readFileSync(path.join(source,'web',name),'utf8');
const calendar='https://www.googleapis.com/auth/calendar.readonly',youtube='https://www.googleapis.com/auth/youtube.readonly';
const reason=fs.readFileSync(path.join(source,'app/server.py'),'utf8').match(/'consent_denied': '([^']+)'/)[1];
const initial=()=>({google:{agreements:{accepted:[],version:'',country:''},agreement_options:agreementOptions,client_configured:true,client_source:'saved',client_id:'fixture.apps.googleusercontent.com',redirect_uri:'https://callback.fixture.invalid/api/google/callback',accounts:[{id:'fixture-account',email:'calendar-demo@example.invalid',status:'active',offline:true,scopes:['openid','email',calendar]}],calendar_binding:{accounts:['fixture-account']},bindings:[],music:{state:'unbound'},blocker:null}});
const agreementOptions={version:'google-2026-11',countries:['GB','US'],documents:[{id:'cloud_terms',title:'Google Cloud Terms of Service',url:'https://cloud.google.com/terms'},{id:'api_terms',title:'Google APIs Terms of Service',url:'https://developers.google.com/terms'},{id:'user_data_policy',title:'Google API Services User Data Policy',url:'https://developers.google.com/terms/api-services-user-data-policy'}]};
let fixture=initial(),connectMode='fixture',delay=0,bindDelay=0,bindError=false,stateError=false,agreementError=false;
fs.mkdirSync(out,{recursive:true});
function check(name,ok=true){assert(ok,name);checks.push({name,ok:true});console.log('PASS '+name);}
// QA-only bridge for standalone pages; production WizardApp and appearance transport
// are unchanged. Palettes are explicit fixture tokens, not live-shell skin proof.
const bridge=`window.WizardApp={ready(){},back:{register(x){window.__qaBack=x.back},push(fn){window.__qaOverlayBack=fn;return {release(){window.__qaOverlayBack=null}}}},update:{hold(){return {release(){}}}}};`;
const palettes={
 nebula:{scheme:'dark',skin:'nebula',tokens:{base:'#05030c',canvas:'#05030c',text:'#f3efff','text-secondary':'#b9b0d8','text-muted':'#a59abf',border:'rgba(205,190,255,.24)',surface:'rgba(243,239,255,.06)','surface-raised':'rgba(243,239,255,.10)',accent:'#b99bff','on-accent':'#160b32','accent-soft':'rgba(143,99,255,.16)',panel:'#191225',radius:'14px','radius-pill':'20px'}},
 light:{scheme:'light',skin:'signal',tokens:{base:'#faf8fd',canvas:'#faf8fd',text:'#1a1933','text-secondary':'#484560','text-muted':'#66617a',border:'#d4cfde',surface:'rgba(26,25,51,.04)','surface-raised':'rgba(26,25,51,.08)',accent:'#6844aa','on-accent':'#ffffff','accent-soft':'rgba(104,68,170,.10)',panel:'#faf8fd',radius:'2px','radius-pill':'2px'}}
};
async function skin(p,name){await p.evaluate(x=>{const h=document.documentElement;h.dataset.skin=x.skin;h.dataset.colorScheme=x.scheme;for(const [k,v]of Object.entries(x.tokens))h.style.setProperty('--wz-'+k,v);},palettes[name]);}
async function capture(p,name,label){
 await skin(p,name);await p.locator('main').waitFor();
 const fit=await p.evaluate(()=>({width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,scheme:document.documentElement.dataset.colorScheme}));
 check(label+' '+name+' fits viewport',!fit.overflow&&fit.width===p.viewportSize().width);
 const file=label+'-'+name+'.png';await p.screenshot({path:path.join(out,file),fullPage:true});screenshots.push(file);
}
const csp="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'";
async function routeHandler(route){
 const req=route.request(),u=new URL(req.url());
 if(u.origin!==origin){blocked.push(u.hostname);return route.abort();}
 const json=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
 if(u.pathname==='/wizard-os-home/core/app-client.js')return route.fulfill({contentType:'application/javascript',body:bridge});
 const rel=u.pathname.slice('/connected-accounts/'.length);
 if(!u.pathname.startsWith('/connected-accounts/')){blocked.push(u.pathname);return route.abort();}
 if(rel==='api/state')return stateError?json({error:'service_unavailable'},503):json(fixture);
 if(rel.startsWith('api/')&&req.method()!=='GET'){
  const data=req.postDataJSON();writes.push({path:rel,data});
  if(rel==='api/google/connect'){
   if(delay)await new Promise(r=>setTimeout(r,delay));
   if(connectMode==='error')return json({error:'broker_unavailable'},503);
   return json({authorization_url:connectMode==='unsafe'?'https://evil.invalid/':'https://accounts.google.com/o/oauth2/v2/auth?state=FIXTURE_ONLY'});
  }
  if(rel==='api/calendar/bind'){
   if(bindDelay)await new Promise(r=>setTimeout(r,bindDelay));
   if(bindError)return json({error:'fixture_write_failure'},503);
   const ids=new Set(fixture.google.calendar_binding.accounts);data.consent?ids.add(data.account):ids.delete(data.account);fixture.google.calendar_binding.accounts=[...ids];return json({ok:true});
  }
  if(rel==='api/google/agreements'){if(agreementError)return json({error:'fixture_storage_failure'},503);fixture.google.agreements={accepted:data.agreements,version:data.version,country:data.country};return json(fixture.google.agreements);}
  if(rel==='api/google/client')return json({error:'local_storage_unavailable'},503);
  if(rel==='api/google/disconnect'){fixture.google.accounts=fixture.google.accounts.filter(a=>a.id!==data.account);return json({ok:true});}
  if(rel==='api/music/bind'){fixture.google.bindings=[{account:data.account}];return json({ok:true});}
  if(rel==='api/music/unlink'){fixture.google.bindings=[];return json({ok:true});}
  if(rel==='api/music/catalog')return json({items:[{title:'Fixture song'}]});
  throw Error('Unexpected fixture write: '+rel);
 }
 const files={'':'index.html','app.js':'app.js','boot.js':'boot.js','styles.css':'styles.css','wizard-ui.css':'wizard-ui.css','privacy':'privacy.html','google-callback.js':'google-callback.js','api/google/connected':'google-connected.html','api/google/error':'google-error.html'};
 if(files[rel]){
  const file=files[rel],body=read(file).replace('{{REASON}}',reason);
  return route.fulfill({headers:{'Content-Security-Policy':csp},contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html',body});
 }
 blocked.push(rel);return route.abort();
}
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.QA_CHROME?{executablePath:process.env.QA_CHROME}:{}),args:['--no-sandbox']});
 try{
  const ctx=await browser.newContext({...devices['Pixel 5'],viewport:{width:390,height:844},permissions:['clipboard-read','clipboard-write']});await ctx.route('**/*',routeHandler);
  const p=await ctx.newPage();p.on('pageerror',e=>errors.push(e.message));
  const open=async()=>{await p.goto(base);await p.getByText('calendar-demo@example.invalid · Calendar on',{exact:true}).waitFor();};
  await open();check('standalone fallback is dark',await p.locator('html').getAttribute('data-color-scheme')==='dark');
  check('one provider card, no duplicate settings or practice card',await p.locator('#navigation button').count()===1&&!(await p.locator('#navigation').innerText()).match(/Practice|Try it out|Manage Google/));
  for(const name of Object.keys(palettes))await capture(p,name,'home-connected');
  await p.locator('#google-row').click();await p.locator('.google-status-pill').getByText('Connected',{exact:true}).waitFor();
  check('active account is healthy, no contradictory status',!(await p.locator('#detail').innerText()).includes('needs attention'));
  check('one email card, Calendar on, More collapsed',await p.locator('.google-account').count()===1&&await p.getByRole('switch').getAttribute('aria-checked')==='true'&&await p.locator('details[open]').count()===0);
  check('one-time setup comes after accounts',await p.evaluate(()=>!!(document.querySelector('.google-connect').compareDocumentPosition(document.querySelector('.google-app-row'))&Node.DOCUMENT_POSITION_FOLLOWING)));
  const identity=await p.evaluate(()=>window.__qaId=crypto.randomUUID());
  for(const name of Object.keys(palettes)){await capture(p,name,'google-calendar-on');check('skin switch keeps account document',await p.evaluate(()=>window.__qaId)===identity);}
  // Slow write: same-task state, disabled control, then readback and reusable switch.
  bindDelay=5000;await p.getByRole('switch').evaluate(e=>{e.click();if(e.getAttribute('aria-checked')!=='false'||e.getAttribute('aria-busy')!=='true'||!e.disabled)throw Error('no immediate feedback');});
  check('five-second write paints switch immediately');await p.locator('[role="switch"][aria-checked="false"]:not([aria-busy])').waitFor({timeout:10000});
  assert.equal(await p.getByRole('switch').getAttribute('aria-checked'),'false');check('switch reconciles after readback',await p.getByRole('switch').isEnabled());bindDelay=0;
  let before=writes.length;p.once('dialog',d=>d.dismiss());await p.getByRole('switch').click();check('Calendar enable needs consent',writes.length===before);
  p.once('dialog',d=>d.accept());await p.getByRole('switch').click();await p.locator('[role="switch"][aria-checked="true"]:not([aria-busy])').waitFor();
  bindError=true;await p.getByRole('switch').click();await p.getByRole('heading',{name:'Could not update Calendar',exact:true}).waitFor();check('failed switch rolls back',await p.getByRole('switch').getAttribute('aria-checked')==='true');await p.locator('#dialog-close').click();bindError=false;
  stateError=true;await p.getByRole('button',{name:'Check accounts',exact:true}).click();await p.getByRole('heading',{name:'Could not check accounts',exact:true}).waitFor();await p.locator('#dialog-close').click();stateError=false;
  fixture.google.accounts[0].status='reauth_required';await p.getByRole('button',{name:'Check accounts',exact:true}).click();await p.locator('.google-status-pill').getByText('Sign in again',{exact:true}).waitFor();check('reauthentication has plain status');fixture.google.accounts[0].status='active';
  fixture.google.accounts[0].scopes=['openid','email'];await p.getByRole('button',{name:'Check accounts',exact:true}).click();await p.getByRole('button',{name:'Allow Calendar',exact:true}).waitFor();check('missing Calendar permission has Allow, not a switch',await p.getByRole('switch').count()===0);
  await p.getByRole('button',{name:'Allow Calendar',exact:true}).click();await p.getByRole('heading',{name:'Finish signing in',exact:true}).waitFor();assert.deepEqual(writes.at(-1).data,{account:'fixture-account',youtube:false,calendar:true});check('Allow requests permission but does not grant app use');
  await p.getByRole('button',{name:'Cancel sign-in',exact:true}).click();
  // Disconnect stays behind More and requires an explicit confirmation.
  await p.locator('.google-account > details > summary').click();before=writes.length;p.once('dialog',d=>d.dismiss());await p.getByRole('button',{name:'Disconnect',exact:true}).click();check('Disconnect cancellation sends no write',writes.length===before);
  await p.getByRole('button',{name:'← Back',exact:true}).click();check('Back stays inside app home',await p.locator('#google-row').isVisible());
  // Adding an account keeps the existing safe popup/return workflow.
  await p.locator('#google-row').click();delay=5000;connectMode='error';await p.getByRole('button',{name:'Add another Google account',exact:true}).click();await p.getByRole('button',{name:'Opening Google…',exact:true}).waitFor({timeout:800});before=writes.length;await p.evaluate(()=>authorize());check('duplicate sign-in fenced while pending',writes.length===before);await p.getByRole('heading',{name:'Couldn’t start Google sign-in',exact:true}).waitFor({timeout:10000});check('sign-in failure offers retry',await p.getByRole('button',{name:'Try again',exact:true}).isVisible());await p.getByRole('button',{name:'Back to accounts',exact:true}).click();
  delay=0;connectMode='unsafe';await p.getByRole('button',{name:'Add another Google account',exact:true}).click();await p.getByText('Google did not return a safe sign-in link.',{exact:false}).waitFor();check('unsafe provider destination rejected');await p.getByRole('button',{name:'Back to accounts',exact:true}).click();
  delay=1200;connectMode='fixture';await p.getByRole('button',{name:'Add another Google account',exact:true}).click();await p.getByRole('button',{name:'Cancel',exact:true}).click();await p.waitForTimeout(1400);check('cancel fences late provider response',await p.locator('.google-continue').count()===0);
  delay=0;await p.evaluate(()=>{window.open=()=>null;});await p.getByRole('button',{name:'Add another Google account',exact:true}).click();await p.getByRole('link',{name:'Continue to Google',exact:true}).waitFor();check('blocked popup offers safe recovery',new URL(await p.locator('.google-continue').getAttribute('href')).origin==='https://accounts.google.com');
  fixture.google.accounts.push({id:'fixture-second',email:'second@example.invalid',status:'active',offline:true,scopes:['openid','email',calendar]});await p.evaluate(()=>window.dispatchEvent(new Event('focus')));await p.getByRole('heading',{name:'second@example.invalid',exact:true}).waitFor();check('return focus refreshes automatically');
  fixture=initial();await p.getByRole('button',{name:'Check accounts',exact:true}).click();await p.getByRole('button',{name:'Change',exact:true}).click();await p.getByLabel('Client ID',{exact:true}).fill('fixture.apps.googleusercontent.com');await p.getByLabel('Client secret',{exact:true}).fill('FIXTURE_ONLY_NOT_A_SECRET');
  check('credential step cannot bypass Save',await p.getByRole('button',{name:'Next',exact:true}).count()===0);await p.getByRole('button',{name:'Save Google app',exact:true}).click();await p.getByRole('heading',{name:'Could not save Google app',exact:true}).waitFor();await p.locator('#dialog-close').click();
  await skin(p,'nebula');check('skin switch preserves unsaved form',await p.getByLabel('Client ID',{exact:true}).inputValue()==='fixture.apps.googleusercontent.com');p.once('dialog',d=>d.dismiss());await p.getByRole('button',{name:'← Back',exact:true}).click();check('Back cancel preserves draft',await p.getByLabel('Client ID',{exact:true}).isVisible());p.once('dialog',d=>d.accept());await p.getByRole('button',{name:'← Back',exact:true}).click();
  fixture.google.client_configured=false;fixture.google.accounts=[];fixture.google.blocker='google_configuration_required';await p.goto(base);await p.locator('#google-row').click();await p.getByRole('button',{name:'Let your wizard set this up',exact:true}).click();
  await p.getByRole('heading',{name:'Before your wizard sets up Google',exact:true}).waitFor();
  const agree=p.getByRole('button',{name:'Agree and continue',exact:true}),country=p.getByLabel('Country',{exact:true});
  check('agreements start unticked and disabled',await p.locator('.google-agreements input:checked').count()===0&&await agree.isDisabled());
  check('three public agreement links',await p.locator('.google-agreement-row a[target="_blank"]').count()===3);
  check('checkbox rows have large touch targets',(await p.locator('.google-agreement-row label').evaluateAll(es=>es.every(e=>e.getBoundingClientRect().height>=44))));
  const agreementsDocument=await p.evaluate(()=>window.__agreementsId=crypto.randomUUID());
  for(const name of Object.keys(palettes)){await capture(p,name,'google-agreements');check('skin switch preserves agreements document',await p.evaluate(()=>window.__agreementsId)===agreementsDocument);}
  for(const c of await p.locator('.google-agreements input[type="checkbox"]').all())await c.check();
  await country.selectOption('');check('country required even with all boxes checked',await agree.isDisabled());await country.selectOption('GB');
  agreementError=true;await agree.click();await p.getByRole('heading',{name:'Could not save your agreements',exact:true}).waitFor();await p.locator('#dialog-close').click();check('save failure retains choices and does not start wizard',await p.locator('.google-agreements input:checked').count()===3&&await agree.isEnabled());agreementError=false;
  await agree.click();await p.getByRole('button',{name:'Copy message',exact:true}).waitFor();
  assert.deepEqual(writes.at(-1).data,{agreements:['cloud_terms','api_terms','user_data_policy'],version:'google-2026-11',country:'GB'});check('explicit agreement version country and ids saved before handoff');
  await p.evaluate(()=>window.__qaBack());await p.getByRole('heading',{name:'Before your wizard sets up Google',exact:true}).waitFor();check('shared Back returns to agreements without leaving app');await agree.click();
  await p.getByRole('button',{name:'Copy message',exact:true}).click();await p.locator('dialog[open]').waitFor();check('setup handoff message exact',await p.locator('pre').innerText()==='Set up my Google app');
  const box=await p.locator('dialog').boundingBox();await p.mouse.click(box.x+box.width/2,box.y-10);await p.locator('dialog[open]').waitFor({state:'detached'});check('outside tap closes dialog');
  await p.getByRole('button',{name:'Set it up myself',exact:true}).click();check('manual setup includes three agreement links',await p.locator('#detail a[href^="https://developers.google.com/terms"],#detail a[href="https://cloud.google.com/terms"]').count()===3);await p.evaluate(()=>window.__qaBack());await p.getByRole('button',{name:'Copy message',exact:true}).waitFor();check('manual Back returns to wizard handoff');await p.getByRole('button',{name:'Set it up myself',exact:true}).click();await p.locator('input[type="checkbox"]').check();await p.getByRole('button',{name:'Next',exact:true}).click();await p.getByText('2 of 7',{exact:true}).waitFor();await p.evaluate(()=>window.__qaBack());await p.getByText('1 of 7',{exact:true}).waitFor();check('nested Back steps once without leaving app');
  for(const [rel,label]of [['api/google/connected','google-connected'],['api/google/error','google-error']]){
   await p.goto(base+rel);await p.getByRole('heading').waitFor();check(label+' has instructions, no nonworking navigation',await p.locator('button,a').count()===0);
   if(label==='google-error')check('error reason replaced',await p.getByText(reason,{exact:true}).isVisible()&&!(await p.locator('main').innerText()).includes('{{REASON}}'));
   for(const name of Object.keys(palettes))await capture(p,name,label);
  }
  // Wide layout uses the same controls, with no desktop-only rail or outer cap.
  fixture=initial();await p.setViewportSize({width:1440,height:1000});await open();await p.locator('#google-row').click();for(const name of Object.keys(palettes))await capture(p,name,'desktop-google');
  check('wide app has no outer width cap',await p.locator('.wz-app').evaluate(e=>getComputedStyle(e).maxWidth)==='none');
  check('no browser exceptions',errors.length===0);check('all traffic fixture-only',blocked.every(h=>h==='accounts.google.com'));
  check('ten requested mobile screen/skin captures',screenshots.filter(x=>!x.startsWith('desktop-')).length===10);
  await ctx.close();
 }finally{
  await browser.close();fs.writeFileSync(path.join(out,'browser-receipt.json'),JSON.stringify({mode:'standalone-candidate-synthetic-api-and-skins',checks,errors,writes,blocked,screenshots,liveOwnerWrites:0},null,2)+'\n');
 }
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
