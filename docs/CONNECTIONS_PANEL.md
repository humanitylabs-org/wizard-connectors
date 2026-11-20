# Agent access in one place (Connections panel)

Status: behind the app switch `grants-panel` (off by default). Issue: humanitylabs-org/wizard-connectors#49, as
rescoped by Miguel on 20 Nov 2026: one screen for every connected account and what agents may do with it, with
**no second source of truth**.

## What it is

Connected accounts > **Agent access** lists every app that holds connected accounts on this box and, for each one,
which agents may use it. Changes go to the place that already keeps them. Connected accounts stores no grants.

| Shown | Kept by (the only source) | How the panel reads and sets it |
|---|---|---|
| Google accounts connected here | this app's Google broker | `/api/state` (as before) |
| Which agents may use an app (the agent.json ticks) | the Agent Service, enforced by its MCP gateway (wizard-os `spec/AGENTS.md` section 5, `spec/PERMISSIONS.md`) | the page calls the Agent Service owner routes `GET` / `PUT /wizard/v1/apps/<app id>/agents` (`{agents: [ids]}` = exactly the agents ticked), the same routes the App Manager's Connections page uses |
| What agents may do with Mail through this app (No access / Read-only / Draft only) | this app (`mail_access.py`, `DATA_DIR/mail-access.json`) | `/api/mail/access` (as before) |
| Google's accounts (names only) and its agent level for mail and calendar (one level for every agent) | the Google app (`agent_access.py`), which enforces it | the page calls the Google app's owner route `GET` / `POST /wizard-google/api/panel/agent-access` (header `X-Wizard-Agent-Access: 1`, same origin), behind the Google app's switch `agent-access-panel` (wizard-google#30). Off, or an older Google app: "set in Google for now" |
| Another app's own agent level (Messenger, Microsoft) | that app, which enforces it | not yet: the panel says "set in <app> for now" (follow-ups below) |

App-to-app grants stay with the App Manager (`wizard-grants.json`); this panel does not show or change them.

## Which apps

Installed account apps, by installed app id: `connected-accounts`, `wizard-google`, `wizard-microsoft`, `messenger`,
`wizard-mail`, `money`, `wizard-health`, `wizard-apple-health`, `wizard-fitbit`, `wizard-oura`, `wizard-whoop`,
`wizard-withings` (`web/connections.js` `APPS`). An app the Agent Service answers `404 app_not_found` for is not
installed and is left out.

## When the Agent Service can't be asked

On a box with the browser boundary on (wizard-os#133) the sandboxed page carries no shell token, so the Agent Service
refuses it; a local preview has no Agent Service at all. The panel then still lists this app's accounts and Mail's
level, and says the ticks are set in App Manager > Connections. Nothing is guessed or cached.

## Follow-ups

- humanitylabs-org/wizard-ux#1668: a bounded shell service so the panel works under the browser boundary.
- humanitylabs-org/wizard-google#30: done (Google's level, above).
- humanitylabs-org/wizard-messenger#342, humanitylabs-org/wizard-microsoft#10:
  let the panel read and set each app's own agent level, still stored and enforced by that app.
- Enforcing anything new, and folding the connector repos together, are out of this slice.
