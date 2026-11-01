"""Keep the verified JWT patch when the live Google/Calendar branch releases.

The existing signed-fixture HTTP suite tests bad signatures, nonce, audience,
expiry, scoped consent and refresh; this test guards the dependency downgrade.
"""
from importlib.metadata import version
from pathlib import Path
import re
import unittest


class LockedJWT(unittest.TestCase):
    def test_runtime_and_hash_lock_keep_the_reviewed_pyjwt_patch(self):
        actual = version('PyJWT')
        self.assertGreaterEqual(tuple(int(n) for n in actual.split('.')[:3]), (2, 15, 1))
        lock = (Path(__file__).resolve().parents[1] / 'requirements.lock').read_text()
        pin = re.search(r'^pyjwt==([^\s]+) \\\n((?:    .*\n)+)', lock, re.M)
        self.assertIsNotNone(pin, 'PyJWT must be exactly pinned with hashes')
        assert pin is not None  # Narrow the match after the regression assertion.
        self.assertEqual(pin.group(1), actual)
        self.assertIn('--hash=sha256:', pin.group(2))


if __name__ == '__main__':
    unittest.main(verbosity=2)
