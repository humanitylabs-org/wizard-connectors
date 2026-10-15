// Real browser -> real HTTP/RPC/store, explicitly FAKE Google transport.
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE);
const base='http://127.0.0.1:19476',out=process.env.QA_ROOT;
fs.mkdirSync(out,{recursive:true});
const env=Object.fromEntries(fs.readFileSync(process.env.QA_ENV,'utf8').split('\n').filter(l=>l.includes('=')).map(l=>{let i=l.indexOf('=');return[l.slice(0,i),l.slice(i+1)]}));
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BINARY});const context=await browser.newContext({viewport:{width:390,height:844}});
const page=await context.newPage(),checks=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
const check=(n,b)=>{if(!b)throw Error(n);checks.push(n)};
async function complete(){const a=page.getByRole('link',{name:'Continue to Google'}).last();await a.waitFor();const url=new URL(await a.getAttribute('href'));check('real Google auth URL, not embedded credential form',url.origin==='https://accounts.google.com');const r=await context.request.get(base+'/api/google/callback?state='+encodeURIComponent(url.searchParams.get('state'))+'&code=FAKE_CODE');check('real callback with signed fake token',r.ok());await page.getByRole('button',{name:'Refresh accounts',exact:true}).click();}
try{
 await context.request.post(base+'/api/session',{data:{token:env.CONNECTORS_OWNER_TOKEN}});await page.goto(base);await page.locator('#google-row').click();
 await page.getByRole('button',{name:'Connect Google',exact:true}).click();await complete();
 await page.getByText('fixture@example.invalid',{exact:true}).waitFor();check('connected identity rendered from broker',true);
 await page.getByRole('button',{name:'Authorize YouTube catalog (read only)',exact:true}).click();await complete();
 await page.getByRole('button',{name:'Use this Google account for Music catalog',exact:true}).click();await page.getByText('Catalog account bound',{exact:true}).waitFor();
 check('binding persisted on actual backend',(await (await context.request.get(base+'/api/state')).json()).google.bindings.length===1);
 await page.reload();await page.locator('#google-row').click();await page.getByText('Catalog account bound',{exact:true}).waitFor();
 check('binding survives page reload',true);check('phone no overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:path.join(out,'phone-bound-fake-provider.png'),fullPage:true});
 await page.getByLabel('YouTube video ID').fill('W8VdVY8diqs');await page.getByRole('button',{name:'Look up catalog item',exact:true}).click();await page.locator('dialog[open]').waitFor();check('fake catalog explicitly not audio', (await page.locator('dialog').innerText()).includes('FAKE catalog fixture'));
 await page.goBack();check('Back closes overlay, app stays open',await page.locator('dialog[open]').count()===0&&page.url().startsWith(base));
 await page.getByRole('button',{name:'Unlink Music catalog',exact:true}).click();await page.getByText('Catalog account unbound',{exact:true}).waitFor();check('unlink preserves account',await page.getByText('fixture@example.invalid',{exact:true}).count()===1);
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'Disconnect Google account',exact:true}).click();await page.getByText('No Google account connected.',{exact:false}).waitFor();
 check('disconnect durable readback',(await (await context.request.get(base+'/api/state')).json()).google.accounts.length===0);
 await page.goBack();check('nested Back returns root',await page.locator('body').getAttribute('data-view')==='root');check('no exceptions',errors.length===0);
 fs.writeFileSync(path.join(out,'receipt.json'),JSON.stringify({provider:'FAKE Google transport; real HTTP/store/UI',checks,passed:checks.length,errors},null,2));console.log(JSON.stringify({passed:checks.length,checks,errors}));
}finally{await browser.close()}
