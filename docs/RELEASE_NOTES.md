# Connected accounts 0.8.2

- **Messenger's agent level on Agent access** (humanitylabs-org/wizard-messenger#342; needs this app's switch `grants-panel` and Messenger's switch `connected-accounts-levels`, both off by default). The Messenger card now lists Messenger's connected chat accounts (names only) and one level picker per agent (No access, Read-only, Draft-only). It reads and sets the level through Messenger's own route, so Messenger stays the only place it is kept and enforced; with Messenger's switch off it says "set in Messenger for now" as before.

# Connected accounts 0.8.1

- **Agent access in one place, reworked** (wizard-connectors#49; switch `grants-panel`, off by default). Following Miguel's rescope, the grants store from 0.8.0 is gone: no `wizard.app-grants/1`, no `/service/grants/v1/*` or `/api/grants*` routes, no audit log. Connected accounts > Agent access is now one screen over the existing owners: each installed account app with a switch per agent for "may use this app" (the agent.json ticks, read and set through the Agent Service's `GET/PUT /wizard/v1/apps/<app>/agents`), and Mail's level from this app. Other apps' own levels stay in those apps for now. See [CONNECTIONS_PANEL.md](CONNECTIONS_PANEL.md).

# Connected accounts 0.8.0

- **Agent access in one place** (wizard-connectors#49; switch `grants-panel`, off by default; withdrawn in 0.8.1, see above). Connected accounts > Agent access lists every connected account with what each agent may do on it (No access, Read, Draft, Send) as taps; only the owner's taps change it, and a new agent starts with no access (Messenger accounts suggest Draft only). Apps and the MCP gateway ask `POST /service/grants/v1/check` (contract `wizard.app-grants/1`) and every yes or no is logged under Recent checks. Other connector apps can list their accounts here. Enforcing it in each app comes next. See [APP_GRANTS.md](APP_GRANTS.md).

# Connected accounts 0.7.1

- **Google sign-in starts on rootless Docker** (wizard-connectors#45; fix, on for everyone). The Google sign-in service no longer crash-loops when it cannot lock down its own data folder (rootless Docker gives that folder to the box user); it carries on as long as it can write there, and the saved sign-ins stay encrypted and private to it.

# Connected accounts 0.7.0

- **Mail opens photos and files from Gmail** (humanitylabs-org/wizard-mail#32; fix, on for everyone). `mail_get` names each attachment's part and Content-ID, and the new owner-only `mail_attachment` gives Mail one file's bytes (up to 25 MB), so Mail shows photos in emails and saves attachments. Agents never get file bytes. Contract `wizard.mail-calendar/1` 1.6; see [MAIL_API.md](MAIL_API.md).

# Connected accounts 0.6.1

- **Gmail for Mail on a Google app set up by hand** (wizard-connectors#38; fix, on for everyone). The agent's `--step api` turns on missing Google APIs (Gmail for Mail) without agreements recorded in Connected accounts, opens the configured app's own project by its number instead of looking for a project named "Wizard", and can fetch the setup scripts from this app when the host copy of the skill has none. A Google terms screen still stops for the owner.

# Connected accounts 0.6.0

- **Calendar edits for your wizard** (wizard-connectors#29; switch `google-calendar-edits`, off by default). The Google app's calendar tools add, move and delete events on the Google account connected here, so there is no sign-in in the Google app. Each account gets a **Calendar edits** row: Allow adds Google's events permission (`calendar.events`). What agents may do stays Calendar > Settings > Agent access, checked by the Google app as before. Needs the Google app with wizard-google#24. See [GOOGLE_TOOLS.md](GOOGLE_TOOLS.md).

# Connected accounts 0.5.1

- **The Google app can use this sign-in** (humanitylabs-org/wizard-google#20). The Google app (`wizard-google`, behind its own switch `connected-accounts`) asks Connected accounts at `/service/google/v1/<tool>` for Drive, Docs, Sheets, Contacts and Gmail search/read/draft, so it needs no second Google sign-in. Only with the Google app's App Manager grant and this app's `google-workspace` switch on; agents keep the owner's mail level and never send. See docs/GOOGLE_TOOLS.md.

# Connected accounts 0.5.0

- **Google tools for your wizard** (wizard-connectors#27; switch `google-workspace`, off by default). The agent lists Drive files, reads Docs, Sheets and Slides, looks up contacts and writes Gmail drafts through the Google account connected here, with no second Google sign-in. Each account gets a **Drive and Contacts** row: Allow adds read-only Drive and Contacts access. Mail drafts keep the owner's level for agents; agents never send. The agent setup also turns on the Drive and People APIs. See [GOOGLE_TOOLS.md](GOOGLE_TOOLS.md).

# Connected accounts 0.4.0

- **Connect Gmail from inside Mail** (wizard-connectors#21; Mail's switch `connect-gmail-in-mail`, off by default). Mail's Continue to Google asks Connected accounts (`POST /service/mail/v1/connect`, the owner's own tap only, never an agent) to start Google's sign-in with the Gmail scope; Google's Allow is the owner's only step, and the tap turns Gmail for Mail on here by itself. The skill tells the agent what to do for "connect my Gmail to Mail". See [MAIL_API.md](MAIL_API.md).

# Connected accounts 0.3.1

- **Fix: the agent's Google setup also turns on the Gmail API** (and the YouTube Data API for Music), so Gmail for Mail no longer needs a Google Cloud visit (wizard-connectors#19). For an app set up earlier for Calendar only, the agent runs the setup script's `--step api`, which turns on just the missing APIs. "Set it up myself" step 3 links all three.

# Connected accounts 0.3.0

- **Gmail for Mail** (switch `gmail-for-mail`, off by default; wizard-connectors#15). Mail reads, searches and drafts Gmail through the Google account connected here: one Google app, one sign-in, no Composio. Each account gets a Mail row (Allow adds Gmail access) and an "Agents and your mail" level (Draft only by default; agents never send). Turn on the Gmail API in the same Google Cloud project. See [MAIL_API.md](MAIL_API.md).

# Connected accounts 0.2.0 release notes

Version **0.2.0** (previous listed release: 0.1.1).

## Changed owner flow


Google → Let your wizard set this up first opens three labelled agreement checkboxes, official links, and a country picker. All three and a country are required before saving. The encrypted broker stores version `google-2026-11`, IDs, country and its own acceptance timestamp. The agent receives only IDs/version/country. Manual setup links the same documents without delegating acceptance.

The agent setup uses a fresh disposable Human Handoff profile. The owner types their password and 2FA during takeover with every inspection paused. The script matches only recorded agreements, declines optional marketing, and stops at new documents, billing, identity checks or unknown UI. On terminal setup exits it attempts Google sign-out, stops the handoff, and verifies stopped/expired status plus actual profile/capability removal. Active owner sign-in/verification is instead paused resumably under its original TTL without inspection or deletion. A deposited app is not task completion until sign-out and teardown are verified. No persistent/shared-browser fallback is enabled. See [security](SECURITY.md#google-app-setup-sign-in).

## Packaging

- `runtime.package: image`. All five services use one public multi-arch (linux/amd64 + linux/arm64) image, `ghcr.io/humanitylabs-org/wizard-connectors`, pinned by tag `sha-<commit>` and digest in `runtipi/docker-compose.yml`, plus the existing shared non-root/read-only/capability-drop/tmpfs hardening. The image is built from `app/Dockerfile` by the shared `app-image` workflow; its `org.opencontainers.image.revision` label is the commit that ran the workflow.
- Network isolation: the ingress service is `wizard-connectors-calendar` (the advertised Calendar endpoint host) and joins no shared main network, so App Manager keeps the app `isolated`.
- Dependency update: PyJWT 2.15.1 (security update carried from the default branch).
- No reviewed-image form field remains. Required fields are auto-generated passwords, including the encrypted-store secret; installer/provider-specific values remain optional.
- The installer must supply its routed Wizard host in `WIZARD_TRUSTED_HOSTS`; loopback/internal hosts are the safe blank default. Origins must match that validated Host or the explicit origin list. Arbitrary matching Host/Origin pairs are refused (DNS-rebinding defense). New redirects use `/connected-accounts/api/google/callback` with validated forwarded route prefixes; already-saved redirects are preserved byte-for-byte, including legacy paths.
- The upstream view serves `/`; the gateway uses the canonical app ID `connected-accounts` as its mount, not a second nested view path.

## Checks run for this release

- Unit suite: 107 tests, OK (real owner HTTP/RPC and encrypted-store restart persistence for agreements, negative auth/origin/validation/storage cases, fake Console behavior, synthetic disposable-profile/sign-out/teardown checks). No browser is launched by these tests.
- Dependency-free Node DOM contracts and `node --check` for `web/app.js` and every `qa/*.cjs`.
- The App Index checker (rules 1-16, including the anonymous multi-arch pull of every compose image) and the App Manager planner (app stays `isolated`, Calendar link intact).

## Not covered by those checks

Real Google Console / consent with a disposable account, in-shell and physical-phone visual acceptance, and an end-to-end Calendar grant on a fresh box are separate gates. No fixture result substitutes for them.

Calendar must declare `uses: [connected-accounts]` or `uses: [calendar-source]` with that slot selected, and integrate the broker API. The provider already declares `calendar-source` and enforces incoming `wizard-calendar` hashes. See [Calendar consumer contract](CALENDAR_API.md#fresh-calendar-compatibility-and-owner-grants).
