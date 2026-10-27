// Thales Chrome, real UI/ingress/RPC/store; explicitly FAKE provider transport.
// Hosted checks use a labelled mock Appearance host, NOT an installed shell.
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE);
const base=process.env.QA_BASE||'http://127.0.0.1:19478',out=process.env.QA_ROOT;
fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BINARY});
const context=await browser.newContext({viewport:{width:1280,height:960}});
const page=await context.newPage(),checks=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));
const check=(name,ok)=>{if(!ok)throw Error(name);checks.push(name);};
async function complete(){const link=page.getByRole('link',{name:'Continue to Google'}).last();await link.waitFor();const url=new URL(await link.getAttribute('href'));check('Google URL only; incremental scopes preserved',url.origin==='https://accounts.google.com'&&url.searchParams.get('include_granted_scopes')==='true');const tab=await context.newPage();const r=await tab.goto(base+'/api/google/callback?state='+encodeURIComponent(url.searchParams.get('state'))+'&code=FAKE_CODE');check('real callback accepts signed FAKE provider token',r.ok());await tab.close();await page.getByRole('button',{name:'Refresh accounts',exact:true}).click();}
let revision=0;
// Owner session cookie is Secure+Strict; read state through the real browser, not the API client.
const ownerState=()=>page.evaluate(()=>fetch('./api/state',{credentials:'same-origin'}).then(r=>r.json()));
async function skin(host,frame,name){
 const light=name==='signal';
 const tokens=Object.fromEntries(['canvas','base','chrome','overlay','surface','surface-raised','text','text-secondary','text-muted','border','accent','accent-soft','on-accent','reader-surface'].map(k=>[k,k.startsWith('text')?(light?'#16221d':'#f3efff'):k==='accent'?(light?'#146648':'#b99bff'):k==='on-accent'?(light?'#ffffff':'#160b32'):k==='border'?(light?'#6f8c7e':'#706080'):(light?'#e6eee9':'#100d1c')]));
 const appearance={version:1,revision:++revision,presentation:'immersive',skin:name,colorScheme:light?'light':'dark',tokens};
 await host.evaluate(a=>{document.documentElement.style.background=a.tokens.base;document.documentElement.style.colorScheme=a.colorScheme;document.querySelector('iframe').contentWindow.postMessage({type:'wizard:appearance',appearance:a},location.origin);},appearance);
 await frame.locator('html').evaluate((el,name)=>new Promise((resolve,reject)=>{const end=Date.now()+5000;const test=()=>{if(el.dataset.skin===name)resolve();else if(Date.now()>end)reject(Error('theme did not arrive'));else requestAnimationFrame(test)};test();}),name);
 check('Appearance '+name+' applied',await frame.locator('html').getAttribute('data-skin')===name);
}
try{
 check('owner session', (await context.request.post(base+'/api/session',{data:{token:'FAKE_OWNER_TOKEN_'.repeat(4)}})).ok());
 await page.goto(base);await page.locator('#google-row').click();
 await page.getByRole('heading',{name:'Your Google app'}).waitFor();
 check('guide includes production publish warning',(await page.locator('.google-guide').innerText()).includes('7 days'));
 check('exact HTTPS prefix suggestion',await page.getByLabel('Authorized redirect URI').inputValue()==='https://owner.example/wizard-connectors/api/google/callback');
 await page.getByLabel('Client ID',{exact:true}).fill('fake-browser.apps.googleusercontent.com');
 await page.getByLabel('Client secret (paste to save or replace)').fill('FAKE_BROWSER_CLIENT_SECRET');
 await page.getByRole('button',{name:'Save Google app',exact:true}).click();
 await page.getByText('Client configured · source: owner',{exact:true}).waitFor();
 check('client secret not read back',await page.getByLabel('Client secret (paste to save or replace)').inputValue()==='');
 await page.getByRole('button',{name:'Connect Google',exact:true}).click();await complete();
 await page.getByRole('button',{name:'Let Calendar read this account',exact:true}).click();await complete();
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Allow Calendar to use this account',exact:true}).click();
 await page.getByRole('button',{name:'Stop Calendar using this account',exact:true}).waitFor();
 await page.getByRole('button',{name:'Authorize YouTube catalog (read only)',exact:true}).click();await complete();
 const state=await ownerState();
 check('Calendar + YouTube union and binding survive incremental consent',state.google.accounts[0].scopes.includes('https://www.googleapis.com/auth/calendar.readonly')&&state.google.accounts[0].scopes.includes('https://www.googleapis.com/auth/youtube.readonly')&&state.google.calendar_binding.accounts.length===1);
 await page.getByRole('button',{name:'Connect Google',exact:true}).click();await complete();
 check('multiple accounts visible',(await ownerState()).google.accounts.length===2);
 const service=await context.request.post(base+'/service/calendar/events',{headers:{'X-Wizard-Grant':'FAKE_BROWSER_CALENDAR_GRANT'},data:{account:state.google.accounts[0].id,calendar_id:'primary@example.invalid',time_min:'2026-10-01T00:00:00Z',time_max:'2026-11-01T00:00:00Z'}});
 check('grant-checked service returns labelled FAKE event',service.ok()&&(await service.json()).events[0].title==='FAKE event');
 await page.getByRole('button',{name:'Stop Calendar using this account',exact:true}).click();
 await page.getByRole('button',{name:'Stop Calendar using this account',exact:true}).waitFor({state:'detached'});
 check('binding toggle persisted',(await ownerState()).google.calendar_binding.accounts.length===0);
 await page.screenshot({path:path.join(out,'desktop-owner-setup.png'),fullPage:true});
 await page.goBack();await page.locator('body[data-view="root"]').waitFor();check('nested browser Back returns root',true);
 await page.goBack();check('root browser Back remains in app',page.url().startsWith(base));
 // Mock host uses the REAL shared app-client.js. State is not intercepted.
 for(const phone of [false,true]){
  const c=await browser.newContext(phone?{viewport:{width:390,height:844},isMobile:true,hasTouch:true,userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'}:{viewport:{width:1280,height:960}});
  await c.request.post(base+'/api/session',{data:{token:'FAKE_OWNER_TOKEN_'.repeat(4)}});
  const p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto(base+'/_qa/host');
  const f=p.frameLocator('iframe');await f.locator('#google-row').click();
  await f.getByLabel('Client ID',{exact:true}).fill('unsaved-draft.apps.googleusercontent.com');
  const identity=await f.locator('body').evaluate(()=>window.__qaIdentity=crypto.randomUUID());
  await f.getByRole('button',{name:'Copy redirect URI',exact:true}).click();await f.locator('dialog[open]').waitFor();
  for(const name of ['nebula','signal']){
   await skin(p,f,name);
   check((phone?'phone':'desktop')+' draft and modal survive '+name,await f.getByLabel('Client ID',{exact:true}).inputValue()==='unsaved-draft.apps.googleusercontent.com'&&await f.locator('dialog[open]').count()===1&&await f.locator('body').evaluate(()=>window.__qaIdentity)===identity);
   {const o=await f.locator('html').evaluate(el=>({ok:el.scrollWidth<=innerWidth,sw:el.scrollWidth,w:innerWidth,off:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+0.5).slice(0,6).map(e=>e.tagName+'.'+e.className+' r='+Math.round(e.getBoundingClientRect().right))}));if(!o.ok)console.log('OVERFLOW',JSON.stringify(o));check((phone?'phone':'desktop')+' no overflow '+name,o.ok);}
   await p.screenshot({path:path.join(out,(phone?'phone':'desktop')+'-'+name+'-modal.png'),fullPage:true});
   await p.evaluate(()=>window.__qaBack());
   check('shared Back closes overlay '+name,await f.locator('dialog[open]').count()===0);
   await f.getByRole('heading',{name:'Your Google app'}).scrollIntoViewIfNeeded();
   await p.screenshot({path:path.join(out,(phone?'phone':'desktop')+'-'+name+'-setup.png'),fullPage:true});
   if(name==='nebula'){await f.getByRole('button',{name:'Copy redirect URI',exact:true}).click();await f.locator('dialog[open]').waitFor();}
  }
  p.once('dialog',d=>d.accept());await f.getByRole('button',{name:'← Back',exact:true}).click();
  await f.locator('body[data-view="root"]').waitFor();check('explicit Back discards confirmed draft and keeps app',true);
  await c.close();
 }
 check('no browser exceptions',errors.length===0);
 const receipt={provider:'FAKE transport; real ingress/UI/RPC/encrypted store',appearance:'mock same-origin Appearance host with real shared app-client; not live shell/device proof',passed:checks.length,checks,errors};
 fs.writeFileSync(path.join(out,'browser-receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt,null,2));
}finally{await browser.close();}
