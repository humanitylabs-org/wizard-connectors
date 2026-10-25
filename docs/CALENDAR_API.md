# Calendar source API

Consumer base: `http://wizard-connectors-calendar:8799` — the `ingress` service's
unique alias on the shared Runtipi main network (`runtipi_tipi_main_network` by
default, overridable via `WIZARD_MAIN_NETWORK` for isolated staging). Ingress
forwards to the internal UI, which verifies the grant before calling the broker.
The App Manager injects its standard `${APP_DATA_DIR}/wizard:/wizard:ro` mount
and `WIZARD_GRANTS_FILE=/wizard/grants.json` into the app services. The application
recipe does not declare a grants mount. The UI verifies the grant; the read-only
directory preserves atomic replacement/revocation visibility. Ingress is `is_main`
with `internal_port: 8799`: WAM must publish that service, not the internal UI,
as `provider_endpoints["wizard-connectors"]`. Consumers use that endpoint first.
No host port is needed for app-to-app access.

Every request requires `X-Wizard-Grant: <Calendar's key>`. The provider hashes
that header with SHA-256 and constant-time matches an incoming row with
`from: "wizard-calendar"`. The JSON file is re-read on every request. Missing, unset,
unreadable or malformed configuration denies access with HTTP 403. Owner tokens,
MCP tokens and `X-Wizard-App` are not substitutes. **Unlike the transitional
report-only rule in PERMISSIONS.md, Calendar always requires a matching grant,
even with `enforce: false`, because this API carries private calendar data.**
Unknown report-only callers are logged without keys or request content.

File shape (provider has hashes, not caller keys):
```json
{"outgoing": {}, "incoming": [{"from": "wizard-calendar", "sha256": "<64 lowercase hex>"}], "provider_endpoints": {}, "enforce": true}
```

## Exact wire contracts

`GET /service/calendar/status` (no body):
```json
{"client_configured": true, "accounts": [{"account": "google-<opaque-id>", "email": "owner@example.com", "calendar_allowed": true, "status": "active"}], "setup_url": "/wizard-connectors/"}
```
`calendar_allowed` requires an active account, Calendar scope, owner-approved
Calendar binding and an enabled/configured broker. Account status is `active` or
`reauth_required`. Accounts not bound are still listed to enable setup guidance.
`client_configured` reports the client triple, not an account authorization.

`POST /service/calendar/calendars`, `Content-Type: application/json`, body `{}`:
```json
{"calendars": [{"account": "google-<opaque-id>", "email": "owner@example.com", "id": "primary@example.com", "name": "Personal", "color": "<provider color>", "primary": true, "access_role": "owner"}]}
```
Lists calendars from every explicitly bound account. Fixed Google calendarList
endpoint, fields-limited, at most 3 pages of 250 calendars per account. If another
page remains, returns 409 `calendar_list_truncated` rather than silently claiming
completeness. Aggregate response over 2 MiB returns `calendar_list_too_large`.
An expired/failed bound account returns an error rather than partial success.

`POST /service/calendar/events`, `Content-Type: application/json`:
```json
{"account": "google-<opaque-id>", "calendar_id": "primary@example.com", "time_min": "2026-10-01T00:00:00Z", "time_max": "2026-11-01T00:00:00+00:00"}
```
Exact keys only. `calendar_id` is a nonempty string, at most 300 characters, no
control characters; encoded as one fixed-endpoint path component. Timestamps are
RFC3339 with timezone; `0 < time_max - time_min <= 400 days`. Account must be in
the persisted Calendar binding with read-only scope. No caller URL or scope.

```json
{"events": [{"id": "event-id", "calendar_id": "primary@example.com", "account": "google-<opaque-id>", "title": "Appointment", "start": "2026-10-24", "end": "2026-10-25", "all_day": true, "location": "", "status": "confirmed", "html_link": "https://calendar.google.com/..."}], "truncated": false}
```
`start`/`end` are date strings for all-day events (end is exclusive), otherwise
Google RFC3339 dateTime strings. `html_link` is optional and only HTTPS. Missing
provider fields become empty strings. Titles/locations are capped at 2000 chars,
IDs at 1024, links at 2048. Fixed events.list uses `singleEvents=true`,
`orderBy=startTime`, `maxResults=2500`, selected fields and at most 3 pages.
`truncated=true` if another page remains or the 2 MiB output budget is reached.
No events, calendars, client secret or tokens are exposed through MCP.

Errors are JSON `{"error":"<code>"}`: 403 `calendar_grant_required`, 415
`json_required`, 400 `invalid_request` / `invalid_operation`, or 409 for broker
refusals (including `invalid_time_window`, `invalid_calendar_id`,
`capability_denied`, `google_disabled`, `reauth_required`,
`scope_consent_required`, `provider_permission_denied`, `provider_unavailable`).
Refresh and subject verification run under the same broker lock as Music,
unlink and disconnect. Refresh scope loss or auth failure marks reauth required,
clears credentials and removes Calendar binding; re-consent is required.

Owner control: `POST /api/calendar/bind {"account":"...","consent":true}` enables
one account after Google Calendar consent; `false` disables it without changing
Music. Disconnect removes it. Saving a changed OAuth client clears both service
bindings and marks all existing accounts `reauth_required`.
