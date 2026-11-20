"use strict";
// Agent access in one place (switch grants-panel, wizard-connectors#49, Miguel's rescope 20 Nov 2026).
// This screen stores nothing itself. Which agents may use an app is the owner's agent.json ticks, kept by the
// Agent Service (wizard-os spec/AGENTS.md section 5, PERMISSIONS.md): read with GET and set with PUT
// /wizard/v1/apps/<app id>/agents, the same owner routes the App Manager's Connections page uses. An app's own finer
// level (Mail's here, Messenger's in Messenger) stays with that app; Messenger's is read and set through Messenger's
// own route when it offers one (wizard-messenger#342). docs/CONNECTIONS_PANEL.md.
(function(root){
 // Apps that hold connected accounts, by installed app id. Only the ones the Agent Service knows are shown.
 const APPS=[
  {id:'connected-accounts',name:'Connected accounts',holds:'Google accounts connected here',own:'here'},
  {id:'wizard-google',name:'Google',holds:'Google accounts signed in to the Google app',own:'Google'},
  {id:'wizard-microsoft',name:'Microsoft',holds:'Microsoft accounts',own:'Microsoft'},
  {id:'messenger',name:'Messenger',holds:'WhatsApp, Signal and other chat accounts',own:'Messenger',recommended:'Draft-only',levels:'/messenger/api/agent-levels'},
  {id:'wizard-mail',name:'Mail',holds:'Mail accounts',own:'Mail'},
  {id:'money',name:'Finances',holds:'Bank accounts',own:'Finances'},
  {id:'wizard-health',name:'Health',holds:'Health accounts',own:'Health'},
  {id:'wizard-apple-health',name:'Apple Health',holds:'Apple Health',own:'Apple Health'},
  {id:'wizard-fitbit',name:'Fitbit',holds:'Fitbit account',own:'Fitbit'},
  {id:'wizard-oura',name:'Oura',holds:'Oura account',own:'Oura'},
  {id:'wizard-whoop',name:'WHOOP',holds:'WHOOP account',own:'WHOOP'},
  {id:'wizard-withings',name:'Withings',holds:'Withings account',own:'Withings'},
 ];
 const BASE='/wizard/v1/apps/';
 const opts=(method,body)=>({method,credentials:'same-origin',cache:'no-store',redirect:'error',
  headers:body===undefined?{Accept:'application/json'}:{Accept:'application/json','Content-Type':'application/json'},
  body:body===undefined?undefined:JSON.stringify(body)});
 function agentsOf(value){
  if(!value||!Array.isArray(value.agents))return null;
  return value.agents.filter(a=>a&&typeof a.id==='string').map(a=>({id:a.id,label:typeof a.label==='string'&&a.label?a.label:a.id,enabled:a.enabled===true,privacy:a.privacy==='private'?'private':'standard'}));
 }
 // One app's agent ticks. {state:'ok', agents} | {state:'absent'} (not installed) | {state:'unavailable'}.
 async function readApp(fetchFn,id){
  let r;
  try{r=await fetchFn(BASE+encodeURIComponent(id)+'/agents',opts('GET'));}catch{return {state:'unavailable'};}
  let d=null;try{d=await r.json();}catch{d=null;}
  if(r.status===404&&d&&d.error==='app_not_found')return {state:'absent'};
  const agents=r.ok?agentsOf(d):null;
  return agents?{state:'ok',agents}:{state:'unavailable'};
 }
 // An app's own agent level, read from that app (wizard-messenger#342: Messenger's GET /api/agent-levels, behind
 // Messenger's switch connected-accounts-levels). The app keeps and enforces it; nothing is copied here.
 // {state:'ok', accounts:[{label,name}], agents:[{id,label,main,level}], levels:[{id,label,recommended}]} |
 // {state:'off'} (the app has no such route yet, or its switch is off) | {state:'unavailable'}.
 const levelOpts=(method,body)=>{const o=opts(method,body);if(body!==undefined)o.headers['X-Wizard-Agent-Level']='1';return o;};
 function levelsOf(value){
  if(!value||!Array.isArray(value.agents)||!Array.isArray(value.levels))return null;
  const text=v=>typeof v==='string'?v:'';
  return {state:'ok',
   accounts:(Array.isArray(value.accounts)?value.accounts:[]).filter(a=>a&&typeof a==='object').map(a=>({label:text(a.label)||text(a.network),name:text(a.name)})),
   agents:value.agents.filter(a=>a&&typeof a.id==='string'&&typeof a.level==='string').map(a=>({id:a.id,label:text(a.label)||a.id,main:a.main===true,level:a.level})),
   levels:value.levels.filter(l=>l&&typeof l.id==='string').map(l=>({id:l.id,label:text(l.label)||l.id,recommended:l.recommended===true}))};
 }
 async function readLevels(fetchFn,url){
  let r;
  try{r=await fetchFn(url,opts('GET'));}catch{return {state:'unavailable'};}
  if(r.status===404)return {state:'off'};
  let d=null;try{d=await r.json();}catch{d=null;}
  return (r.ok&&levelsOf(d))||{state:'unavailable'};
 }
 // Sets one agent's level in that app, then answers the app's levels as now stored.
 async function setLevel(fetchFn,url,agent,level){
  const r=await fetchFn(url,levelOpts('POST',{agent,level}));
  let d=null;try{d=await r.json();}catch{d=null;}
  const out=r.ok?levelsOf(d):null;
  if(!out){const e=new Error((d&&d.code)||(d&&d.error)||'request_failed');e.status=r.status;throw e;}
  return out;
 }
 // Every account app at once. reachable=false: the Agent Service could not be asked from this page.
 async function load(fetchFn){
  const rows=await Promise.all(APPS.map(async app=>({...app,...await readApp(fetchFn,app.id)})));
  const reachable=rows.some(x=>x.state!=='unavailable');
  const apps=rows.filter(x=>x.state==='ok'||(x.id==='connected-accounts'));
  await Promise.all(apps.filter(a=>a.levels).map(async a=>{a.ownLevels=await readLevels(fetchFn,a.levels);}));
  return {reachable,apps};
 }
 // Sets exactly which agents may use one app (the owner's tick), then answers the app's ticks as now stored.
 async function setAgents(fetchFn,id,ids){
  const r=await fetchFn(BASE+encodeURIComponent(id)+'/agents',opts('PUT',{agents:ids}));
  let d=null;try{d=await r.json();}catch{d=null;}
  const agents=r.ok?agentsOf(d):null;
  if(!agents){const e=new Error((d&&d.error)||'request_failed');e.status=r.status;throw e;}
  return agents;
 }
 // The ids to PUT when the owner turns one agent on or off for an app.
 function toggled(agents,id,on){return agents.filter(a=>a.id===id?on:a.enabled).map(a=>a.id);}
 const api={APPS,load,setAgents,toggled,readApp,readLevels,setLevel};
 if(typeof module==='object'&&module.exports)module.exports=api;else root.WizConnections=api;
})(typeof window==='undefined'?globalThis:window);
