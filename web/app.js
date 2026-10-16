"use strict";
/* Connected accounts: one list home with drill-in views. Routes:
 *   root ─┬─ google ── account(id)
 *         ├─ thread(id) ── summary(id)
 *         └─ about(from)
 * Back (platform or on-screen) closes the dialog first, then climbs one route, and at root returns
 * false to the host. Every async write checks `nav` (view changed) or `generation` (summary fence). */

// Absolute same-origin base so the same files work when served from /wizard-connectors/design/.
const API = '/wizard-connectors/api/';
const YOUTUBE = 'https://www.googleapis.com/auth/youtube.readonly';
const $ = id => document.getElementById(id);
const viewEl = $('view'), dock = $('dock'), statusEl = $('status'), dialogEl = $('dialog');

let state = null;
let route = { name: 'loading' };
let nav = 0;                 // bumps on every navigation; late responses for an old view are dropped
let generation = 0;          // summary fence: bumps on start, cancel, leaving the thread and policy changes
let job = null;              // { id, thread } while a summary runs
let starting = false;        // summarize request in flight (prevents double submit)
let poll = null;
let result = null;           // { thread, text, source_ids, ... } human-view result
let outcome = null;          // { thread, text } last non-success summary outcome
let authLink = null;         // { account, href } Google consent page, opened by the user's own tap
let lookup = null;           // { text } last Music catalog lookup
let overlay = null, returnFocus = null, statusTimer = null;
const busy = new Set();
const conversations = new Map(), loadingConversations = new Set(), failedConversations = new Set();
const scrollMemo = new Map();

const PARENT = {
  google: () => ({ name: 'root' }),
  account: () => ({ name: 'google' }),
  thread: () => ({ name: 'root' }),
  summary: r => ({ name: 'thread', id: r.id }),
  about: r => r.from === 'google' ? { name: 'google' } : { name: 'root' },
};
const TERMINAL = ['blocked', 'cancelled', 'quarantined', 'expired'];
const PREPARING = ['google_configuration_required', 'invalid_redirect_configuration', 'credential_key_required'];

const MESSAGES = {
  private_route_disabled: 'Private processing is turned off. No model was called.',
  private_route_not_configured: 'The private route isn’t set up on this Wizard. No other model was tried.',
  private_provider_unavailable: 'The private model (tinfoil · glm-5-3) didn’t respond in time. No fallback model was tried.',
  attestation_failed: 'The private route couldn’t prove it was secure, so the summary was blocked.',
  worker_busy: 'Another summary is still running. Wait for it or cancel it.',
  incomplete_output: 'The private model stopped before finishing. Try again.',
  invalid_output: 'The private model returned nothing usable. Try again.',
  tool_output_rejected: 'The private model asked to use a tool. That output was rejected and no tool ran.',
  stale_delivery: 'Settings changed while the summary was running, so the result was discarded.',
  policy_changed: 'Private processing settings changed while summarizing, so the result was discarded.',
  retention_expired: 'This summary expired and was discarded.',
  owner_cancelled: 'Summary cancelled. Nothing was kept.',
  idempotency_conflict: 'That request clashed with an earlier one. Try again.',
  isolation_review_required: 'Google sign-in is waiting for an independent review.',
  google_configuration_required: 'Google sign-in isn’t set up on this Wizard yet.',
  invalid_redirect_configuration: 'Google sign-in isn’t set up on this Wizard yet.',
  credential_key_required: 'Google sign-in isn’t set up on this Wizard yet.',
  broker_unavailable: 'The account service isn’t responding. Your connections are unchanged.',
  invalid_authorization_url: 'Google sign-in returned an unexpected address, so it wasn’t opened.',
  authorization_busy: 'Too many sign-ins are in progress. Try again in a few minutes.',
  account_not_found: 'That account is no longer connected.',
  reauth_required: 'Google needs you to reconnect this account first.',
  incremental_consent_required: 'Allow YouTube read-only access for this account first.',
  explicit_consent_required: 'Linking needs your explicit choice. Nothing changed.',
  capability_denied: 'This account isn’t linked to the Music catalog.',
  invalid_video_id: 'A YouTube video ID is 11 characters: letters, numbers, - or _.',
  provider_unavailable: 'Google didn’t respond. Try again shortly.',
  provider_permission_denied: 'Google refused this request for the account.',
  local_storage_unavailable: 'This Wizard couldn’t save the change. Nothing was changed.',
  network_unavailable: 'Couldn’t reach this Wizard. Check your connection and try again.',
  owner_auth_required: 'Your preview session ended. Unlock it again to continue.',
};
const errorText = code => MESSAGES[code] || 'That didn’t work (' + code + '). Try again.';
const codeOf = e => e?.message || 'request_failed';

