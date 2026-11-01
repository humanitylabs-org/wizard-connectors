/* Run only on the queued forum worker. No Google navigation or owner-data writes. */
const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium,devices}=require('/srv/work/provider-signin-browser/node_modules/playwright');
const source=path.resolve(process.argv[2]||'.'),out=path.resolve(process.argv[3]||'evidence');
const liveOnly=process.argv.includes('--live');
const origin='https://wizard.tailc0f369.ts.net';
const checks=[],errors=[],requests=[];let mode='baseline',fixture=null,stateError=false,connectMode='real',delay=0,connectCalls=0,realStarts=0;
fs.mkdirSync(out,{recursive:true});
function check(name,ok,detail){checks.push({name,ok:!!ok,...(detail?{detail}: {})});console.log((ok?'PASS ':'FAIL ')+name,Math.round(performance.now()/1000)+'s');assert(ok,name);}
function read(name){return fs.readFileSync(path.join(source,'web',name));}
async function appFrame(page){const end=Date.now()+90000;let last;while(Date.now()<end){try{const loc=page.locator('iframe[src*="/connected-accounts/"]:visible').last();if(!await loc.count()){await page.waitForTimeout(3000);if(!await loc.count())await page.evaluate(()=>__wos.openApp({id:'connected-accounts',kind:'wizard',url:'/connected-accounts/',name:'Connected accounts'}));}await loc.waitFor({timeout:20000});const fr=await (await loc.elementHandle()).contentFrame();if(fr){await fr.waitForSelector('#google-row',{timeout:15000});await page.waitForTimeout(500);if(!fr.isDetached())return fr;}}catch(e){last=e;}await page.waitForTimeout(500);}/* shell may swap the iframe while opening; retry on detach */await page.screenshot({path:path.join(out,'frame-failure.png')}).catch(()=>{});throw last||new Error('connected accounts frame');}
(async()=>{const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const ctx=await browser.newContext({...devices['Pixel 5'],viewport:{width:390,height:844},permissions:['clipboard-read','clipboard-write']});
 const routeHandler=async route=>{const req=route.request(),u=new URL(req.url());
  if(!['https:', 'about:'].includes(u.protocol)||u.hostname!==new URL(origin).hostname){requests.push({blocked:u.hostname});return route.abort();}
  const prefix=u.pathname.startsWith('/connected-accounts/')?'/connected-accounts/':u.pathname.startsWith('/wizard-connectors/')?'/wizard-connectors/':null;
  if(!prefix)return route.continue();const rel=u.pathname.slice(prefix.length);
  if(rel.startsWith('api/')&&req.method()!=='GET'){
   if(fixture&&rel==='api/google/client')return route.fulfill({status:503,contentType:'application/json',body:'{"error":"local_storage_unavailable"}'});
   if(fixture&&rel==='api/calendar/bind'){const d=req.postDataJSON();fixture.google.calendar_binding={accounts:d.consent?[d.account]:[]};return route.fulfill({contentType:'application/json',body:'{"ok":true}'});}
   if(rel==='api/google/connect'){
    connectCalls++;const payload=req.postDataJSON();check('connect asks read-only Calendar without granting service use',payload.calendar===true&&payload.youtube===false&&payload.account===null);
    if(delay)await new Promise(r=>setTimeout(r,delay));
    if(connectMode==='real'){realStarts++;check('at most one real broker start, no provider call',realStarts===1);return route.continue();}
    if(connectMode==='error')return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'broker_unavailable'})});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({authorization_url:connectMode==='unsafe'?'https://evil.invalid/':'https://accounts.google.com/o/oauth2/v2/auth?state=FIXTURE_ONLY'})});
   }
   requests.push({blockedWrite:rel});return route.fulfill({status:403,contentType:'application/json',body:'{"error":"qa_write_fence"}'});
  }
  if(stateError&&rel==='api/state')return route.fulfill({status:503,contentType:'application/json',body:'{"error":"service_unavailable"}'});
  if(fixture&&rel==='api/state')return route.fulfill({contentType:'application/json',body:JSON.stringify(fixture)});
  if(mode==='candidate'&&!liveOnly){
   const files={'':'index.html','app.js':'app.js','boot.js':'boot.js','styles.css':'styles.css','wizard-ui.css':'wizard-ui.css','privacy':'privacy.html','google-callback.js':'google-callback.js'};
   if(files[rel])return route.fulfill({contentType:rel.endsWith('.js')?'application/javascript':rel.endsWith('.css')?'text/css':'text/html',body:read(files[rel])});
  }
  return route.continue();
 };
 await ctx.route('**/*',routeHandler);
 const p=await ctx.newPage();p.on('pageerror',e=>errors.push(e.message));
 await p.goto(origin+'/wizard-os-home/?shell=phone',{waitUntil:'domcontentloaded'});
 await p.waitForFunction(()=>window.__wos&&window.WosSkin,{timeout:90000});
 check('actual phone shell',await p.evaluate(()=>document.documentElement.dataset.shell==='phone'));
 await p.evaluate(()=>__wos.openApp({id:'connected-accounts',kind:'wizard',url:'/connected-accounts/',name:'Connected accounts'}));
 // Frame URL can still be about:blank when the iframe element appears; take the element's own frame.
 let f=await appFrame(p);
 const originalSkin=await p.evaluate(()=>WosSkin.get?.()||null);
 async function settle(){await p.evaluate(async()=>{await Promise.all(document.getAnimations().filter(a=>Number.isFinite(a.effect?.getTiming().iterations)&&a.playState==='running').map(a=>a.finished.catch(()=>{})));});await p.waitForTimeout(650);}
 const tokens={};let identity=null;
 async function shot(skin,label){await p.evaluate(x=>WosSkin.set(x),skin);await settle();
  const v=await f.evaluate(()=>({id:window.__googleQAId||(window.__googleQAId=crypto.randomUUID()),skin:document.documentElement.dataset.skin,base:getComputedStyle(document.documentElement).getPropertyValue('--wz-base').trim(),ink:getComputedStyle(document.body).color,width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth}));
  check(label+' '+skin+' is hosted, phone width, no horizontal overflow',v.width===390&&!v.overflow&&!!v.base,v);
  tokens[skin]=v.base+'|'+v.ink;if(identity)check(label+' keeps document on live skin switch',v.id===identity);else identity=v.id;
  await p.screenshot({path:path.join(out,label+'-'+skin+'.png')});
 }
 async function pair(label){for(const skin of ['nebula','signal'])await shot(skin,label);check(label+' live skin colours change',tokens.nebula!==tokens.signal,tokens);}
 if(!liveOnly){await pair('before-root-live');await f.click('#google-row');await f.getByRole('button',{name:'Connect Google',exact:true}).waitFor();await pair('before-google-live');}
 mode='candidate';identity=null;await f.goto(origin+'/connected-accounts/');await f.waitForSelector('#google-row');
 check('root gives direct next action',await f.getByRole('button',{name:'Connect your Google account',exact:true}).isVisible());check('Try it out retains Practice a private summary',await f.getByRole('button',{name:/Practice a private summary/}).isVisible()&&await f.getByText('Try it out',{exact:true}).isVisible());await pair((liveOnly?'live':'candidate')+'-root');
 await f.getByRole('button',{name:'Manage Google settings',exact:true}).click();
 check('clear two sections',await f.getByRole('heading',{name:'Your Google app',exact:true}).isVisible()&&await f.getByRole('heading',{name:'Your Google accounts',exact:true}).isVisible());
 check('technical extras collapsed',await f.locator('details[open]').count()===0);await pair((liveOnly?'live':'candidate')+'-google-empty');
 stateError=true;await f.getByRole('button',{name:'Check accounts',exact:true}).click();await f.getByRole('heading',{name:'Could not check accounts',exact:true}).waitFor();stateError=false;await f.locator('#dialog-close').click();
 // Real broker creates a URL only. Every request to accounts.google.com is aborted before network.
 const before=connectCalls;await f.getByRole('button',{name:'← Back',exact:true}).click();await f.getByRole('button',{name:'Connect your Google account',exact:true}).click();
 await f.getByRole('heading',{name:'Finish signing in',exact:true}).waitFor({timeout:20000});
 check('real broker start once',connectCalls===before+1&&realStarts===1);await p.waitForTimeout(150);check('one tap navigates its popup to Google before network fence',requests.some(x=>x.blocked==='accounts.google.com'));
 const link=await f.locator('.google-continue').getAttribute('href');check('real generated Google link is usable without exposing it',new URL(link).origin==='https://accounts.google.com');
 await pair((liveOnly?'live':'candidate')+'-waiting-real-broker');
 await f.getByRole('button',{name:'Cancel sign-in',exact:true}).click();
 // Fixture-only failure and throttled-backend proof. Live state and permissions remain untouched.
 connectMode='error';delay=5000;const t=Date.now();await f.getByRole('button',{name:'Connect a Google account',exact:true}).click();
 await f.getByRole('button',{name:'Opening Google…',exact:true}).waitFor({timeout:800});const pendingCount=connectCalls;await f.evaluate(()=>authorize());check('duplicate taps cannot create two sign-in requests',connectCalls===pendingCount);
 check('five-second backend still paints immediate disabled feedback',Date.now()-t<1000&&await f.getByRole('button',{name:'Opening Google…',exact:true}).isDisabled());
 await pair('fixture-pending');await f.getByRole('heading',{name:'Couldn’t start Google sign-in',exact:true}).waitFor({timeout:10000});
 check('plain actionable failure',await f.getByRole('button',{name:'Try again',exact:true}).isVisible()&&!(await f.locator('#detail').innerText()).includes('broker_unavailable'));await pair('fixture-error');
 await f.getByRole('button',{name:'Back to accounts',exact:true}).click();
 connectMode='unsafe';delay=0;await f.getByRole('button',{name:'Connect a Google account',exact:true}).click();await f.getByRole('heading',{name:'Couldn’t start Google sign-in',exact:true}).waitFor();check('unsafe destination is rejected before navigation',await f.getByText('Google did not return a safe sign-in link.',{exact:false}).isVisible());await f.getByRole('button',{name:'Back to accounts',exact:true}).click();
 connectMode='fixture';delay=1500;await f.getByRole('button',{name:'Connect a Google account',exact:true}).click();await f.getByRole('button',{name:'Cancel',exact:true}).click();await p.waitForTimeout(1800);check('cancel fences late response and keeps account screen',await f.getByRole('heading',{name:'Your Google accounts',exact:true}).isVisible()&&await f.locator('.google-continue').count()===0);
 connectMode='fixture';delay=0;await f.evaluate(()=>{window.__realOpen=window.open;window.open=()=>null;});await f.getByRole('button',{name:'Connect a Google account',exact:true}).click();
 await f.getByRole('link',{name:'Continue to Google',exact:true}).waitFor();check('popup-blocked recovery stays inside viewport',await f.locator('.google-continue').evaluate(e=>{const r=e.getBoundingClientRect();return r.top>=0&&r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;}));check('popup-blocked browser keeps a visible recovery action',await f.getByText('Your browser kept the sign-in window closed.',{exact:false}).isVisible());await pair('fixture-popup-blocked');
 // Returning account is synthetic: fake scope, no Calendar binding, never writes to the owner broker.
 const liveState=await f.evaluate(async()=>await (await fetch('api/state')).json());fixture=structuredClone(liveState);fixture.google.accounts=[{id:'fixture-account',email:'calendar-demo@example.invalid',status:'connected',offline:true,scopes:['openid','email','https://www.googleapis.com/auth/calendar.readonly']}];fixture.google.state='connected';fixture.google.client_source='saved';fixture.google.calendar_binding={accounts:[]};
 await f.evaluate(()=>window.dispatchEvent(new Event('focus')));await f.getByRole('heading',{name:'calendar-demo@example.invalid',exact:true}).waitFor({timeout:10000});
 check('focus refresh shows account automatically with no Calendar binding',await f.getByRole('button',{name:'Show this account’s calendar in Calendar',exact:true}).isVisible());await pair('fixture-connected');
 p.once('dialog',d=>d.accept());await f.getByRole('button',{name:'Show this account’s calendar in Calendar',exact:true}).click();await f.getByRole('button',{name:'Stop showing this account in Calendar',exact:true}).waitFor();await f.getByRole('button',{name:'Stop showing this account in Calendar',exact:true}).click();await f.getByRole('button',{name:'Show this account’s calendar in Calendar',exact:true}).waitFor();
 await f.getByRole('button',{name:'Change',exact:true}).click();await f.getByLabel('Client ID',{exact:true}).fill('fixture.apps.googleusercontent.com');await f.getByLabel('Client secret',{exact:true}).fill('FIXTURE_ONLY_NOT_A_SECRET');
 check('credential step cannot bypass Save with Next',await f.getByRole('button',{name:'Next',exact:true}).count()===0);
 await f.getByRole('button',{name:'Save Google app',exact:true}).click();await f.getByRole('heading',{name:'Could not save Google app',exact:true}).waitFor();check('failed save leaves typed credentials and draft intact',await f.getByLabel('Client ID',{exact:true}).inputValue()==='fixture.apps.googleusercontent.com');await f.locator('#dialog-close').click();
 await p.evaluate(()=>WosSkin.set('nebula'));await settle();check('live skin switch preserves unsaved input',await f.getByLabel('Client ID',{exact:true}).inputValue()==='fixture.apps.googleusercontent.com');
 // Blank out synthetic secret before evidence. Back cancel preserves input; accepted discard never submits it.
 p.once('dialog',d=>{check('Discard unsaved Google app configuration? guard remains',d.message()==='Discard unsaved Google app configuration?');d.dismiss();});await f.getByRole('button',{name:'← Back',exact:true}).click();check('Back cancel preserves draft',await f.getByLabel('Client ID',{exact:true}).inputValue()==='fixture.apps.googleusercontent.com');p.once('dialog',d=>d.accept());await f.getByRole('button',{name:'← Back',exact:true}).click();
 // New unconfigured fixture proves setup and copy without Google Cloud interaction.
 fixture=structuredClone(liveState);fixture.google.client_configured=false;fixture.google.client_source=null;fixture.google.accounts=[];fixture.google.blocker='google_configuration_required';identity=null;await f.goto(origin+'/connected-accounts/');await f.click('#google-row');await pair('fixture-not-configured');
 await f.getByRole('button',{name:'Let your wizard set this up',exact:true}).click();check('handoff message exact',await f.locator('pre').innerText()==='Set up my Google app');await f.getByRole('button',{name:'Copy message',exact:true}).click();await f.locator('dialog[open]').waitFor();check('copy succeeds',await f.evaluate(async()=>await navigator.clipboard.readText())==='Set up my Google app');await pair('fixture-copy-modal');
 const box=await f.locator('dialog').boundingBox();await p.mouse.click(box.x+box.width/2,box.y-12);await f.locator('dialog[open]').waitFor({state:'detached'});
 await p.evaluate(()=>__wosNativeBack());await f.getByRole('button',{name:'Set it up myself',exact:true}).click();check('manual guide has real Next',await f.getByRole('button',{name:'Next',exact:true}).isDisabled());await f.locator('input[type="checkbox"]').check();await f.getByRole('button',{name:'Next',exact:true}).click();check('manual guide advances',await f.getByText('2 of 7',{exact:false}).isVisible());
 await p.evaluate(()=>__wosNativeBack());check('native Back stays in nested guide',await f.getByText('1 of 7',{exact:false}).isVisible());
 check('no page exceptions',errors.length===0,errors);check('no unintended owner writes',!requests.some(x=>x.blockedWrite),requests.filter(x=>x.blockedWrite));
 check('Google requests fenced before network',requests.every(x=>!x.blocked||x.blocked==='accounts.google.com'||x.blocked.endsWith('.invalid')),requests);
 // The shell's skin is browser-local; leave the QA browser in its first skin where possible.
 if(typeof originalSkin==='string')await p.evaluate(x=>WosSkin.set(x),originalSkin);
 await ctx.close();
 fixture=null;delay=0;
 const dc=await browser.newContext({viewport:{width:1440,height:1000},colorScheme:'dark'});await dc.route('**/*',routeHandler);
 for(const pass of (liveOnly?['candidate']:['baseline','candidate'])){
  mode=pass;const d=await dc.newPage();d.on('pageerror',e=>errors.push(e.message));await d.goto(origin+'/wizard-os-home/?shell=desktop',{waitUntil:'domcontentloaded'});await d.waitForFunction(()=>window.__wos&&window.WosSkin,{timeout:90000});check('actual desktop shell',await d.evaluate(()=>document.documentElement.dataset.shell==='desktop'));
  await d.evaluate(()=>__wos.openApp({id:'connected-accounts',kind:'wizard',url:'/connected-accounts/',name:'Connected accounts'}));const df=await appFrame(d);const full=d.getByRole('button',{name:'Full screen',exact:true});if(await full.count())await full.last().click();await d.waitForTimeout(900);
  const bodyId=await df.evaluate(()=>window.__desktopQA=crypto.randomUUID());
  for(const screen of ['root','google']){
   if(screen==='google')await df.click(pass==='baseline'?'#google-row':'#google-manage');
   const paints=[];for(const skin of ['nebula','signal']){await d.evaluate(x=>WosSkin.set(x),skin);await d.waitForTimeout(900);const v=await df.evaluate(()=>({id:window.__desktopQA,w:innerWidth,max:getComputedStyle(document.querySelector('.wz-app')).maxWidth,overflow:document.documentElement.scrollWidth>innerWidth,ink:getComputedStyle(document.body).color}));paints.push(v.ink);check('desktop '+pass+' '+screen+' '+skin+' keeps frame and fits',v.id===bodyId&&v.w>900&&!v.overflow,v);if(pass==='candidate')check('desktop app has no narrow outer cap',v.max==='none');await d.screenshot({path:path.join(out,(pass==='baseline'?'before':liveOnly?'live':'candidate')+'-desktop-'+screen+'-'+skin+'.png')});}check('desktop live skin switch recolours',paints[0]!==paints[1]);
  }await d.close();
 }
 mode='candidate';const standalone=await dc.newPage();await standalone.goto(origin+'/connected-accounts/');await standalone.locator('#google-row').waitFor();check('standalone defaults dark',await standalone.evaluate(()=>document.documentElement.dataset.colorScheme==='dark'));await standalone.screenshot({path:path.join(out,(liveOnly?'live':'candidate')+'-standalone-dark.png')});await dc.close();
 check('all captures have no page exceptions',errors.length===0,errors);
}finally{await browser.close();fs.writeFileSync(path.join(out,'browser-receipt.json'),JSON.stringify({mode:liveOnly?'exact-live':'candidate-static-in-real-shell',checks,errors,realStarts,connectCalls,blocked:requests},null,2));}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
