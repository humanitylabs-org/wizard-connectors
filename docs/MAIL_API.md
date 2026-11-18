# Gmail for Mail (switch `gmail-for-mail`, off by default)

wizard-connectors#15: Mail uses the Google account Connected accounts already holds, so Gmail needs no Composio and no
second Google app. One Google app (the owner's own, set up here), one sign-in per account.

## Owner side

- Turn the switch on (Tracker Try it: `connected-accounts:gmail-for-mail`). Each Google account card gets a **Mail**
  row: **Allow** opens Google's sign-in once more and adds Gmail access (`https://www.googleapis.com/auth/gmail.modify`:
  read, search, labels, drafts; Mail sends a draft only on the owner's tap).
- In the owner's Google Cloud project, turn on the **Gmail API** (`gmail.googleapis.com`) next to the Calendar API.
  Without it Gmail answers 403 and Mail says so (`google_permission_missing`); the account stays signed in.
- **Agents and your mail**: No access, Read-only, Draft only (the default), the same levels as the Google and
  Microsoft apps. Agents never send.

## Mail side (contract `wizard.mail-calendar/1`, mail tools only)

Base: `provider_endpoints["connected-accounts"]` (the `wizard-connectors-calendar` ingress, port 8799) on the
Mail → Connected accounts link network. Paths: `GET /service/mail/v1/status`, `POST /service/mail/v1/<tool>` for
`mail_search`, `mail_get`, `mail_update`, `mail_update_bulk`, `mail_draft`, `mail_send`, and
`POST /service/mail/v1/agent_access {mail}` (owner only). Shapes are the contract's (wizard-google
`docs/mail-calendar-contract.md`); every answer carries `contract`, `source: google`, `via: own-client`, `account`.

- Every request needs Mail's App Manager grant (`X-Wizard-Grant`, an incoming row `from: wizard-mail`), also in
  report-only mode, because this is private mail.
- Every request says who it is for: `X-Wizard-Owner: 1` (the owner's own tap in Mail) or `X-Wizard-Agent: <name>`
  (an agent through Mail's MCP, held to the owner's level; `mail_send` is refused as `agent_send_refused`).
- Switch off: every call answers 409 `service_off`.
- Errors: `{error: {code, message}}` with the contract's codes (`not_connected`, `account_required`,
  `account_not_found`, `permission_missing`, `google_permission_missing`, `reauth_required`, `invalid_arguments`,
  `not_found`, `rate_limited`, `provider_unavailable`).
- Tokens never leave the broker; Gmail is called only on `https://gmail.googleapis.com/gmail/v1/users/me/…`.
  Request bodies up to 26 MB on this path (a draft with 18 MB of files), answers up to 8 MB.
