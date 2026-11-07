"""Offline packaging pin regressions; no browser/package installation."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BrowserVersionTests(unittest.TestCase):
    def test_separate_published_python_and_node_pins(self):
        pins = json.loads((ROOT/'tools/browser_versions.json').read_text())
        self.assertEqual(pins['python'], '1.56.0')
        self.assertEqual(pins['node'], '1.56.1')
        self.assertEqual(pins['driver'], pins['node'])
        self.assertEqual(pins['chromium_revision'], '1194')
        self.assertEqual(pins['chromium_version'], '141.0.7390.37')

    def test_runner_reads_python_pin_not_node_or_unpublished_literal(self):
        tree = ast.parse((ROOT/'tools/alpha_runner.py').read_text())
        selections = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp)
                      and isinstance(n.left, ast.Constant) and n.left.value == 'playwright==']
        self.assertEqual(len(selections), 1)
        self.assertEqual(ast.unparse(selections[0].right), "pins['python']")
        self.assertNotIn('playwright==1.56.1', ast.unparse(tree))


if __name__ == '__main__': unittest.main()
