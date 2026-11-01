# Guided Google app setup

## Owner model

The owner uses their own **main Google account** to own **one** project + Web OAuth client. The wizard needs **no Google account**. One app connects all the owner's accounts; it is a permission key, not a data store. External + In production is the personal default. Internal is only for an administrator's Workspace organization.

The Google panel separates **Your Google app — one time** from **Your Google accounts — add as many as you like**. Agent setup first shows three unchecked, labelled agreements with official document links and a country picker (language-region default when available). Agree and continue stays disabled until every box and country are selected. Only a successful owner-authenticated same-origin save opens the handoff; saving failures retain choices and never start setup. Shared Back returns through each prior screen; the manual entry links the same documents without recording delegated acceptance. Agent setup then shows exactly `Set up my Google app` and a Copy message button. The shared host's `nav.openThread` forbids `__new__`, admits only selected thread apps, and `openContextDraft` is Notifications-only: Connected accounts must not invent a send API or bypass those guards.

Manual setup has seven screens: account/audience; project; Calendar API; Auth branding/audience/production; Web client + exact redirect URI Copy; validated credentials Save; connect accounts and grant/bind Calendar. Steps 1–5 require owner confirmation, step 6 requires an actual successful save, step 7 finishes into a compact configured row. Shared Back goes to the preceding step, then setup entry, then the app root. No URL navigation or exit sentinels. Unsaved credentials hold app updates and must be discarded explicitly on Back.

## Reuse inventory

- **REUSE** `WizardApp` (`/wizard-os-home/core/app-client.js`) for Appearance v1, root/nested/overlay Back and update holds; shared kit/skin layers for inputs/buttons. Native `progress`, labelled fields and checkboxes, no parallel design system.
- **EXTEND** Connected accounts' domain-only Google view using the existing Setup checklist → in-app screen pattern (`wizard-ux/web/setup/setup.js`), with the same shared Back callback. Examined `web/core/tour.js`, Setup and COMPONENTS: neither exports a reusable generic setup-stepper/checklist; Tour depends on the live microphone/gesture shell, so importing it would be incorrect. No new platform component or API.
- **NEW** only app-owned Google setup state/capability, broker typed operations and Google Console task automation. No replacement for shared chat, theme, auth, history or human takeover.

## MCP and intake protocol

Existing MCP Bearer authentication protects both new tools. Empty-object arguments only:

- `google_app_setup_status`: `configured`, `managed`, `redirect_uri`, `required_apis`, `required_scopes`, `agreements: {accepted, version, country}`. No client ID, secret, email, accounts or calendar content.
- `google_app_setup_begin`: `intake_url`, `expires_in: 1800`, `redirect_uri`, `agreements: {accepted, version, country}`. The URL is `http://wizard-connectors-calendar:8799/api/google/setup/intake#<capability>`, on the existing private Wizard main-network ingress. The fragment never goes in an HTTP request URL or access log. A new begin invalidates any earlier setup; restart invalidates all.

The automation process splits the fragment and POSTs **only** `{client_id,client_secret}` with `Authorization: Bearer <capability>` and no cookies, Origin or proxy/forwarded headers. It does not fetch through a Google-page browser context (CORS/private-network-access would block that); the browser-control script carries values in its isolated Python memory directly to the fixed internal ingress. Proxy environment variables and HTTP redirects are disabled. Intake is not a public browser form and must not be opened as a browser URL.

Ingress permits the fixed internal alias/loopback host and rejects public Host, `Origin`, `Cookie`, `Forwarded`, `Via`, `X-Forwarded-*`, `Tailscale-*` before relay. It rewrites Host to the fixed app upstream only for that checked lane. The UI service independently rejects public/forwarded/browser requests. Broker validates the 256-bit capability digest, expires and consumes it atomically under its lock **before validating credentials**. Wrong/expired/used token returns 403; malformed values 400; success is only `{ok:true}`. Unknown request fields reject before broker delivery. MCP/owner/Calendar credentials cannot substitute for the minted capability.

Only the broker writes credentials: same encrypted atomic store, environment precedence, replacement invalidation/reauthentication and fixed Google endpoints as before. Intake has no caller-selected redirect URI or provider URL. Logs suppress bodies, authorization headers and exception values. The public client ID remains visible in the human owner view as before, not in MCP/status/intake results. Memory on the trusted browser/script/UI/RPC/broker hosts is in the threat boundary; this is not host-administrator isolation.

## Script and human gates

Source: `skill/scripts/google_cloud_setup.py`, shipped alongside `skill/SKILL.md` and included in the image. Needs Python Playwright and the Human Handoff CLI/owner-only session metadata on the same automation host, not in the credential-broker runtime. Start a fresh empty default disposable profile, never a shared logged-in browser. Use a private loopback intake tunnel when that host cannot resolve the internal ingress alias.

