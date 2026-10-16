// Browser-only static substitution in the real shell: no installed files or backend settings changed.
import {createRequire} from 'node:module';import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';
const require=createRequire(process.env.PLAYWRIGHT_PACKAGE);const {chromium}=require('playwright');
const base=process.env.QA_BASE;assert(base,'QA_BASE is required');const root=path.resolve(import.meta.dirname,'..'),out=path.join(root,'evidence');fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BINARY});
const report={checks:[],screenshots:[],errors:[]};const check=(n,b)=>{assert(b,n);report.checks.push(n);};
async function shot(page,name){await page.screenshot({path:path.join(out,name+'.png')});report.screenshots.push(name+'.png');}
async function candidate(opts={}){
 const context=await browser.newContext(opts);const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
 await context.route('**/wizard-connectors/**',async r=>{const p=new URL(r.request().url()).pathname;if(p.includes('/api/'))return r.continue();
 const name=p.endsWith('/')?'index.html':p.split('/').pop();const file=path.join(root,'web',name);if(!['index.html','app.js','styles.css','wizard-ui.css','boot.js'].includes(name))return r.continue();
 await r.fulfill({status:200,contentType:name.endsWith('.html')?'text/html':name.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(file),headers:{'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'self'",'Cache-Control':'no-store'}});});
 await page.goto(base+'/wizard-os-home/?open=wizard-connectors');await page.locator('iframe[src*="wizard-connectors"]').waitFor({timeout:30000});await page.waitForTimeout(300);const frame=page.frames().find(f=>f.url().includes('/wizard-connectors/'));assert(frame,'real shell connector iframe');
 // Exercise deployment at the protected design subdirectory, not only the original app path.
 await frame.goto(base+'/wizard-connectors/design/');await frame.locator('#google-row').waitFor();await page.waitForTimeout(300);
 return {context,page,frame};}
const mobile={viewport:{width:390,height:844},isMobile:true,hasTouch:true,userAgent:'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36'};
try{
 const {context,page,frame:f}=await candidate(mobile);
 check('shared core hosted',await f.evaluate(()=>WizardApp.hosted));check('no root history inflation',await f.evaluate(()=>history.length)<8);
 await shot(page,'candidate-phone-home');await f.locator('#google-row').click();
 check('calm setup pending',await f.getByText('Google sign-in isn’t set up yet',{exact:true}).isVisible());check('no dead-end Connect',await f.getByRole('button',{name:/Connect a Google/}).count()===0);await shot(page,'candidate-phone-google');
 await context.route('**/wizard-connectors/api/state',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'broker_unavailable'})}));
 await f.getByRole('button',{name:'Refresh status',exact:true}).click();await f.locator('dialog[open]').waitFor();
 const material=await f.locator('dialog').evaluate(e=>({bg:getComputedStyle(e).backgroundColor,width:e.getBoundingClientRect().width,viewport:innerWidth,occluded:e.matches(':modal')}));check('opaque modal material',!material.bg.includes('rgba')&&material.bg!=='transparent');check('modal fits and top layer',material.width<=material.viewport&&material.occluded);report.material=material;await shot(page,'candidate-phone-error-sheet');
 await page.goBack();await page.waitForTimeout(250);check('platform Back closes overlay first',await f.locator('dialog[open]').count()===0);check('overlay Back stays Google',await f.getByText('Google sign-in isn’t set up yet',{exact:true}).isVisible());
 await page.goBack();await page.waitForTimeout(250);check('platform Back nested to root',await f.locator('#google-row').isVisible());check('Back app remains open',page.url().includes('/wizard-os-home/'));
 await context.unroute('**/wizard-connectors/api/state');
 await f.locator('#thread-garden').click();await f.locator('.ca-msg').first().waitFor();await shot(page,'candidate-phone-fictional-thread');
 await f.getByRole('button',{name:'Summarize privately',exact:true}).click();await f.getByRole('heading',{name:'Private summary',exact:true}).waitFor({timeout:140000});
 check('actual private summary prose',await f.locator('.ca-prose').innerText().then(t=>t.length>100));check('actual summary source references',await f.locator('.ca-sources li').count()===8);check('fictional provenance',await f.getByText('Fictional sample',{exact:true}).isVisible());report.summaryText=await f.locator('.ca-prose').innerText();await shot(page,'candidate-phone-real-summary');
 await context.close();
 const desk=await candidate({viewport:{width:1440,height:960}});await shot(desk.page,'candidate-desktop-home');
 report.shellGlobals=await desk.page.evaluate(()=>Object.keys(window).filter(k=>/Skin|Theme|Appearance|AppServices/.test(k)));
 await desk.context.close();
 const light=await browser.newContext({viewport:{width:390,height:844},colorScheme:'light'});const tab=await light.newPage();tab.on('pageerror',e=>report.errors.push(e.message));
 await light.route('**/wizard-connectors/design/**',r=>{const p=new URL(r.request().url()).pathname;const name=p.endsWith('/')?'index.html':p.split('/').pop();return r.fulfill({status:200,contentType:name.endsWith('.html')?'text/html':name.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync(path.join(root,'web',name))})});
 await tab.goto(base+'/wizard-connectors/design/');await tab.locator('#google-row').click();check('standalone light fallback',await tab.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor)==='rgb(250, 248, 253)');await shot(tab,'candidate-standalone-light');
 await tab.goBack();await tab.waitForTimeout(200);check('standalone Back returns nested to root',await tab.locator('#google-row').isVisible());await tab.goBack();await tab.waitForTimeout(200);check('standalone first root Back stays',tab.url().includes('/wizard-connectors/design/'));check('root exit notice',await tab.getByText('Press back again to exit',{exact:true}).isVisible());await light.close();check('no browser JS errors',report.errors.length===0);
}finally{fs.writeFileSync(path.join(out,'native-report.json'),JSON.stringify(report,null,2));await browser.close();}
console.log(JSON.stringify(report,null,2));
