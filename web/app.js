"use strict";
const $ = id => document.getElementById(id);
let clientHold = null;
let googleSetup = null, googleStep = 1, googleProject = '', googleAudience = 'External';
const googleChecks = new Set();
let googleRedirect = '', googleAuth = null, googleAuthRequest = 0;
let googleDraft = {id:'', secret:''};
function discardClientDraft(){googleDraft={id:'',secret:''};clientHold?.release();clientHold=null;}
function clearGoogleWatch(){clearInterval(googleWatch);googleWatch=null;}
function cancelGoogleAuth(){googleAuthRequest++;clearGoogleWatch();if(googleAuth?.popup)try{googleAuth.popup.close();}catch{}googleAuth=null;}
let googleWatch=null, googleChecking=false;
async function checkGoogleReturn(){
 const a=googleAuth;if(!a||a.status!=='ready'||googleChecking)return;
 if(Date.now()>a.expires){clearGoogleWatch();try{a.popup?.close();}catch{}a.status='error';a.error='sign_in_timeout';render();return;}
 googleChecking=true;
 try{const next=await api('state');if(googleAuth!==a||view!=='google')return;
  const account=next.google.accounts.find(x=>a.account?x.id===a.account:!a.before.includes(x.id));
  let closed=false;try{closed=!!a.popup?.closed;}catch{}
  const changed=!a.account||JSON.stringify(account||null)!==a.previous||closed;
  if(account&&changed&&(!a.calendar||account.scopes.includes('https://www.googleapis.com/auth/calendar.readonly'))){cancelGoogleAuth();state=next;render();}
 }catch{}finally{googleChecking=false;}
}
window.addEventListener('focus',checkGoogleReturn);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkGoogleReturn();});
let state, view = 'root', selected = 'garden', activeJob = null, poll = null, generation = 0, result = null, overlay = null;
const detail = $('detail');
function element(tag, text, cls) {const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function append(tag,text,cls){const e=element(tag,text,cls);detail.append(e);return e;}
function button(label,action,parent=detail,cls=''){const b=element('button',label,cls);b.type='button';b.onclick=e=>{const task=action(e);if(view==='google'&&task&&typeof task.then==='function'&&b.isConnected){b.disabled=true;b.setAttribute('aria-busy','true');if(b.textContent===label)b.textContent='Working…';task.finally(()=>{if(b.isConnected){b.disabled=false;b.removeAttribute('aria-busy');if(b.textContent==='Working…')b.textContent=label;}});}};parent.append(b);return b;}
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
function navigate(next){if(view==='google'&&next!=='google'){if(clientHold){if(!confirm('Discard unsaved Google app configuration?'))return;discardClientDraft();}cancelGoogleAuth();}view=next;document.body.dataset.view=view;render();}
function back(){if(view==='google'&&googleAuth){cancelGoogleAuth();render();return true;}if(view==='google'&&googleSetup){if(clientHold){if(!confirm('Discard unsaved Google app configuration?'))return true;discardClientDraft();}if(googleSetup==='manual'&&googleStep>1)googleStep--;else googleSetup=null;render();return true;}if(view==='summary'){navigate('chat');return true;}if(view!=='root'){stop();navigate('root');return true;}return false;}
function renderRootGoogle(){const g=state.google,n=g.accounts.length;$('google-row').textContent=!g.client_configured?'Set up Google':n?'Manage Google accounts':'Connect your Google account';$('google-summary').textContent=n?n+' Google '+(n===1?'account connected':'accounts connected'):g.client_configured?'See your Google calendars in Wizard. Connect an account to get started.':'Set up once to connect your Google accounts and calendars.';$('google-manage').hidden=!g.client_configured||n>0;}
async function refresh(){state=await api('state');$('unlock').hidden=true;$('workspace').hidden=false;renderRootGoogle();render();}
function render(){detail.replaceChildren();document.body.dataset.view=view;if(!state)return;renderRootGoogle();if(view==='root')return;
button('← Back',back);if(view==='google')return renderGoogle();if(view==='summary')return renderSummary();renderChat();}
async function accountAction(path,data){try{await api(path,data);await refresh();}catch(e){dialog('Account action unavailable',errorText(e.message));}}
function googleError(code){return ({sign_in_timeout:'This sign-in link has expired. Try again to open a fresh Google sign-in window.',authorization_busy:'There are several unfinished sign-in attempts. Wait a few minutes, then try again.',service_unavailable:'Google connections are temporarily unavailable. Try again in a moment.',google_disabled:'Google connections are turned off. Ask your wizard to enable them, then try again.',google_configuration_required:'Your Google app needs setting up before you can connect an account.',broker_unavailable:'Google connections are temporarily unavailable. Check again in a moment.',provider_unavailable:'Google did not respond. Try again in a moment.',owner_auth_required:'Your owner session has expired. Close and reopen Connected accounts, then try again.',invalid_authorization_url:'Google did not return a safe sign-in link. Try again; if it keeps happening, ask your wizard to check Google setup.',local_storage_unavailable:'Your Wizard could not save the sign-in request. Ask your wizard to check its storage.'})[code]||'Could not prepare Google sign-in. Try again; if it keeps happening, ask your wizard to check Google setup.';}
async function authorize(account=null,youtube=false,calendar=true){
 if(googleAuth?.status==='pending')return;
 // Open inside the click gesture, before any await. If blocked, the same-screen link remains usable.
 let popup=null;try{popup=window.open('about:blank','_blank');if(popup)popup.opener=null;}catch{}
 const request=++googleAuthRequest;
 googleAuth={status:'pending',account,youtube,calendar,popup};render();detail.scrollIntoView({block:'start'});
 try{
  const auth=await api('google/connect',{account,youtube,calendar});
  const url=new URL(auth.authorization_url);
  if(url.origin!=='https://accounts.google.com'||url.username||url.password)throw new Error('invalid_authorization_url');
  if(request!==googleAuthRequest||view!=='google'){try{popup?.close();}catch{}return;}
  let opened=false;try{if(popup&&!popup.closed){popup.location.replace(url.href);opened=true;}}catch{}
  googleAuth={status:'ready',account,youtube,calendar,url:url.href,popup,opened,before:state.google.accounts.map(x=>x.id),previous:JSON.stringify(state.google.accounts.find(x=>x.id===account)||null),expires:Date.now()+600000};
  googleWatch=setInterval(checkGoogleReturn,5000);render();
 }catch(e){try{popup?.close();}catch{}if(request!==googleAuthRequest||view!=='google')return;googleAuth={status:'error',account,youtube,calendar,error:e.message};render();}
}
function renderGoogleAuthorization(){
 const a=googleAuth;
 append('h2',a.status==='pending'?'Connecting Google':a.status==='ready'?'Finish signing in':"Couldn’t start Google sign-in");
 if(a.status==='pending'){const busyButton=button('Opening Google…',()=>{},detail,'primary');busyButton.disabled=true;busyButton.setAttribute('aria-busy','true');append('p','Getting a secure sign-in link. This usually takes a moment.','google-status').setAttribute('role','status');const busy=append('progress');busy.setAttribute('aria-label','Preparing Google sign-in');button('Cancel',()=>{cancelGoogleAuth();render();});return;}
 if(a.status==='ready'){
  append('p',a.opened?'Finish signing in in the Google window. Your accounts will appear here when you return.':'Your browser kept the sign-in window closed. Continue below to choose your account.','google-status').setAttribute('role','status');
  const link=append('a',a.opened?'Open Google again':'Continue to Google','google-continue '+(a.opened?'secondary':'primary'));link.href=a.url;link.target='_blank';link.rel='noopener noreferrer';
  append('small','You’ll review the permissions on Google. Connecting does not yet give Calendar permission to show the account.');
  button('Check now',checkGoogleReturn,detail,'text-button');
  button('Cancel sign-in',()=>{cancelGoogleAuth();render();},detail,'text-button');return;
 }
 append('p',googleError(a.error),'google-status').setAttribute('role','alert');
 button('Try again',()=>authorize(a.account,a.youtube,a.calendar),detail,'primary');
 if(a.error==='google_configuration_required')button('Set up Google app',()=>{cancelGoogleAuth();googleSetup='agent';render();});
 button('Back to accounts',()=>{cancelGoogleAuth();render();});
}
function googleLink(label,path){const a=append('a',label,'google-link');a.href='https://console.cloud.google.com'+path+(googleProject?'?project='+encodeURIComponent(googleProject):'');a.target='_blank';a.rel='noopener noreferrer';return a;}
async function copyGoogle(text,label){try{await navigator.clipboard.writeText(text);dialog('Copied',label+' copied.');}catch{dialog('Copy unavailable','Select and copy the text shown on this screen.');}}
function renderGoogleApp(g){
 if(googleSetup==='manual')return renderGoogleSteps(g);
 append('h2',googleSetup==='agent'?'Let your wizard do the setup':'Set up Google once');
 if(googleSetup==='agent'){
  append('p','Send this message to your wizard:');append('pre','Set up my Google app','google-copy');
  button('Copy message',()=>copyGoogle('Set up my Google app','Message'),detail,'primary');
  append('p','You sign in with your own main Google account in the Wizard Browser. Your wizard creates the app and pauses for anything only you can approve. The secret goes straight to Connected accounts, never into chat.');
  button('Check setup',async()=>{try{const next=await api('state');state=next;if(next.google.client_configured){googleSetup=null;render();}else dialog('Not set up yet','Ask your wizard to finish, then check again.');}catch{dialog('Could not check','Try again when Connected accounts is available.');}});
  button('Set it up myself',()=>{googleSetup='manual';googleStep=1;render();});return;
 }
 append('p','Before connecting accounts, your Wizard needs a Google app: a permission key you create in your own Google account. Set it up once, then add as many accounts as you like.');
 const actions=append('div',undefined,'actions google-setup-actions');
 button('Let your wizard set this up',()=>{googleSetup='agent';render();},actions,'primary');
 button('Set it up myself',()=>{googleSetup='manual';googleStep=1;render();},actions);
 append('small','Your wizard does not need its own Google account. You choose what each connected account can share.');
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
  const id=field('Client ID','text',230);id.value=googleDraft.id||g.client_id||'';id.pattern='[A-Za-z0-9_\\-]{1,200}\\.apps\\.googleusercontent\\.com';
  const secret=field('Client secret','password',512);secret.value=googleDraft.secret;secret.minLength=8;secret.pattern='[^\\s]{8,512}';
  const save=button('Save Google app',()=>{},form,'primary');save.type='submit';
  const validate=()=>{save.disabled=g.client_source==='env'||!form.checkValidity();};
  for(const i of [id,secret])i.oninput=()=>{googleDraft={id:id.value,secret:secret.value};clientHold??=window.WizardApp?.update?.hold?.('Unsaved Google app configuration')||{release(){}};validate();};validate();
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;save.textContent='Saving…';try{await api('google/client',{client_id:id.value,client_secret:secret.value,redirect_uri:redirect()});secret.value='';discardClientDraft();googleChecks.add(6);state=await api('state');googleStep=7;render();}catch(err){save.textContent='Save Google app';const msg=err.message==='google_client_environment_managed'?'Your installer manages this Google app; ask your wizard to change it.':'Check both values and try again. The secret was not shown or sent to chat.';dialog('Could not save Google app',msg);validate();}};
  if(g.client_source==='env')append('p','Managed by your installer. Ask them to change the environment settings.');
  if(g.client_configured&&g.client_source!=='env')button('Remove Google app',async()=>{if(!confirm('Remove the app credentials? All accounts will need reauthentication and new service consent.'))return;try{const r=await fetch('api/google/client',{method:'DELETE',credentials:'same-origin'});if(!r.ok)throw new Error('remove_failed');discardClientDraft();googleChecks.delete(6);googleSetup=null;await refresh();}catch(e){dialog('Could not remove Google app','Ask your wizard to check the saved app settings, then try again.');}});
  return;
 }
 if(googleStep===7){append('p','Your Google app is saved. You can now connect accounts and choose their permissions.');button('Go to accounts',()=>{googleSetup=null;render();},detail,'primary');return;}
 if(googleStep<6){const l=append('label',undefined,'google-done');const c=element('input');c.type='checkbox';c.checked=googleChecks.has(googleStep);l.append(c,document.createTextNode(googleStep===1?'I’ll use my own account':googleStep===4?(googleAudience==='Internal'?'Done — Internal is selected':'Done — app is In production'):'Done in Google'));c.onchange=()=>{if(c.checked)googleChecks.add(googleStep);else googleChecks.delete(googleStep);next.disabled=!c.checked;};}
 const next=button('Next',()=>{googleStep++;render();detail.scrollIntoView({block:'start'});},detail,'primary');next.disabled=!googleChecks.has(googleStep)||(googleStep===6&&!g.client_configured);
}
function disclosure(title,parent=detail){const d=element('details',undefined,'google-disclosure');d.append(element('summary',title));const body=element('div',undefined,'google-disclosure-body');d.append(body);parent.append(d);return body;}
function renderGoogle(){
 const g=state.google;
 if(googleAuth)return renderGoogleAuthorization();
 if(googleSetup||!g.client_configured)return renderGoogleApp(g);
 append('h2','Google');
 append('p','Connect your accounts, then choose what Calendar and Music can use.','google-intro');
 const appCard=append('section',undefined,'wz-sec google-app-card');
 const appText=element('div');appText.append(element('h3','Your Google app'),element('p','Set up ✓ — created in your Google account. You only do this once.'));appCard.append(appText);
 button('Change',()=>{googleSetup='manual';googleStep=6;render();},appCard,'text-button');
 renderGoogleAccounts(g);
 const tech=disclosure('Connection details');
 if(g.client_source==='env')tech.append(element('small','Managed by your installer. Ask your wizard to change it.'));
 for(const [label,value] of [['Client ID',g.client_id],['Redirect URI',g.redirect_uri||g.suggested_redirect_uri]])if(value){tech.append(element('strong',label),element('p',value,'google-technical'));}
 append('small','Your sign-in details stay on your own Wizard server, not in chat. You can disconnect an account and remove its Google permissions at any time.','google-privacy');
 const privacy=append('a','Privacy','google-link');privacy.href='privacy';privacy.target='_blank';privacy.rel='noopener noreferrer';
}
function renderGoogleAccounts(g){
 const intro=append('section',undefined,'wz-sec google-connect');
 intro.append(element('h3','Your Google accounts'));
 if(!g.accounts.length)intro.append(element('p','Connect any Google account to see its calendar in Wizard. You can add as many as you like.'));
 const actions=element('div',undefined,'actions');intro.append(actions);
 const connect=button(g.accounts.length?'Add another account':'Connect a Google account',()=>authorize(),actions,'primary');
 connect.disabled=!!g.blocker;
 button('Check accounts',async()=>{try{await refresh();}catch{dialog('Could not check accounts','Try again in a moment. Your connected accounts have not been changed.');}},actions,'text-button');
 if(g.blocker)intro.append(element('p',googleError(g.blocker),'google-status'));
 for(const a of g.accounts){
  const card=append('article',undefined,'google-account');
  card.append(element('h3',a.email||'Google account'));
  card.append(element('p',a.status==='connected'?'Connected':a.status==='reauth_required'?'Sign in again to restore access':'Account needs attention','google-help'));
  const calendarScope=a.scopes.includes('https://www.googleapis.com/auth/calendar.readonly');
  const allowed=(g.calendar_binding?.accounts||[]).includes(a.id);
  card.append(element('p',allowed?'Calendar can use this account.':calendarScope?'Calendar read access approved. Choose whether Calendar can use it.':'Calendar does not have access to this account.'));
  if(!calendarScope)button('Show this account’s calendar in Calendar',()=>authorize(a.id,false,true),card,'primary');
  else button(allowed?'Stop showing this account in Calendar':'Show this account’s calendar in Calendar',()=>{if(!allowed&&!confirm('Show this account’s calendars and events in the Calendar app?'))return;return accountAction('calendar/bind',{account:a.id,consent:!allowed});},card,allowed?'':'primary');
  const options=disclosure('Account options and permissions',card);
  button('Reconnect this account',()=>authorize(a.id,a.scopes.includes('https://www.googleapis.com/auth/youtube.readonly')),options);
  if(!a.scopes.includes('https://www.googleapis.com/auth/youtube.readonly'))button('Authorize YouTube catalog (read only)',()=>authorize(a.id,true),options);
  else button('Use this Google account for Music catalog',()=>accountAction('music/bind',{account:a.id,consent:true}),options);
  button('Disconnect Google account',()=>{if(confirm('Disconnect this account and unlink dependent Music and Calendar access? Google will be asked to revoke this app’s grant.'))return accountAction('google/disconnect',{account:a.id});},options);
  const permissions=disclosure('Technical permission details',options);
  permissions.append(element('p',a.offline?'Offline refresh authorized':'Session access only'),element('p',a.scopes.join(', '),'google-technical'));
 }
 const music=disclosure('Other uses');
 music.append(element('h3','YouTube Music catalog'),element('span',g.music.state==='bound'?'Music account selected':'No Music account selected','badge'),element('p','Read-only catalog access does not authorize audio playback or change your existing Music source. No shared browser cookies are used.'));
 if(g.bindings.length){button('Unlink Music catalog',()=>accountAction('music/unlink',{}),music);const label=element('label','YouTube video ID','wz-label'),input=element('input',undefined,'wz-input');input.maxLength=11;input.placeholder='11-character video ID';label.append(input);music.append(label);button('Look up catalog item',async()=>{try{const r=await api('music/catalog',{account:g.bindings[0].account,video_id:input.value});dialog('Catalog metadata only',r.items.map(i=>i.title).join('\n')||'No catalog item returned. This is not proof of playback.');}catch(e){dialog('Catalog unavailable',errorText(e.message));}},music);}
 const open=element('a','Open Music','google-link');open.href='/wizard-music/';open.target='_top';music.append(open);
 if(g.provider_revocation==='failed_manual_revocation_required'||g.provider_revocation==='pending')append('p','Local access removed; provider revocation is not confirmed. Remove this app in your Google account permissions.');
}
function renderChat(){append('h2','Simulated chat');append('span','Fictional · contains private data','badge');const label=append('label','Conversation');const select=element('select');for(const t of state.threads){const o=element('option',t.title+' · '+t.count+' messages');o.value=t.id;select.append(o);}select.value=selected;select.disabled=!!activeJob;select.onchange=()=>{selected=select.value;result=null;render();};label.append(select);const messages=append('div');const captured=selected;api('conversations/'+selected).then(p=>{if(view!=='chat'||selected!==captured)return;for(const m of p.messages){const box=element('article',undefined,'message');box.append(element('strong',m.sender+' · '+m.id),element('time',m.at),element('p',m.text));messages.append(box);}}).catch(()=>messages.textContent='Could not load fictional conversation.');append('p','Summary route: tinfoil · glm-5-3. No tools. No fallback. Results remain in this app for 15 minutes and are discarded on restart.');append('small','Synthetic preview: human-view authentication is implemented, but a host administrator can bypass it. No real chat is connected.');const actions=append('div',undefined,'actions');const summarize=button(activeJob?'Summarizing on tinfoil/glm-5-3…':'Summarize privately',start,actions,'primary');summarize.disabled=!!activeJob||!state.private_route.configured||!state.private_route.enabled;if(activeJob){append('progress');button('Cancel summary',async()=>{await stop();render();},actions);}else{button(state.private_route.enabled?'Disable private processing':'Enable private processing',async()=>{await stop();try{await api('policy',{enabled:!state.private_route.enabled});result=null;await refresh();}catch(e){dialog('Could not change policy',errorText(e.message));}},actions);}if(!state.private_route.configured)append('p','Private route is not configured. Summaries are off.');if(!state.private_route.enabled)append('p','Private processing disabled. Summaries block without calling any model.');}
async function start(){const gen=++generation;try{const j=await api('summarize',{thread:selected,request_id:crypto.randomUUID()});if(gen!==generation){await api('cancel/'+j.id,{});return;}activeJob=j.id;render();const check=async()=>{if(gen!==generation)return;try{const status=await api('jobs/'+j.id);if(gen!==generation)return;if(status.status==='complete'){result=await api('results/'+j.id);if(gen!==generation)return;activeJob=null;navigate('summary');}else if(['blocked','cancelled','quarantined','expired'].includes(status.status)){activeJob=null;render();dialog('Private summary unavailable',errorText(status.reason||status.status));}else{poll=setTimeout(check,1000);}}catch(e){if(gen!==generation)return;await stop();render();dialog('Could not read summary',errorText(e.message));}};poll=setTimeout(check,500);}catch(e){activeJob=null;render();dialog('Private summary unavailable',errorText(e.message));}}
function renderSummary(){append('h2','Private summary');append('span','Human view · not returned by MCP','badge');append('pre',result?.text||'This result is no longer available.');append('small','tinfoil · glm-5-3 · simulated data · untrusted plain text');append('small','Source references: '+(result?.source_ids||[]).join(', '));const actions=append('div',undefined,'actions');button('Done',()=>navigate('chat'),actions);button('Discard',async()=>{if(result?.id)await api('cancel/'+result.id,{});result=null;navigate('chat');},actions);}
$('google-row').onclick=()=>{stop();googleSetup=null;navigate('google');if(state.google.client_configured&&!state.google.accounts.length)authorize();};$('google-manage').onclick=()=>{stop();googleSetup=null;navigate('google');};$('chat-row').onclick=()=>navigate('chat');
$('unlock').onsubmit=async e=>{e.preventDefault();try{await api('session',{token:$('owner-token').value});$('owner-token').value='';await refresh();}catch{dialog('Could not unlock','Use the app installer’s owner token, not a Google password.');}};
if(!window.WizardApp){$('system-error').hidden=false;$('system-error').textContent='Shared WizardApp core is unavailable. Configure the approved shell resource before using this preview.';$('workspace').hidden=true;}else{WizardApp.ready({name:'Connected accounts',version:'0.1.0'});WizardApp.back.register({canGoBack:()=>view!=='root',back});refresh().catch(e=>{if(e.message==='owner_auth_required'){$('workspace').hidden=true;$('unlock').hidden=false;}else{$('system-error').hidden=false;$('system-error').textContent='Could not load app state.';}});}
