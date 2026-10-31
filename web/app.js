"use strict";
const $ = id => document.getElementById(id);
let clientHold = null;
let googleSetup = null, googleStep = 1, googleProject = '', googleAudience = 'External';
const googleChecks = new Set();
let googleRedirect = '';
let state, view = 'root', selected = 'garden', activeJob = null, poll = null, generation = 0, result = null, overlay = null;
const detail = $('detail');
function element(tag, text, cls) {const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function append(tag,text,cls){const e=element(tag,text,cls);detail.append(e);return e;}
function button(label,action,parent=detail,cls=''){const b=element('button',label,cls);b.onclick=action;parent.append(b);return b;}
function errorText(code){return ({private_route_disabled:'Private processing is disabled. No model was called.',private_route_not_configured:'The private route is not configured. No other model was tried.',private_provider_unavailable:'Tinfoil/glm-5-3 was unavailable or timed out. No fallback model was tried.',attestation_failed:'Private-route attestation failed. Summary blocked.',worker_busy:'A summary is still running. Wait or cancel it.',incomplete_output:'The private model returned an incomplete summary. Try again.',invalid_output:'The private model returned no usable summary.',tool_output_rejected:'The private model requested a tool. The output was rejected; no tool ran.',stale_delivery:'The request changed before delivery. This result was discarded.'})[code]||'This operation could not complete ('+code+').';}
async function api(path, data){const r=await fetch('api/'+path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data),credentials:'same-origin',cache:'no-store'});const d=await r.json();if(!r.ok){const e=new Error(d.error||'request_failed');e.data=d;throw e;}return d;}
function closeDialog(){if($('dialog').open)$('dialog').close();overlay?.release();overlay=null;}
function dialog(title,text){$('dialog-title').textContent=title;$('dialog-text').textContent=text;$('dialog').showModal();overlay=WizardApp.back.push(()=>{closeDialog();return true;});}
let dialogOutsideDown=false;
const outsideDialog=e=>{const r=$('dialog').getBoundingClientRect();return e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom;};
$('dialog').addEventListener('pointerdown',e=>{dialogOutsideDown=e.target===$('dialog')&&outsideDialog(e);});
$('dialog').addEventListener('click',e=>{if(e.target===$('dialog')&&dialogOutsideDown&&outsideDialog(e))closeDialog();dialogOutsideDown=false;});
$('dialog-close').onclick=closeDialog;$('dialog').addEventListener('cancel',e=>{e.preventDefault();closeDialog();});
async function stop(){generation++;clearTimeout(poll);if(activeJob){const id=activeJob;activeJob=null;try{await api('cancel/'+id,{});}catch{}}}
function navigate(next){if(view==='google'&&next!=='google'&&clientHold){if(!confirm('Discard unsaved Google app configuration?'))return;clientHold.release();clientHold=null;}view=next;document.body.dataset.view=view;render();}
function back(){if(view==='google'&&googleSetup){if(clientHold){if(!confirm('Discard unsaved Google app configuration?'))return true;clientHold.release();clientHold=null;}if(googleSetup==='manual'&&googleStep>1)googleStep--;else googleSetup=null;render();return true;}if(view==='summary'){navigate('chat');return true;}if(view!=='root'){stop();navigate('root');return true;}return false;}
async function refresh(){state=await api('state');$('unlock').hidden=true;$('workspace').hidden=false;document.querySelector('#google-row small').textContent=state.google.blocker?'Google · '+state.google.blocker.replaceAll('_',' '):state.google.state==='connected'?'Connected · permissions managed here':'Not connected';render();}
function render(){detail.replaceChildren();document.body.dataset.view=view;if(!state)return;if(view==='root'){append('h2','Choose a connection');append('p','Google accounts and service permissions stay separate. Practice private summaries with fictional messages and connect your own Google app for Calendar read access.');return;}
button('← Back',back);if(view==='google')return renderGoogle();if(view==='summary')return renderSummary();renderChat();}
async function accountAction(path,data){try{await api(path,data);await refresh();}catch(e){dialog('Account action unavailable',errorText(e.message));}}
async function authorize(account=null,youtube=false,calendar=false){try{const auth=await api('google/connect',{account,youtube,calendar});const url=new URL(auth.authorization_url);if(url.origin!=='https://accounts.google.com')throw new Error('invalid_authorization_url');append('p','Continue in your browser. After consent, close the new tab and refresh accounts here.');const a=append('a','Continue to Google');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';}catch(e){dialog('Can’t connect yet',errorText(e.message));}}
function googleLink(label,path){const a=append('a',label,'google-link');a.href='https://console.cloud.google.com'+path+(googleProject?'?project='+encodeURIComponent(googleProject):'');a.target='_blank';a.rel='noopener noreferrer';return a;}
async function copyGoogle(text,label){try{await navigator.clipboard.writeText(text);dialog('Copied',label+' copied.');}catch{dialog('Copy unavailable','Select and copy the text shown on this screen.');}}
function renderGoogleApp(g){
 if(googleSetup==='manual')return renderGoogleSteps(g);
 append('h3','Your Google app — one time','wz-sec-h');
 if(g.client_configured){
  const row=append('div',undefined,'actions google-configured');row.append(element('strong','Google app: set up ✓'));
  button('Change',()=>{googleSetup='manual';googleStep=6;render();},row);
  if(g.client_source==='env')append('small','Managed by your installer. Environment settings must be changed there.');
  return;
 }
 append('p','Your Google app is only a permission key your Wizard uses to ask Google; it holds no data. Make it in your own main Google account. One app connects all your accounts. Your wizard does not need a Google account.');
 if(googleSetup==='agent'){
  append('p','Say this to your wizard:');append('pre','Set up my Google app','google-copy');
  button('Copy message',()=>copyGoogle('Set up my Google app','Message'),detail,'primary');
  append('p','You sign in to your own main Google account in the Wizard Browser. Your wizard does the setup, pausing for any terms or approval only you can accept. The client secret goes straight to Connected accounts, never into chat.');
  button('Check setup',async()=>{try{await refresh();if(state.google.client_configured){googleSetup=null;render();}else dialog('Not set up yet','Ask your wizard to finish, then check again.');}catch{dialog('Could not check','Try again when Connected accounts is available.');}});
  button('Set it up myself',()=>{googleSetup='manual';googleStep=1;render();});return;
 }
 const actions=append('div',undefined,'actions');
 button('Let your wizard set this up',()=>{googleSetup='agent';render();},actions,'primary');
 button('Set it up myself',()=>{googleSetup='manual';googleStep=1;render();},actions);
}
function renderGoogleSteps(g){
 const titles=['Use your own Google account','Create your Google Cloud project','Enable Google Calendar API','Set up Google Auth Platform','Create a Web application client','Save your Google app','Connect your accounts'];
 append('small',googleStep+' of 7','google-progress').setAttribute('aria-live','polite');
 const progress=append('progress');progress.max=7;progress.value=googleStep;progress.setAttribute('aria-label','Google app setup progress');
 append('h2',titles[googleStep-1]);
 const redirect=()=>googleRedirect||g.redirect_uri||g.suggested_redirect_uri;
 if(googleStep===1){
  append('p','Use your own main Google account to own the app, not an account for your wizard. This one app can connect all your Google accounts.');
  const l=append('label','Who will use it?','wz-label'),s=element('select',undefined,'wz-input');
  for(const [v,t] of [['External','My own accounts — External'],['Internal','Company Workspace only — Internal (admin)']]){const o=element('option',t);o.value=v;s.append(o);}s.value=googleAudience;s.onchange=()=>googleAudience=s.value;l.append(s);
  append('small','External works across your accounts. Internal is only for accounts inside your company’s Google Workspace organization.');
 }
 if(googleStep===2){
  append('p','Create a project named Wizard in your own main Google account. Keep the project selected for the next steps.');
  googleLink('Open Google Cloud — create project','/projectcreate');
  const l=append('label','Project ID (optional)','wz-label'),i=element('input',undefined,'wz-input');i.value=googleProject;i.placeholder='wizard-…';i.pattern='[a-z][a-z0-9-]{4,28}[a-z0-9]';i.oninput=()=>{googleProject=i.validity.valid?i.value:'';};l.append(i);
  append('small','If Google asks you to accept Cloud terms, review and accept them yourself. No billing or paid service is needed for this setup.');
 }
 if(googleStep===3){append('p','In this project, open Google Calendar API and choose Enable. If it is already enabled, continue.');googleLink('Open Google Calendar API','/apis/library/calendar-json.googleapis.com');}
 if(googleStep===4){
  append('p','In Google Auth Platform, choose Get started. Name the app Wizard and use your own email for support and contact information.');
  append('p',googleAudience==='Internal'?'Choose Internal for your company Workspace organization.':'Choose External. Then open Audience → Publish app → Confirm so its status is In production. Publishing avoids the 7-day logouts of Testing mode.');
  googleLink('Open Google Auth Platform','/auth/overview');googleLink('Open Branding','/auth/branding');googleLink('Open Audience','/auth/audience');
  append('small','Review and accept Google’s data policy yourself if asked. An “unverified app” screen is expected for your own personal app; publishing is not Google verification. Do not submit it for public verification just to connect your own accounts.');
 }
 if(googleStep===5){
  append('p','Open Clients → Create client. Choose Web application, name it Wizard, and under Authorized redirect URIs choose Add URI. Paste this exact address:');
  const l=append('label','Authorized redirect URI','wz-label'),i=element('textarea',undefined,'wz-input google-uri');i.rows=3;i.spellcheck=false;i.value=redirect();i.oninput=()=>{googleRedirect=i.value;};l.append(i);
  button('Copy redirect URI',()=>copyGoogle(i.value,'Redirect URI'));
  append('small','If needed, correct this to your Wizard’s public HTTPS address before copying. Keep the full /api/google/callback ending.');
  googleLink('Open Google Auth clients','/auth/clients');append('p','Click Create in Google. Keep its client details open for the next step.');
 }
 if(googleStep===6){
  append('p','Paste the Client ID and Client secret from Google here — not into chat. They are saved encrypted by the Google broker.');
  const form=append('form',undefined,'wz-sec');
  function field(label,type,max){const l=element('label',label,'wz-label'),i=element('input',undefined,'wz-input');i.type=type;i.required=true;i.autocomplete='off';i.maxLength=max;l.append(i);form.append(l);return i;}
  const id=field('Client ID','text',230);id.value=g.client_id||'';id.pattern='[A-Za-z0-9_\\-]{1,200}\\.apps\\.googleusercontent\\.com';
  const secret=field('Client secret','password',512);secret.minLength=8;secret.pattern='[^\\s]{8,512}';
  const save=button('Save Google app',()=>{},form,'primary');save.type='submit';
  const validate=()=>{save.disabled=g.client_source==='env'||!form.checkValidity();};
  for(const i of [id,secret])i.oninput=()=>{clientHold??=WizardApp.update.hold('Unsaved Google app configuration');validate();};validate();
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await api('google/client',{client_id:id.value,client_secret:secret.value,redirect_uri:redirect()});secret.value='';clientHold?.release();clientHold=null;googleChecks.add(6);await refresh();}catch(err){dialog('Could not save Google app',errorText(err.message));validate();}};
  if(googleChecks.has(6)&&g.client_configured)append('p','Google app saved ✓');
  if(g.client_source==='env')append('p','Managed by your installer. Ask them to change the environment settings.');
  if(g.client_configured&&g.client_source!=='env')button('Remove Google app',async()=>{if(!confirm('Remove the app credentials? All accounts will need reauthentication and new service consent.'))return;try{const r=await fetch('api/google/client',{method:'DELETE',credentials:'same-origin'});if(!r.ok)throw new Error('remove_failed');googleChecks.delete(6);await refresh();}catch(e){dialog('Could not remove Google app',errorText(e.message));}});
 }
 if(googleStep===7){append('p','Connect each Google account you want to use. Then let Calendar read that account and explicitly allow Calendar to use it. Repeat for as many accounts as you like.');renderGoogleAccounts(g);button('Finish setup',()=>{googleSetup=null;render();},detail,'primary');return;}
 if(googleStep<6){const l=append('label',undefined,'google-done');const c=element('input');c.type='checkbox';c.checked=googleChecks.has(googleStep);l.append(c,document.createTextNode(googleStep===1?'I’ll use my own account':googleStep===4?(googleAudience==='Internal'?'Done — Internal is selected':'Done — app is In production'):'Done in Google'));c.onchange=()=>{if(c.checked)googleChecks.add(googleStep);else googleChecks.delete(googleStep);next.disabled=!c.checked;};}
 const next=button('Next',()=>{googleStep++;render();detail.scrollIntoView({block:'start'});},detail,'primary');next.disabled=!googleChecks.has(googleStep)||(googleStep===6&&!g.client_configured);
}
function renderGoogle(){
 const g=state.google;
 if(googleSetup==='manual')return renderGoogleSteps(g);
 append('h2','Google');renderGoogleApp(g);
 if(googleSetup==='agent')return;
 renderGoogleAccounts(g);
}
function renderGoogleAccounts(g){
 append('h3','Your Google accounts — add as many as you like','wz-sec-h');
 append('span',g.state==='connected'?'Connected':g.state==='unavailable'?'Broker unavailable':'Not connected','badge');
 if(g.blocker)append('p',g.blocker==='google_configuration_required'?'Save your Google app above before connecting.':'Account operations unavailable: '+g.blocker);
 button('Connect Google',()=>authorize()).disabled=!!g.blocker;button('Refresh accounts',()=>{if(clientHold&&!confirm('Discard unsaved Google app configuration and refresh?'))return;clientHold?.release();clientHold=null;refresh().catch(e=>dialog('Refresh unavailable',errorText(e.message)));});
 append('h3','Identity and granted permissions');
 if(!g.accounts.length)append('p','No Google account connected. Identity permission alone does not authorize Music catalog or audio.');
 for(const a of g.accounts){
  append('strong',a.email||a.id);append('p',a.status+' · '+(a.offline?'offline refresh authorized':'session access only'));append('small',a.scopes.join(', '));
  button('Reconnect this account',()=>authorize(a.id,a.scopes.includes('https://www.googleapis.com/auth/youtube.readonly')));
  if(!a.scopes.includes('https://www.googleapis.com/auth/youtube.readonly'))button('Authorize YouTube catalog (read only)',()=>authorize(a.id,true));
  else button('Use this Google account for Music catalog',()=>accountAction('music/bind',{account:a.id,consent:true}));
  const calendarScope=a.scopes.includes('https://www.googleapis.com/auth/calendar.readonly');
  if(!calendarScope)button('Let Calendar read this account',()=>authorize(a.id,false,true));
  else {const allowed=(g.calendar_binding?.accounts||[]).includes(a.id);button(allowed?'Stop Calendar using this account':'Allow Calendar to use this account',()=>{if(!allowed&&!confirm('Allow the Calendar app to read calendars and events from this account?'))return;accountAction('calendar/bind',{account:a.id,consent:!allowed});});}
  button('Disconnect Google account',()=>{if(confirm('Disconnect this account and unlink dependent Music and Calendar access? Google will be asked to revoke this app’s grant.'))accountAction('google/disconnect',{account:a.id});});
 }
 append('h3','YouTube Music');append('span',g.music.state==='bound'?'Catalog account bound':'Catalog account unbound','badge');
 append('p','Connecting Google and binding read-only catalog access does not authorize audio playback or change the existing Music source. No shared browser cookies are mounted.');
 if(g.bindings.length){button('Unlink Music catalog',()=>accountAction('music/unlink',{}));const label=append('label','YouTube video ID');const input=element('input');input.maxLength=11;input.placeholder='11-character video ID';label.append(input);button('Look up catalog item',async()=>{try{const r=await api('music/catalog',{account:g.bindings[0].account,video_id:input.value});dialog('Catalog metadata only',r.items.map(i=>i.title).join('\n')||'No catalog item returned. This is not proof of playback.');}catch(e){dialog('Catalog unavailable',errorText(e.message));}});}
 if(g.provider_revocation==='failed_manual_revocation_required'||g.provider_revocation==='pending')append('p','Local access removed; provider revocation is not confirmed. Remove this app in your Google account permissions.');
 const a=append('a','Open Music');a.href='/wizard-music/';a.target='_top';
 append('small','Credentials are held only by the provider broker. The host administrator remains trusted. Real private chat remains disabled.');
}
function renderChat(){append('h2','Simulated chat');append('span','Fictional · contains private data','badge');const label=append('label','Conversation');const select=element('select');for(const t of state.threads){const o=element('option',t.title+' · '+t.count+' messages');o.value=t.id;select.append(o);}select.value=selected;select.disabled=!!activeJob;select.onchange=()=>{selected=select.value;result=null;render();};label.append(select);const messages=append('div');const captured=selected;api('conversations/'+selected).then(p=>{if(view!=='chat'||selected!==captured)return;for(const m of p.messages){const box=element('article',undefined,'message');box.append(element('strong',m.sender+' · '+m.id),element('time',m.at),element('p',m.text));messages.append(box);}}).catch(()=>messages.textContent='Could not load fictional conversation.');append('p','Summary route: tinfoil · glm-5-3. No tools. No fallback. Results remain in this app for 15 minutes and are discarded on restart.');append('small','Synthetic preview: human-view authentication is implemented, but a host administrator can bypass it. No real chat is connected.');const actions=append('div',undefined,'actions');const summarize=button(activeJob?'Summarizing on tinfoil/glm-5-3…':'Summarize privately',start,actions,'primary');summarize.disabled=!!activeJob||!state.private_route.configured||!state.private_route.enabled;if(activeJob){append('progress');button('Cancel summary',async()=>{await stop();render();},actions);}else{button(state.private_route.enabled?'Disable private processing':'Enable private processing',async()=>{await stop();try{await api('policy',{enabled:!state.private_route.enabled});result=null;await refresh();}catch(e){dialog('Could not change policy',errorText(e.message));}},actions);}if(!state.private_route.configured)append('p','Private route is not configured. Summaries are off.');if(!state.private_route.enabled)append('p','Private processing disabled. Summaries block without calling any model.');}
async function start(){const gen=++generation;try{const j=await api('summarize',{thread:selected,request_id:crypto.randomUUID()});if(gen!==generation){await api('cancel/'+j.id,{});return;}activeJob=j.id;render();const check=async()=>{if(gen!==generation)return;try{const status=await api('jobs/'+j.id);if(gen!==generation)return;if(status.status==='complete'){result=await api('results/'+j.id);if(gen!==generation)return;activeJob=null;navigate('summary');}else if(['blocked','cancelled','quarantined','expired'].includes(status.status)){activeJob=null;render();dialog('Private summary unavailable',errorText(status.reason||status.status));}else{poll=setTimeout(check,1000);}}catch(e){if(gen!==generation)return;await stop();render();dialog('Could not read summary',errorText(e.message));}};poll=setTimeout(check,500);}catch(e){activeJob=null;render();dialog('Private summary unavailable',errorText(e.message));}}
function renderSummary(){append('h2','Private summary');append('span','Human view · not returned by MCP','badge');append('pre',result?.text||'This result is no longer available.');append('small','tinfoil · glm-5-3 · simulated data · untrusted plain text');append('small','Source references: '+(result?.source_ids||[]).join(', '));const actions=append('div',undefined,'actions');button('Done',()=>navigate('chat'),actions);button('Discard',async()=>{if(result?.id)await api('cancel/'+result.id,{});result=null;navigate('chat');},actions);}
$('google-row').onclick=async()=>{await stop();navigate('google');};$('chat-row').onclick=()=>navigate('chat');
$('unlock').onsubmit=async e=>{e.preventDefault();try{await api('session',{token:$('owner-token').value});$('owner-token').value='';await refresh();}catch{dialog('Could not unlock','Use the app installer’s owner token, not a Google password.');}};
if(!window.WizardApp){$('system-error').hidden=false;$('system-error').textContent='Shared WizardApp core is unavailable. Configure the approved shell resource before using this preview.';$('workspace').hidden=true;}else{WizardApp.ready({name:'Connected accounts',version:'0.1.0'});WizardApp.back.register({canGoBack:()=>view!=='root',back});refresh().catch(e=>{if(e.message==='owner_auth_required'){$('workspace').hidden=true;$('unlock').hidden=false;}else{$('system-error').hidden=false;$('system-error').textContent='Could not load app state.';}});}
