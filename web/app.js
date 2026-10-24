"use strict";
const $ = id => document.getElementById(id);
let clientHold = null;
let state, view = 'root', selected = 'garden', activeJob = null, poll = null, generation = 0, result = null, overlay = null;
const detail = $('detail');
function element(tag, text, cls) {const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function append(tag,text,cls){const e=element(tag,text,cls);detail.append(e);return e;}
function button(label,action,parent=detail,cls=''){const b=element('button',label,cls);b.onclick=action;parent.append(b);return b;}
function errorText(code){return ({private_route_disabled:'Private processing is disabled. No model was called.',private_route_not_configured:'The private route is not configured. No other model was tried.',private_provider_unavailable:'Tinfoil/glm-5-3 was unavailable or timed out. No fallback model was tried.',attestation_failed:'Private-route attestation failed. Summary blocked.',worker_busy:'A summary is still running. Wait or cancel it.',incomplete_output:'The private model returned an incomplete summary. Try again.',invalid_output:'The private model returned no usable summary.',tool_output_rejected:'The private model requested a tool. The output was rejected; no tool ran.',stale_delivery:'The request changed before delivery. This result was discarded.'})[code]||'This operation could not complete ('+code+').';}
async function api(path, data){const r=await fetch('api/'+path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data),credentials:'same-origin',cache:'no-store'});const d=await r.json();if(!r.ok){const e=new Error(d.error||'request_failed');e.data=d;throw e;}return d;}
function closeDialog(){if($('dialog').open)$('dialog').close();overlay?.release();overlay=null;}
function dialog(title,text){$('dialog-title').textContent=title;$('dialog-text').textContent=text;$('dialog').showModal();overlay=WizardApp.back.push(()=>{closeDialog();return true;});}
$('dialog-close').onclick=closeDialog;$('dialog').addEventListener('cancel',e=>{e.preventDefault();closeDialog();});
async function stop(){generation++;clearTimeout(poll);if(activeJob){const id=activeJob;activeJob=null;try{await api('cancel/'+id,{});}catch{}}}
function navigate(next){if(view==='google'&&next!=='google'&&clientHold){if(!confirm('Discard unsaved Google app configuration?'))return;clientHold.release();clientHold=null;}view=next;document.body.dataset.view=view;render();}
function back(){if(view==='summary'){navigate('chat');return true;}if(view!=='root'){stop();navigate('root');return true;}return false;}
async function refresh(){state=await api('state');$('unlock').hidden=true;$('workspace').hidden=false;document.querySelector('#google-row small').textContent=state.google.blocker?'Google · '+state.google.blocker.replaceAll('_',' '):state.google.state==='connected'?'Connected · permissions managed here':'Not connected';render();}
function render(){detail.replaceChildren();document.body.dataset.view=view;if(!state)return;if(view==='root'){append('h2','Choose a connection');append('p','Google accounts and service permissions stay separate. Practice private summaries with fictional messages and connect your own Google app for Calendar read access.');return;}
button('← Back',back);if(view==='google')return renderGoogle();if(view==='summary')return renderSummary();renderChat();}
async function accountAction(path,data){try{await api(path,data);await refresh();}catch(e){dialog('Account action unavailable',errorText(e.message));}}
async function authorize(account=null,youtube=false,calendar=false){try{const auth=await api('google/connect',{account,youtube,calendar});const url=new URL(auth.authorization_url);if(url.origin!=='https://accounts.google.com')throw new Error('invalid_authorization_url');append('p','Continue in your browser. After consent, close the new tab and refresh accounts here.');const a=append('a','Continue to Google');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';}catch(e){dialog('Can’t connect yet',errorText(e.message));}}
function renderGoogleApp(g){
 append('h3','Your Google app','wz-sec-h');
 append('p','Create your own Google OAuth app once. Your client secret stays encrypted in the broker; it is never returned to this screen or MCP.');
 const guide=append('ol',undefined,'google-guide');
 for(const text of [
  'Create a project in Google Cloud Console.',
  'Enable Google Calendar API. Enable YouTube Data API v3 too if you use Music catalog.',
  'Configure the OAuth consent screen: External. Add yourself as a test user. Then Publish app to “In production” so refresh tokens do not expire after 7 days. An unverified-app warning is expected for personal use.',
  'Open Credentials → Create OAuth client ID → Web application.',
  'Paste the exact Authorized redirect URI below into Google. Save the Google client.',
  'Paste its Client ID and Client secret here, then Save. Connect each account, grant Calendar read access, and explicitly allow Calendar to use it.'
 ])guide.append(element('li',text));
 const consoleLink=append('a','Open Google Cloud Console');consoleLink.href='https://console.cloud.google.com/';consoleLink.target='_blank';consoleLink.rel='noopener noreferrer';
 append('p',g.client_configured?'Client configured · source: '+g.client_source:'No Google app configured yet.');
 const form=append('form',undefined,'wz-sec');
 function field(label,type,value,max){const l=element('label',label,'wz-label');const i=element('input',undefined,'wz-input');i.type=type;i.value=value;i.maxLength=max;i.required=true;i.autocomplete='off';l.append(i);form.append(l);return i;}
 const redirect=field('Authorized redirect URI','url',g.redirect_uri||g.suggested_redirect_uri||new URL('api/google/callback',location.href).href,2048);
 button('Copy redirect URI',async()=>{try{await navigator.clipboard.writeText(redirect.value);dialog('Copied','Redirect URI copied.');}catch{dialog('Copy unavailable','Select and copy the redirect URI shown above.');}},form).type='button';
 const id=field('Client ID','text',g.client_id||'',230);
 const secret=field('Client secret (paste to save or replace)','password','',512);secret.minLength=8;
 const managed=g.client_source==='env';
 for(const i of [redirect,id,secret]){i.disabled=managed;i.oninput=()=>{clientHold??=WizardApp.update.hold('Unsaved Google app configuration');};}
 const save=button('Save Google app',()=>{},form,'primary');save.type='submit';save.disabled=managed;
 form.onsubmit=async e=>{e.preventDefault();try{await api('google/client',{client_id:id.value,client_secret:secret.value,redirect_uri:redirect.value});secret.value='';await refresh();clientHold?.release();clientHold=null;}catch(err){dialog('Could not save Google app',errorText(err.message));}};
 if(managed)append('p','Managed by environment. Ask the installer to change or remove the environment client settings.');
 else if(g.client_configured)button('Remove Google app',async()=>{if(!confirm('Remove the app credentials? All accounts will need reauthentication and new service consent.'))return;try{const response=await fetch('api/google/client',{method:'DELETE',credentials:'same-origin'});const d=await response.json();if(!response.ok)throw new Error(d.error);await refresh();clientHold?.release();clientHold=null;}catch(e){dialog('Could not remove Google app',errorText(e.message));}});
 append('small','If the suggested URI does not match your public HTTPS route, edit it before registering and saving. Replacing this client requires account reauthentication.');
}
function renderGoogle(){
 append('h2','Google accounts');const g=state.google;renderGoogleApp(g);
 append('span',g.state==='connected'?'Connected':g.state==='unavailable'?'Broker unavailable':'Not connected','badge');
 if(g.blocker)append('p',g.blocker==='google_configuration_required'?'Save your Google app above before connecting.':'Account operations unavailable: '+g.blocker);
 button('Connect Google',()=>authorize());button('Refresh accounts',()=>{if(clientHold&&!confirm('Discard unsaved Google app configuration and refresh?'))return;clientHold?.release();clientHold=null;refresh().catch(e=>dialog('Refresh unavailable',errorText(e.message)));});
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