/* ---------- small DOM kit ---------- */
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k === 'key') e.dataset.key = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c);
  return e;
}
const ICON = {
  back: 'M15 5l-7 7 7 7', go: 'M9 5l7 7-7 7',
  chat: 'M5 5h14v10H10l-5 4z', info: 'M12 11v5M12 7.6v.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z',
  clock: 'M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', person: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20c1.4-3.6 4.2-5 7.5-5s6.1 1.4 7.5 5',
  note: 'M9 17V6l10-2v11M9 17a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM19 15a3 3 0 1 1-6 0 3 3 0 0 1 6 0z',
  shield: 'M12 3l7.5 3v5.5c0 4.6-3.2 8-7.5 9.5-4.3-1.5-7.5-4.9-7.5-9.5V6z', check: 'M5 12.5l4.5 4.5L19 7.5',
  lock: 'M7 11V8a5 5 0 0 1 10 0v3M5.5 11h13v9h-13z',
};
function icon(name) {
  const NS = 'http://www.w3.org/2000/svg', s = document.createElementNS(NS, 'svg'), p = document.createElementNS(NS, 'path');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); p.setAttribute('d', ICON[name]); s.append(p);
  return s;
}
const tile = content => h('span', { class: 'wz-tile', 'aria-hidden': 'true' }, typeof content === 'string' && ICON[content] ? icon(content) : content);
const section = (title, ...kids) => h('section', { class: 'wz-sec' }, h('h3', { class: 'wz-sec-h' }, ...[title].flat()), ...kids);
const list = (...rows) => h('ul', { class: 'wz-list', role: 'list' }, ...rows.flat().map(r => h('li', {}, r)));
const note = text => h('p', { class: 'ca-note', text });
function row({ key, id, glyph, title, sub, onclick, label, disabled }) {
  return h('button', { class: 'wz-row', type: 'button', key, id, onclick, 'aria-label': label, disabled },
    tile(glyph), h('span', { class: 'wz-main' }, h('b', { text: title }), sub && h('small', { text: sub })),
    h('span', { class: 'ca-go' }, icon('go')));
}
const fact = (title, sub, glyph) => h('div', { class: 'wz-row ca-static' }, glyph && tile(glyph),
  h('span', { class: 'wz-main' }, h('b', { text: title }), sub && h('small', { text: sub })));
function btn(text, onclick, { kind = '', key, label, disabled } = {}) {
  return h('button', { class: 'ca-btn' + (kind ? ' ' + kind : ''), type: 'button', key: key || text, 'aria-label': label, disabled, onclick, text });
}
const actions = (...kids) => h('div', { class: 'ca-actions' }, ...kids);
function viewHeader(title) {
  return h('div', { class: 'ca-top' },
    h('button', { class: 'ca-back', type: 'button', key: 'back', 'aria-label': 'Back', onclick: () => back() }, icon('back')),
    h('h2', { id: 'view-title', tabindex: '-1', text: title }));
}
function emptyState(glyph, title, text, ...kids) {
  return h('div', { class: 'ca-state' }, tile(glyph), h('strong', { text: title }), text && h('p', { text }), ...kids);
}
function announce(text) {
  clearTimeout(statusTimer); statusEl.textContent = text;
  statusTimer = setTimeout(() => { statusEl.textContent = ''; }, 4000);
}

/* ---------- API ---------- */
async function api(path, data) {
  const post = data !== undefined;
  let r, d = null;
  try {
    r = await fetch(API + path, { method: post ? 'POST' : 'GET', headers: post ? { 'Content-Type': 'application/json' } : {},
      body: post ? JSON.stringify(data) : undefined, credentials: 'same-origin', cache: 'no-store' });
  } catch { throw new Error('network_unavailable'); }
  try { d = await r.json(); } catch {}
  if (!r.ok || !d) {
    const e = new Error(d?.error || 'request_failed'); e.data = d;
    if (e.message === 'owner_auth_required' && path !== 'session') { e.handled = true; sessionEnded(); }
    throw e;
  }
  return d;
}
function requestId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, '0')).join('');
}
async function refresh() { state = await api('state'); render(); }

/* ---------- navigation and Back ---------- */
const routeKey = r => r.name + ':' + (r.id || '');
function go(next, from = null) {
  scrollMemo.set(routeKey(route), viewEl.scrollTop);
  nav++; route = next; lookup = null;
  if (next.name === 'root') authLink = null;
  document.body.dataset.view = next.name;
  render(false);
  viewEl.scrollTop = from ? scrollMemo.get(routeKey(next)) || 0 : 0;
  const opener = from && (viewEl.querySelector(`[data-key="${CSS.escape('open:' + routeKey(from))}"]`) ||
    (from.name === 'summary' ? dock.querySelector('[data-key="summarize"]') : null));
  (opener || $('view-title'))?.focus({ preventScroll: !!opener });
}
function back() {
  const up = PARENT[route.name];
  if (!up) return false;
  const from = route;
  if (from.name === 'thread') stop();   // leaving the thread cancels its summary and fences late replies
  go(up(from), from);
  return true;
}

