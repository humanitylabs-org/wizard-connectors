# Google connect interaction contract

## Reuse decision

REUSE the existing WizardApp Back, update hold and theme bridge, the vendored Wizard UI kit, the role-isolated Google broker, and the existing explicit Calendar/Music binding APIs. EXTEND the existing Google view and HTTP handler only. No new OAuth client, theme store, credential channel or provider endpoint is introduced. The shell component inventory remains the authority for shared components.

## Regression contract

- Connect opens one blank window inside the click gesture, paints a disabled Opening Google… state before awaiting the broker, then replaces the blank window location only with a validated HTTPS accounts.google.com URL. A blocked/closed window leaves a prominent in-view continuation link. Duplicate and stale results cannot stack links or restore a dismissed view.
- Initial identity consent requests Calendar read-only, but never binds Calendar automatically. Show this account’s calendar in Calendar remains a separate owner-confirmed operation. Music catalog and playback remain separate.
- The waiting view checks on focus/visibility and every five seconds, stopping after an account arrives, Back/Cancel, or ten minutes. No automatic repeated provider starts.
- Manual step 6 requires Save; Next cannot skip credential validation. Failed saves and cancelled Back retain in-memory drafts. A deliberate discard erases the draft and releases the existing update hold. No credentials are persisted in browser storage.
- Callback success/error pages retain the existing PKCE/state/nonce/browser-cookie handling, clear the callback cookie and never echo query parameters. Success auto-closes script-opened windows; ordinary tabs keep return instructions. The public, host-checked privacy page exposes no account data.
- Hosted canvas stays transparent; app layout has no desktop outer max-width. Token-based controls follow live skin changes, with an opaque base under floating panels. Standalone boot remains dark. Do not edit the vendored kit.

## Evidence runner

Run `node qa/google_connect_ux.cjs SOURCE OUTPUT` on the authorized browser worker for live-before and candidate-static-in-real-shell screenshots. Run with `--live` only after the exact candidate image is installed, for installed evidence. The browser fences every provider navigation before network; only one real broker *start* request is allowed, and no account is connected. All account, scope, binding, failure and draft fixtures are explicitly labelled as fixtures. All credential saves and Calendar binding changes in this runner are intercepted, never forwarded to owner data.

Run the Python unittest discovery suite inside the candidate image. The new HTTP tests use a fake provider behind the real broker/RPC/server and cover the exact browser payload, public privacy route, branded callback success/error, secret non-echo, cleared cookies and rejected malformed input. Run the feature parity gate against an archive of the exact installed image revision, using `qa/google-connect-renames.txt` for wording-only migrations. Screenshots are acceptance evidence only after visual inspection; a successful browser receipt alone is not visual approval.
