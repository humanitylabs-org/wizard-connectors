# Connected accounts 0.2.0 release notes

Version **0.2.0** (previous listed release: 0.1.1).

## Changed owner flow


Google → Let your wizard set this up first opens three labelled agreement checkboxes, official links, and a country picker. All three and a country are required before saving. The encrypted broker stores version `google-2026-11`, IDs, country and its own acceptance timestamp. The agent receives only IDs/version/country. Manual setup links the same documents without delegating acceptance.

The agent setup uses a fresh disposable Human Handoff profile. The owner types their password and 2FA during takeover with every inspection paused. The script matches only recorded agreements, declines optional marketing, and stops at new documents, billing, identity checks or unknown UI. On terminal setup exits it attempts Google sign-out, stops the handoff, and verifies stopped/expired status plus actual profile/capability removal. Active owner sign-in/verification is instead paused resumably under its original TTL without inspection or deletion. A deposited app is not task completion until sign-out and teardown are verified. No persistent/shared-browser fallback is enabled. See [security](SECURITY.md#google-app-setup-sign-in).

## Packaging

- `runtime.package: image`. All five services use one public multi-arch (linux/amd64 + linux/arm64) image, `ghcr.io/humanitylabs-org/wizard-connectors`, pinned by tag `sha-<commit>` and digest in `runtipi/docker-compose.yml`, plus the existing shared non-root/read-only/capability-drop/tmpfs hardening. The image is built from `app/Dockerfile` by the shared `app-image` workflow; its `org.opencontainers.image.revision` label is the commit that ran the workflow.
- Network isolation: the ingress service is `wizard-connectors-calendar` (the advertised Calendar endpoint host) and joins no shared main network, so App Manager keeps the app `isolated`.
- Dependency update: PyJWT 2.15.1 (security update carried from the default branch).
- No reviewed-image form field remains. Required fields are auto-generated passwords, including the encrypted-store secret; installer/provider-specific values remain optional.
- The installer must supply its routed Wizard host in `WIZARD_TRUSTED_HOSTS`; loopback/internal hosts are the safe blank default. Origins must match that validated Host or the explicit origin list. Arbitrary matching Host/Origin pairs are refused (DNS-rebinding defense). New redirects use `/connected-accounts/api/google/callback` with validated forwarded route prefixes; already-saved redirects are preserved byte-for-byte, including legacy paths.
- The upstream view serves `/`; the gateway uses the canonical app ID `connected-accounts` as its mount, not a second nested view path.

## Checks run for this release

- Unit suite: 107 tests, OK (real owner HTTP/RPC and encrypted-store restart persistence for agreements, negative auth/origin/validation/storage cases, fake Console behavior, synthetic disposable-profile/sign-out/teardown checks). No browser is launched by these tests.
- Dependency-free Node DOM contracts and `node --check` for `web/app.js` and every `qa/*.cjs`.
- The App Index checker (rules 1-16, including the anonymous multi-arch pull of every compose image) and the App Manager planner (app stays `isolated`, Calendar link intact).

## Not covered by those checks

Real Google Console / consent with a disposable account, in-shell and physical-phone visual acceptance, and an end-to-end Calendar grant on a fresh box are separate gates. No fixture result substitutes for them.

Calendar must declare `uses: [connected-accounts]` or `uses: [calendar-source]` with that slot selected, and integrate the broker API. The provider already declares `calendar-source` and enforces incoming `wizard-calendar` hashes. See [Calendar consumer contract](CALENDAR_API.md#fresh-calendar-compatibility-and-owner-grants).