/* ---------- dialog: opaque sheet, Back and Close are the same step ---------- */
function openDialog(title, text, choices = [{ label: 'OK' }]) {
  closeDialog(false);
  returnFocus = document.activeElement;
  $('dialog-title').textContent = title;
  $('dialog-text').textContent = text;
  $('dialog-actions').replaceChildren(...choices.map(c => h('button', { type: 'button', class: 'ca-btn' + (c.kind ? ' ' + c.kind : ''), text: c.label,
    onclick: () => { closeDialog(!c.run); c.run?.(); } })));
  dialogEl.showModal();
  overlay = WizardApp.back.push(() => { closeDialog(); return true; });
}
function closeDialog(restore = true) {
  if (dialogEl.open) dialogEl.close();
  overlay?.release(); overlay = null;
  if (restore && returnFocus?.isConnected) returnFocus.focus();
  returnFocus = null;
}
dialogEl.addEventListener('cancel', e => { e.preventDefault(); closeDialog(); });
const fail = (title, e) => { if (!e?.handled) openDialog(title, errorText(codeOf(e))); };

/* ---------- render ---------- */
const VIEWS = { loading: renderLoading, unlock: renderUnlock, error: renderError, root: renderRoot, google: renderGoogle,
  account: renderAccount, thread: renderThread, summary: renderSummary, about: renderAbout };
function render(keepFocus = true) {
  const key = keepFocus && (viewEl.contains(document.activeElement) || dock.contains(document.activeElement)) ? document.activeElement.dataset.key : null;
  viewEl.replaceChildren(); dock.replaceChildren(); dock.hidden = true;
  if (!state && !['loading', 'unlock', 'error'].includes(route.name)) route = { name: 'loading' };
  VIEWS[route.name]();
  if (key) (viewEl.querySelector(`[data-key="${CSS.escape(key)}"]`) || dock.querySelector(`[data-key="${CSS.escape(key)}"]`))?.focus({ preventScroll: true });
}
function renderLoading() { viewEl.append(h('div', { class: 'ca-state', role: 'status' }, h('strong', { text: 'Loading…' }))); }
function renderError() {
  const missing = route.id === 'platform';
  viewEl.append(h('h2', { id: 'view-title', class: 'wz-sr', tabindex: '-1', text: 'Connected accounts' }),
    emptyState('info', missing ? 'This app needs the Wizard platform' : 'Couldn’t load Connected accounts',
      missing ? 'The shared Wizard app core didn’t load, so this preview stays closed.' : 'Check your connection, then try again.',
      actions(btn('Try again', () => missing ? location.reload() : start(), { kind: 'primary', key: 'retry' }))));
}

function preparation(g) {
  if (g.state === 'unavailable' || g.blocker === 'broker_unavailable')
    return { title: 'Google isn’t responding right now', text: 'Account details can’t be read at the moment. Your connections are unchanged.' };
  if (g.blocker === 'isolation_review_required')
    return { title: 'Google sign-in is waiting for review', text: 'An independent privacy review has to finish before Google accounts can be connected. Nothing is needed from you.' };
  if (PREPARING.includes(g.blocker))
    return { title: 'Google sign-in is being prepared', text: 'This Wizard’s Google sign-in hasn’t been set up yet. Connect will appear here once it’s ready. Nothing is needed from you.' };
  if (g.blocker) return { title: 'Google sign-in is paused', text: 'Connect will return here when setup is complete.' };
  return null;
}
function googleSummary(g) {
  const n = g.accounts.length;
  if (g.state === 'unavailable' || g.blocker === 'broker_unavailable') return 'Not responding right now';
  if (n) return n + (n === 1 ? ' account' : ' accounts') + ' connected' + (g.blocker ? ' · sign-in paused' : '');
  if (g.blocker) return 'Being prepared · not available yet';
  return 'Not connected';
}
const google = () => ({ accounts: [], bindings: [], music: { state: 'unbound' }, ...state.google });
const connectable = g => !g.blocker && g.state !== 'unavailable';
const accountName = a => a.email || 'Google account';
const hasYouTube = a => (a.scopes || []).includes(YOUTUBE);
const statusLabel = a => a.status === 'active' ? 'Active' : a.status === 'reauth_required' ? 'Needs reconnecting' : String(a.status || 'Unknown').replaceAll('_', ' ');

function renderRoot() {
  const g = google();
  viewEl.append(
    h('h2', { id: 'view-title', class: 'wz-sr', tabindex: '-1', text: 'Connected accounts' }),
    section('Accounts', list(row({ key: 'open:google:', id: 'google-row', glyph: h('b', { class: 'ca-mono', text: 'G' }), title: 'Google', sub: googleSummary(g), onclick: () => go({ name: 'google' }) }))),
    section(['Private summaries', h('small', { text: 'Practice' })],
      list(state.threads.map(t => row({ key: 'open:thread:' + t.id, id: 'thread-' + t.id, glyph: 'chat', title: t.title,
        sub: 'Fictional sample · ' + t.count + (t.count === 1 ? ' message' : ' messages'), onclick: () => go({ name: 'thread', id: t.id }) }))),
      note('Sample conversations written for this preview. None of your own messages are connected.')),
    section('About', list(row({ key: 'open:about:', glyph: 'shield', title: 'How this preview works', sub: 'Privacy, private processing and setup details', onclick: () => go({ name: 'about', from: 'root' }) }))));
}

