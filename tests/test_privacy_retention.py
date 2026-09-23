"""Tests for candid/privacy_retention.py (per-category retention policies).

Isolation: CANDID_DATA_DIR/CANDID_CONFIG_DIR are set before importing candid,
and each test re-points candid.config.DATA_DIR plus privacy's policy/audit
paths at a fresh temp dir in setUp (restored in tearDown).
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
from unittest import mock

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-privret"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-privret-config"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import privacy as P  # noqa: E402
from candid import privacy_retention as R  # noqa: E402


def _parser():
    p = argparse.ArgumentParser(prog="candid privacy")
    sub = p.add_subparsers(dest="cmd")
    R.add_parsers(sub)
    return p


class RetentionBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-privret-"))
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

    def age_file(self, path: Path, days_old: float) -> None:
        stamp = time.time() - days_old * 86400
        os.utime(path, (stamp, stamp))


class TestSetShow(RetentionBase):
    def test_set_show_round_trip(self):
        rc, _ = self.run_handler(R.cmd_set, Namespace(category="tracker", days=30))
        self.assertEqual(rc, 0)
        saved = json.loads(P.RETENTION_POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"tracker": 30})
        rc, out = self.run_handler(R.cmd_show, Namespace(json=False))
        self.assertEqual(rc, 0)
        self.assertIn("tracker", out)
        self.assertIn("30 days", out)

    def test_set_zero_disables(self):
        rc, out = self.run_handler(R.cmd_set, Namespace(category="tracker", days=0))
        self.assertEqual(rc, 0)
        self.assertIn("disabled", out.lower())
        saved = json.loads(P.RETENTION_POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved["tracker"], 0)

    def test_set_rejects_unknown_category(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_handler(R.cmd_set, Namespace(category="nope", days=30))
        self.assertEqual(cm.exception.code, 2)

    def test_set_rejects_negative_days(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_handler(R.cmd_set, Namespace(category="tracker", days=-1))
        self.assertEqual(cm.exception.code, 2)

    def test_set_rejects_non_integer_days_via_parser(self):
        parser = _parser()
        with self.assertRaises(SystemExit) as cm:
            parser.parse_args(["retention", "set", "tracker", "abc"])
        self.assertEqual(cm.exception.code, 2)

    def test_show_json(self):
        self.run_handler(R.cmd_set, Namespace(category="prep", days=14))
        rc, out = self.run_handler(R.cmd_show, Namespace(json=True))
        self.assertEqual(rc, 0)
        data = json.loads(out)
        by_name = {row["name"]: row for row in data["policies"]}
        self.assertEqual(by_name["prep"]["days"], 14)
        self.assertIsNone(by_name["tracker"]["days"])
        self.assertIn("meaning", by_name["prep"])

    def test_show_explains_meanings(self):
        self.run_handler(R.cmd_set, Namespace(category="tracker", days=0))
        rc, out = self.run_handler(R.cmd_show, Namespace(json=False))
        self.assertEqual(rc, 0)
        self.assertIn("0 (disabled)", out)
        self.assertIn("not set", out)
        self.assertIn("What this means", out)


class TestRun(RetentionBase):
    def _make_prep_files(self):
        d = self.tmp / "prep_packs"
        d.mkdir()
        old = d / "old.md"
        new = d / "new.md"
        old.write_text("old")
        new.write_text("new")
        self.age_file(old, 60)
        self.age_file(new, 1)
        return old, new

    def test_run_dry_run_deletes_nothing_but_reports(self):
        old, new = self._make_prep_files()
        self.run_handler(R.cmd_set, Namespace(category="prep", days=30))
        rc, out = self.run_handler(
            R.cmd_run, Namespace(dry_run=True, yes=False)
        )
        self.assertEqual(rc, 0)
        self.assertTrue(old.exists(), "dry-run must not delete")
        self.assertTrue(new.exists(), "dry-run must not delete")
        self.assertIn("old.md", out)
        self.assertIn("dry-run", out.lower())

    def test_run_deletes_only_old_files(self):
        old, new = self._make_prep_files()
        self.run_handler(R.cmd_set, Namespace(category="prep", days=30))
        rc, out = self.run_handler(
            R.cmd_run, Namespace(dry_run=False, yes=True)
        )
        self.assertEqual(rc, 0)
        self.assertFalse(old.exists(), "old file should be deleted")
        self.assertTrue(new.exists(), "fresh file must be kept")
        self.assertIn("Deleted 1 file", out)

    def test_run_respects_confirmation_decline(self):
        old, new = self._make_prep_files()
        self.run_handler(R.cmd_set, Namespace(category="prep", days=30))
        with mock.patch.object(P, "confirm", return_value=False):
            rc, out = self.run_handler(
                R.cmd_run, Namespace(dry_run=False, yes=False)
            )
        self.assertEqual(rc, 0)
        self.assertTrue(old.exists(), "declined run must delete nothing")
        self.assertIn("cancelled", out.lower())

    def test_run_no_policies(self):
        rc, out = self.run_handler(R.cmd_run, Namespace(dry_run=False, yes=True))
        self.assertEqual(rc, 0)
        self.assertIn("No retention policies", out)

    def test_run_nothing_old_enough(self):
        _, new = self._make_prep_files()
        self.run_handler(R.cmd_set, Namespace(category="prep", days=90))
        rc, out = self.run_handler(
            R.cmd_run, Namespace(dry_run=False, yes=True)
        )
        self.assertEqual(rc, 0)
        self.assertTrue(new.exists())
        self.assertIn("Nothing to delete", out)

    def test_run_audits_with_counts(self):
        old, _ = self._make_prep_files()
        self.run_handler(R.cmd_set, Namespace(category="prep", days=30))
        self.run_handler(R.cmd_run, Namespace(dry_run=False, yes=True))
        entries = P.read_audit_log(limit=100)
        runs = [e for e in entries if e["action"] == "retention.run"]
        self.assertEqual(len(runs), 1)
        self.assertIn("deleted=1", runs[0]["detail"])

    def test_parser_wiring(self):
        parser = _parser()
        for argv in (
            ["retention", "set", "tracker", "30"],
            ["retention", "show"],
            ["retention", "show", "--json"],
            ["retention", "run"],
            ["retention", "run", "--dry-run", "--yes"],
        ):
            args = parser.parse_args(argv)
            self.assertTrue(callable(args.func), f"func not set for {argv}")
        set_args = parser.parse_args(["retention", "set", "tracker", "30"])
        self.assertEqual(set_args.category, "tracker")
        self.assertEqual(set_args.days, 30)
        run_args = parser.parse_args(["retention", "run", "--dry-run"])
        self.assertTrue(run_args.dry_run)
        self.assertFalse(run_args.yes)


if __name__ == "__main__":
    unittest.main()
