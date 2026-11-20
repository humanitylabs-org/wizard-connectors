# wizard.app-grants/1: what each agent may do with each connected account

Status: first slice, behind the app switch `grants-panel` (off by default). Issue:
humanitylabs-org/wizard-connectors#49 (Miguel, 20 Nov 2026: grants only mean something if the agent can't get around
them, so they live outside the agent and outside the Agent Service, here in Connected accounts).

## What it is

- **One grants store on the box** (Connected accounts, `DATA_DIR/agent-grants.json`). For each connected account and
  each agent: `none`, `read`, `draft` or `send`. An app-specific row may narrow (or widen, up to the account's cap) the
  account-wide level for one app.
- **Only the owner changes it**, by tapping in Connected accounts > Agent access (owner session API below). Apps, the
  MCP gateway and agents can only ask. The agent's own MCP on this app has no grant tool.
- **A new agent gets nothing** until the owner grants it. Any agent an app asks about is added to the panel with
  No access so the owner sees it.
- **Recommended levels:** Messenger accounts show Draft as recommended (shown, never granted by itself).
- **Caps per kind of account** (the highest level that means something): `google` draft, `microsoft` draft (agents
  never send mail; the owner sends from Mail), `messenger` send, `bank` read, `health` read, `ai` send, `other` send.
  A registering app may lower the cap with `max`.
- **Audit log** (`DATA_DIR/grants-audit.jsonl`, last 500 to 1000 answers): every check, allowed or refused, with time,
  asking app, agent, account id, action, app, result and reason. No content, no tokens.

## Accounts

- Google accounts connected here are listed as `google:<account id>`.
- Other connector apps keep their own back ends and list their accounts here: `POST /service/grants/v1/accounts`
  (below). Their ids become `<app id>:<their id>`. A new list replaces that app's earlier one.

## Service API (apps and the MCP gateway)

Box app network, like the other service APIs: `http://wizard-connectors-calendar:8799/service/grants/v1/...`. The
caller sends its App Manager grant key as `X-Wizard-Grant`; any app with an incoming grant row to this app may ask,
and the matched row's `from` is recorded as who asked. While the switch is off every route answers
`409 {"error":{"code":"service_off"}}`; callers then keep their current behaviour.

`GET status`:

```json
{"contract": "wizard.app-grants/1", "levels": ["none", "read", "draft", "send"],
 "accounts": [{"id": "google:abc", "kind": "google", "label": "me@example.com", "max": "draft"}]}
```

`POST check` with `{"agent": "main", "account": "google:abc", "action": "read" | "draft" | "send", "app": "wizard-mail"?}`
always answers 200 when the request is well formed:

```json
{"contract": "wizard.app-grants/1", "allowed": false, "level": "none", "need": "read", "reason": "not_granted"}
```

`reason` is one of `granted`, `not_granted`, `not_offered` (above the account's cap) or `account_unknown`. The caller
must refuse the agent's call unless `allowed` is true, and treat any error or timeout as a refusal.

`POST accounts` with `{"accounts": [{"id": "whatsapp", "kind": "messenger", "label": "WhatsApp", "max": "send"?}]}`
(at most 64; `kind` is one of the kinds above except `google`) answers `{"registered": ["<app>:whatsapp"]}`.

There is no service route that changes a grant.

## Owner API (Connected accounts' own screen, owner session)

- `GET /api/grants`: `{contract, agents, levels, accounts: [{id, kind, label, source, max, levels, recommended?,
  agents: {<agent>: <level>}, apps?}]}`.
- `POST /api/grants` `{account, agent, level, app?}`: set one level; answers the new view.
- `POST /api/grants/agents` `{agent}`: add an agent by name before any app asked about it.
- `GET /api/grants/audit`: the latest 50 answers, newest first.

## Not in this slice

Enforcing the answer in every app and in the Agent Service / MCP gateway, and folding the connector repos together.
Those are follow-ups once this contract is settled. Today's per-app checks (for example Mail's level in
`mail_access.py`) keep working unchanged.
