"""wizard-connectors#66: a row hidden by its switch must not be shown.

The kit's `.wz-row { display: flex }` overrides the browser's default `[hidden]`
rule, so `#grants-row` stayed visible with grants-panel off. The app stylesheet
must restore `[hidden] { display: none }` with enough weight to beat the kit.
"""
import pathlib
import re
import unittest

WEB = pathlib.Path(__file__).resolve().parents[1] / "web"


class HiddenRowsTests(unittest.TestCase):
    def test_hidden_attribute_beats_kit_display(self):
        css = (WEB / "styles.css").read_text()
        rule = re.search(r"(?m)^\[hidden\]\s*\{([^}]*)\}", css)
        self.assertIsNotNone(rule, "styles.css needs a top-level [hidden] rule")
        self.assertRegex(rule.group(1), r"display\s*:\s*none\s*!important")

    def test_grants_row_starts_hidden_and_is_gated(self):
        html = (WEB / "index.html").read_text()
        self.assertRegex(html, r'<button id="grants-row"[^>]*\bhidden\b')
        js = (WEB / "app.js").read_text()
        self.assertIn("$('grants-row').hidden=!state.grants_panel?.on", js)


if __name__ == "__main__":
    unittest.main()
