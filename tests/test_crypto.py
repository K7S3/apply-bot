"""Tests for candid.crypto (passphrase encryption at rest).
Run: CANDID_DATA_DIR=/tmp/x CANDID_CONFIG_DIR=/tmp/xc python3 -m unittest tests.test_crypto -v
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("CANDID_DATA_DIR", tempfile.mkdtemp(prefix="candid-test-data-"))
os.environ.setdefault("CANDID_CONFIG_DIR", tempfile.mkdtemp(prefix="candid-test-config-"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import crypto as C  # noqa: E402


FAST_ITER = 2_000  # fast KDF for tests; real default is 600_000
GOOD = "Tr0ub4dor&3-horse-battery!"  # strong
WEAK = "abc"  # score 0


def _clear_keystore():
    p = Path(os.environ["CANDID_CONFIG_DIR"]) / "keystore.json"
    if p.exists():
        p.unlink()


# The missing-package path is tested in a fresh subprocess where the
# `cryptography` import is blocked before candid.crypto is ever imported.
# (Purging sys.modules in-process and re-importing creates duplicate Rust
# extension state inside `cryptography`, which breaks its own isinstance
# checks — a faithful simulation needs a clean interpreter.)
_MISSING_PKG_SCRIPT = r"""
import os, sys, tempfile, importlib.abc
os.environ["CANDID_DATA_DIR"] = tempfile.mkdtemp(prefix="candid-nocrypto-data-")
os.environ["CANDID_CONFIG_DIR"] = tempfile.mkdtemp(prefix="candid-nocrypto-config-")
sys.path.insert(0, CANDID_ROOT_PLACEHOLDER)

class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "cryptography" or name.startswith("cryptography."):
            raise ImportError("blocked for test: " + name)
        return None

sys.meta_path.insert(0, _Block())

from candid import crypto as C

assert C.crypto_available() is False, "crypto_available should be False"

def expect_unavailable(fn, *a, **k):
    try:
        fn(*a, **k)
    except C.CryptoUnavailableError as e:
        assert "pip install cryptography" in str(e), str(e)
        return
    except Exception as e:
        raise AssertionError("expected CryptoUnavailableError, got %r" % e)
    raise AssertionError("expected CryptoUnavailableError from %r" % (fn,))

expect_unavailable(C.encrypt_bytes, b"x", "pw")
expect_unavailable(C.decrypt_bytes, C.MAGIC + b"\x00" * 40, "pw")
expect_unavailable(C.derive_key, "pw", b"s" * 16, 2000)
expect_unavailable(C.init_keystore, "Some-Good-Passphrase-1!")

