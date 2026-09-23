"""Tests for candid.lock (session lock/unlock).
Run: CANDID_DATA_DIR=/tmp/x CANDID_CONFIG_DIR=/tmp/xc python3 -m unittest tests.test_lock -v
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("CANDID_DATA_DIR", tempfile.mkdtemp(prefix="candid-test-data-"))
os.environ.setdefault("CANDID_CONFIG_DIR", tempfile.mkdtemp(prefix="candid-test-config-"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import lock as L  # noqa: E402
from candid import config as _config  # noqa: E402
from candid.crypto import CryptoError, init_keystore  # noqa: E402


FAST_ITER = 2_000  # fast KDF for tests; real default is 600_000
GOOD = "Tr0ub4dor&3-horse-battery!"  # strong
WRONG = "Wr0ng-horse-battery-staple!"


def _session_path():
    return Path(os.environ["CANDID_CONFIG_DIR"]) / "session.json"


def _keystore_path():
    return Path(os.environ["CANDID_CONFIG_DIR"]) / "keystore.json"


def _clear_state():
    for p in (_session_path(), _keystore_path()):
        if p.exists():
            p.unlink()


class TestLock(unittest.TestCase):
    def setUp(self):
        _clear_state()

    def tearDown(self):
        _clear_state()

    def _init_and_unlock(self, passphrase=GOOD, **kwargs):
        init_keystore(passphrase, iterations=FAST_ITER)
        L.unlock_session(passphrase, **kwargs)

    # --- unlock failures ---------------------------------------------------

    def test_unlock_without_keystore_fails_cleanly(self):
        with self.assertRaises(CryptoError) as ctx:
            L.unlock_session(GOOD)
        self.assertIn("candid crypto init", str(ctx.exception))
        self.assertFalse(_session_path().exists())

    def test_unlock_with_wrong_passphrase_fails(self):
        init_keystore(GOOD, iterations=FAST_ITER)
        with self.assertRaises(CryptoError):
            L.unlock_session(WRONG)
        self.assertTrue(L.is_locked())
        self.assertIsNone(L.get_session_passphrase())

    def test_unlock_with_bad_timeout_fails(self):
        init_keystore(GOOD, iterations=FAST_ITER)
        with self.assertRaises(CryptoError):
            L.unlock_session(GOOD, timeout_minutes=0)
        self.assertTrue(L.is_locked())

    # --- round trip ----------------------------------------------------------

    def test_lock_unlock_round_trip(self):
        init_keystore(GOOD, iterations=FAST_ITER)
        self.assertTrue(L.is_locked())  # keystore but no session
        L.unlock_session(GOOD)
        self.assertFalse(L.is_locked())
        self.assertEqual(L.get_session_passphrase(), GOOD)
        L.lock_now()
        self.assertTrue(L.is_locked())
        self.assertIsNone(L.get_session_passphrase())
        self.assertFalse(_session_path().exists())

    def test_lock_now_noop_without_session(self):
        init_keystore(GOOD, iterations=FAST_ITER)
        L.lock_now()  # must not raise
        self.assertTrue(L.is_locked())

    def test_default_timeout_from_config(self):
        init_keystore(GOOD, iterations=FAST_ITER)
        L.unlock_session(GOOD)
        info = L.session_info()
        self.assertEqual(info["timeout_minutes"],
                         _config.CONFIG_DEFAULTS["lock_timeout_minutes"])
        self.assertEqual(info["timeout_minutes"], 30)

    def test_custom_timeout(self):
        init_keystore(GOOD, iterations=FAST_ITER)
        L.unlock_session(GOOD, timeout_minutes=5)
        info = L.session_info()
        self.assertEqual(info["timeout_minutes"], 5)
        self.assertGreater(info["expires_in_seconds"], 0)

    # --- require_unlocked ----------------------------------------------------

    def test_require_unlocked_noop_without_keystore(self):
        L.require_unlocked()  # no keystore: backward compatible, no raise

    def test_locked_state_blocks(self):
        init_keystore(GOOD, iterations=FAST_ITER)
        with self.assertRaises(L.LockError) as ctx:
            L.require_unlocked()
        self.assertIn("candid is locked", str(ctx.exception))
        self.assertIn("candid unlock", str(ctx.exception))
        # LockError is LookupError-ish
        self.assertIsInstance(ctx.exception, LookupError)
        # and unlocked passes
        L.unlock_session(GOOD)
        L.require_unlocked()

    # --- expiry ----------------------------------------------------------------

    def test_expired_session_counts_as_locked(self):
        self._init_and_unlock()
        # age the session file 2 hours back so it is expired
        p = _session_path()
        data = json.loads(p.read_text(encoding="utf-8"))
        data["created_at"] = (datetime.now(timezone.utc)
                              - timedelta(hours=2)).isoformat()
        data["timeout_minutes"] = 30
        p.write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(L.is_locked())
        self.assertIsNone(L.get_session_passphrase())
        with self.assertRaises(L.LockError):
            L.require_unlocked()

    # --- file perms ------------------------------------------------------------

    def test_session_file_has_0600_perms(self):
        self._init_and_unlock()
        p = _session_path()
        self.assertTrue(p.exists())
        mode = stat.S_IMODE(p.stat().st_mode)
        self.assertEqual(mode, 0o600)

    # --- no secret leakage ------------------------------------------------------

    def test_passphrase_never_in_session_info(self):
        self._init_and_unlock()
        info = L.session_info()
        blob = json.dumps(info)
        self.assertNotIn(GOOD, blob)
        self.assertNotIn("passphrase", blob.lower())
        self.assertFalse(info["locked"])
        self.assertIsNotNone(info["created_at"])
        self.assertIsNotNone(info["expires_in_seconds"])
        # and after locking, metadata is empty but still secret-free
        L.lock_now()
        info = L.session_info()
        self.assertTrue(info["locked"])
        self.assertIsNone(info["created_at"])
        self.assertNotIn(GOOD, json.dumps(info))

    def test_touch_session_is_noop(self):
        self._init_and_unlock()
        before = _session_path().read_text(encoding="utf-8")
        L.touch_session()
        after = _session_path().read_text(encoding="utf-8")
        self.assertEqual(before, after)

    # --- CLI wrappers -----------------------------------------------------------

    def test_cmd_lock_and_unlock(self):
        init_keystore(GOOD, iterations=FAST_ITER)
        L.cmd_unlock(SimpleNamespace(timeout=None), _passphrase=GOOD)
        self.assertFalse(L.is_locked())
        L.cmd_lock(SimpleNamespace())
        self.assertTrue(L.is_locked())
        self.assertFalse(_session_path().exists())

    def test_cmd_unlock_wrong_passphrase_raises(self):
        init_keystore(GOOD, iterations=FAST_ITER)
        with self.assertRaises(CryptoError):
            L.cmd_unlock(SimpleNamespace(timeout=None), _passphrase=WRONG)

    def test_register_lock_commands(self):
        import argparse

        parser = argparse.ArgumentParser(prog="candid")
        subs = parser.add_subparsers()
        L.register_lock_commands(subs)
        args = parser.parse_args(["lock"])
        self.assertEqual(args.func, L.cmd_lock)
        args = parser.parse_args(["unlock", "--timeout", "10"])
        self.assertEqual(args.func, L.cmd_unlock)
        self.assertEqual(args.timeout, 10)
        args = parser.parse_args(["unlock"])
        self.assertIsNone(args.timeout)


if __name__ == "__main__":
    unittest.main()
