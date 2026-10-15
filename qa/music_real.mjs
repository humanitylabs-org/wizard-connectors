// Isolated, uncached real YouTube Music proof using a pinned existing Music revision.
// No Google/browser credentials, owner library or live Music data are mounted.
import {spawn} from 'node:child_process';
import {createServer,request} from 'node:http';
import {createRequire} from 'node:module';
import {randomBytes} from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=process.env.MUSIC_SOURCE, out=process.env.QA_ROOT, data=path.join(out,'data');
fs.mkdirSync(data,{recursive:true});
const audioFiles=()=>fs.existsSync(path.join(data,'cache'))?fs.readdirSync(path.join(data,'cache')).filter(n=>/\.(m4a|mp3|webm|opus|wav|flac)$/.test(n)):[];
if(audioFiles().length)throw Error('fresh-cache proof requires an empty audio cache');
const env={...process.env,WIZARD_MUSIC_HUB_HOME:data,WIZARD_MUSIC_CACHE:path.join(data,'cache'),WIZARD_MUSIC_LIBRARY:path.join(data,'empty-library'),WIZARD_MUSIC_ONLINE:'1',WIZARD_MUSIC_YTDLP:process.env.YTDLP,WIZARD_MUSIC_HUB_HOST:'127.0.0.1',WIZARD_MUSIC_HUB_PORT:'19480',WIZARD_MUSIC_APP_PORT:'19481',WIZARD_MUSIC_HUB_ORIGIN:'http://127.0.0.1:19480',WIZARD_MUSIC_HUB_TOKEN:randomBytes(32).toString('hex'),WIZARD_TRUSTED_ORIGINS:'http://127.0.0.1:19482'};
const log=fs.openSync(path.join(out,'runtime.log'),'w');
const hub=spawn(process.env.MUSIC_PYTHON,[path.join(root,'hub/hub.py')],{env,cwd:root,stdio:['ignore',log,log]});
const app=spawn(process.execPath,[path.join(root,'server/index.mjs')],{env,cwd:root,stdio:['ignore',log,log]});
const proxy=createServer((req,res)=>{
 if(['/wizard-os-home/core/app-client.js','/wizard-os-home/core/app-capture.js'].includes(req.url)){const b=fs.readFileSync(path.join(process.env.CORE_DIR,path.basename(req.url)));res.writeHead(200,{'Content-Type':'text/javascript'});res.end(b);return;}
 const up=request({hostname:'127.0.0.1',port:19481,path:req.url,method:req.method,headers:req.headers},r=>{res.writeHead(r.statusCode,r.headers);r.pipe(res)});up.on('error',()=>{res.writeHead(502);res.end()});req.pipe(up);
});
await new Promise(r=>proxy.listen(19482,'127.0.0.1',r));
let browser;
try{
 let healthy=false;for(let i=0;i<50;i++){try{healthy=(await fetch('http://127.0.0.1:19481/health')).ok;if(healthy)break;}catch{}await new Promise(r=>setTimeout(r,100));}if(!healthy)throw Error('Music source did not start');
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_BINARY,args:['--autoplay-policy=no-user-gesture-required']});
 const page=await browser.newPage({viewport:{width:390,height:844}}),errors=[],responses=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.url().includes('/stream/'))responses.push({status:r.status(),url:new URL(r.url()).pathname,contentType:r.headers()['content-type']});});
 await page.addInitScript(()=>{const RealAudio=window.Audio;window.Audio=class extends RealAudio{constructor(...args){super(...args);window.__qaAudio=this;}}});
 await page.goto('http://127.0.0.1:19482/wizard-music/');
 const search=page.getByRole('searchbox',{name:'Search music'});await search.fill('Tycho Awake');await search.press('Enter');
 await page.locator('.music-results .music-row').first().waitFor({timeout:45000});
 const cachedBefore=audioFiles();
 if(cachedBefore.length)throw Error('cache unexpectedly populated before playback');
 await page.locator('.music-results .music-row').filter({has:page.locator('img[src*="W8VdVY8diqs"]')}).locator('.music-row-main').click();
 await page.waitForFunction(()=>window.__qaAudio&&!window.__qaAudio.paused&&window.__qaAudio.currentTime>5,{},{timeout:150000});
 const audio=await page.evaluate(()=>({time:window.__qaAudio.currentTime,duration:window.__qaAudio.duration,readyState:window.__qaAudio.readyState,paused:window.__qaAudio.paused,currentSrc:window.__qaAudio.currentSrc,decodedBytes:window.__qaAudio.webkitAudioDecodedByteCount||null}));
 await page.screenshot({path:path.join(out,'fresh-youtube-playing.png'),fullPage:true});
 await page.getByRole('button',{name:'Pause',exact:true}).last().click();
 if(!await page.evaluate(()=>window.__qaAudio.paused))throw Error('pause did not stop audio');
 if(errors.length)throw Error(JSON.stringify(errors));
 const receipt={ok:true,source_revision:process.env.MUSIC_REVISION,provider:'YouTube Music',google_account_connected:false,cachedBefore,audio,responses,cacheAfter:audioFiles().map(name=>({name,bytes:fs.statSync(path.join(data,'cache',name)).size})),checks:['isolated empty library','empty audio cache before playback','real YouTube Music search','real uncached audio clock advanced above five seconds','pause stops real media','no uncaught browser errors'],errors};
 fs.writeFileSync(path.join(out,'receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt,null,2));
}catch(error){const p=browser?.contexts()[0]?.pages()[0];if(p){await p.screenshot({path:path.join(out,'failure.png'),fullPage:true});fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:error.message,body:await p.locator('body').innerText()},null,2));}throw error;}finally{await browser?.close();hub.kill();app.kill();proxy.close();fs.closeSync(log);}
