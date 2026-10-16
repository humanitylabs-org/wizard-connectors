# Connected accounts: native Wizard UX

Files: `web/index.html`, `web/app.js`, `web/styles.css` on top of the shared kit `web/wizard-ui.css`.
Frontend only; the auth broker and backend APIs are unchanged.

## Structure

One list home with drill-in views, modelled on Wizard Settings (`.design-reference/reference-settings.png`):

```
root ─┬─ Google ── account(id)
      ├─ sample thread(id) ── private summary(id)
      └─ How this preview works (from root or Google)
```

- **Root**: three sections, Accounts (Google row with a one-line status), Private summaries ·
  Practice (fictional sample threads) and About.
- **Google**: calm setup state when sign-in isn't ready ("isn’t set up yet" / "waiting for review",
  "Nothing is needed from you", Refresh status, Setup details). Raw blocker codes appear only in About.
  When ready: account rows, Connect, and a Continue-on-Google panel that the user opens with their own tap.
- **Account**: status, granted permissions in plain language, YouTube Music linking, Reconnect,
  Disconnect (confirmed in the sheet).
- **Thread / Summary**: every sample carries a "Fictional sample" tag. The summary dock names the real
  private model (tinfoil · glm-5-3, no tools, no fallback). Model output renders as text nodes only.

## Back

Back (platform or on-screen) closes the sheet first, then climbs one route, and at root returns
`false` to the host, so it never exits. Leaving a thread cancels its summary. Focus returns to the row
that opened the view, and scroll position is restored.

## Visual system

- Only kit roles: `--ink`, `--ink-2`, `--ink-3`, `--line`, `--line-2`, `--fill`, `--fill-2`, `--accent`,
  `--accent-soft`, `--on-accent`, `--danger`, `--wz-base`, plus `--r`, `--r-tile`, `--r-pill`, `--ease`. There are
  no app colours, so every skin (including Signal's square shape) flows through.
- Hosted: body transparent (kit rule 1); the shell's window glass is the canvas.
- Lists are grouped panels (hairline border, faint fill, separators), the same as Settings. Tiles use
  `--accent-soft` with accent line icons.
- Buttons: pill, 44px minimum; primary = accent, ghost = accent text, danger = outlined `--danger`.
- Modal (`dialog.ca-sheet`): fully opaque `var(--wz-base, var(--canvas))`, so it never shows text through
  it (fixes the overlap in `before-phone.png`). Centred on wide screens, bottom sheet at ≤520px.
- Bottom dock for thread and summary actions, like the Chats composer, with safe-area padding.

## Constraints

- No inline styles or scripts (CSP); all styling is in classes.
- `[hidden]` is forced to `display: none !important`.
- 320px: actions, the lookup field, provenance and the dock stack vertically. Text wraps everywhere
  (`overflow-wrap: anywhere`), with no fixed text heights, so enlarged type reflows.
- Reduced motion: the kit disables transitions and animations, including the spinner.

## Opus review and operator refinement

First-party Claude CLI `--model opus` designed the candidate. Completed design continuation and
render-review envelopes both report `claude-opus-5-5`, provider `firstParty`, `is_error: false`, and
no permission denials. The initial longer call wrote HTML/JS but timed out before its final JSON;
its missing envelope is not represented as a successful completion. A bounded continuation wrote
CSS and this design document. Three excess closing parentheses in the original JS were repaired
before the first render.

Opus inspected actual native Settings and candidate shell screenshots, including the real private
summary. Verdict: **accept with fixes**, explicitly not production approval. Operator refinements:
- Relative type sizes and text-holding tile/input sizes, preserving default kit sizing.
- Honest setup-pending copy, not an implication of installation actively running.
- Citation groups and accessible source names; success announcements are screen-reader-only.
- Narrower desktop content; fully opaque themed dialogs retained.
- Client result expiry clears text from both memory and DOM; navigation fences cancel late jobs.
- Escape closes only the active sheet before desktop shell shortcuts can consume the key.

The model's summary heading is preserved rather than heuristically deleting generated content.
Open Music remains a secondary ghost link, with the catalog/playback distinction immediately above it.

## Executable acceptance

`qa/native-candidate.mjs` substitutes only this candidate's static assets inside a browser session
against the real Wizard shell and API. It exercises `/wizard-connectors/design/`, not a duplicated
backend. It verifies real fictional-message private summarization, source references, opaque
phone modal, mobile browser Back, standalone light fallback and standalone first-root-Back guard.

`qa/native-matrix.mjs` verifies all registered skins (Nebula, Grove, Tide, Ember, Signal), opaque
sheet material in each, actual window/fullscreen integration, 320px iframe with 150% text,
Escape, theme persistence of an unsent input and scroll, and state/lifecycle fixtures. Account
and failure fixtures are explicitly labeled; they are not evidence of real Google consent.
No live policy/account mutation occurs. Actual platform client/services are never mocked.

Run on the approved external-volume build/QA host with `QA_BASE`, `PLAYWRIGHT_PACKAGE` (existing
Playwright package.json), and `CHROME_BINARY` configured. Browser reports and screenshots go to
`evidence/`. The tests do not deploy, register, or alter an installed view.

The five currently registered hosted skins are dark; generic light fallback is separately tested
standalone. Missing/transparent host `--wz-base` on an unknown future skin is not certified here.

## Deployment boundary

Static `web/` is the deployable artifact. It requires the existing same-origin shared core at
`/wizard-os-home/core/app-client.js` and owner-protected `/wizard-connectors/api/`. Serve the static
directory at the protected `/wizard-connectors/design/` location; do not embed a token, copy secrets,
change Google configuration, or create a second backend. Parent owns final hosted-path verification
and any promotion. The original installed app and production configuration are unchanged.
