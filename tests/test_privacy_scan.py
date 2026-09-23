"""Tests for candid.privacy_scan (privacy scan / egress commands).

Test isolation: CANDID_DATA_DIR / CANDID_CONFIG_DIR point at unique temp
dirs, set before candid is imported. Fixtures seed data files in setUp and
remove them in tearDown. Egress tests inspect the real package source, so
they point at the real candid package dir (no data-dir dependence).
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import unittest
from pathlib import Path

# Test isolation: must be set before importing candid.
os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-privscan"
os.environ["CANDID_CONFIG_DIR"] = "/tmp/candid-test-privscan-config"

import candid.config as C  # noqa: E402
from candid import privacy as P  # noqa: E402
from candid import privacy_scan as PS  # noqa: E402

DATA_DIR = Path(os.environ["CANDID_DATA_DIR"])
CONFIG_DIR = Path(os.environ["CANDID_CONFIG_DIR"])

EMAIL = "keshavan@example.com"
MASKED_EMAIL = "k***@example.com"
PHONE = "+1-555-010-1234"


def _ns(**kwargs):
    base = {"json": False, "category": None}
    base.update(kwargs)
    return argparse.Namespace(**base)


def _run(func, args):
    """Run a handler, capturing stdout/stderr. Returns (exit_code, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = func(args)
    return code, out.getvalue(), err.getvalue()


class PrivacyScanTest(unittest.TestCase):
    def setUp(self):
        # Point candid.config at this test's temp dir regardless of which test
        # module imported candid first (config.DATA_DIR is bound at import).
        self._saved_data_dir = C.DATA_DIR
        self._saved_audit_log = P.AUDIT_LOG_PATH
        C.DATA_DIR = DATA_DIR
        P.AUDIT_LOG_PATH = DATA_DIR / "privacy_audit.jsonl"
        for d in (DATA_DIR, CONFIG_DIR):
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)

        # profile.json: email + phone in a json category
        (DATA_DIR / "profile.json").write_text(
            json.dumps(
                {
                    "name": "Test User",
                    "email": EMAIL,
                    "phone": PHONE,
                    "ssn": "123-45-6789",
                }
            ),
            encoding="utf-8",
        )
        # tailored dir: another text file with an email, plus a binary file
        # that also contains an email but must be skipped.
        tailored = DATA_DIR / "tailored"
        tailored.mkdir(parents=True, exist_ok=True)
        (tailored / "resume.md").write_text(
            f"# Resume\nContact me at friend@example.org any time\n",
            encoding="utf-8",
        )
        (tailored / "logo.bin").write_bytes(
            b"\x00\x01\x02\x03binary-blob\xff\xfe" + EMAIL.encode("utf-8")
        )

    def tearDown(self):
        C.DATA_DIR = self._saved_data_dir
        P.AUDIT_LOG_PATH = self._saved_audit_log
        for d in (DATA_DIR, CONFIG_DIR):
            shutil.rmtree(d, ignore_errors=True)

    # --- scan: findings -------------------------------------------------

    def test_scan_finds_email_and_phone(self):
        code, out, _ = _run(PS.cmd_scan, _ns())
        self.assertEqual(code, 0)
        self.assertIn("profile.json", out)
        self.assertIn("[email]", out)
        self.assertIn("[phone]", out)
        self.assertIn(PHONE, out)

    def test_scan_masks_email_local_part(self):
        code, out, _ = _run(PS.cmd_scan, _ns())
        self.assertEqual(code, 0)
        self.assertIn(MASKED_EMAIL, out)
        self.assertNotIn(EMAIL, out)
        # matches in json output are masked too
        code, out, _ = _run(PS.cmd_scan, _ns(json=True))
        self.assertEqual(code, 0)
        doc = json.loads(out)
        matches = [f["match"] for f in doc["findings"]]
        self.assertIn(MASKED_EMAIL, matches)
        for m in matches:
            self.assertNotIn(EMAIL, m)

    def test_scan_reports_type_line_and_relative_path(self):
        code, out, _ = _run(PS.cmd_scan, _ns(json=True))
        self.assertEqual(code, 0)
        doc = json.loads(out)
        email_hits = [f for f in doc["findings"] if f["type"] == "email"]
        self.assertTrue(email_hits)
        hit = email_hits[0]
        self.assertEqual(hit["file"], "profile.json")
        self.assertIsInstance(hit["line"], int)
        self.assertGreaterEqual(hit["line"], 1)
        # no absolute temp path leaks into the file field
        self.assertNotIn("/tmp/", hit["file"])

    def test_scan_truncates_long_matches(self):
        (DATA_DIR / "profile.json").write_text(
            json.dumps({"token": "api_key = 'abcdefghij0123456789xyz-SECRET-long-value-here'"}),
            encoding="utf-8",
        )
        code, out, _ = _run(PS.cmd_scan, _ns(json=True))
        self.assertEqual(code, 0)
        doc = json.loads(out)
        for f in doc["findings"]:
            self.assertLessEqual(len(f["match"]), 40)

    def test_scan_category_limits_scope(self):
        code, out, _ = _run(PS.cmd_scan, _ns(category="profile"))
        self.assertEqual(code, 0)
        self.assertIn("profile.json", out)
        self.assertNotIn("resume.md", out)
        code, out, _ = _run(PS.cmd_scan, _ns(category="tailored"))
        self.assertEqual(code, 0)
        self.assertIn("resume.md", out)
        self.assertNotIn("profile.json", out)

    def test_scan_bad_category_exits_2(self):
        with self.assertRaises(SystemExit) as ctx:
            PS.cmd_scan(_ns(category="nope"))
        self.assertEqual(ctx.exception.code, 2)

    def test_scan_exit_zero_with_findings_and_summary(self):
        code, out, _ = _run(PS.cmd_scan, _ns())
        self.assertEqual(code, 0)  # findings are informational, not errors
        self.assertIn("finding", out)

    def test_binary_files_are_skipped(self):
        code, out, _ = _run(PS.cmd_scan, _ns(json=True))
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertGreaterEqual(doc["summary"]["skipped_binary"], 1)
        for f in doc["findings"]:
            self.assertFalse(f["file"].endswith("logo.bin"),
                             "binary file must not be scanned")

    def test_scan_writes_audit_entry(self):
        code, _, _ = _run(PS.cmd_scan, _ns())
        self.assertEqual(code, 0)
        entries = P.read_audit_log(limit=10)
        self.assertTrue(entries)
        self.assertEqual(entries[-1]["action"], "scan")

    def test_scan_json_structure(self):
        code, out, _ = _run(PS.cmd_scan, _ns(json=True))
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertIn("findings", doc)
        self.assertIn("summary", doc)
        self.assertIn("files_scanned", doc["summary"])
        self.assertIn("skipped_binary", doc["summary"])

    # --- egress ---------------------------------------------------------

    def test_egress_reports_localhost_binding(self):
        code, out, _ = _run(PS.cmd_egress, _ns())
        self.assertEqual(code, 0)
        self.assertIn("127.0.0.1", out)

    def test_egress_lists_job_source_urls(self):
        code, out, _ = _run(PS.cmd_egress, _ns())
        self.assertEqual(code, 0)
        self.assertTrue(
            "arbeitnow.com" in out or "remoteok.com" in out,
            "egress report must list at least one job source URL",
        )

    def test_egress_no_warnings_when_localhost_only(self):
        code, out, _ = _run(PS.cmd_egress, _ns(json=True))
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["warnings"], [])
        self.assertTrue(doc["ok"])
        self.assertTrue(doc["components"])

    def test_egress_states_data_sent_per_source(self):
        code, out, _ = _run(PS.cmd_egress, _ns(json=True))
        self.assertEqual(code, 0)
        doc = json.loads(out)
        for c in doc["components"]:
            self.assertIn("data_sent", c)
            self.assertIn("when_contacted", c)
            self.assertIn("url_or_purpose", c)
        job_rows = [c for c in doc["components"] if "jobs.py" in c["component"]]
        self.assertTrue(job_rows)
        for c in job_rows:
            self.assertIn("None", c["data_sent"])

    def test_egress_writes_audit_entry(self):
        code, _, _ = _run(PS.cmd_egress, _ns())
        self.assertEqual(code, 0)
        entries = P.read_audit_log(limit=10)
        self.assertTrue(entries)
        self.assertEqual(entries[-1]["action"], "egress")


if __name__ == "__main__":
    unittest.main()
