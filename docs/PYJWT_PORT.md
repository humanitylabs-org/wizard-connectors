# PyJWT patch on the Google/Calendar live branch

REUSE: retain the existing encrypted Google store, signed-ID-token verifier,
client setup, Calendar account binding/grants and ingress unchanged.
EXTEND: carry the already-reviewed dependency-only patch from PR #5
(`1b5c1a76668ddc96138383311452003e8e6d2d52`, PyJWT 2.15.1 plus hash lock)
onto the actual served `feature/byo-google-calendar` source, now bced097.
No store tree is copied and no Google/Calendar feature is removed.

`tests/test_locked_dependencies.py` prevents a dependency downgrade. The existing
`test_google_http`, `test_google_setup`, `test_google_connect_ux`, `test_contract`
and `test_media_isolation` suites must pass against the candidate. Browser
proof uses the existing separately mounted `qa/byo_browser_server.py` and real
UI/ingress/RPC/encrypted store with FakeGoogle only; the Appearance host is
explicitly mocked, not a live-shell or real-provider claim.

This is a maintenance candidate, not a deployed or published update. No visible
layout change is intended. It must remain a draft until parity, suite, image
identity and inspected screenshots are recorded. The other branch's manifest
changes (external connector/non-system/id) are already on the live lineage;
the rest of its tree must not replace this branch. Review this PR against
`feature/byo-google-calendar`, not the older default branch.
