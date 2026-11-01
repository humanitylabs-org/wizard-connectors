# Connected accounts Alpha preparation

Version: **0.2.0-alpha.1**. This is source preparation, not a deployment or a published Alpha package.

## Changed owner flow

Google → Let your wizard set this up first opens three labelled agreement checkboxes, official links, and a country picker. All three and a country are required before saving. The encrypted broker stores version `google-2026-11`, IDs, country and its own acceptance timestamp. The agent receives only IDs/version/country. Manual setup links the same documents without delegating acceptance.

The agent setup uses a fresh disposable Human Handoff profile. The owner types their password and 2FA during takeover with every inspection paused. The script matches only recorded agreements, declines optional marketing, and stops at new documents, billing, identity checks or unknown UI. On terminal setup exits it attempts Google sign-out, stops the handoff, and verifies stopped/expired status plus actual profile/capability removal. Active owner sign-in/verification is instead paused resumably under its original TTL without inspection or deletion. A deposited app is not task completion until sign-out and teardown are verified. No persistent/shared-browser fallback is enabled. See [security](SECURITY.md#google-app-setup-sign-in).

## Portable recipe

- All five services use exactly `wizard-connectors:0.2.0-alpha.1`, `pull_policy: never`, and the existing shared non-root/read-only/capability-drop/tmpfs hardening. `runtime.package: image` avoids rebuilding an Alpha archive as a build-tier source app.
- No reviewed-image form field remains. Required fields are auto-generated passwords, including the encrypted-store secret; installer/provider-specific values remain optional.
- The installer must supply its routed Wizard host in `WIZARD_TRUSTED_HOSTS`; loopback/internal hosts are the safe blank default. Origins must match that validated Host or the explicit origin list. Arbitrary matching Host/Origin pairs are refused (DNS-rebinding defense). New redirects use `/connected-accounts/api/google/callback` with validated forwarded route prefixes; already-saved redirects are preserved byte-for-byte, including legacy paths. Confirm installer host injection in the fresh-box gate; no owner-specific host is embedded here.
- The upstream view serves `/`; the gateway uses the canonical app ID `connected-accounts` as its mount, not a second nested view path.
- The native image must be loaded under that exact tag before install. Merely changing Compose does not create a distributable image.

## Verification in source preparation

- Unit suite: **96 tests, OK**. Includes real owner HTTP/RPC and encrypted-store restart persistence for agreements, negative auth/origin/validation/storage cases, fake Console exact accept/stop/country/marketing behavior, and synthetic disposable-profile/sign-out/teardown checks. No browser is launched by these tests.
- Dependency-free Node DOM contracts exercise checkbox/country gating, save payload, Back, account cards and existing interaction feedback. `node --check` passes for `web/app.js` and every `qa/*.cjs`.
- All three Google document URLs returned HTTP 200 to `curl -sI`.
- Source scan found no owner name, private tailnet/domain or personal email. The remaining email literals are deliberately synthetic example/invalid-domain fixtures and a fake provider UID.
- `wam check` passes the approved checker and shared-system-function gate. Existing warnings remain for the shared-kit copy, native confirm dialogs and style debt; this does not claim visual acceptance.

## Not executed / next acceptance gates

No containers, Caddy, installed recipes or live data were changed. No build jobs were submitted. The prepared native-architecture runner is syntax-checked only; it has not been executed and no image/archive/hash is claimed.

`qa/google_connect_ux.cjs` is extended to capture the new agreements screen in dark Nebula and a light fixture skin, including live skin preservation, touch-target size, disabled states, failed/successful save, manual links, nested Back and outside-tap close. Those screenshots have **not** been produced or inspected for this change. Real in-shell/mobile acceptance remains separate from the standalone synthetic harness.

Still required when separately authorized: native amd64/arm64 build/export and OCI-revision checks; amd64 browser/Console fixtures; actual current Google Console plus disposable handoff sign-out/profile deletion; fresh-box Alpha Store install/Open; actual Calendar grant/network integration. No fixture result substitutes for those gates.

Calendar's current upstream manifest still has `uses: []`; it must declare `uses: [connected-accounts]` or `uses: [calendar-source]` with that slot selected, and integrate the broker API. The provider already declares `calendar-source` and enforces incoming `wizard-calendar` hashes. See [Calendar consumer contract](CALENDAR_API.md#fresh-calendar-compatibility-and-owner-grants).
