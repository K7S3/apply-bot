"""Tests for candid.atrest (transparent encryption at rest).
Run: CANDID_DATA_DIR=/tmp/x CANDID_CONFIG_DIR=/tmp/xc python3 -m unittest tests.test_atrest -v
"""
import argparse
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("CANDID_DATA_DIR", tempfile.mkdtemp(prefix="candid-test-data-"))
os.environ.setdefault("CANDID_CONFIG_DIR", tempfile.mkdtemp(prefix="candid-test-config-"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import candid as _candid_pkg  # noqa: E402
from candid import atrest as A  # noqa: E402
from candid import config as C  # noqa: E402
from candid import crypto  # noqa: E402
from candid import profile as _profile  # noqa: E402,F401
from candid import tracker as _tracker  # noqa: E402,F401

# Force-import `cryptography` NOW, before any test touches sys.modules.
# Rationale: re-importing it mid-process (e.g. after a sys.modules purge)
# creates duplicate Rust extension state inside `cryptography`, which breaks
# its own isinstance checks ("Expected instance of hashes.HashAlgorithm").
crypto.crypto_available()

SAMPLES = ROOT / "samples" / "candid"

GOOD = "Tr0ub4dor&3-horse-battery!"  # strong passphrase
FAST_ITER = 2_000  # fast KDF for tests; real default is 600_000

_MISSING = object()


def make_lock_stub():
    """A contract-conformant stub of candid.lock for tests.

    Implements exactly the documented contract: LockError,
    require_unlocked(), get_session_passphrase(), is_locked(), lock_now(),
    unlock_session(). State starts locked.
    """
    mod = types.ModuleType("candid.lock")

    class LockError(Exception):
        """Raised when the session is locked."""

    state = {"passphrase": None}

    def require_unlocked():
        if state["passphrase"] is None:
            raise LockError("session is locked")

    def get_session_passphrase():
        return state["passphrase"]

    def is_locked():
        return state["passphrase"] is None

    def lock_now():
        state["passphrase"] = None

    def unlock_session(passphrase, timeout_minutes=None):
        if not passphrase:
            raise LockError("passphrase must not be empty")
        state["passphrase"] = passphrase
        return True

    mod.LockError = LockError
    mod.require_unlocked = require_unlocked
    mod.get_session_passphrase = get_session_passphrase
    mod.is_locked = is_locked
    mod.lock_now = lock_now
    mod.unlock_session = unlock_session
    return mod


class AtrestTest(unittest.TestCase):
    def setUp(self):
        # Fresh, isolated DATA_DIR / CONFIG_DIR per test via config patching.
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.data = base / "data"
        self.conf = base / "conf"
        self.data.mkdir()
        self.conf.mkdir()
        paths = {
            "DATA_DIR": self.data,
            "CONFIG_DIR": self.conf,
            "PROFILE_PATH": self.data / "profile.json",
            "TRACKER_PATH": self.data / "tracker.json",
            "OFFERS_PATH": self.data / "offers.json",
            "GMAIL_PROPOSALS_PATH": self.data / "gmail_proposals.json",
            "PREP_PACKS_DIR": self.data / "prep_packs",
            "TAILOR_DIR": self.data / "tailored",
        }
        self._cfg = [mock.patch.object(C, k, v) for k, v in paths.items()]
        for p in self._cfg:
            p.start()
        # Stub candid.lock (the real module is built by another worker).
        # Surgical sys.modules injection: a plain assignment + targeted
        # restore. (mock.patch.dict(sys.modules, ...) is NOT safe here:
        # its __exit__ does sys.modules.clear(), which drops modules
        # imported mid-test and forces re-imports — for `cryptography`
        # that creates duplicate Rust extension state and breaks its
        # isinstance checks.)
        self.lock = make_lock_stub()
        self._saved_mod = sys.modules.get("candid.lock", _MISSING)
        self._saved_attr = getattr(_candid_pkg, "lock", _MISSING)
        sys.modules["candid.lock"] = self.lock
        _candid_pkg.lock = self.lock

    def tearDown(self):
        if self._saved_attr is _MISSING:
            try:
                del _candid_pkg.lock
            except AttributeError:
                pass
        else:
            _candid_pkg.lock = self._saved_attr
        if self._saved_mod is _MISSING:
            sys.modules.pop("candid.lock", None)
        else:
            sys.modules["candid.lock"] = self._saved_mod
        for p in self._cfg:
            p.stop()
        self.tmp.cleanup()

    # -- helpers ---------------------------------------------------------

    def init_keystore(self):
        crypto.init_keystore(GOOD, iterations=FAST_ITER)

    def unlock(self):
        self.lock.unlock_session(GOOD)

    # -- write/read_protected --------------------------------------------

    def test_roundtrip_with_keystore(self):
        self.init_keystore()
        self.unlock()
        p = self.data / "secret.bin"
        A.write_protected(p, b"hello world")
        self.assertTrue(A.is_encrypted(p))
        self.assertTrue(crypto.is_encrypted_blob(p.read_bytes()))
        # owner-only permissions
        self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
        self.assertEqual(A.read_protected(p), b"hello world")
        # explicit passphrase also works
        self.assertEqual(A.read_protected(p, passphrase=GOOD), b"hello world")

    def test_no_keystore_plain_passthrough(self):
        p = self.data / "plain.bin"
        data = b'{"a": 1}'
        A.write_protected(p, data)
        self.assertFalse(A.is_encrypted(p))
        self.assertEqual(p.read_bytes(), data)  # byte-identical plain write
        self.assertEqual(A.read_protected(p), data)

    def test_read_missing_raises_filenotfound(self):
        with self.assertRaises(FileNotFoundError):
            A.read_protected(self.data / "nope.bin")

    def test_locked_session_raises_lockerror(self):
        self.init_keystore()
        self.unlock()
        p = self.data / "secret.bin"
        A.write_protected(p, b"data")
        self.lock.lock_now()
        with self.assertRaises(self.lock.LockError):
            A.write_protected(self.data / "other.bin", b"data")
        with self.assertRaises(self.lock.LockError):
            A.read_protected(p)

    def test_tampered_blob_detected(self):
        self.init_keystore()
        self.unlock()
        p = self.data / "secret.bin"
        A.write_protected(p, b"important")
        raw = bytearray(p.read_bytes())
        raw[len(raw) // 2] ^= 0xFF  # flip a byte in the ciphertext
        p.write_bytes(bytes(raw))
        with self.assertRaises(crypto.CryptoError):
            A.read_protected(p)

    def test_wrong_explicit_passphrase_detected(self):
        self.init_keystore()
        self.unlock()
        p = self.data / "secret.bin"
        A.write_protected(p, b"important")
        with self.assertRaises(crypto.CryptoError):
            A.read_protected(p, passphrase="Wrong-Passphrase-1234!")

    # -- is_encrypted / sensitive_files ----------------------------------

    def test_is_encrypted_missing_is_false(self):
        self.assertFalse(A.is_encrypted(self.data / "missing.json"))

    def test_sensitive_files(self):
        (self.data / "profile.json").write_text("{}")
        (self.data / "tracker.json").write_text("[]")
        (self.data / "offers.json").write_text("[]")
        (self.data / "gmail_proposals.json").write_text("[]")
        (self.data / "not_sensitive.txt").write_text("x")
        pp = self.data / "prep_packs"
        pp.mkdir()
        (pp / "pack_a.md").write_text("pack")
        td = self.data / "tailored"
        td.mkdir()
        (td / "resume_v1.md").write_text("resume")
        found = {f.name for f in A.sensitive_files()}
        self.assertEqual(
            found,
            {"profile.json", "tracker.json", "offers.json",
             "gmail_proposals.json", "pack_a.md", "resume_v1.md"},
        )

    def test_sensitive_files_empty_dirs(self):
        self.assertEqual(A.sensitive_files(), [])

    # -- secure_wipe ------------------------------------------------------

    def test_secure_wipe_removes_file(self):
        p = self.data / "wipe.me"
        p.write_bytes(b"sensitive" * 1000)
        A.secure_wipe(p)
        self.assertFalse(p.exists())

    def test_secure_wipe_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            A.secure_wipe(self.data / "missing")

    # -- migrate ----------------------------------------------------------

    def _make_plaintext_sensitive(self):
        originals = {
            self.data / "profile.json": b'{"name": "Alex Rivera"}',
            self.data / "tracker.json": b'[{"id": 1}]',
            self.data / "offers.json": b'[]',
            self.data / "gmail_proposals.json": b'{}',
        }
        pp = self.data / "prep_packs"
        pp.mkdir()
        originals[pp / "pack.md"] = b"# prep pack"
        td = self.data / "tailored"
        td.mkdir()
        originals[td / "resume.md"] = b"# tailored resume"
        for path, data in originals.items():
            path.write_bytes(data)
        return originals

    def test_migrate_encrypts_then_decrypts_identically(self):
        self.init_keystore()
        self.unlock()
        originals = self._make_plaintext_sensitive()

        report = A.migrate_atrest()
        self.assertEqual(len(report), len(originals))
        self.assertTrue(all(s == "encrypted" for _, s in report))
        for path in originals:
            self.assertTrue(A.is_encrypted(path), path)
        # plaintext bytes are gone from disk
        for path, data in originals.items():
            self.assertNotIn(data, path.read_bytes())

        # second run: everything already encrypted -> skipped
        report2 = A.migrate_atrest()
        self.assertTrue(all(s == "skipped (already encrypted)" for _, s in report2))

        # decrypt back
        report3 = A.migrate_atrest(decrypt=True)
        self.assertTrue(all(s == "decrypted" for _, s in report3))
        for path, data in originals.items():
            self.assertFalse(A.is_encrypted(path), path)
            self.assertEqual(path.read_bytes(), data)

        # decrypt again: plaintext files skipped
        report4 = A.migrate_atrest(decrypt=True)
        self.assertTrue(all(s == "skipped (plaintext)" for _, s in report4))

    def test_migrate_requires_unlocked_session(self):
        self.init_keystore()
        self._make_plaintext_sensitive()
        # session starts locked
        with self.assertRaises(self.lock.LockError):
            A.migrate_atrest()

    def test_migrate_refuses_without_keystore(self):
        with self.assertRaises(crypto.CryptoError) as ctx:
            A.migrate_atrest()
        self.assertIn("candid crypto init", str(ctx.exception))

    def test_cmd_migrate_refuses_without_keystore(self):
        with self.assertRaises(crypto.CryptoError) as ctx:
            A.cmd_crypto_migrate(SimpleNamespace(decrypt=False))
        self.assertIn("candid crypto init", str(ctx.exception))

    # -- integration: profile + tracker ------------------------------------

    def test_profile_transparent_with_keystore(self):
        from candid import profile as P

        self.init_keystore()
        self.unlock()
        prof = P.onboard(resume_path=SAMPLES / "sample_resume.md")
        self.assertTrue(A.is_encrypted(C.PROFILE_PATH))
        loaded = P.load_profile()
        self.assertEqual(loaded, prof)
        # locked session blocks transparent reads
        self.lock.lock_now()
        with self.assertRaises(self.lock.LockError):
            P.load_profile()

    def test_tracker_transparent_with_keystore(self):
        from candid import tracker as T

        self.init_keystore()
        self.unlock()
        T.add("Acme", "Data Scientist")
        T.add("Globex", "ML Engineer", status="applied")
        self.assertTrue(A.is_encrypted(C.TRACKER_PATH))
        apps = T.list_apps()
        self.assertEqual(len(apps), 2)
        self.assertEqual(apps[0]["company"], "Acme")

    def test_profile_tracker_plain_without_keystore(self):
        from candid import profile as P
        from candid import tracker as T

        prof = P.onboard(resume_path=SAMPLES / "sample_resume.md")
        raw = C.PROFILE_PATH.read_bytes()
        self.assertEqual(raw, json.dumps(prof, indent=2).encode("utf-8"))
        self.assertFalse(A.is_encrypted(C.PROFILE_PATH))
        self.assertEqual(P.load_profile(), prof)

        T.add("Acme", "Data Scientist")
        apps = T.list_apps()
        self.assertEqual(len(apps), 1)
        self.assertFalse(A.is_encrypted(C.TRACKER_PATH))

    # -- CLI registration ---------------------------------------------------

    def test_register_atrest_commands(self):
        parser = argparse.ArgumentParser(prog="candid crypto")
        sub = parser.add_subparsers(dest="cmd", required=True)
        A.register_atrest_commands(sub)
        args = parser.parse_args(["migrate"])
        self.assertIs(args.func, A.cmd_crypto_migrate)
        self.assertFalse(args.decrypt)
        args = parser.parse_args(["migrate", "--decrypt"])
        self.assertTrue(args.decrypt)

    def test_cmd_migrate_end_to_end(self):
        self.init_keystore()
        self.unlock()
        originals = self._make_plaintext_sensitive()
        parser = argparse.ArgumentParser(prog="candid crypto")
        sub = parser.add_subparsers(dest="cmd", required=True)
        A.register_atrest_commands(sub)
        args = parser.parse_args(["migrate"])
        report = args.func(args)
        self.assertEqual(len(report), len(originals))
        for path in originals:
            self.assertTrue(A.is_encrypted(path))


if __name__ == "__main__":
    unittest.main()