```sh
# Values come from MCP; neither contains a Google client secret.
# Keep the capability in the environment, not in shared logs.
hermes-human-handoff doctor
hermes-human-handoff start --purpose oauth --ttl 3600 --url https://console.cloud.google.com/auth/overview
# Owner types their own password and 2FA during takeover. Pause ALL inspection.
# After the owner reports completion: run on that same host (sid is from start).
# run injects HANDOFF_SESSION_ID and HANDOFF_CDP_URL; do not use BROWSER_CDP_URL.
hermes-human-handoff run <session_id> skill/scripts/google_cloud_setup.py
# The task signs out and stops/deletes this profile, including on failure.
hermes-human-handoff status <session_id>
```

Set `GOOGLE_SETUP_AGREEMENTS` to the JSON agreements object returned by MCP (or pass `--agreements`), plus `GOOGLE_SETUP_INTAKE_URL` and `GOOGLE_SETUP_REDIRECT_URI` from `google_app_setup_begin` immediately before writes. The default public-project-only cache is `~/.cache/wizard-google-setup/project.json` (owner-only); override with `--state-file`. `--step` = project/api/branding/audience/client/all; client captures and deposits in the same invocation. `--audience Internal` requires explicit Workspace intent. `--dry-run` never accepts terms and still destroys its disposable session; it is diagnostic only, not the first step in the normal one-sign-in flow.

Structured stdout: allowlisted step/status codes (running/ok or needs_owner) and allowlisted reason only. No project/account/page data. The public project ID is retained only in the local owner-only state file for safe continuation. Never screenshots, page dumps, traces, downloaded JSON credentials, secrets or raw exceptions. Unknown UI, no visible existing secret, wrong redirect, multiple matches, unrecorded/new agreements, agreement version mismatch, identity or billing prompts stop. The versioned allowlist matches whole checkbox labels and official document URLs, not generic accept/terms substrings. Country comes only from recorded acceptance; optional marketing emails are always unticked. Validation of the whole legal form precedes acceptance. `--dry-run` never accepts a legal form. Never rotate secrets or create duplicate clients to work around a missing secret. The wizard accepts only the recorded Cloud terms, APIs terms and User Data Policy on the owner's behalf; during authentication/identity takeover all inspection is paused. Keep the shared `skill/scripts/google_agreement_definitions.py` registry beside the script; both are shipped with the portable app skill. No source checkout outside the installed skill is required. The script refuses shared/persistent/clone profiles by default, checks the selected local handoff metadata and CDP binding before connecting, then signs out and deletes its verified temporary session on every exit. It requires stopped status readback, no cleanup error, and actual profile/capability removal before `setup: ok`. Sign-out failure still triggers deletion and reports `needs_owner`. `--allow-persistent-profile` is an explicitly approved diagnostic exception and does not bypass removal checks; retained profiles cannot claim success. See [Security: Google app setup sign-in](SECURITY.md#google-app-setup-sign-in).

The script is fail-closed and uses role/text/label selectors against the Google Auth Platform pages. **Fake-console PASS is not real-console validation.** Parent/owner must later exercise the signed-in current Console and verify project/API/branding/audience/client state, then MCP status and actual account consent. In particular table/URI field markup and the one-time secret dialog can change. An existing hidden secret needs the manual owner-only form, not automatic rotation.

## Evidence and limits

`python3 -m unittest discover -s tests -v` includes intake HTTP/RPC/expiry/single-use/concurrency/restart/malformed/storage/log-echo/ingress tests. `qa/google_console_fixture.py` drives the shipped Playwright code against a clearly fake Console and real intake/RPC/store, testing create/reuse, Calendar API, recorded terms/country, unrecorded-agreement refusal, marketing declined, publishing, redirect/credential capture and no duplicate client or log echo. Never runs against a real Google account.

`qa/thales_calendar_proof.py <pushed-sha>` builds the exact image on Thales/Colima, runs all unit tests and isolated compose/grant checks, then `qa/byo_browser.mjs` in native Chrome: 390 touch/mobile UA + 1280, light Signal + dark Nebula, all seven steps, live skin changes/draft preservation, nested/overlay/outside/root Back, real save/callback/incremental Calendar+YouTube scopes and multiple accounts. Provider transport is explicitly FAKE. The host is an explicit mock Appearance host using real shared resources, not installed-shell or physical-device evidence.

Current Google documentation used for the page model:
- https://developers.google.com/workspace/guides/configure-oauth-consent
- https://developers.google.com/workspace/guides/create-credentials
- https://developers.google.com/identity/protocols/oauth2/web-server
- Console paths: `/auth/overview`, `/auth/branding`, `/auth/audience`, `/auth/clients`; Calendar API library `calendar-json.googleapis.com`.
