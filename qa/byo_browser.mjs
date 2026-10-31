// Native Thales Chrome. REAL UI/ingress/RPC/store, explicitly FAKE Google.
// Appearance is the labelled mock host with the REAL shared app-client, not an installed shell.
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE);
const base=process.env.QA_BASE||'http://127.0.0.1:19478',out=process.env.QA_ROOT;
fs.mkdirSync(out,{recursive:true});
let browser;
const checks=[],errors=[];
const check=(name,ok)=>{if(!ok)throw Error(name);checks.push(name);};
let revision=0;
async function skin(host,frame,name){
 const light=name==='signal';
 const tokens=Object.fromEntries(['canvas','base','chrome','overlay','panel','panel-raised','surface','surface-raised','text','text-secondary','text-muted','border','accent','accent-soft','on-accent','reader-surface'].map(k=>[k,k.startsWith('text')?(light?'#16221d':'#f3efff'):k==='accent'?(light?'#146648':'#b99bff'):k==='on-accent'?(light?'#ffffff':'#160b32'):k==='border'?(light?'#6f8c7e':'#706080'):(light?'#e6eee9':'#100d1c')]));
 const appearance={version:1,revision:++revision,presentation:'immersive',skin:name,colorScheme:light?'light':'dark',tokens};
 await host.evaluate(a=>{document.documentElement.style.background=a.tokens.base;document.documentElement.style.colorScheme=a.colorScheme;document.querySelector('iframe').contentWindow.postMessage({type:'wizard:appearance',appearance:a},location.origin);},appearance);
 await frame.locator('html').evaluate((el,name)=>new Promise((resolve,reject)=>{const end=Date.now()+5000;const test=()=>{if(el.dataset.skin===name)resolve();else if(Date.now()>end)reject(Error('theme did not arrive'));else requestAnimationFrame(test)};test();}),name);
}
async function shot(p,f,label){
 await f.locator('#detail').evaluate(e=>e.scrollIntoView({block:'start'}));
 check(label+' no overflow',await f.locator('html').evaluate(e=>e.scrollWidth<=innerWidth));
 await p.screenshot({path:path.join(out,'gsetup-'+label+'.png'),fullPage:true});
}
try{
 for(const phone of [true,false]){
  // Native macOS Chrome can terminate when its last emulated context closes.
  // Own a fresh process per viewport rather than reopening a dead browser.
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BINARY,args:['--disable-gpu']});
  const c=await browser.newContext(phone?{viewport:{width:390,height:844},isMobile:true,hasTouch:true,userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'}:{viewport:{width:1280,height:960}});
  check('owner session',(await c.request.post(base+'/api/session',{data:{token:'FAKE_OWNER_TOKEN_'.repeat(4)}})).ok());
  await c.request.delete(base+'/api/google/client');
  const p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));await p.goto(base+'/_qa/host');
  const f=p.frameLocator('iframe'),size=phone?'390':'1280';
  await f.locator('#google-row').click();
  check('correct mobile frame width',await f.locator('body').evaluate(()=>innerWidth)===(phone?390:1280));
  check('whose account plain explanation',(await f.locator('#detail').innerText()).includes('Your wizard does not need a Google account'));
  await f.getByRole('button',{name:'Let your wizard set this up',exact:true}).click();
  check('exact safe agent request',await f.locator('pre').innerText()==='Set up my Google app');
  await f.getByRole('button',{name:'Copy message',exact:true}).click();await f.locator('dialog[open]').waitFor();
  await p.evaluate(()=>window.__qaBack());check('Back closes copy overlay',await f.locator('dialog[open]').count()===0);
  for(const name of ['nebula','signal']){await skin(p,f,name);await shot(p,f,size+'-'+name+'-agent');}
  await p.evaluate(()=>window.__qaBack());
  await f.getByRole('button',{name:'Set it up myself',exact:true}).click();
  for(let step=1;step<=7;step++){
   await f.getByText(step+' of 7',{exact:true}).waitFor();
   if(step===6){
    check('step6 Next requires successful save',await f.getByRole('button',{name:'Next',exact:true}).isDisabled());
    await f.getByLabel('Client ID',{exact:true}).fill('malformed');await f.getByLabel('Client secret',{exact:true}).fill('short');
    check('malformed credentials cannot save',await f.getByRole('button',{name:'Save Google app',exact:true}).isDisabled());
    await f.getByLabel('Client ID',{exact:true}).fill('fake-browser.apps.googleusercontent.com');
    await f.getByLabel('Client secret',{exact:true}).fill('FAKE_BROWSER_CLIENT_SECRET');
    const identity=await f.locator('body').evaluate(()=>window.__qaIdentity=crypto.randomUUID());
    for(const name of ['nebula','signal']){await skin(p,f,name);check('draft survives live skin '+name,await f.getByLabel('Client secret',{exact:true}).inputValue()==='FAKE_BROWSER_CLIENT_SECRET'&&await f.locator('body').evaluate(()=>window.__qaIdentity)===identity);await shot(p,f,size+'-'+name+'-step6');}
    await f.getByRole('button',{name:'Save Google app',exact:true}).click();await f.getByText('Google app saved ✓',{exact:true}).waitFor();
    check('secret never read back',await f.getByLabel('Client secret',{exact:true}).inputValue()==='');
   }else{
    for(const name of ['nebula','signal']){await skin(p,f,name);await shot(p,f,size+'-'+name+'-step'+step);}
   }
   if(step<6){
    const next=f.getByRole('button',{name:'Next',exact:true});check('step '+step+' waits for owner confirmation',await next.isDisabled());
    if(step===2)await f.getByLabel('Project ID (optional)').fill('wizard-fixture-123');
    if(step===3)check('project-aware Calendar API deep link',(await f.getByRole('link',{name:'Open Google Calendar API'}).getAttribute('href')).includes('calendar-json.googleapis.com?project=wizard-fixture-123'));
    if(step===4)check('production and expected warning explained',(await f.locator('#detail').innerText()).includes('7-day logouts'));
    if(step===5){
     check('redirect presented only when needed',await f.getByLabel('Authorized redirect URI').inputValue()==='https://owner.example/wizard-connectors/api/google/callback');
     await f.getByRole('button',{name:'Copy redirect URI',exact:true}).click();await f.locator('dialog[open]').waitFor();
     for(const name of ['nebula','signal']){await skin(p,f,name);await shot(p,f,size+'-'+name+'-redirect-modal');}
     // Native dialog backdrop dismissal, not only its close button.
     await f.locator('dialog').evaluate(d=>{const r=d.getBoundingClientRect();d.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientX:r.left-2,clientY:r.top-2}));d.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:r.left-2,clientY:r.top-2}));});
     check('outside closes modal',await f.locator('dialog[open]').count()===0);
     await p.evaluate(()=>window.__qaBack());await f.getByText('4 of 7',{exact:true}).waitFor();
     check('nested shared Back stays in setup',true);await f.getByRole('button',{name:'Next',exact:true}).click();
    }
    await f.getByRole('checkbox').check();
   }
   if(step<7)await f.getByRole('button',{name:'Next',exact:true}).click();
  }
  async function complete(){const link=f.getByRole('link',{name:'Continue to Google'}).last();await link.waitFor();const url=new URL(await link.getAttribute('href'));check('fixed Google authorization endpoint',url.origin==='https://accounts.google.com');const tab=await c.newPage();check('real callback with FAKE signed token',(await tab.goto(base+'/api/google/callback?state='+encodeURIComponent(url.searchParams.get('state'))+'&code=FAKE_CODE')).ok());await tab.close();await f.getByRole('button',{name:'Refresh accounts',exact:true}).click();}
  await f.getByRole('button',{name:'Connect Google',exact:true}).click();await complete();
  // Existing accounts remain visible after client replacement, so use the new one.
  await f.getByRole('button',{name:'Let Calendar read this account',exact:true}).last().click();await complete();
  p.once('dialog',d=>d.accept());await f.getByRole('button',{name:'Allow Calendar to use this account',exact:true}).last().click();
  await f.getByRole('button',{name:'Stop Calendar using this account',exact:true}).waitFor();
  await f.getByRole('button',{name:'Authorize YouTube catalog (read only)',exact:true}).last().click();await complete();
  const state=await f.locator('body').evaluate(()=>fetch('./api/state').then(r=>r.json()));
  const a=state.google.accounts.at(-1);
  check('Calendar+YouTube incremental consent and binding',a.scopes.includes('https://www.googleapis.com/auth/calendar.readonly')&&a.scopes.includes('https://www.googleapis.com/auth/youtube.readonly')&&state.google.calendar_binding.accounts.includes(a.id));
  await f.getByRole('button',{name:'Connect Google',exact:true}).click();await complete();
  check('multiple Google accounts', (await f.locator('body').evaluate(()=>fetch('./api/state').then(r=>r.json()))).google.accounts.length>=2);
  await f.getByRole('button',{name:'Finish setup',exact:true}).click();await f.getByText('Google app: set up ✓',{exact:true}).waitFor();
  check('stepper collapses',await f.locator('.google-progress').count()===0);
  await f.getByRole('button',{name:'Change',exact:true}).click();await f.getByText('6 of 7',{exact:true}).waitFor();
  await p.evaluate(()=>window.__qaBack());await f.getByText('5 of 7',{exact:true}).waitFor();
  check('Change nested Back goes to previous step',true);
  for(let i=0;i<6;i++)await p.evaluate(()=>window.__qaBack());
  await f.locator('body[data-view="root"]').waitFor();check('root remains inside app',p.url().startsWith(base));
  await browser.close();
 }
 check('no browser exceptions',errors.length===0);
 const receipt={provider:'FAKE Google; real UI/ingress/RPC/store',appearance:'mock host with real WizardApp; NOT installed-shell or device proof',passed:checks.length,checks,errors};
 fs.writeFileSync(path.join(out,'browser-receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt,null,2));
}finally{await browser.close();}
