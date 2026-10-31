# Guided Google app setup

## Owner model

The owner uses their own **main Google account** to own **one** project + Web OAuth client. The wizard needs **no Google account**. One app connects all the owner's accounts; it is a permission key, not a data store. External + In production is the personal default. Internal is only for an administrator's Workspace organization.

The Google panel separates **Your Google app — one time** from **Your Google accounts — add as many as you like**. Agent setup shows exactly `Set up my Google app` and a Copy message button. The shared host's `nav.openThread` forbids `__new__`, admits only selected thread apps, and `openContextDraft` is Notifications-only: Connected accounts must not invent a send API or bypass those guards.

Manual setup has seven screens: account/audience; project; Calendar API; Auth branding/audience/production; Web client + exact redirect URI Copy; validated credentials Save; connect accounts and grant/bind Calendar. Steps 1–5 require owner confirmation, step 6 requires an actual successful save, step 7 finishes into a compact configured row. Shared Back goes to the preceding step, then setup entry, then the app root. No URL navigation or exit sentinels. Unsaved credentials hold app updates and must be discarded explicitly on Back.

## Reuse inventory

- **REUSE** `WizardApp` (`/wizard-os-home/core/app-client.js`) for Appearance v1, root/nested/overlay Back and update holds; shared kit/skin layers for inputs/buttons. Native `progress`, labelled fields and checkboxes, no parallel design system.
- **EXTEND** Connected accounts' domain-only Google view using the existing Setup checklist → in-app screen pattern (`wizard-ux/web/setup/setup.js`), with the same shared Back callback. Examined `web/core/tour.js`, Setup and COMPONENTS: neither exports a reusable generic setup-stepper/checklist; Tour depends on the live microphone/gesture shell, so importing it would be incorrect. No new platform component or API.
- **NEW** only app-owned Google setup state/capability, broker typed operations and Google Console task automation. No replacement for shared chat, theme, auth, history or human takeover.

## MCP and intake protocol

Existing MCP Bearer authentication protects both new tools. Empty-object arguments only:

- `google_app_setup_status`: `configured`, `managed`, `redirect_uri`, `required_apis`, `required_scopes`. No client ID, secret, email, accounts or calendar content.
- `google_app_setup_begin`: `intake_url`, `expires_in: 1800`, `redirect_uri`. The URL is `http://wizard-connectors-calendar:8799/api/google/setup/intake#<capability>`, on the existing private Wizard main-network ingress. The fragment never goes in an HTTP request URL or access log. A new begin invalidates any earlier setup; restart invalidates all.

The automation process splits the fragment and POSTs **only** `{client_id,client_secret}` with `Authorization: Bearer <capability>` and no cookies, Origin or proxy/forwarded headers. It does not fetch through a Google-page browser context (CORS/private-network-access would block that); the browser-control script carries values in its isolated Python memory directly to the fixed internal ingress. Proxy environment variables and HTTP redirects are disabled. Intake is not a public browser form and must not be opened as a browser URL.

Ingress permits the fixed internal alias/loopback host and rejects public Host, `Origin`, `Cookie`, `Forwarded`, `Via`, `X-Forwarded-*`, `Tailscale-*` before relay. It rewrites Host to the fixed app upstream only for that checked lane. The UI service independently rejects public/forwarded/browser requests. Broker validates the 256-bit capability digest, expires and consumes it atomically under its lock **before validating credentials**. Wrong/expired/used token returns 403; malformed values 400; success is only `{ok:true}`. Unknown request fields reject before broker delivery. MCP/owner/Calendar credentials cannot substitute for the minted capability.

Only the broker writes credentials: same encrypted atomic store, environment precedence, replacement invalidation/reauthentication and fixed Google endpoints as before. Intake has no caller-selected redirect URI or provider URL. Logs suppress bodies, authorization headers and exception values. The public client ID remains visible in the human owner view as before, not in MCP/status/intake results. Memory on the trusted browser/script/UI/RPC/broker hosts is in the threat boundary; this is not host-administrator isolation.

## Script and human gates

Source: `skill/scripts/google_cloud_setup.py`, shipped alongside `skill/SKILL.md` and included in the image. Needs Python Playwright in the browser automation runner, not in the credential-broker runtime.

```sh
# Values come from MCP; neither contains a Google client secret.
# Keep the capability in the environment, not in shared logs.
# HANDOFF_CDP_URL is injected by the platform's preserved-browser runner,
# or BROWSER_CDP_URL names the existing Wizard Browser.
python3 skill/scripts/google_cloud_setup.py --dry-run
python3 skill/scripts/google_cloud_setup.py
python3 skill/scripts/google_cloud_setup.py --project wizard-public-id --step audience
python3 skill/scripts/google_cloud_setup.py --project wizard-public-id --step client
```

Set `GOOGLE_SETUP_INTAKE_URL` and `GOOGLE_SETUP_REDIRECT_URI` from `google_app_setup_begin` immediately before writes. The default public-project-only cache is `~/.cache/wizard-google-setup/project.json` (owner-only); override with `--state-file`. `--step` = project/api/branding/audience/client/all; client captures and deposits in the same invocation. `--audience Internal` requires explicit Workspace intent. `--dry-run` only navigates/reads human gates.

Structured stdout: running/ok + public project ID, or needs_owner + allowlisted reason. Never screenshots, page dumps, traces, downloaded JSON credentials, secrets or raw exceptions. Unknown UI, no visible existing secret, wrong redirect, multiple matches, legal acceptance, identity or billing prompts stop. Never rotate secrets or create duplicate clients to work around a missing secret. The owner accepts Cloud terms/data policy themselves; during takeover all inspection is paused. Script disconnects without closing the shared browser.

The script is fail-closed and uses role/text/label selectors against the Google Auth Platform pages. **Fake-console PASS is not real-console validation.** Parent/owner must later exercise the signed-in current Console and verify project/API/branding/audience/client state, then MCP status and actual account consent. In particular table/URI field markup and the one-time secret dialog can change. An existing hidden secret needs the manual owner-only form, not automatic rotation.

## Evidence and limits

`python3 -m unittest discover -s tests -v` includes intake HTTP/RPC/expiry/single-use/concurrency/restart/malformed/storage/log-echo/ingress tests. `qa/google_console_fixture.py` drives the shipped Playwright code against a clearly fake Console and real intake/RPC/store, testing create/reuse, Calendar API, owner-only policy, publishing, redirect/credential capture and no duplicate client or log echo. Never runs against a real Google account.

`qa/thales_calendar_proof.py <pushed-sha>` builds the exact image on Thales/Colima, runs all unit tests and isolated compose/grant checks, then `qa/byo_browser.mjs` in native Chrome: 390 touch/mobile UA + 1280, light Signal + dark Nebula, all seven steps, live skin changes/draft preservation, nested/overlay/outside/root Back, real save/callback/incremental Calendar+YouTube scopes and multiple accounts. Provider transport is explicitly FAKE. The host is an explicit mock Appearance host using real shared resources, not installed-shell or physical-device evidence.

Current Google documentation used for the page model:
- https://developers.google.com/workspace/guides/configure-oauth-consent
- https://developers.google.com/workspace/guides/create-credentials
- https://developers.google.com/identity/protocols/oauth2/web-server
- Console paths: `/auth/overview`, `/auth/branding`, `/auth/audience`, `/auth/clients`; Calendar API library `calendar-json.googleapis.com`.
