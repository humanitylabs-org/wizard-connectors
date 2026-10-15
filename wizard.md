---
wizard: 0.2
id: wizard-connectors
name: Connected accounts
type: service
category: app
version: 0.1.0
summary: Google connector readiness and simulated private chat summaries.
license: GPL-3.0-only
source: https://github.com/humanitylabs-org/wizard-connectors
runtime:
  kind: runtipi
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
provides: [connector-status, simulated-private-summary]
system: false
uses: []
needs: []
health: /healthz
---
# Connected accounts
Synthetic-only preview. Real Google credentials are not accepted until independent isolation review. No shared platform manifest extension is required.