function authPanel(account) {
  if (!authLink || authLink.account !== account) return null;
  return h('div', { class: 'ca-notice' }, h('strong', { text: 'Continue on Google' }),
    h('p', { text: 'Google’s own sign-in page opens in a new tab. When you’ve finished there, come back and check for the account.' }),
    actions(h('a', { class: 'ca-btn primary', href: authLink.href, target: '_blank', rel: 'noopener noreferrer', key: 'auth-open', text: 'Continue to Google' }),
      btn('I’ve finished', () => { authLink = null; checkAgain(); }, { kind: 'ghost', key: 'auth-done' })));
}
function renderGoogle() {
  const g = google(), prep = preparation(g);
  viewEl.append(viewHeader('Google'));
  if (prep && !g.accounts.length) {
    viewEl.append(emptyState('clock', prep.title, prep.text,
      actions(btn('Check again', checkAgain, { key: 'google-refresh', disabled: busy.has('refresh') }),
        btn('Setup details', () => go({ name: 'about', from: 'google' }), { kind: 'ghost', key: 'open:about:' }))));
  } else if (prep) {
    viewEl.append(h('div', { class: 'ca-notice' }, h('strong', { text: prep.title }), h('p', { text: 'Connected accounts stay as they are. Adding or reconnecting accounts returns when sign-in is ready.' })));
  }
  if (g.accounts.length) {
    viewEl.append(section('Accounts', list(g.accounts.map(a => row({ key: 'open:account:' + a.id, glyph: 'person', title: accountName(a),
      sub: statusLabel(a) + ' · ' + (hasYouTube(a) ? 'Sign-in and YouTube read-only' : 'Sign-in only'), onclick: () => go({ name: 'account', id: a.id }) })))));
  }
  if (connectable(g)) {
    viewEl.append(section(g.accounts.length ? 'Add another' : 'Connect',
      authPanel(null) || actions(btn('Connect a Google account', () => authorize(null, false), { kind: 'primary', key: 'connect', disabled: busy.has('auth:new') })),
      note('Sign-in happens on Google’s own page. Never type your Google password into this app.')));
  }
  if (g.provider_revocation === 'pending' || g.provider_revocation === 'failed_manual_revocation_required') {
    viewEl.append(h('div', { class: 'ca-notice warn', role: 'status' }, h('strong', { text: 'Google hasn’t confirmed the removal' }),
      h('p', { text: 'Access was removed here. To finish, remove “Connected accounts” from the third-party access list in your Google Account.' })));
  }
  viewEl.append(musicSection(g, null));
  if (!prep || g.accounts.length) viewEl.append(actions(btn('Check again', checkAgain, { kind: 'ghost', key: 'google-refresh', disabled: busy.has('refresh') })));
}
function musicSection(g, onlyAccount) {
  const binding = g.bindings[0], bound = g.music.state === 'bound' && binding;
  const boundAccount = bound && g.accounts.find(a => a.id === binding.account);
  if (onlyAccount && bound && binding.account !== onlyAccount.id) return section('YouTube Music', fact('Not used for Music', 'Another account (' + (boundAccount ? accountName(boundAccount) : 'unknown') + ') is linked to the Music catalog.', 'note'));
  const kids = [fact(bound ? 'Music catalog linked' : 'Music catalog not linked',
    bound ? (boundAccount ? accountName(boundAccount) : 'Linked account') + ' · titles and details only' : g.accounts.length ? 'Choose an account with YouTube read-only access' : 'Available after a Google account is connected', 'note')];
  if (onlyAccount && !bound) {
    if (!hasYouTube(onlyAccount)) {
      if (connectable(g)) kids.push(authPanel(onlyAccount.id + ':yt') || actions(btn('Allow YouTube read-only', () => authorize(onlyAccount.id, true, ':yt'), { key: 'yt', disabled: busy.has('auth:' + onlyAccount.id) })));
    } else kids.push(actions(btn('Use for Music catalog', () => accountAction('music/bind', { account: onlyAccount.id, consent: true }, 'bind', 'Music catalog linked'), { kind: 'primary', key: 'bind', disabled: busy.has('bind') })));
  }
  if (bound) {
    const input = h('input', { class: 'wz-input', id: 'video-id', maxlength: '11', autocomplete: 'off', spellcheck: 'false', placeholder: 'e.g. dQw4w9WgXcQ', 'aria-describedby': 'video-help' });
    kids.push(h('form', { class: 'ca-lookup', onsubmit: e => { e.preventDefault(); catalogLookup(binding.account, input.value.trim()); } },
      h('label', { for: 'video-id', text: 'Look up a YouTube video ID' }),
      h('div', { class: 'ca-inline' }, input, h('button', { class: 'ca-btn', type: 'submit', key: 'lookup', disabled: busy.has('lookup'), text: 'Look up' })),
      h('small', { id: 'video-help', class: 'ca-help', text: 'Shows catalog details only. It doesn’t check or unlock playback.' })));
    if (lookup) kids.push(h('div', { class: 'ca-notice', role: 'status' }, h('strong', { text: 'Catalog details' }), h('p', { class: 'ca-pre', text: lookup.text })));
    kids.push(actions(btn('Unlink Music catalog', () => accountAction('music/unlink', {}, 'unlink', 'Music catalog unlinked'), { kind: 'ghost', key: 'unlink', disabled: busy.has('unlink') })));
  }
  kids.push(note('Linking lets Music look up titles and details in the YouTube catalog. It doesn’t grant audio playback, and the Music app’s own playback is unchanged.'));
  if (!onlyAccount) kids.push(actions(h('a', { class: 'ca-btn ghost', href: '/wizard-music/', target: '_top', key: 'open-music', text: 'Open Music' })));
  return section('YouTube Music', ...kids);
}
const SCOPES = {
  openid: ['Sign-in identity', 'Confirms which Google account this is'],
  email: ['Email address', 'Shows which account is connected'],
  'https://www.googleapis.com/auth/userinfo.email': ['Email address', 'Shows which account is connected'],
  profile: ['Basic profile', 'Your name and picture'],
  [YOUTUBE]: ['YouTube, read-only', 'Look up catalog details. No audio, no changes'],
};
function renderAccount() {
  const g = google(), a = g.accounts.find(x => x.id === route.id);
  if (!a) { viewEl.append(viewHeader('Account'), emptyState('person', 'This account is no longer connected', null)); return; }
  viewEl.append(viewHeader(accountName(a)),
    section('Status', fact(statusLabel(a), a.offline ? 'Stays connected in the background' : 'Connected for this session only', a.status === 'active' ? 'check' : 'clock')),
    section('Permissions you granted', list((a.scopes || []).map(s => fact(...(SCOPES[s] || [s, 'Granted on Google’s consent page'])))),
      note('Sign-in permissions on their own don’t allow Music catalog access or audio.')),
    musicSection(g, a));
  const manage = [];
  if (connectable(g)) manage.push(authPanel(a.id) || btn('Reconnect', () => authorize(a.id, hasYouTube(a)), { key: 'reconnect', disabled: busy.has('auth:' + a.id) }));
  manage.push(btn('Disconnect', () => openDialog('Disconnect ' + accountName(a) + '?',
    'This removes the account here and unlinks the Music catalog if it uses this account. Google will be asked to revoke this app’s access.',
    [{ label: 'Keep connected', kind: 'ghost' }, { label: 'Disconnect', kind: 'danger', run: () => disconnect(a.id) }]), { kind: 'danger', key: 'disconnect', disabled: busy.has('disconnect') }));
  viewEl.append(section('Manage', actions(...manage)));
}

