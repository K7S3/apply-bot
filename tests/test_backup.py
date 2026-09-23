"""Tests for candid.backup (full JSON backup + restore).

Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_cli_ux.py).
"""
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import backup as B  # noqa: E402
from candid import config as C  # noqa: E402


class BackupBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-backup-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def seed_data(self):
        (self.tmp / "profile.json").write_text(json.dumps({"name": "Test User"}))
        (self.tmp / "tracker.json").write_text(
            json.dumps([{"id": 1, "company": "Acme", "status": "applied"}]))
        (self.tmp / "offers.json").write_text(json.dumps([]))
        (self.tmp / "gmail_proposals.json").write_text(json.dumps([]))
        (self.tmp / "salary.db").write_bytes(b"\x00fake-sqlite-bytes\x00")
        (self.tmp / "prep_packs").mkdir(exist_ok=True)
        (self.tmp / "prep_packs" / "1.md").write_text("# prep")
        (self.tmp / "tailored").mkdir(exist_ok=True)
        (self.tmp / "tailored" / "Acme.md").write_text("# resume")


class CreateBackupTests(BackupBase):
    def test_create_backup_zip_structure_and_manifest(self):
        self.seed_data()
        zip_path = B.create_backup("my-backup", data_dir=self.tmp)
        self.assertTrue(zip_path.is_file())
        self.assertEqual(zip_path.parent, self.tmp / "backups")
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            for expected in ("profile.json", "tracker.json", "offers.json",
                             "gmail_proposals.json", "salary.db",
                             "prep_packs/1.md", "tailored/Acme.md",
                             "manifest.json"):
                self.assertIn(expected, names)
            manifest = json.loads(zf.read("manifest.json"))
            self.assertIn("candid_version", manifest)
            self.assertIn("created", manifest)
            datetime.fromisoformat(manifest["created"])  # parses
            self.assertEqual(set(manifest["files"]), set(names) - {"manifest.json"})

    def test_create_backup_default_name(self):
        self.seed_data()
        zip_path = B.create_backup(data_dir=self.tmp)
        self.assertRegex(zip_path.stem, r"^candid-backup-\d{8}-\d{6}$")

    def test_create_backup_skips_missing_files(self):
        # No files seeded at all: still makes a valid zip with just a manifest.
        zip_path = B.create_backup("empty", data_dir=self.tmp)
        with zipfile.ZipFile(zip_path) as zf:
            self.assertEqual(zf.namelist(), ["manifest.json"])

    def test_create_backup_bad_name(self):
        with self.assertRaises(B.BackupError):
            B.create_backup("///", data_dir=self.tmp)


class ListBackupTests(BackupBase):
    def test_list_empty(self):
        self.assertEqual(B.list_backups(data_dir=self.tmp), [])

    def test_list_newest_first(self):
        self.seed_data()
        b1 = B.create_backup("first", data_dir=self.tmp)
        b2 = B.create_backup("second", data_dir=self.tmp)
        entries = B.list_backups(data_dir=self.tmp)
        self.assertEqual([e["name"] for e in entries], ["second", "first"])
        for e in entries:
            self.assertIn("path", e)
            self.assertIn("created", e)
            self.assertGreater(e["size_bytes"], 0)
        self.assertEqual(entries[0]["path"], str(b2))
        self.assertEqual(entries[1]["path"], str(b1))


class RestoreBackupTests(BackupBase):
    def test_round_trip_integrity(self):
        self.seed_data()
        before = {}
        for rel in ("profile.json", "tracker.json", "offers.json",
                    "gmail_proposals.json", "salary.db",
                    "prep_packs/1.md", "tailored/Acme.md"):
            before[rel] = (self.tmp / rel).read_bytes()

        B.create_backup("snap", data_dir=self.tmp)

        # Mutate everything, then delete a file and a dir entry.
        (self.tmp / "profile.json").write_text(json.dumps({"name": "Changed"}))
        (self.tmp / "tracker.json").write_text(json.dumps([]))
        (self.tmp / "prep_packs" / "1.md").unlink()
        (self.tmp / "tailored" / "Acme.md").unlink()

        res = B.restore_backup("snap", data_dir=self.tmp)
        self.assertEqual(res["restored"], "snap")

        for rel, content in before.items():
            self.assertEqual((self.tmp / rel).read_bytes(), content, rel)

    def test_restore_creates_pre_restore_snapshot(self):
        self.seed_data()
        B.create_backup("snap", data_dir=self.tmp)
        (self.tmp / "tracker.json").write_text(json.dumps([{"id": 9}]))

        res = B.restore_backup("snap", data_dir=self.tmp)
        snapshot = Path(res["snapshot"])
        self.assertTrue(snapshot.is_file())
        self.assertIn("pre-restore-", snapshot.stem)
        with zipfile.ZipFile(snapshot) as zf:
            tracker = json.loads(zf.read("tracker.json"))
            self.assertEqual(tracker, [{"id": 9}])  # state at restore time

    def test_restore_unknown_name(self):
        self.seed_data()
        B.create_backup("real", data_dir=self.tmp)
        with self.assertRaises(B.BackupError) as ctx:
            B.restore_backup("nope", data_dir=self.tmp)
        self.assertIn("real", str(ctx.exception))  # hints at known backups

    def test_restore_never_leaves_data_dir(self):
        self.seed_data()
        (self.tmp / "backups").mkdir(exist_ok=True)
        evil = self.tmp / "backups" / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../../pwned.txt", "pwned")
            zf.writestr("manifest.json", json.dumps({"candid_version": "0.2.0"}))
        with self.assertRaises(B.BackupError):
            B.restore_backup("evil", data_dir=self.tmp, force=True)
        self.assertFalse((self.tmp.parent / "pwned.txt").exists())

    def test_restore_version_mismatch_needs_force(self):
        self.seed_data()
        # Build a backup whose manifest claims a different candid version.
        (self.tmp / "backups").mkdir(exist_ok=True)
        zip_path = self.tmp / "backups" / "old-version.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("tracker.json", json.dumps([{"id": 1}]))
            zf.writestr("manifest.json",
                        json.dumps({"candid_version": "0.0.0",
                                    "created": "2020-01-01T00:00:00",
                                    "files": ["tracker.json"]}))
        with self.assertRaises(B.BackupError):
            B.restore_backup("old-version", data_dir=self.tmp)
        # force=True proceeds
        res = B.restore_backup("old-version", data_dir=self.tmp, force=True)
        self.assertEqual(res["restored"], "old-version")
        self.assertEqual(json.loads((self.tmp / "tracker.json").read_text()),
                         [{"id": 1}])


if __name__ == "__main__":
    unittest.main()
