# Assurance and deployment gate

This is a **simulated private-chat preview**, not private-data eligible. Fictional messages are classified private. No Google credential loading endpoint exists. Account lifecycle code is tested using fixture grants, never falsely presented as connected Google accounts.

## Implemented
- Deterministic whole-request admission; invalid labels block; private input never chooses the ordinary provider. Private preference fixed to the selected Tinfoil/glm-5-3 route.
- SDK attestation before/after inference; max_retries=0; no tool schemas, agent harness, arbitrary URL, recipient or read-set output; tool calls rejected.
- Separate owner HTTP session and content-free MCP authentication; no conversation/sender/title/result tool. JSON-only mutations and Host/Origin checks; no permissive CORS. Place behind the authenticated same-origin app route.
- Immutable snapshot, stable IDs, one conversation, fixed byte-bounded fixtures, deduplication, bounded output and concurrent job admission. Cancellation, epoch changes and expiry gate delivery.
- Plain-text renderer with strict same-origin CSP, no Markdown or external assets. Fifteen-minute memory-only result retention; no result database, diagnostics or notification side channel. Expired bytes are cleared on subsequent access and all results clear on restart. Policy persists separately; no backup/export defaults.
- Account/grant/binding separation, consent and operation checks, wrong-account refusal, serialized expiry refresh, local unlink vs disconnect, shared-grant reauthentication invalidation in fixture-tested core.

## Not proved / deliberately disabled
Host administrators and unrestricted host agents can read runtime secrets and private memory. Containers are non-root/read-only with no Docker/home mounts, but model-worker egress is not OS constrained. No actual Google OAuth custody, provider revocation, refresh or personal-account authorization is proved. No live chat adapter. No official YouTube audio-delivery entitlement is claimed. Existing Music playback is untouched until its exact source/runtime and uncached path are independently proved. This app is not a replacement for shared Account Manager.

## Installer contract
Build only from a pushed revision on the designated worker. Pin the exact image. Inject owner/MCP credentials and Tinfoil key at runtime; never commit credentials or mount a Google cookie jar. Supply approved WizardApp core at `/wizard-os-home/core/app-client.js` and register using actual App Manager lifecycle. Staging does not register production. Parent integration must verify cold in-shell open, route owner authentication and stop/uninstall without data deletion. Google connect intentionally returns `isolation_review_required` until a later independently reviewed adapter implementation.

## Source attribution
`web/boot.js` and `web/wizard-ui.css` copied unchanged from Wizard App Manager hello-wizard (GPL-3.0-only). No shared system implementation is copied. App calls WizardApp for Back and appearance. Claude Opus first-party supplied the bounded UI design before view authoring.
