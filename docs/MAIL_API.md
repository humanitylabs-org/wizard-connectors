# Gmail for Mail (switch `gmail-for-mail`, off by default)

wizard-connectors#15: Mail uses the Google account Connected accounts already holds, so Gmail needs no Composio and no
second Google app. One Google app (the owner's own, set up here), one sign-in per account.

## Owner side

- Turn the switch on (Tracker Try it: `connected-accounts:gmail-for-mail`). Each Google account card gets a **Mail**
  row: **Allow** opens Google's sign-in once more and adds Gmail access (`https://www.googleapis.com/auth/gmail.modify`:
  read, search, labels, drafts; Mail sends a draft only on the owner's tap).
- The **Gmail API** (`gmail.googleapis.com`) is in `required_apis`: the agent setup turns it on with the Calendar API, and
  for a project set up earlier for Calendar only the agent runs the setup script's `--step api` (wizard-connectors#19).
  Without it Gmail answers 403 and Mail says so (`google_permission_missing`); the account stays signed in.
- **Agents and your mail**: No access, Read-only, Draft only (the default), the same levels as the Google and
  Microsoft apps. Agents never send.

## Mail side (contract `wizard.mail-calendar/1`, mail tools only)

Base: `provider_endpoints["connected-accounts"]` (the `wizard-connectors-calendar` ingress, port 8799) on the
Mail → Connected accounts link network. Paths: `GET /service/mail/v1/status`, `POST /service/mail/v1/<tool>` for
`mail_search`, `mail_get`, `mail_attachment`, `mail_update`, `mail_update_bulk`, `mail_draft`, `mail_send`, and
`POST /service/mail/v1/agent_access {mail}` (owner only). Shapes are the contract's (wizard-google
`docs/mail-calendar-contract.md`); every answer carries `contract`, `source: google`, `via: own-client`, `account`.

- Every request needs Mail's App Manager grant (`X-Wizard-Grant`, an incoming row `from: wizard-mail`), also in
  report-only mode, because this is private mail.
- Every request says who it is for: `X-Wizard-Owner: 1` (the owner's own tap in Mail) or `X-Wizard-Agent: <name>`
  (an agent through Mail's MCP, held to the owner's level; `mail_send` is refused as `agent_send_refused`).
- Attachments (contract 1.6, wizard-mail#32): `mail_get` lists each file's `part` (Gmail `partId`), `content_id` and
  `inline`, plus `inline_parts[]` (nameless pictures the HTML shows as `cid:`). `mail_attachment {id, part}` answers
  `attachment {name, mime, size, base64}` so Mail can show a photo or save a file: at most 25 MB (413
  `attachment_too_big`), unknown part 404 `not_found`, and owner only (an agent gets 403 `owner_only`; it is not in an
  agent's tool list).
- Switch off: every call answers 409 `service_off`, except `connect` below.
- `POST /service/mail/v1/connect {}` (wizard-connectors#21; Mail sends it behind its switch `connect-gmail-in-mail`):
  the owner's own tap only (`X-Wizard-Owner: 1`; an agent gets 403 `owner_only`). Starts Google's sign-in on the
  owner's Google app with the Gmail scope and answers `{authorization_url, expires_in, scope}`; Mail opens the URL and
  Google's Allow is the owner's only step (Google's account chooser picks a new or an already connected account; for
  one already here the Gmail scope is added to its other services). The tap also turns `gmail-for-mail` on, so there is
  no switch for the owner to find; it can still be turned off. No Google app yet: 409 `google_configuration_required`
  and nothing is turned on (the agent sets the app up; see skill/SKILL.md).
- Errors: `{error: {code, message}}` with the contract's codes (`not_connected`, `account_required`,
  `account_not_found`, `permission_missing`, `google_permission_missing`, `reauth_required`, `invalid_arguments`,
  `not_found`, `rate_limited`, `provider_unavailable`).
- Tokens never leave the broker; Gmail is called only on `https://gmail.googleapis.com/gmail/v1/users/me/…`.
  Request bodies up to 26 MB on this path (a draft with 18 MB of files), answers up to 36 MB (one 25 MB attachment as base64).
