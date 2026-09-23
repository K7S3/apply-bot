"""Tests for candid.encbackup (encrypted backups, crypto status, audit log).
Run: CANDID_DATA_DIR=/tmp/x CANDID_CONFIG_DIR=/tmp/xc python3 -m unittest tests.test_encbackup -v
"""
import argparse
import io
import json
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", tempfile.mkdtemp(prefix="candid-test-data-"))
os.environ.setdefault("CANDID_CONFIG_DIR", tempfile.mkdtemp(prefix="candid-test-config-"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as cfg  # noqa: E402
from candid import crypto as C  # noqa: E402
from candid import encbackup as EB  # noqa: E402
from candid import lock as L  # noqa: E402

FAST_ITER = 2_000  # fast KDF for tests; real default is 600_000
GOOD = "Tr0ub4dor&3-horse-battery!zzz"  # strong passphrase


def _unlock(pw):
    L.unlock_session(pw)


def _relock():
    L.lock_now()


class EncBackupTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="encbackup-test-")
        self.data_dir = Path(self.tmp.name) / "data"
        self.config_dir = Path(self.tmp.name) / "conf"
        os.environ["CANDID_DATA_DIR"] = str(self.data_dir)
        os.environ["CANDID_CONFIG_DIR"] = str(self.config_dir)
        cfg.DATA_DIR = self.data_dir
        cfg.CONFIG_DIR = self.config_dir
        C.init_keystore(GOOD, iterations=FAST_ITER)
        _unlock(GOOD)

    def tearDown(self):
        _relock()
        self.tmp.cleanup()

    # -- helpers ---------------------------------------------------------

    def _seed_data(self, files=None):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        files = files or {
            "profile.json": '{"name": "Keshavan"}',
            "tracker.json": '{"apps": []}',
            "nested/deep.txt": "deep content",
        }
        for rel, content in files.items():
            p = self.data_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return files

    def _snapshot_files(self):
        out = {}
        for p in sorted(self.data_dir.rglob("*")):
            if p.is_file():
                out[p.relative_to(self.data_dir).as_posix()] = p.read_bytes()
        return out

    # -- round trip -------------------------------------------------------

    def test_backup_restore_roundtrip_restores_identical_files(self):
        original = self._seed_data()
        out = EB.create_encrypted_backup("nightly1")
        self.assertTrue(out.name.endswith(".candidbak"))
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)

        # Wipe and add junk, then restore: must come back identical.
        for p in self.data_dir.rglob("*"):
            if p.is_file():
                p.unlink()
        (self.data_dir / "junk.txt").write_text("junk")
        EB.restore_encrypted_backup("nightly1", force=True)
        restored = self._snapshot_files()
        self.assertNotIn("junk.txt", restored)
        self.assertEqual(
            {k: v.decode("utf-8") for k, v in restored.items()}, original
        )

    def test_backup_manifest_has_expected_fields_and_no_secrets(self):
        self._seed_data()
        EB.create_encrypted_backup("m1")
        man = json.loads(
            (EB.BACKUP_DIR / "m1.candidbak.json").read_text(encoding="utf-8")
        )
        self.assertEqual(man["name"], "m1")
        self.assertIn("created_at", man)
        self.assertEqual(man["n_files"], 3)
        self.assertGreater(man["total_bytes"], 0)
        self.assertIn("iterations", man["key_info"])
        blob = json.dumps(man)
        for secret in ("salt", "verifier", "passphrase", GOOD):
            self.assertNotIn(secret, blob)

    def test_backup_of_missing_data_dir_warns_but_succeeds(self):
        # DATA_DIR does not exist: allowed, empty backup.
        out = EB.create_encrypted_backup("empty1")
        self.assertTrue(out.exists())
        man = json.loads(
            (EB.BACKUP_DIR / "empty1.candidbak.json").read_text(encoding="utf-8")
        )
        self.assertEqual(man["n_files"], 0)

    def test_BACKUP_DIR_respects_config_override(self):
        self.assertEqual(EB.BACKUP_DIR, self.config_dir / "backups")

    # -- restore guards ---------------------------------------------------

    def test_restore_snapshots_pre_restore_state(self):
        self._seed_data({"a.txt": "version-one"})
        EB.create_encrypted_backup("v1")
        # Change data, then restore: the pre-change state must be snapshotted.
        (self.data_dir / "a.txt").write_text("version-two")
        EB.restore_encrypted_backup("v1", force=True)
        snaps = [
            b for b in EB.list_backups() if b["name"].startswith("pre-restore-")
        ]
        self.assertEqual(len(snaps), 1)
        snap = Path(snaps[0]["path"])
        self.assertEqual(stat.S_IMODE(snap.stat().st_mode), 0o600)
        payload = C.decrypt_bytes(snap.read_bytes(), GOOD)
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            self.assertEqual(zf.read("a.txt"), b"version-two")

    def test_restore_refuses_newer_data_without_force(self):
        self._seed_data({"a.txt": "old"})
        EB.create_encrypted_backup("v1")
        # Make a current file newer than the backup manifest.
        future = datetime.now(timezone.utc).timestamp() + 3600
        p = self.data_dir / "a.txt"
        p.write_text("newer")
        os.utime(p, (future, future))
        with self.assertRaisesRegex(C.CryptoError, "--force"):
            EB.restore_encrypted_backup("v1")
        # force=True proceeds.
        EB.restore_encrypted_backup("v1", force=True)
        self.assertEqual((self.data_dir / "a.txt").read_text(), "old")

    def test_restore_unknown_backup_raises(self):
        with self.assertRaisesRegex(C.CryptoError, "no such backup"):
            EB.restore_encrypted_backup("does-not-exist")

    def test_tampered_backup_fails(self):
        self._seed_data()
        out = EB.create_encrypted_backup("v1")
        blob = bytearray(out.read_bytes())
        blob[-10] ^= 0xFF  # flip a byte in the ciphertext/tag region
        out.write_bytes(bytes(blob))
        with self.assertRaises(C.CryptoError):
            EB.restore_encrypted_backup("v1", force=True)

    def test_wrong_passphrase_fails(self):
        self._seed_data()
        EB.create_encrypted_backup("v1")
        # Explicit wrong passphrase (session stays unlocked with GOOD).
        with self.assertRaisesRegex(C.CryptoError, "wrong passphrase"):
            EB.restore_encrypted_backup("v1", passphrase="Wr0ng-passphrase-9!", force=True)

    def test_zip_slip_paths_are_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.txt", "pwned")
            zf.writestr("/abs/path.txt", "pwned")
        blob = C.encrypt_bytes(buf.getvalue(), GOOD)
        (EB.BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        evil = EB.BACKUP_DIR / "evil.candidbak"
        evil.write_bytes(blob)
        with self.assertRaisesRegex(C.CryptoError, "unsafe archive path"):
            EB.restore_encrypted_backup("evil", force=True)
        # Nothing escaped the data dir.
        self.assertFalse((self.data_dir / "evil.txt").exists())

    def test_requires_unlocked_session(self):
        self._seed_data()
        _relock()
        with self.assertRaises(L.LockError):
            EB.create_encrypted_backup("x1")
        with self.assertRaises(L.LockError):
            EB.restore_encrypted_backup("x1")

    def test_requires_keystore(self):
        (self.config_dir / "keystore.json").unlink()
        self._seed_data()
        with self.assertRaisesRegex(C.CryptoError, "keystore"):
            EB.create_encrypted_backup("x1")

    # -- listing ----------------------------------------------------------

    def test_list_backups_marks_orphan_manifest_missing(self):
        self._seed_data()
        EB.create_encrypted_backup("good1")
        orphan = EB.BACKUP_DIR / "orphan.candidbak"
        orphan.write_bytes(C.encrypt_bytes(b"{}", GOOD))
        backups = {b["name"]: b for b in EB.list_backups()}
        self.assertFalse(backups["good1"]["manifest_missing"])
        self.assertTrue(backups["orphan"]["manifest_missing"])
        self.assertIsNone(backups["orphan"]["created_at"])

    # -- status -----------------------------------------------------------

    def test_status_reflects_plaintext_missing_encrypted(self):
        st = EB.crypto_status()
        self.assertTrue(st["crypto_available"])
        self.assertIsNotNone(st["keystore"])
        self.assertIn("iterations", st["keystore"])
        self.assertFalse(st["locked"])
        self.assertEqual(st["session"]["locked"], False)
        self.assertEqual(st["backups"], 0)
        # Nothing seeded yet: all four sensitive files missing.
        for state in st["files"].values():
            self.assertEqual(state, "missing")

        self._seed_data()
        st = EB.crypto_status()
        prof = str(self.data_dir / "profile.json")
        trk = str(self.data_dir / "tracker.json")
        self.assertEqual(st["files"][prof], "plaintext")
        self.assertEqual(st["files"][trk], "plaintext")

        # Encrypt one of the sensitive files in place: status must say so.
        tracker = Path(trk)
        tracker.write_bytes(C.encrypt_bytes(tracker.read_bytes(), GOOD))
        st = EB.crypto_status()
        self.assertEqual(st["files"][trk], "encrypted")
        self.assertEqual(st["files"][prof], "plaintext")

        EB.create_encrypted_backup("s1")
        self.assertEqual(EB.crypto_status()["backups"], 1)

    def test_status_when_locked(self):
        _relock()
        st = EB.crypto_status()
        self.assertTrue(st["locked"])
        self.assertEqual(st["session"]["locked"], True)

    # -- audit ------------------------------------------------------------

    def test_audit_log_newest_first_and_limit(self):
        EB.audit_log("first", "d1")
        EB.audit_log("second", "d2")
        EB.audit_log("third", "d3")
        entries = EB.read_audit()
        self.assertEqual([e["event"] for e in entries], ["third", "second", "first"])
        self.assertEqual(entries[0]["detail"], "d3")
        for e in entries:
            self.assertIn("ts", e)
            datetime.fromisoformat(e["ts"])  # parses
        limited = EB.read_audit(limit=2)
        self.assertEqual([e["event"] for e in limited], ["third", "second"])
        log = self.config_dir / "audit.log"
        self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
        # JSON-lines: one object per line.
        for line in log.read_text(encoding="utf-8").splitlines():
            self.assertIn("event", json.loads(line))

    def test_backup_and_restore_write_audit_events(self):
        self._seed_data()
        EB.create_encrypted_backup("a1")
        EB.restore_encrypted_backup("a1", force=True)
        events = [e["event"] for e in EB.read_audit()]
        self.assertIn("backup_created", events)
        self.assertIn("pre_restore_snapshot", events)
        self.assertIn("backup_restored", events)

    # -- name sanitization ------------------------------------------------

    def test_name_sanitization_rejects(self):
        for bad in ("../../evil", "a b", "a/b", "", ".hidden", "x" * 65,
                    "semi;colon", "star*"):
            with self.assertRaises(C.CryptoError, msg=bad):
                EB.create_encrypted_backup(bad)
            with self.assertRaises(C.CryptoError, msg=bad):
                EB.restore_encrypted_backup(bad)
        EB.create_encrypted_backup("ok-name_123")
        self.assertTrue((EB.BACKUP_DIR / "ok-name_123.candidbak").exists())

    # -- CLI --------------------------------------------------------------

    def _crypto_parser(self):
        parser = argparse.ArgumentParser(prog="candid crypto")
        subs = parser.add_subparsers()
        EB.register_encbackup_commands(subs)
        return parser

    def test_cli_backup_and_restore(self):
        parser = self._crypto_parser()
        self._seed_data({"p.txt": "hello"})
        args = parser.parse_args(["backup", "cli1"])
        out = args.func(args)
        self.assertTrue(Path(out).exists())
        (self.data_dir / "p.txt").write_text("changed")
        args = parser.parse_args(["restore", "cli1", "--force"])
        dest = args.func(args)
        self.assertEqual((Path(dest) / "p.txt").read_text(), "hello")

    def test_cli_status_json_and_human(self):
        parser = self._crypto_parser()
        args = parser.parse_args(["status", "--json"])
        status = args.func(args)
        self.assertIn("keystore", status)
        args = parser.parse_args(["status"])
        self.assertIsNotNone(args.func(args))

    def test_cli_audit(self):
        parser = self._crypto_parser()
        EB.audit_log("cli-event", "x")
        args = parser.parse_args(["audit", "--limit", "5"])
        entries = args.func(args)
        self.assertEqual(entries[0]["event"], "cli-event")
        args = parser.parse_args(["audit", "--json"])
        self.assertIsInstance(args.func(args), list)

    def test_cli_requires_crypto_package(self):
        real = EB.crypto_available
        EB.crypto_available = lambda: False  # noqa: E731
        try:
            parser = self._crypto_parser()
            for argv in (["backup", "x"], ["restore", "x"], ["status"], ["audit"]):
                args = parser.parse_args(argv)
                with self.assertRaises(C.CryptoUnavailableError):
                    args.func(args)
        finally:
            EB.crypto_available = real

    def test_cli_documents_session_only_passphrase(self):
        parser = self._crypto_parser()
        # No passphrase option may exist on backup/restore (shell-history safety).
        for sub in ("backup", "restore"):
            args = parser.parse_args([sub, "n"] if sub == "backup" else [sub, "n"])
            for attr in vars(args):
                self.assertNotIn("passphrase", attr.lower())
        help_text = parser.format_help()
        self.assertIn("backup", help_text)


if __name__ == "__main__":
    unittest.main()
