# Assurance and deployment gate

This is a **simulated private-chat preview**, not real-chat eligible. Fictional messages are classified private. Google account authorization is a genuine configurable broker, disabled pending exact-source review and client provisioning. No real Google authorization is claimed. See GOOGLE_RELEASE.md for custody, configuration, install and evidence boundaries.

## Implemented
- Deterministic whole-request admission; invalid labels block; private input never chooses the ordinary provider. Private preference fixed to the selected Tinfoil/glm-5-3 route.
- SDK attestation before/after inference; max_retries=0; no tool schemas, agent harness, arbitrary URL, recipient or read-set output; tool calls rejected.
- Separate owner HTTP session and content-free MCP authentication; no conversation/sender/title/result tool. JSON-only mutations and Host/Origin checks; no permissive CORS. Place behind the authenticated same-origin app route.
- Immutable snapshot, stable IDs, one conversation, fixed byte-bounded fixtures, deduplication, bounded output and concurrent job admission. Cancellation, epoch changes and expiry gate delivery.
- Plain-text renderer with strict same-origin CSP, no Markdown or external assets. Fifteen-minute memory-only result retention; no result database, diagnostics or notification side channel. Expired bytes are cleared on subsequent access and all results clear on restart. Policy persists separately; no backup/export defaults.
- Account/grant/binding separation, consent and operation checks, wrong-account refusal, serialized expiry refresh, local unlink vs disconnect, shared-grant reauthentication invalidation in fixture-tested core.

## Not proved / deliberately disabled
Host administrators and unrestricted host agents can read runtime secrets and private memory. Containers are non-root/read-only with no Docker/home mounts. UI internet egress is denied by internal Docker networks; broker/private-worker are separate processes/volumes/networks with fixed application-level outbound operations, not destination-firewalled or host-admin-resistant. Actual handlers, encrypted custody, signed ID validation, refresh and revocation are exercised with explicitly fake provider transport; personal Google consent remains unproved. No live chat adapter or official YouTube audio-delivery entitlement is claimed. Existing Music source is untouched. This app is not a replacement for shared Account Manager.

## Installer contract
Build only from a pushed revision on the designated worker. Pin the exact image. Inject credentials using the normal form into only the service needing them; never commit credentials or mount a Google cookie jar. Supply approved WizardApp core at `/wizard-os-home/core/app-client.js` and register using actual App Manager lifecycle. Staging does not register production. Parent integration must verify cold in-shell open, route owner authentication and stop/uninstall without data deletion. Google connect returns `isolation_review_required` by default, then `google_configuration_required` if reviewed but not provisioned; with both gates satisfied it initiates the implemented browser flow.

## Source attribution
`web/boot.js` and `web/wizard-ui.css` copied unchanged from Wizard App Manager hello-wizard (GPL-3.0-only). No shared system implementation is copied. App calls WizardApp for Back and appearance. Claude Opus first-party supplied the bounded UI design before view authoring.
