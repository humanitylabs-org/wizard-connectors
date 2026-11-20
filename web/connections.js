"use strict";
// Agent access in one place (switch grants-panel, wizard-connectors#49, Miguel's rescope 20 Nov 2026).
// This screen stores nothing itself. Which agents may use an app is the owner's agent.json ticks, kept by the
// Agent Service (wizard-os spec/AGENTS.md section 5, PERMISSIONS.md): read with GET and set with PUT
// /wizard/v1/apps/<app id>/agents, the same owner routes the App Manager's Connections page uses. An app's own finer
// level (Mail's here, Messenger's in Messenger) stays with that app. docs/CONNECTIONS_PANEL.md.
(function(root){
 // Apps that hold connected accounts, by installed app id. Only the ones the Agent Service knows are shown.
 const APPS=[
  {id:'connected-accounts',name:'Connected accounts',holds:'Google accounts connected here',own:'here'},
  {id:'wizard-google',name:'Google',holds:'Google accounts signed in to the Google app',own:'Google'},
  {id:'wizard-microsoft',name:'Microsoft',holds:'Microsoft accounts',own:'Microsoft'},
  {id:'messenger',name:'Messenger',holds:'WhatsApp, Signal and other chat accounts',own:'Messenger',recommended:'Draft-only'},
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
 // Every account app at once. reachable=false: the Agent Service could not be asked from this page.
 async function load(fetchFn){
  const rows=await Promise.all(APPS.map(async app=>({...app,...await readApp(fetchFn,app.id)})));
  const reachable=rows.some(x=>x.state!=='unavailable');
  return {reachable,apps:rows.filter(x=>x.state==='ok'||(x.id==='connected-accounts'))};
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
 const api={APPS,load,setAgents,toggled,readApp};
 if(typeof module==='object'&&module.exports)module.exports=api;else root.WizConnections=api;
})(typeof window==='undefined'?globalThis:window);
