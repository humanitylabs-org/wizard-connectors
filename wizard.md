---
wizard: 0.2
id: wizard-connectors
name: Connected accounts
type: external
category: app
version: 0.1.1
summary: Review-gated Google account broker and simulated private chat summaries.
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
provides: [connector-status, simulated-private-summary]
system: false
uses: []
needs: []
health: /healthz
---
# Connected accounts
Synthetic-only chat; implemented Google OAuth broker remains guarded until independent review and client provisioning. Normal installer forms configure the separate provider and private-worker services. No shared platform manifest extension is required.
