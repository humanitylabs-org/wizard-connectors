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
- **Google**: calm setup state when sign-in isn't ready ("being prepared" / "waiting for review",
  "Nothing is needed from you", Check again, Setup details). Raw blocker codes appear only in About.
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

## Open points for review

- No rendered screenshot yet: the operator renders this for the second-round review.
- `--wz-base` falls back to the kit `--canvas` when the host doesn't send it. Check that every skin sends it.
- The Back test (open a nested view, press Back, assert still open) belongs to the QA harness
  (`qa/native-baseline.mjs`) and isn't added here.
