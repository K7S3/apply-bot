"""Tests for candid/privacy_audit.py (read-only privacy audit log view).

Isolation: CANDID_DATA_DIR/CANDID_CONFIG_DIR are set before importing candid,
and each test re-points candid.config.DATA_DIR plus privacy's audit path at
a fresh temp dir in setUp (restored in tearDown).
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-aud"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-aud-config"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import privacy as P  # noqa: E402
from candid import privacy_audit as A  # noqa: E402
from candid import privacy_retention as R  # noqa: E402


class AuditBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-privaud-"))
        self._saved = {
            "DATA_DIR": C.DATA_DIR,
            "RETENTION_POLICY_PATH": P.RETENTION_POLICY_PATH,
            "AUDIT_LOG_PATH": P.AUDIT_LOG_PATH,
        }
        C.DATA_DIR = self.tmp
        P.RETENTION_POLICY_PATH = self.tmp / "privacy_retention.json"
        P.AUDIT_LOG_PATH = self.tmp / "privacy_audit.jsonl"

    def tearDown(self):
        C.DATA_DIR = self._saved["DATA_DIR"]
        P.RETENTION_POLICY_PATH = self._saved["RETENTION_POLICY_PATH"]
        P.AUDIT_LOG_PATH = self._saved["AUDIT_LOG_PATH"]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_handler(self, func, args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = func(args)
        return rc, buf.getvalue()


class TestAudit(AuditBase):
    def test_empty_log_shows_friendly_message(self):
        rc, out = self.run_handler(A.cmd_audit, Namespace(json=False, limit=20))
        self.assertEqual(rc, 0)
        self.assertIn("no privacy actions recorded yet", out.lower())

    def test_shows_entries_after_direct_audit(self):
        P.audit("export", "category=tracker files=1")
        rc, out = self.run_handler(A.cmd_audit, Namespace(json=False, limit=20))
        self.assertEqual(rc, 0)
        self.assertIn("export", out)
        self.assertIn("category=tracker", out)
        self.assertRegex(out, r"\d{4}-\d{2}-\d{2}")  # timestamp present

    def test_shows_entries_after_retention_run(self):
        d = self.tmp / "prep_packs"
        d.mkdir()
        old = d / "old.md"
        old.write_text("old")
        stamp = time.time() - 60 * 86400
        os.utime(old, (stamp, stamp))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.cmd_set(Namespace(category="prep", days=30))
            R.cmd_run(Namespace(dry_run=False, yes=True))
        rc, out = self.run_handler(A.cmd_audit, Namespace(json=False, limit=20))
        self.assertEqual(rc, 0)
        self.assertIn("retention.set", out)
        self.assertIn("retention.run", out)

    def test_limit_respected(self):
        for i in range(5):
            P.audit(f"probe.{i}", f"detail-{i}")
        rc, out = self.run_handler(A.cmd_audit, Namespace(json=False, limit=2))
        self.assertEqual(rc, 0)
        self.assertNotIn("probe.0", out)
        self.assertIn("probe.3", out)
        self.assertIn("probe.4", out)
        self.assertIn("2 entries shown", out)

    def test_json_output(self):
        P.audit("purge", "category=tracker files=2")
        rc, out = self.run_handler(A.cmd_audit, Namespace(json=True, limit=20))
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["action"], "purge")
        self.assertEqual(data[0]["detail"], "category=tracker files=2")
        self.assertIn("ts", data[0])

    def test_json_limit_respected(self):
        for i in range(4):
            P.audit(f"jsonprobe.{i}")
        rc, out = self.run_handler(A.cmd_audit, Namespace(json=True, limit=3))
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 3)

    def test_negative_limit_is_usage_error(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_handler(A.cmd_audit, Namespace(json=False, limit=-1))
        self.assertEqual(cm.exception.code, 2)

    def test_parser_wiring(self):
        p = argparse.ArgumentParser(prog="candid privacy")
        sub = p.add_subparsers(dest="cmd")
        A.add_parsers(sub)
        args = p.parse_args(["audit"])
        self.assertTrue(callable(args.func))
        self.assertFalse(args.json)
        self.assertEqual(args.limit, 20)
        args = p.parse_args(["audit", "--json", "--limit", "5"])
        self.assertTrue(args.json)
        self.assertEqual(args.limit, 5)


if __name__ == "__main__":
    unittest.main()
