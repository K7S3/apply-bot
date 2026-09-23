"""Tests for candid.release_verify: read-only remote verification checks.

On this machine there is no git auth and tmp repos have no remote, so the
ls-remote checks must degrade to skipped (ok=None) instead of failing.
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import release_verify as RV  # noqa: E402


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=60
    )


class VerifyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="candid-verify-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = Path(self.tmp)
        git(self.repo, "init")
        git(self.repo, "config", "user.name", "Test User")
        git(self.repo, "config", "user.email", "test@example.com")
        (self.repo / "file.txt").write_text("hello\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "initial commit")

    def _by_name(self, checks):
        return {c["name"]: c for c in checks}


class RunChecksTest(VerifyBase):
    def test_check_names(self):
        checks = RV.run_checks(self.repo)
        self.assertEqual(
            [c["name"] for c in checks],
            [
                "working tree clean",
                "local main matches origin/main",
                "tags present on remote",
            ],
        )

    def test_working_tree_clean_ok(self):
        check = self._by_name(RV.run_checks(self.repo))["working tree clean"]
        self.assertTrue(check["ok"])
        self.assertIn("empty", check["detail"])

    def test_working_tree_dirty_fails(self):
        (self.repo / "file.txt").write_text("modified\n")
        check = self._by_name(RV.run_checks(self.repo))["working tree clean"]
        self.assertFalse(check["ok"])

    def test_no_remote_main_check_skipped(self):
        # no origin configured: must degrade to skipped, not fail
        check = self._by_name(RV.run_checks(self.repo))["local main matches origin/main"]
        self.assertIsNone(check["ok"])
        self.assertIn("could not reach origin", check["detail"])

    def test_no_remote_tags_check_skipped(self):
        git(self.repo, "tag", "v0.9.0")
        check = self._by_name(RV.run_checks(self.repo))["tags present on remote"]
        self.assertIsNone(check["ok"])
        self.assertIn("could not reach origin", check["detail"])

    def test_no_local_tags_reports_ok(self):
        check = self._by_name(RV.run_checks(self.repo))["tags present on remote"]
        self.assertTrue(check["ok"])
        self.assertIn("no local v* tags", check["detail"])

    def test_checks_are_read_only(self):
        before = git(self.repo, "status", "--short").stdout
        before_tags = git(self.repo, "tag", "-l").stdout
        RV.run_checks(self.repo)
        self.assertEqual(git(self.repo, "status", "--short").stdout, before)
        self.assertEqual(git(self.repo, "tag", "-l").stdout, before_tags)


if __name__ == "__main__":
    unittest.main()
