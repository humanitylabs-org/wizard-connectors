---
wizard: 0.2
id: wizard-connectors
name: Connected accounts
type: service
category: app
version: 0.1.0
summary: Owner-managed Google account broker and simulated private chat summaries.
license: MIT
source: https://github.com/humanitylabs-org/wizard-connectors
runtime:
  kind: runtipi
  package: build
  config: runtipi/config.json
  compose: runtipi/docker-compose.yml
api:
  port: 8799
  path: /api
  spec: openapi.json
mcp:
  path: /mcp
  port: 8799
  transport: streamable-http
skill: skill/SKILL.md
view:
  path: /
  port: 8799
  source:
    path: web
    build: python3 app/build_view.py
    dist: web
provides: [connector-status, simulated-private-summary, calendar-source]
system: false
uses: []
needs: []
health: /healthz
---
# Connected accounts
Bring your own Google OAuth app in **Your Google app**, then connect each account,
authorize Calendar read-only scope, and explicitly allow Calendar to use it.
Music binding is separate; private chat remains synthetic-only.

Calendar consumer base URL: **http://wizard-connectors-calendar:8799** (the
`ingress` service's unique network alias on `runtipi_tipi_main_network`). Paths:
`/service/calendar/status`, `/service/calendar/calendars`, `/service/calendar/events`.
WAM layer-2 grants must contain an incoming SHA-256 row for `calendar`;
Calendar sends its key as `X-Wizard-Grant`. There is no owner-session requirement
on this service API. Report-only mode does not weaken Calendar authentication.
`APP_DATA_DIR/wizard` is mounted read-only into the UI; other services do not
receive the grants file. Shared network name can be configured with
`WIZARD_MAIN_NETWORK` for isolated staging. See docs/CALENDAR_API.md.