function renderThread() {
  const t = state.threads.find(x => x.id === route.id);
  if (!t) { viewEl.append(viewHeader('Sample'), emptyState('chat', 'This sample isn’t available', null)); return; }
  viewEl.append(viewHeader(t.title), provenance('Written for this preview to show how private summaries work. These aren’t your messages, and no real chat is connected.'));
  const conv = conversations.get(t.id);
  if (conv) {
    viewEl.append(h('ol', { class: 'ca-messages', 'aria-label': 'Sample messages' }, conv.messages.map(m => h('li', { class: 'ca-msg' },
      h('div', { class: 'ca-msg-h' }, h('b', { text: m.sender }), h('time', { datetime: m.at, text: when(m.at) }), h('span', { class: 'ca-ref', 'aria-label': 'Message ' + m.id, text: m.id })),
      h('p', { text: m.text })))));
  } else if (failedConversations.has(t.id)) {
    viewEl.append(emptyState('chat', 'Couldn’t load this sample', null, actions(btn('Try again', () => { failedConversations.delete(t.id); render(); }, { key: 'conv-retry' }))));
  } else {
    viewEl.append(h('div', { class: 'ca-state', role: 'status' }, h('strong', { text: 'Loading sample…' })));
    loadConversation(t.id);
  }
  renderSummaryDock(t);
}
function provenance(text) { return h('div', { class: 'ca-provenance' }, h('span', { class: 'ca-tag', text: 'Fictional sample' }), h('p', { text })); }
function when(at) {
  const d = new Date(at);
  return isNaN(d) ? '' : d.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' });
}
function loadConversation(id) {
  if (loadingConversations.has(id)) return;
  loadingConversations.add(id);
  api('conversations/' + id).then(p => { conversations.set(id, p); }, () => { failedConversations.add(id); })
    .finally(() => { loadingConversations.delete(id); if (route.name === 'thread' && route.id === id) render(); });
}
function renderSummaryDock(t) {
  const p = state.private_route, kids = [];
  if (job && job.thread === t.id) {
    kids.push(h('div', { class: 'ca-busy', role: 'status' }, h('span', { class: 'ca-spin', 'aria-hidden': 'true' }),
      h('span', { text: 'Summarizing privately… this can take a minute.' })),
      h('div', { class: 'ca-dock-row' }, btn('Cancel', cancelSummary, { kind: 'ghost', key: 'cancel', label: 'Cancel summary' })));
  } else if (!p.configured) {
    kids.push(h('p', { class: 'ca-dock-note', text: 'Private summaries aren’t set up on this Wizard, so no model will be called.' }),
      h('div', { class: 'ca-dock-row' }, btn('Summarize privately', null, { kind: 'primary', key: 'summarize', disabled: true })));
  } else if (!p.enabled) {
    kids.push(h('p', { class: 'ca-dock-note', text: 'Private processing is turned off, so summaries are blocked and no model is called.' }),
      h('div', { class: 'ca-dock-row' }, btn('Summarize privately', null, { kind: 'primary', key: 'summarize', disabled: true }),
        btn('Turn on', togglePolicy, { kind: 'ghost', key: 'policy', label: 'Enable private processing', disabled: busy.has('policy') })));
  } else {
    kids.push(h('div', { class: 'ca-dock-row' }, btn(starting ? 'Starting…' : 'Summarize privately', () => summarize(t.id), { kind: 'primary', key: 'summarize', disabled: starting })),
      h('p', { class: 'ca-dock-note', text: 'Private route: tinfoil · glm-5-3. No tools, no fallback model.' }));
  }
  if (outcome?.thread === t.id && !(job && job.thread === t.id)) kids.unshift(h('p', { class: 'ca-outcome', role: 'status', text: outcome.text }));
  dock.append(...kids); dock.hidden = false;
}