# non-crypto parts must keep working without the package
assert C.verify_passphrase("pw") is False  # no keystore, no crypto needed
assert C.get_key_info() == {"iterations": None, "created_at": None, "has_verifier": False}
score, fb = C.passphrase_strength("abc")
assert score < 2 and fb
assert C.is_encrypted_blob(b"nope") is False
print("GRACEFUL-OK")
"""


class AvailabilityTest(unittest.TestCase):
    def test_available_when_installed(self):
        self.assertTrue(C.crypto_available())

    def test_graceful_without_package(self):
        """Simulate a missing `cryptography` in a fresh interpreter."""
        proc = subprocess.run(
            [sys.executable, "-c",
             _MISSING_PKG_SCRIPT.replace("CANDID_ROOT_PLACEHOLDER", repr(str(ROOT)))],
            capture_output=True, text=True, env=dict(os.environ), timeout=120,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr[-3000:])
        self.assertIn("GRACEFUL-OK", proc.stdout)

    def test_unavailable_error_message(self):
        self.assertTrue(issubclass(C.CryptoUnavailableError, C.CryptoError))


class KdfTest(unittest.TestCase):
    def test_deterministic(self):
        salt = b"0123456789abcdef"
        self.assertEqual(
            C.derive_key("secret", salt, iterations=FAST_ITER),
            C.derive_key("secret", salt, iterations=FAST_ITER),
        )

    def test_key_length(self):
        self.assertEqual(len(C.derive_key("secret", b"s" * 16, iterations=FAST_ITER)), 32)

    def test_unique_salts_unique_keys(self):
        k1 = C.derive_key("secret", b"a" * 16, iterations=FAST_ITER)
        k2 = C.derive_key("secret", b"b" * 16, iterations=FAST_ITER)
        self.assertNotEqual(k1, k2)

    def test_different_passphrases_different_keys(self):
        salt = b"s" * 16
        self.assertNotEqual(
            C.derive_key("one", salt, iterations=FAST_ITER),
            C.derive_key("two", salt, iterations=FAST_ITER),
        )


class EncryptTest(unittest.TestCase):
    def test_round_trip(self):
        pt = b"hello candid, this is secret data \x00\xff"
        blob = C.encrypt_bytes(pt, GOOD)
        self.assertEqual(C.decrypt_bytes(blob, GOOD), pt)

    def test_round_trip_empty_plaintext(self):
        blob = C.encrypt_bytes(b"", GOOD)
        self.assertEqual(C.decrypt_bytes(blob, GOOD), b"")

    def test_envelope_format(self):
        blob = C.encrypt_bytes(b"data", GOOD)
        self.assertTrue(blob.startswith(C.MAGIC))
        header = len(C.MAGIC) + C.SALT_LEN + C.NONCE_LEN
        self.assertGreater(len(blob), header)

    def test_random_salt_and_nonce(self):
        b1 = C.encrypt_bytes(b"same", GOOD)
        b2 = C.encrypt_bytes(b"same", GOOD)
        self.assertNotEqual(b1, b2)  # different salt/nonce => different blob

    def test_wrong_passphrase_fails(self):
        blob = C.encrypt_bytes(b"secret", GOOD)
        with self.assertRaises(C.CryptoError) as cm:
            C.decrypt_bytes(blob, "Wrong-Passphrase-1!")
        self.assertEqual(str(cm.exception), "wrong passphrase or corrupt data")

    def test_tampered_blob_fails(self):
        blob = bytearray(C.encrypt_bytes(b"secret", GOOD))
        blob[-1] ^= 0x01  # flip a bit in ciphertext/tag
        with self.assertRaises(C.CryptoError) as cm:
            C.decrypt_bytes(bytes(blob), GOOD)
        self.assertEqual(str(cm.exception), "wrong passphrase or corrupt data")

    def test_tampered_header_fails(self):
        blob = bytearray(C.encrypt_bytes(b"secret", GOOD))
        blob[len(C.MAGIC)] ^= 0x01  # flip a bit in the salt
        with self.assertRaises(C.CryptoError):
            C.decrypt_bytes(bytes(blob), GOOD)

    def test_bad_magic_rejected(self):
        with self.assertRaises(C.CryptoError):
            C.decrypt_bytes(b"NOTMAGIC" + b"\x00" * 40, GOOD)

    def test_truncated_blob_rejected(self):
        blob = C.encrypt_bytes(b"secret", GOOD)
        with self.assertRaises(C.CryptoError):
            C.decrypt_bytes(blob[:10], GOOD)

    def test_empty_passphrase_rejected(self):
        with self.assertRaises(C.CryptoError):
            C.encrypt_bytes(b"x", "")
        with self.assertRaises(C.CryptoError):
            C.decrypt_bytes(C.encrypt_bytes(b"x", GOOD), "")


class MagicTest(unittest.TestCase):
    def test_detects_envelope(self):
        self.assertTrue(C.is_encrypted_blob(C.MAGIC + b"\x00" * 30))

    def test_rejects_other_data(self):
        self.assertFalse(C.is_encrypted_blob(b"plain text"))
        self.assertFalse(C.is_encrypted_blob(b""))
        self.assertFalse(C.is_encrypted_blob(b"CANDID"))  # too short / wrong magic
        self.assertFalse(C.is_encrypted_blob(None))

    def test_real_blob_detected(self):
        self.assertTrue(C.is_encrypted_blob(C.encrypt_bytes(b"x", GOOD)))


class StrengthTest(unittest.TestCase):
    def test_empty_is_zero(self):
        score, feedback = C.passphrase_strength("")
        self.assertEqual(score, 0)
        self.assertTrue(feedback)

    def test_weak_short(self):
        score, _ = C.passphrase_strength(WEAK)
        self.assertLess(score, 2)

    def test_common_password_weak(self):
        score, feedback = C.passphrase_strength("password123")
        self.assertLess(score, 3)
        self.assertTrue(any("common" in f for f in feedback))

    def test_strong_passphrase(self):
        score, feedback = C.passphrase_strength(GOOD)
        self.assertGreaterEqual(score, 3)
        self.assertIn("looks good", feedback)

    def test_score_bounds(self):
        for pw in ["", "a", "abcdefghijkl", GOOD, "x" * 100 + "A1!"]:
            score, feedback = C.passphrase_strength(pw)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 4)
            self.assertTrue(feedback)

    def test_length_matters(self):
        s1, _ = C.passphrase_strength("Ab1!xxxx")
        s2, _ = C.passphrase_strength("Ab1!xxxxYYYYZZZZ")
        self.assertGreater(s2, s1)


class KeystoreTest(unittest.TestCase):
    def setUp(self):
        _clear_keystore()

    def tearDown(self):
        _clear_keystore()

    def test_init_and_verify(self):
        C.init_keystore(GOOD, iterations=FAST_ITER)
        self.assertTrue(C.keystore_exists())
        self.assertTrue(C.verify_passphrase(GOOD))
        self.assertFalse(C.verify_passphrase("nope-wrong-1!"))

    def test_verify_without_keystore(self):
        self.assertFalse(C.keystore_exists())
        self.assertFalse(C.verify_passphrase(GOOD))

    def test_init_refuses_second_without_force(self):
        C.init_keystore(GOOD, iterations=FAST_ITER)
        with self.assertRaises(C.CryptoError):
            C.init_keystore("Another-Good-1!", iterations=FAST_ITER)

    def test_init_refuses_weak_without_force(self):
        with self.assertRaises(C.CryptoError) as cm:
            C.init_keystore(WEAK, iterations=FAST_ITER)
        self.assertIn("too weak", str(cm.exception))

    def test_init_weak_with_force(self):
        C.init_keystore(WEAK, iterations=FAST_ITER, force=True)
        self.assertTrue(C.verify_passphrase(WEAK))

    def test_change_passphrase(self):
        C.init_keystore(GOOD, iterations=FAST_ITER)
        C.change_passphrase(GOOD, "N3w-Str0ng-Phrase!!", force=False)
        self.assertTrue(C.verify_passphrase("N3w-Str0ng-Phrase!!"))
        self.assertFalse(C.verify_passphrase(GOOD))

    def test_change_wrong_old_fails_and_keeps_old(self):
        C.init_keystore(GOOD, iterations=FAST_ITER)
        with self.assertRaises(C.CryptoError):
            C.change_passphrase("wrong-old-1!", "N3w-Str0ng-Phrase!!")
        self.assertTrue(C.verify_passphrase(GOOD))  # old still works

    def test_change_refuses_weak_new(self):
        C.init_keystore(GOOD, iterations=FAST_ITER)
        with self.assertRaises(C.CryptoError):
            C.change_passphrase(GOOD, WEAK)

    def test_no_secrets_in_keystore_file(self):
        C.init_keystore(GOOD, iterations=FAST_ITER)
        raw = (Path(os.environ["CANDID_CONFIG_DIR"]) / "keystore.json").read_text()
        self.assertNotIn(GOOD, raw)
        data = json.loads(raw)
        verifier = base64.b64decode(data["verifier"])
        # verifier is a derived value, not a usable data key
        self.assertNotEqual(verifier, C.derive_key(GOOD, base64.b64decode(data["salt"]),
                                                  iterations=FAST_ITER))

    def test_get_key_info(self):
        self.assertEqual(C.get_key_info(),
                         {"iterations": None, "created_at": None, "has_verifier": False})
        C.init_keystore(GOOD, iterations=FAST_ITER)
        info = C.get_key_info()
        self.assertEqual(info["iterations"], FAST_ITER)
        self.assertTrue(info["created_at"])
        self.assertTrue(info["has_verifier"])
        self.assertNotIn("salt", info)
        self.assertNotIn("verifier", info)

    def test_keystore_file_permissions(self):
        C.init_keystore(GOOD, iterations=FAST_ITER)
        p = Path(os.environ["CANDID_CONFIG_DIR"]) / "keystore.json"
        mode = p.stat().st_mode & 0o777
        self.assertLessEqual(mode, 0o600)


class CliTest(unittest.TestCase):
    def setUp(self):
        _clear_keystore()

    def tearDown(self):
        _clear_keystore()

    def test_register_crypto_commands(self):
        import argparse
        parser = argparse.ArgumentParser(prog="candid")
        subs = parser.add_subparsers(dest="crypto_cmd")
        C.register_crypto_commands(subs)
        for name in ("init", "change", "verify"):
            ns = parser.parse_args([name])
            self.assertTrue(callable(ns.func))
        ns = parser.parse_args(["init", "--force"])
        self.assertTrue(ns.force)

    def test_cmd_init_verify_change_flow(self):
        args = SimpleNamespace(force=False)
        C.cmd_crypto_init(args, _passphrase=GOOD, _confirm=GOOD)
        self.assertTrue(C.keystore_exists())
        self.assertTrue(C.cmd_crypto_verify(args, _passphrase=GOOD))
        self.assertFalse(C.cmd_crypto_verify(args, _passphrase="wrong-1!"))
        C.cmd_crypto_change(args, _old=GOOD, _new="N3w-Str0ng-Phrase!!",
                            _confirm="N3w-Str0ng-Phrase!!")
        self.assertTrue(C.verify_passphrase("N3w-Str0ng-Phrase!!"))

    def test_cmd_init_weak_refused(self):
        args = SimpleNamespace(force=False)
        with self.assertRaises(C.CryptoError):
            C.cmd_crypto_init(args, _passphrase=WEAK, _confirm=WEAK)
        self.assertFalse(C.keystore_exists())

    def test_cmd_init_weak_force(self):
        args = SimpleNamespace(force=True)
        C.cmd_crypto_init(args, _passphrase=WEAK, _confirm=WEAK)
        self.assertTrue(C.verify_passphrase(WEAK))

    def test_cmd_init_mismatch(self):
        args = SimpleNamespace(force=False)
        with self.assertRaises(C.CryptoError):
            C.cmd_crypto_init(args, _passphrase=GOOD, _confirm="different-1!")

    def test_cmd_change_wrong_old(self):
        args = SimpleNamespace(force=False)
        C.cmd_crypto_init(args, _passphrase=GOOD, _confirm=GOOD)
        with self.assertRaises(C.CryptoError):
            C.cmd_crypto_change(args, _old="wrong-1!", _new="N3w-Str0ng-Phrase!!",
                                _confirm="N3w-Str0ng-Phrase!!")


if __name__ == "__main__":
    unittest.main()
