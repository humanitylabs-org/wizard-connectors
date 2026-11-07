# Google connect interaction contract

## Reuse decision

Reuse:
- navigation/theme: REUSE WizardApp Back, update hold and theme bridge, and the vendored Wizard UI kit. Do not edit the kit.
- Google accounts: EXTEND the existing DOM helpers, account cards, disclosures, safe sign-in flow and Calendar/Music APIs. No new credential channel or provider endpoint.
- setup: REUSE the existing one-time guide, draft protection and saved app settings.

Visual: forum-only `qa/google_connect_ux.cjs` captures phone and wide standalone candidate pages in two fixture palettes. These are not live-shell or physical Android evidence.

## Screens

- Home has one tappable Google provider card. Its subtitle names one account or the account count and Calendar on/off, or explains that Google is not connected/set up. No duplicate settings link. The unrelated private-summary practice card and its web-only renderer/styles are removed at the owner's request; backend summary contracts are unchanged.
- Google has one email-titled card per account. Both broker `active` and legacy `connected` mean **Connected**; `reauth_required` means **Sign in again**. Under **Used by**, Calendar has a labelled switch when permission exists, or **Allow** when it does not. Enabling requires confirmation. Music appears in Used by when YouTube permission exists; its optional permission, catalog lookup, selection/unlink and Open Music remain available under More. Catalog access does not enable playback.
- **More** keeps reconnect, confirmed Disconnect and permission details quiet. Add another Google account follows the cards. The completed Google app setup is one quiet bottom row with Change.
- Browser completion pages are instruction-only: a check mark and **Google connected**, or the existing server-selected error reason. They never call `window.close`, show a nonworking close button, or link back into the app in the phone's browser. The error template retains `{{REASON}}` for the server's fixed reason replacement.

## Security and interaction regressions

- Connect opens one blank window inside the click gesture, paints Opening Google… before awaiting the server, then only uses a validated HTTPS accounts.google.com URL. Blocked windows have a visible continuation link. Duplicate and stale responses cannot stack links or restore a cancelled view.
- Initial identity consent requests read-only Calendar permission, never Calendar service use. A separate owner-confirmed switch sends the existing calendar/bind action with explicit true/false consent. The switch paints the choice, disabled state and aria-busy before I/O, then reads back state; failures restore the prior choice and explain the uncertainty.
- The waiting view checks on focus/visibility and every five seconds, stopping after an account arrives, Back/Cancel, or one day. This is unchanged; no automatic repeated sign-in starts.
- Manual step 6 requires Save, not Next. Failed saves and cancelled Back retain in-memory drafts; deliberate discard clears them and releases the existing update hold. No browser-storage credentials.
- Callback PKCE/state/nonce/browser-cookie validation, cookie clearing, query non-echo, owner auth, CSRF/Origin and host checks remain in the untouched backend. No Google calls or owner-data writes are needed for visual QA.
- Hosted canvas stays transparent; desktop has no outer width cap. All added colors/radii use Appearance roles and dark kit fallbacks. Floating dialogs retain an opaque base. Standalone boot is dark.

## Evidence runner

Run `node qa/google_connect_ux.cjs SOURCE OUTPUT` only on the authorized forum worker. The suite now uses standalone fixture pages rather than the flaky live shell iframe. Every request is fulfilled from candidate assets/synthetic state or aborted; it makes zero real broker starts and zero live owner writes. It preserves the production CSP in its HTML responses and injects only a QA bridge for standalone Back/update-hold calls. Fixture colors are Nebula/dark and Signal/light; changing them keeps the actual app document and draft.

The eight required phone screenshots are `home-connected-{nebula,light}.png`, `google-calendar-on-{nebula,light}.png`, `google-connected-{nebula,light}.png`, and `google-error-{nebula,light}.png`. Two wide Google-page screenshots are also saved. `browser-receipt.json` records checks, intercepted actions, blocked destinations and the exact screenshot inventory. A receipt is not visual approval: inspect the images after the queued job.

Run `node qa/google_account_ui_test.cjs` for dependency-free real-renderer DOM contracts without a browser. Python unittest discovery invokes it when Node is installed; the Python-only runtime image skips only that Node wrapper, so the forum runner also runs the DOM suite on the host. HTTP tests still exercise the real broker/RPC/server with a fake provider, including malformed-input refusal, privacy protection, callback reasons, secret non-echo and cookies.

No deployment is part of this change.