/* ---------- summary jobs: one fenced run at a time ---------- */
function stop() {
  generation++; clearTimeout(poll); poll = null; starting = false;
  const id = job?.id; job = null;
  return id ? api('cancel/' + id, {}).catch(() => {}) : Promise.resolve();
}
async function summarize(thread) {
  if (job || starting) return;
  const gen = ++generation;
  starting = true; outcome = null; render();
  try {
    const j = await api('summarize', { thread, request_id: requestId() });
    if (gen !== generation) { api('cancel/' + j.id, {}).catch(() => {}); return; }
    starting = false; job = { id: j.id, thread }; render();
    poll = setTimeout(() => check(gen), 500);
  } catch (e) {
    if (gen !== generation) return;
    starting = false; finish(thread, e.handled ? null : errorText(codeOf(e)));
  }
}
async function check(gen) {
  if (gen !== generation || !job) return;
  const { id, thread } = job;
  try {
    const s = await api('jobs/' + id);
    if (gen !== generation) return;
    if (s.status === 'complete') {
      const r = await api('results/' + id);
      if (gen !== generation) return;
      job = null; poll = null;
      if (typeof r.text !== 'string' || !r.text.trim()) return finish(thread, errorText(r.reason || 'retention_expired'));
      result = { ...r, thread };
      announce('Private summary ready');
      go({ name: 'summary', id: thread });
    } else if (TERMINAL.includes(s.status)) {
      job = null; poll = null;
      finish(thread, s.status === 'cancelled' ? MESSAGES.owner_cancelled : s.status === 'expired' ? MESSAGES.retention_expired : errorText(s.reason || s.status));
    } else poll = setTimeout(() => check(gen), 1000);
  } catch (e) {
    if (gen !== generation) return;
    await stop();
    finish(thread, e.handled ? null : errorText(codeOf(e)));
  }
}
function finish(thread, text) {
  outcome = text ? { thread, text } : null;
  if (route.name === 'thread' && route.id === thread) render();
}
async function cancelSummary() {
  const thread = job?.thread;
  await stop();
  finish(thread, MESSAGES.owner_cancelled);
  dock.querySelector('[data-key="summarize"]')?.focus();
}

function renderSummary() {
  viewEl.append(viewHeader('Private summary'));
  if (!result || result.thread !== route.id) {
    viewEl.append(emptyState('clock', 'This summary is no longer available', 'Summaries are kept for a short time and then discarded.'));
    dock.append(h('div', { class: 'ca-dock-row' }, btn('Done', () => back(), { kind: 'primary', key: 'done' }))); dock.hidden = false;
    return;
  }
  const t = state.threads.find(x => x.id === result.thread), conv = conversations.get(result.thread);
  const ids = Array.isArray(result.source_ids) ? result.source_ids.map(String) : [];
  viewEl.append(provenance('Summary of “' + (t?.title || 'sample') + '”, a conversation written for this preview. Not your messages.'),
    h('article', { class: 'ca-prose', 'aria-label': 'Summary text' }, prose(String(result.text), new Set(ids))));
  if (ids.length) {
    viewEl.append(section('Sources', h('ol', { class: 'ca-sources', 'aria-label': 'Source messages' }, ids.map(id => {
      const m = conv?.messages.find(x => x.id === id);
      return h('li', {}, h('span', { class: 'ca-ref', text: id }), h('span', { class: 'ca-src' }, m ? h('b', { text: m.sender + ' ' }) : null, m ? m.text : 'Message ' + id));
    }))));
  }
  const verified = result.attestation?.security_verified === true;
  viewEl.append(section('How it was made', list(
    fact('tinfoil · glm-5-3', verified ? 'Private route verified before and after this run' : 'Private route', 'shield'),
    fact('Kept here only', 'Up to 15 minutes, discarded on restart. Agents never see the text.', 'lock'),
    fact('Shown as plain text', 'Model output is untrusted. Links and markup are never active.', 'info'))));
  dock.append(h('div', { class: 'ca-dock-row' }, btn('Done', () => back(), { kind: 'primary', key: 'done' }),
    btn('Discard', discardSummary, { kind: 'ghost', key: 'discard', label: 'Discard summary', disabled: busy.has('discard') })));
  dock.hidden = false;
}
/* Readable prose from untrusted model text. Text nodes only: headings, lists and paragraphs are
 * recognised by line shape, Markdown emphasis is stripped, known source IDs become reference chips. */
