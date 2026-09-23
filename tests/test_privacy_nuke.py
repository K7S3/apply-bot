"""Tests for candid.privacy_nuke (privacy nuke command).

Test isolation: CANDID_DATA_DIR / CANDID_CONFIG_DIR are set before candid
is imported, and setUp/tearDown additionally redirect candid.config.DATA_DIR
and the derived paths in candid.privacy (same approach as
tests/test_dashboard.py), so these tests are independent of import order.
"""

import argparse
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-privnuke"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-privnuke-config"

from candid import config as C  # noqa: E402
from candid import privacy as P  # noqa: E402
from candid import privacy_nuke as pn  # noqa: E402


def make_args(**kwargs):
    base = dict(yes=False, export_first=False)
    base.update(kwargs)
    return Namespace(**base)


class PrivacyNukeTest(unittest.TestCase):
    def setUp(self):
        # Fixture data in setUp: fresh temp DATA_DIR, paths redirected.
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-privnuke-"))
        self._saved = {
            "DATA_DIR": C.DATA_DIR,
            "PRIVACY_EXPORT_DIR": P.PRIVACY_EXPORT_DIR,
            "AUDIT_LOG_PATH": P.AUDIT_LOG_PATH,
        }
        C.DATA_DIR = self.tmp
        P.PRIVACY_EXPORT_DIR = self.tmp / "privacy_exports"
        P.AUDIT_LOG_PATH = self.tmp / "privacy_audit.jsonl"
        (self.tmp / "profile.json").write_text(
            '{"name": "Keshavan", "email": "keshavan@example.com"}',
            encoding="utf-8",
        )
        (self.tmp / "tracker.json").write_text(
            '{"applications": [{"company": "Acme"}]}', encoding="utf-8"
        )
        sub = self.tmp / "tailored"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "resume.txt").write_text("resume text", encoding="utf-8")
        exp = self.tmp / "privacy_exports"
        exp.mkdir(parents=True, exist_ok=True)
        (exp / "keep.zip").write_bytes(b"PK\x03\x04keep")
        P.audit("scan", "before-nuke")

    def tearDown(self):
        C.DATA_DIR = self._saved["DATA_DIR"]
        P.PRIVACY_EXPORT_DIR = self._saved["PRIVACY_EXPORT_DIR"]
        P.AUDIT_LOG_PATH = self._saved["AUDIT_LOG_PATH"]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read_audit(self):
        log = self.tmp / "privacy_audit.jsonl"
        if not log.exists():
            return []
        return [
            json.loads(line)
            for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def run_nuke(self, **kwargs):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = pn.cmd_nuke(make_args(**kwargs))
        return rc, buf.getvalue()

    def test_declined_confirm_deletes_nothing(self):
        with patch("builtins.input", return_value="no"):
            rc, out = self.run_nuke()
        self.assertEqual(rc, 0)
        self.assertIn("cancelled", out.lower())
        self.assertTrue((self.tmp / "profile.json").exists())
        self.assertTrue((self.tmp / "tracker.json").exists())
        self.assertTrue((self.tmp / "tailored" / "resume.txt").exists())
        self.assertTrue((self.tmp / "privacy_exports" / "keep.zip").exists())
        self.assertFalse(
            any(e["action"] == "nuke" for e in self.read_audit())
        )

    def test_typed_delete_wipes(self):
        with patch("builtins.input", return_value="DELETE"):
            rc, out = self.run_nuke()
        self.assertEqual(rc, 0)
        self.assertFalse((self.tmp / "profile.json").exists())
        self.assertFalse((self.tmp / "tracker.json").exists())
        self.assertFalse((self.tmp / "tailored").exists())
        # protected category survives intact
        self.assertTrue((self.tmp / "privacy_exports" / "keep.zip").exists())
        self.assertIn("freed", out)

    def test_yes_wipes_data_preserves_exports(self):
        rc, out = self.run_nuke(yes=True)
        self.assertEqual(rc, 0)
        self.assertIn("WARNING", out)
        self.assertFalse((self.tmp / "profile.json").exists())
        self.assertFalse((self.tmp / "tracker.json").exists())
        self.assertFalse((self.tmp / "tailored").exists())
        self.assertTrue((self.tmp / "privacy_exports" / "keep.zip").exists())

    def test_export_first_creates_zip_before_wiping(self):
        rc, _ = self.run_nuke(yes=True, export_first=True)
        self.assertEqual(rc, 0)
        zips = list((self.tmp / "privacy_exports").glob("full-backup-*.zip"))
        self.assertEqual(len(zips), 1)
        with zipfile.ZipFile(zips[0]) as zf:
            names = zf.namelist()
        self.assertIn("profile.json", names)
        self.assertIn("tracker.json", names)
        self.assertIn("tailored/resume.txt", names)
        # data wiped, but the backup zip itself survived
        self.assertFalse((self.tmp / "profile.json").exists())
        self.assertTrue(zips[0].exists())

    def test_audit_log_survives_nuke_with_nuke_entry(self):
        rc, _ = self.run_nuke(yes=True)
        self.assertEqual(rc, 0)
        log = self.tmp / "privacy_audit.jsonl"
        self.assertTrue(log.exists())
        entries = self.read_audit()
        self.assertTrue(
            any(e["action"] == "nuke" for e in entries),
            "nuke entry must be present after the wipe",
        )
        # the pre-nuke history was wiped along with the old log file
        self.assertFalse(any(e["action"] == "scan" for e in entries))

    def test_add_parsers_registers_nuke(self):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        pn.add_parsers(sub)
        args = parser.parse_args(["nuke", "--yes"])
        self.assertIs(args.func, pn.cmd_nuke)
        self.assertTrue(args.yes)
        args = parser.parse_args(["nuke", "--export-first"])
        self.assertTrue(args.export_first)


if __name__ == "__main__":
    unittest.main()
