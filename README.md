# Connected accounts — Google broker and synthetic private chat

Google account readiness and a real no-tool Tinfoil `glm-5-3` summary of fictional chat. Real YouTube Music remains the selected provider in the existing Music app; this preview does not replace or modify playback.

## Boundaries

- The real Google authorization-code/PKCE broker is implemented and configurable but review-gated. No real account has been imported or authorized during this build. Signed fake-provider tests exercise actual handlers, refresh, revocation and encrypted storage. See [Google release and install gates](docs/GOOGLE_RELEASE.md).
- Owner HTTP token/session and distinct content-free MCP token. Never expose the loopback service without authenticated routing. All browser API calls are same-origin. Installer supplies approved `/wizard-os-home/core/app-client.js`.
- Only `tinfoil==0.14.0` attested SDK, fixed `glm-5-3`, no agent tools, no fallback. Attestation is checked before and after inference. Model key is runtime injected, never browser-visible. General host administrators can still inspect this synthetic preview.
- Results are memory-only, expire after 15 minutes, clear on restart/policy change/cancel, and never enter MCP or normal request logs. Expired bytes are purged on subsequent requests; restart clears all. No export, automatic links, remote assets or executable Markdown.
- Provider account, grant and service binding are distinct. Typed Music operations cannot invoke Gmail; local unlink is not provider revocation. Credentials are returned only to a trusted fixed adapter inside the seam, never HTTP/MCP.

## Run and package

Build `docker build --build-arg SOURCE_REVISION=<pushed-sha> -f app/Dockerfile -t wizard-connectors:<pushed-sha> .` on the designated worker. Deploy the checked-in four-service compose, not just the UI container: UI is on internal networks, Google broker and private worker use distinct outbound lanes and credentials. The normal install form supplies all runtime configuration. Bind the UI through the authenticated Wizard route. Never bake secrets into images.

`python3 -m unittest discover -s tests -v` exercises policy/lifecycle without network. The checked-in compose is the portable manifest; pin `CONNECTORS_IMAGE` to the worker-built image in the local lifecycle installer. App Manager's approved checker plus shared-function gate remain authoritative. Production installation goes through App Manager, not manual registry edits.

Shared UI kit/boot origins: Wizard App Manager `hello-wizard`, GPL-3.0-only. UI design: first-party Claude Opus consultation, implemented here; no private owner data in source.
