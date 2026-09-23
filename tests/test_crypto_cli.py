"""End-to-end CLI tests for the batch-72 encryption wiring.

Drives the real argparse dispatch (candid.__main__.main) with isolated
data/config dirs. The passphrase never appears on argv: `crypto init`
goes through the handler's private kwarg (function-level), `unlock`
monkeypatches getpass in-process, and everything else uses the session.

Run: CANDID_DATA_DIR=/tmp/x CANDID_CONFIG_DIR=/tmp/xc python3 -m unittest tests.test_crypto_cli -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("CANDID_DATA_DIR", tempfile.mkdtemp(prefix="candid-e2e-data-"))
os.environ.setdefault("CANDID_CONFIG_DIR", tempfile.mkdtemp(prefix="candid-e2e-config-"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import atrest  # noqa: E402
from candid import config as C  # noqa: E402
from candid import crypto  # noqa: E402
from candid import encbackup  # noqa: E402
from candid import lock  # noqa: E402
from candid import tracker  # noqa: E402

PW = "Tr0ub4dor&3-horse-battery!"  # strong test passphrase; never printed
FAST_ITER = 2_000  # fast KDF for state setup; one test uses the real 600k


def _run(argv):
    """Run the CLI in-process; return (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            CLI.main(argv)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue(), err.getvalue()


class CryptoCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-e2e-"))
        self._saved = {}
        for name in ("DATA_DIR", "CONFIG_DIR", "TRACKER_PATH", "PROFILE_PATH",
                     "PREP_PACKS_DIR", "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH"):
            self._saved[name] = getattr(C, name)
        C.DATA_DIR = self.tmp / "data"
        C.CONFIG_DIR = self.tmp / "config"
        C.TRACKER_PATH = C.DATA_DIR / "tracker.json"
        C.PROFILE_PATH = C.DATA_DIR / "profile.json"
        C.OFFERS_PATH = C.DATA_DIR / "offers.json"
        C.GMAIL_PROPOSALS_PATH = C.DATA_DIR / "gmail_proposals.json"
        C.PREP_PACKS_DIR = C.DATA_DIR / "prep_packs"
        C.TAILOR_DIR = C.DATA_DIR / "tailor"
        C.SALARY_DB = C.DATA_DIR / "salary.db"
        C.DATA_DIR.mkdir(parents=True, exist_ok=True)
        C.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    # -- helpers ---------------------------------------------------------
    def _init_keystore(self, passphrase=PW, iterations=FAST_ITER):
        return crypto.init_keystore(passphrase, iterations=iterations)

    def _unlock_session(self, passphrase=PW):
        lock.unlock_session(passphrase)

    def _keystore_path(self):
        return Path(C.CONFIG_DIR) / "keystore.json"

    def _session_path(self):
        return Path(C.CONFIG_DIR) / "session.json"


class TestCryptoInit(CryptoCLIBase):
    def test_init_through_handler(self):
        """`crypto init` handler with the private kwarg (no tty needed)."""
        info = crypto.cmd_crypto_init(
            SimpleNamespace(force=False), _passphrase=PW, _confirm=PW)
        self.assertTrue(self._keystore_path().is_file())
        self.assertTrue(info.get("has_verifier"))
        # The keystore must not contain anything resembling the passphrase.
        blob = self._keystore_path().read_bytes()
        self.assertNotIn(PW.encode(), blob)

    def test_init_twice_fails_cleanly(self):
        self._init_keystore()
        with self.assertRaises(crypto.CryptoError):
            crypto.cmd_crypto_init(
                SimpleNamespace(force=False), _passphrase=PW, _confirm=PW)

    def test_init_rejects_weak_passphrase_without_force(self):
        with self.assertRaises(crypto.CryptoError):
            crypto.cmd_crypto_init(
                SimpleNamespace(force=False), _passphrase="abc", _confirm="abc")


class TestLockUnlockCLI(CryptoCLIBase):
    def test_unlock_and_lock_via_main(self):
        self._init_keystore()
        with mock.patch.object(lock.getpass, "getpass", return_value=PW):
            code, out, _ = _run(["unlock"])
        self.assertEqual(code, 0)
        self.assertIn("Unlocked", out)
        self.assertFalse(lock.is_locked())
        self.assertTrue(self._session_path().is_file())

        code, out, _ = _run(["lock"])
        self.assertEqual(code, 0)
        self.assertIn("locked", out.lower())
        self.assertTrue(lock.is_locked())
        self.assertFalse(self._session_path().exists())

    def test_unlock_wrong_passphrase_is_friendly_error(self):
        self._init_keystore()
        with mock.patch.object(lock.getpass, "getpass", return_value="wrong-pw"):
            code, _, err = _run(["unlock"])
        self.assertEqual(code, 1)
        self.assertIn("incorrect passphrase", err)
        self.assertIn("python -m candid crypto --help", err)  # CryptoError next-step

    def test_lock_timeout_config_default(self):
        self.assertEqual(int(C.CONFIG_DEFAULTS["lock_timeout_minutes"]), 30)


class TestLockedGuard(CryptoCLIBase):
    def test_locked_blocks_data_command(self):
        self._init_keystore()
        self.assertTrue(lock.is_locked())
        code, _, err = _run(["track", "list"])
        self.assertEqual(code, 1)
        self.assertIn("locked", err.lower())
        self.assertIn("python -m candid unlock", err)  # LockError next-step

    def test_crypto_and_lock_commands_still_reachable_while_locked(self):
        self._init_keystore()
        code, out, _ = _run(["crypto", "status"])
        self.assertEqual(code, 0)
        self.assertIn("keystore", out.lower())
        code, out, _ = _run(["lock"])  # locking twice is fine
        self.assertEqual(code, 0)

    def test_no_keystore_is_noop(self):
        """Without a keystore the guard must not block anything (existing UX)."""
        self.assertFalse(crypto.keystore_exists())
        code, out, _ = _run(["track", "list"])
        self.assertEqual(code, 0)
        self.assertIn("application(s) tracked", out)

    def test_unlocked_allows_data_command(self):
        self._init_keystore()
        self._unlock_session()
        code, out, _ = _run(["track", "list"])
        self.assertEqual(code, 0)


class TestMigrateRoundTrip(CryptoCLIBase):
    def test_migrate_encrypt_decrypt_via_main(self):
        # Plaintext data first (no keystore yet -> plain write).
        rec = tracker.add("Acme", "Data Scientist", status="applied")
        self.assertFalse(atrest.is_encrypted(C.TRACKER_PATH))

        self._init_keystore()
        self._unlock_session()

        code, out, _ = _run(["crypto", "migrate"])
        self.assertEqual(code, 0)
        self.assertTrue(atrest.is_encrypted(C.TRACKER_PATH))

        # Data command reads through the encryption while unlocked.
        code, out, _ = _run(["track", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Acme", out)

        code, out, _ = _run(["crypto", "migrate", "--decrypt"])
        self.assertEqual(code, 0)
        self.assertFalse(atrest.is_encrypted(C.TRACKER_PATH))
        apps = tracker.list_apps()
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["company"], "Acme")
        self.assertEqual(apps[0]["id"], rec["id"])


class TestStatusJson(CryptoCLIBase):
    def test_status_json_shape(self):
        self._init_keystore()
        self._unlock_session()
        code, out, _ = _run(["crypto", "status", "--json"])
        self.assertEqual(code, 0)
        status = json.loads(out)
        self.assertEqual(
            set(status),
            {"keystore", "locked", "session", "crypto_available", "files", "backups"})
        self.assertTrue(status["crypto_available"])
        self.assertFalse(status["locked"])
        self.assertIsNotNone(status["keystore"])
        self.assertEqual(status["backups"], 0)
        self.assertIn(str(C.TRACKER_PATH), status["files"])


class TestBackupRestoreCLI(CryptoCLIBase):
    def test_backup_and_restore_via_main(self):
        self._init_keystore()
        self._unlock_session()
        tracker.add("Acme", "Data Scientist", status="applied")

        code, out, _ = _run(["crypto", "backup", "e2ebak"])
        self.assertEqual(code, 0)
        bak = Path(encbackup.BACKUP_DIR) / "e2ebak.candidbak"
        self.assertTrue(bak.is_file())
        self.assertNotIn(b"Acme", bak.read_bytes())  # encrypted, not plaintext

        tracker.add("Beta", "ML Engineer", status="saved")
        self.assertEqual(len(tracker.list_apps()), 2)

        code, out, _ = _run(["crypto", "restore", "e2ebak", "--force"])
        self.assertEqual(code, 0)
        apps = tracker.list_apps()
        companies = {a["company"] for a in apps}
        self.assertIn("Acme", companies)
        self.assertNotIn("Beta", companies)

    def test_backup_requires_unlocked_session(self):
        self._init_keystore()  # locked: no session
        code, _, err = _run(["crypto", "backup", "nope"])
        self.assertEqual(code, 1)
        # The main() lock guard fires before the handler: LockError next-step.
        self.assertIn("locked", err.lower())
        self.assertIn("python -m candid unlock", err)


if __name__ == "__main__":
    unittest.main()
