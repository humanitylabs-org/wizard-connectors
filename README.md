# Connected accounts — Google broker and synthetic private chat

Google account readiness and a real no-tool Tinfoil `glm-5-3` summary of fictional chat. Real YouTube Music remains the selected provider in the existing Music app; this preview does not replace or modify playback.

## Boundaries

- The real Google authorization-code/PKCE broker is implemented with owner-supplied Google app configuration and read-only Calendar bindings. No real account has been imported or authorized during this build. Signed fake-provider tests exercise actual handlers, refresh, revocation and encrypted storage. See [Google setup](docs/GOOGLE_RELEASE.md) and [Calendar service API](docs/CALENDAR_API.md).
- Owner HTTP token/session and distinct content-free MCP token. Never expose the loopback service without authenticated routing. All browser API calls are same-origin. Installer supplies approved `/wizard-os-home/core/app-client.js`.
- Only `tinfoil==0.14.0` attested SDK, fixed `glm-5-3`, no agent tools, no fallback. Attestation is checked before and after inference. Model key is runtime injected, never browser-visible. General host administrators can still inspect this synthetic preview.
- Results are memory-only, expire after 15 minutes, clear on restart/policy change/cancel, and never enter MCP or normal request logs. Expired bytes are purged on subsequent requests; restart clears all. No export, automatic links, remote assets or executable Markdown.
- Provider account, grant and service binding are distinct. Typed Music operations cannot invoke Gmail; local unlink is not provider revocation. Credentials are returned only to a trusted fixed adapter inside the seam, never HTTP/MCP.

## Run and package

`runtime.package: build` lets App Manager build the pinned source on either CPU architecture. All five services share the same repository-root context and `app/Dockerfile`; App Manager assigns each service its own local image name. The digest-pinned Python base installs distro ffmpeg and hash-locked, binary-only Python dependencies from `requirements.lock` (no native compilation).

For development, build `docker build --build-arg SOURCE_REVISION=<pushed-sha> -f app/Dockerfile -t wizard-connectors:<pushed-sha> .` on the designated worker. Deploy the checked-in five-service compose, not just the UI container: UI is on internal networks, Google broker and private worker use distinct outbound lanes and credentials. The normal install form supplies all runtime configuration. Bind the UI through the authenticated Wizard route. Never bake secrets into images.

`python3 -m unittest discover -s tests -v` exercises policy/lifecycle without network. Regenerate the cross-platform lock with `uv pip compile requirements.txt --universal --python-version 3.12 --generate-hashes -o requirements.lock`. The checked-in compose is the portable manifest; it no longer needs `CONNECTORS_IMAGE` or a manually prebuilt image. App Manager's approved checker plus shared-function gate remain authoritative. Production installation goes through App Manager, not manual registry edits.

Shared UI kit/boot origins: Wizard App Manager `hello-wizard` (first-party Humanity Labs code, used here under MIT). UI design: first-party Claude Opus consultation, implemented here; no private owner data in source.
