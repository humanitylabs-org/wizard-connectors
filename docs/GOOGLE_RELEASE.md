# Google: bring your own OAuth app

Each Wizard owner creates a Google Cloud OAuth **Web application** once. No
shared managed Google client, cookie import or CLI credential reuse is needed.
In Connected accounts → Google accounts → **Your Google app**:

1. Create a Google Cloud project.
2. Enable **Google Calendar API** (and **YouTube Data API v3** for Music catalog).
3. Configure the OAuth consent screen as **External**. Add yourself as a test
   user, then Publish app to **In production** so refresh tokens do not expire
   after 7 days. An unverified-app warning is expected for personal use.
4. Credentials → Create OAuth client ID → **Web application**.
5. Copy the exact **Authorized redirect URI** from the app into Google. It is
   your trusted HTTPS origin + route prefix + `/api/google/callback`, typically
   `https://<host>/wizard-connectors/api/google/callback`. The UI uses configured
   trusted HTTPS origins and a validated `X-Forwarded-Prefix`; when the route is
   not derivable it offers an editable best guess. Verify it before registering.
6. Paste the Client ID and Client secret in the app and Save. The secret is never
   read back. Connect each account. Click **Let Calendar read this account** for
   incremental Google consent, then explicitly **Allow Calendar to use this
   account**. Multiple Google accounts may be connected and bound independently.

`POST /api/google/client` (owner authentication + same-origin) accepts exactly
`{client_id, client_secret, redirect_uri}`. Client ID must end in
`.apps.googleusercontent.com`; secret is 8–512 non-whitespace characters;
redirect must be HTTPS (or localhost HTTP), with no credentials/query/fragment
and a path ending `/api/google/callback`. `DELETE /api/google/client` clears it.
Replacing or deleting a client cancels pending consent, clears saved tokens,
marks existing accounts reauth_required and removes Music/Calendar bindings.
A reconnected account still needs explicit service binding consent.

Optional `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` retain
installer compatibility and take precedence over owner configuration. Any
partial environment triple reserves configuration for the installer and fails
closed rather than falling back. Status labels `client_source: env | owner`,
`client_configured`, `client_id`, `redirect_uri`, never the secret.
`GOOGLE_DISABLED=true` is the kill switch for provider operations. The obsolete
`GOOGLE_REVIEW_APPROVED` flag is no longer required or used.

## Storage and installation

WAM auto-generates required password form field `GOOGLE_STORE_SECRET` (minimum
32 characters). The broker derives its Fernet key with HKDF-SHA256, length 32,
salt `wizard-connectors/google-store/v1`, info `fernet-credential-store`, then
URL-safe-base64 encodes it. Existing `GOOGLE_STORE_KEY` takes precedence and
remains supported. Retain the original key/secret separately for restores.
Changing or losing it with existing encrypted data **refuses startup**; never
reset or discard the store to conceal a decryption failure.

Only the broker receives Google client/key settings and encrypted volume.
UI → broker uses existing token-authenticated fixed RPC, not generic fetch.
Five services retain isolated networks, non-root/read-only execution, capability
drops, bounded tmpfs, no-new-privileges and no host sockets/home mounts. Ingress
joins the shared main network for grant-checked Calendar access. WAM injects the
standard read-only grants directory into app services; the application recipe
contains no grants mount. The UI validates incoming `wizard-calendar` grants.
See [Calendar API](CALENDAR_API.md).
Google/private/media outbound lanes remain separate. Host administrators remain
trusted; this is not host-admin-resistant isolation.

Build from a pushed revision on Thales using the repository-root Dockerfile and
five-service compose. No image publication or live installation is implied by a
PR or isolated staging. Private summaries remain fictional and use only the
existing attested Tinfoil/glm-5-3 route. Existing Music playback is untouched.

## Authorization invariants

Initial scopes are `openid email`. Account-specific incremental consent adds
`youtube.readonly` and/or `calendar.readonly`; `include_granted_scopes=true`
accepts previously granted supported scope unions without dropping the other
service. Unsupported scopes or a missing requested scope are refused. Music
binding and Calendar binding are independent; authorization never auto-binds.
OAuth uses code + S256 PKCE, nonce, one-use state and browser binding. RS256 ID
verification checks issuer, audience, azp, expiry/iat, nonce and stable subject.
Refresh uses the existing lock and verified userinfo subject; auth failure or
scope loss marks reauth_required and removes Calendar access. Disconnect clears
local credentials first and separately reports revocation success/failure.
TLS proxies must not log callback query strings or Authorization headers.

`tests/test_google_http.py` is explicitly **FAKE provider transport**, with
locally signed fake ID tokens checked by production verification, real HTTP/RPC
and encrypted storage. It is not live Google authorization proof. Neither tests
nor the PR claim a real owner account has consented. Personal Google console
setup and real consent are owner actions.

Sources:
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/identity/openid-connect/openid-connect
- https://developers.google.com/calendar/api/v3/reference/calendarList/list
- https://developers.google.com/calendar/api/v3/reference/events/list
