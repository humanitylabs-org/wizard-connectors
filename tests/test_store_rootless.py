"""#45: the Google broker starts on rootless Docker, where it cannot chmod its own /data volume."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
from cryptography.fernet import Fernet
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from google_broker import Store

def _no_chmod(*a, **k): raise PermissionError(1, 'Operation not permitted')

class RootlessStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'data'; self.root.mkdir(); os.chmod(self.root, 0o777)

    def test_writable_volume_it_cannot_chmod_still_starts_and_saves(self):
        with mock.patch('google_broker.os.chmod', _no_chmod):
            store = Store(str(self.root), Fernet.generate_key().decode())
        store.save({'accounts': {'a': 1}, 'binding': None})
        self.assertEqual(store.load()['accounts'], {'a': 1})
        self.assertEqual((self.root / 'google.enc').stat().st_mode & 0o777, 0o600)

    def test_volume_it_can_neither_chmod_nor_write_fails_with_a_clear_error(self):
        with mock.patch('google_broker.os.chmod', _no_chmod), mock.patch('google_broker.os.access', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'credential_store_not_writable'):
                Store(str(self.root), Fernet.generate_key().decode())

    def test_owned_volume_is_still_locked_to_0700(self):
        Store(str(self.root), '')
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

if __name__ == '__main__': unittest.main()