function prose(text, ids) {
  const out = [], plain = s => s.replace(/\*\*(.+?)\*\*/g, '$1').replace(/__(.+?)__/g, '$1').replace(/`([^`]+)`/g, '$1');
  const inline = s => {
    const parts = plain(s).split(/\b([a-z]\d{1,3})\b/);
    return parts.map((p, i) => i % 2 && ids.has(p) ? h('span', { class: 'ca-ref', text: p }) : p);
  };
  let para = [], items = null;
  const flush = () => {
    if (para.length) { out.push(h('p', {}, inline(para.join(' ')))); para = []; }
    if (items) { out.push(items); items = null; }
  };
  for (const raw of text.replace(/\r/g, '').split('\n')) {
    const line = raw.trim();
    if (!line || /^([-*_=]\s*){3,}$/.test(line)) { flush(); continue; }
    const heading = line.match(/^#{1,6}\s+(.*)$/) || line.match(/^\*\*([^*]+?):?\*\*:?$/);
    if (heading) { flush(); out.push(h('h3', { class: 'ca-prose-h' }, plain(heading[1]).replace(/:$/, ''))); continue; }
    const item = line.match(/^([-*•+]|\d+[.)])\s+(.*)$/);
    if (item) {
      if (para.length) { out.push(h('p', {}, inline(para.join(' ')))); para = []; }
      const ordered = /\d/.test(item[1]);
      if (!items || (items.tagName === 'OL') !== ordered) { if (items) out.push(items); items = h(ordered ? 'ol' : 'ul'); }
      items.append(h('li', {}, inline(item[2])));
      continue;
    }
    if (items) { out.push(items); items = null; }
    para.push(line);
  }
  flush();
  return out;
}
async function discardSummary() {
  if (busy.has('discard')) return;
  const id = result?.id;
  busy.add('discard'); render();
  if (id) await api('cancel/' + id, {}).catch(() => {});
  busy.delete('discard');
  const thread = result?.thread; result = null;
  if (route.name === 'summary') { outcome = { thread, text: 'Summary discarded.' }; back(); }
}

function renderAbout() {
  const p = state.private_route, a = state.assurance || {}, g = google();
  const blockerDetail = {
    isolation_review_required: 'Waiting for the independent isolation review to be approved.',
    google_configuration_required: 'The installer needs a registered Google Web client and secret, the exact callback address and a credential encryption key.',
    invalid_redirect_configuration: 'The configured Google callback address isn’t an accepted secure address.',
    credential_key_required: 'The installer needs a credential encryption key.',
    broker_unavailable: 'The separate account service didn’t answer.',
  }[g.blocker] || (g.blocker ? 'Setup step pending.' : 'Ready.');
  viewEl.append(viewHeader('How this preview works'),
    section('This preview', list(
      fact(state.synthetic_only ? 'Fictional samples only' : 'Real data', state.synthetic_only ? 'Private summaries use conversations written for this preview' : 'Connected data sources are in use', 'chat'),
      fact(a.real_data_eligible ? 'Real messages eligible' : 'Your real messages aren’t connected', a.real_data_eligible ? 'Approved for real data' : 'This preview isn’t yet approved for real data', 'lock'),
      fact(a.host_admin_isolation ? 'Isolated from the host administrator' : 'Host administrator is trusted', a.host_admin_isolation ? 'The host administrator can’t read this app’s data' : 'Whoever runs this Wizard’s server can reach this app’s data', 'person'),
      fact(a.network_confinement ? 'Network confined' : 'Network not confined', a.network_confinement ? 'This app can only reach its approved services' : 'Outbound network access isn’t restricted', 'shield'))),
    section('Private processing',
      h('button', { class: 'wz-row ca-switch-row', type: 'button', role: 'switch', 'aria-checked': String(p.enabled), key: 'policy-switch', disabled: busy.has('policy'),
        'aria-label': p.enabled ? 'Disable private processing' : 'Enable private processing', onclick: togglePolicy },
        tile('shield'), h('span', { class: 'wz-main' }, h('b', { text: 'Private processing' }), h('small', { text: p.enabled ? 'On · summaries may call the private model' : 'Off · summaries are blocked, no model is called' })),
        h('span', { class: 'ca-sw' + (p.enabled ? ' on' : ''), 'aria-hidden': 'true' }, h('i'))),
      list(fact(p.model || 'tinfoil/glm-5-3', p.configured ? 'Private model route is set up' : 'Private model route isn’t set up', 'info'),
        fact('No fallback, no tools', (p.fallback ? 'A fallback model is allowed' : 'If the private model fails, nothing else is tried') + (p.tools ? ' · tools allowed' : ' · it can’t run tools'), 'check')),
      note('Summaries stay in this app for up to 15 minutes and are discarded on restart. Agents can see that a job ran, never what it said.')),
    section('Google sign-in', list(
      fact(googleSummary(g), blockerDetail, 'clock'),
      fact('Credentials stay in the account service', 'Google tokens are held by a separate broker, never by this page.', 'lock')),
      g.blocker ? h('p', { class: 'ca-note ca-code' }, 'Status code: ', h('code', { text: g.blocker })) : null),
    section('YouTube Music', list(
      fact('Catalog details only', 'Titles and details come from the YouTube Data API', 'note'),
      fact('Playback is separate', 'Audio stays with the Music app. Connecting Google doesn’t authorize or change it.', 'info'))));
}

/* ---------- account actions ---------- */
async function guarded(key, run) {
  if (busy.has(key)) return;
  busy.add(key); render();
  try { await run(); } finally { busy.delete(key); render(); }
}
function checkAgain() {
  return guarded('refresh', async () => {
    try { await refresh(); announce('Up to date'); } catch (e) { fail('Couldn’t check accounts', e); }
  });
}
function authorize(account, youtube, suffix = '') {
  const n = nav;
  return guarded('auth:' + (account || 'new'), async () => {
    try {
      const auth = await api('google/connect', account ? { account, youtube } : { youtube });
      const url = new URL(auth.authorization_url);
      if (url.origin !== 'https://accounts.google.com') throw new Error('invalid_authorization_url');
      if (n === nav) authLink = { account: account ? account + suffix : null, href: url.href };
    } catch (e) { if (n === nav) fail('Can’t open Google sign-in', e); }
  });
}
function accountAction(path, data, key, done) {
  const n = nav;
  return guarded(key, async () => {
    try { await api(path, data); await refresh(); announce(done); }
    catch (e) { if (n === nav) fail('That didn’t work', e); }
  });
}
function disconnect(id) {
  const n = nav;
  return guarded('disconnect', async () => {
    try {
      const r = await api('google/disconnect', { account: id });
      await refresh();
      announce(r.provider_revocation === 'revoked' ? 'Account disconnected' : 'Disconnected here. Google hasn’t confirmed yet.');
      if (n === nav && route.name === 'account') go({ name: 'google' });
    } catch (e) { if (n === nav) fail('Couldn’t disconnect', e); }
  });
}
function catalogLookup(account, videoId) {
  const n = nav;
  if (!/^[A-Za-z0-9_-]{11}$/.test(videoId)) { lookup = { text: errorText('invalid_video_id') }; render(); return; }
  return guarded('lookup', async () => {
    try {
      const r = await api('music/catalog', { account, video_id: videoId });
      if (n === nav) lookup = { text: r.items.map(i => i.title).join('\n') || 'No catalog item found for that ID. This says nothing about playback.' };
    } catch (e) { if (n === nav && !e.handled) lookup = { text: errorText(codeOf(e)) }; }
  });
}
function togglePolicy() {
  const next = !state.private_route.enabled;
  return guarded('policy', async () => {
    await stop(); result = null; outcome = null;
    try { await api('policy', { enabled: next }); await refresh(); announce(next ? 'Private processing on' : 'Private processing off'); }
    catch (e) { fail('Couldn’t change private processing', e); }
  });
}

/* ---------- owner session ---------- */
function sessionEnded() {
  stop(); closeDialog(false); result = null; state = null;
  if (route.name !== 'unlock') go({ name: 'unlock' });
}
let unlockError = '';
function renderUnlock() {
  const input = h('input', { class: 'wz-input', id: 'owner-token', type: 'password', autocomplete: 'off', required: true, 'aria-describedby': 'owner-help' });
  viewEl.append(h('div', { class: 'ca-state' }, tile('lock'), h('h2', { id: 'view-title', tabindex: '-1', text: 'Unlock this preview' }),
    h('p', { text: 'Enter the owner access token from this Wizard’s installer.' })),
    h('form', { class: 'ca-form', onsubmit: e => { e.preventDefault(); unlock(input); } },
      h('label', { for: 'owner-token', text: 'Owner access token' }), input,
      h('small', { id: 'owner-help', class: 'ca-help', text: 'This isn’t your Google password. Google sign-in only ever happens on Google’s own page.' }),
      unlockError ? h('p', { class: 'ca-error', role: 'alert', text: unlockError }) : null,
      actions(h('button', { class: 'ca-btn primary', type: 'submit', key: 'unlock', disabled: busy.has('unlock'), text: busy.has('unlock') ? 'Unlocking…' : 'Unlock' }))));
}
async function unlock(input) {
  if (busy.has('unlock')) return;
  const token = input.value;
  busy.add('unlock'); unlockError = ''; render();
  try {
    await api('session', { token });
    busy.delete('unlock');
    await start();
  } catch (e) {
    busy.delete('unlock');
    unlockError = codeOf(e) === 'owner_auth_required' ? 'That token didn’t work. Use the owner token from the installer, never a Google password.' : errorText(codeOf(e));
    render(); $('owner-token')?.focus();
  }
}

/* ---------- start ---------- */
async function start() {
  if (route.name !== 'loading') go({ name: 'loading' });
  try {
    state = await api('state');
    go({ name: 'root' });
  } catch (e) {
    if (!e.handled) go({ name: 'error' });
  }
}
if (!window.WizardApp) {
  route = { name: 'error', id: 'platform' }; document.body.dataset.view = 'error'; render(false);
} else {
  WizardApp.ready({ name: 'Connected accounts', version: '0.2.0' });
  WizardApp.back.register({ canGoBack: () => !!PARENT[route.name], back });
  start();
}
