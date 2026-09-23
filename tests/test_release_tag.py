"""Tests for candid.release_tag: tag naming/message, dry-run flow, real tag
creation, duplicate/dirty refusals, require_checks_fn abort, prerequisites.

All git writes happen in throwaway tmp repos, never in the real checkout.
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import release_tag as RT  # noqa: E402
from candid import __version__  # noqa: E402


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=60
    )


def init_repo(path, with_identity=True):
    """git init + one commit in path. Identity can be omitted to test the
    'git identity configured' check (commit itself uses -c overrides)."""
    git(path, "init")
    if with_identity:
        git(path, "config", "user.name", "Test User")
        git(path, "config", "user.email", "test@example.com")
    (path / "file.txt").write_text("hello\n")
    git(path, "add", ".")
    if with_identity:
        git(path, "commit", "-m", "initial commit")
    else:
        git(
            path,
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "initial commit",
        )


class TagBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="candid-tag-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = Path(self.tmp)
        init_repo(self.repo)


class TagNameTest(TagBase):
    def test_tag_name(self):
        self.assertEqual(RT.tag_name("0.2.0"), "v0.2.0")
        self.assertEqual(RT.tag_name("1.0.0"), "v1.0.0")

    def test_tag_message_template(self):
        msg = RT.tag_message("0.2.0", "some notes")
        self.assertTrue(msg.startswith("candid 0.2.0\n\n"))
        self.assertIn("some notes", msg)

    def test_tag_message_no_notes_has_no_trailing_blank(self):
        self.assertEqual(RT.tag_message("0.2.0"), "candid 0.2.0")


class TreeCleanTest(TagBase):
    def test_tree_is_clean_fresh_repo(self):
        self.assertTrue(RT.tree_is_clean(self.repo))

    def test_tree_is_clean_dirty_repo(self):
        (self.repo / "file.txt").write_text("modified\n")
        self.assertFalse(RT.tree_is_clean(self.repo))

    def test_tree_is_clean_not_a_repo(self):
        self.assertFalse(RT.tree_is_clean(Path(self.tmp) / "nope"))


class CreateTagTest(TagBase):
    def test_dry_run_creates_nothing(self):
        res = RT.create_tag(self.repo, "9.9.9", notes="test release")
        self.assertTrue(res["ok"])
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["tag"], "v9.9.9")
        self.assertIn("would create annotated tag v9.9.9 on", res["detail"])
        self.assertEqual(git(self.repo, "tag", "-l").stdout.strip(), "")

    def test_real_tag_creation(self):
        res = RT.create_tag(self.repo, "9.9.9", notes="test release", dry_run=False)
        self.assertTrue(res["ok"])
        self.assertFalse(res["dry_run"])
        self.assertEqual(res["tag"], "v9.9.9")
        self.assertIn("created annotated tag v9.9.9", res["detail"])
        r = git(self.repo, "rev-parse", "-q", "--verify", "refs/tags/v9.9.9")
        self.assertEqual(r.returncode, 0)
        # annotated tag object, not a lightweight pointer
        self.assertEqual(git(self.repo, "cat-file", "-t", "v9.9.9").stdout.strip(), "tag")

    def test_duplicate_tag_refused(self):
        first = RT.create_tag(self.repo, "1.2.3", dry_run=False)
        self.assertTrue(first["ok"])
        second = RT.create_tag(self.repo, "1.2.3", dry_run=False)
        self.assertFalse(second["ok"])
        self.assertIn("already exists", second["detail"])
        self.assertEqual(second["tag"], "v1.2.3")

    def test_duplicate_tag_refused_even_in_dry_run(self):
        RT.create_tag(self.repo, "1.2.3", dry_run=False)
        res = RT.create_tag(self.repo, "1.2.3", dry_run=True)
        self.assertFalse(res["ok"])
        self.assertIn("already exists", res["detail"])

    def test_dirty_tree_refused_when_not_dry_run(self):
        (self.repo / "file.txt").write_text("modified\n")
        res = RT.create_tag(self.repo, "9.9.9", dry_run=False)
        self.assertFalse(res["ok"])
        self.assertIn("dirty", res["detail"])
        self.assertEqual(git(self.repo, "tag", "-l").stdout.strip(), "")

    def test_dirty_tree_allowed_in_dry_run(self):
        (self.repo / "file.txt").write_text("modified\n")
        res = RT.create_tag(self.repo, "9.9.9", dry_run=True)
        self.assertTrue(res["ok"])
        self.assertTrue(res["dry_run"])

    def test_require_checks_fn_abort_records_failed_checks(self):
        def failing():
            return [
                {"name": "working tree clean", "ok": False, "detail": "dirty"},
                {"name": "other check", "ok": True, "detail": "fine"},
            ]

        res = RT.create_tag(self.repo, "9.9.9", dry_run=False,
                            require_checks_fn=failing)
        self.assertFalse(res["ok"])
        self.assertIn("working tree clean", res["detail"])
        self.assertNotIn("other check", res["detail"])
        self.assertEqual(git(self.repo, "tag", "-l").stdout.strip(), "")

    def test_require_checks_fn_skipped_checks_do_not_abort(self):
        def with_skip():
            return [{"name": "remote check", "ok": None, "detail": "skipped"}]

        res = RT.create_tag(self.repo, "9.9.9", dry_run=True,
                            require_checks_fn=with_skip)
        self.assertTrue(res["ok"])


class RunChecksTest(TagBase):
    def _by_name(self, checks):
        return {c["name"]: c for c in checks}

    def test_all_pass_on_clean_repo(self):
        checks = RT.run_checks(self.repo)
        by_name = self._by_name(checks)
        self.assertEqual(
            [c["name"] for c in checks],
            [
                "working tree clean",
                "no duplicate tag for current version",
                "git identity configured",
            ],
        )
        for c in checks:
            self.assertTrue(c["ok"], c["name"])

    def test_dirty_tree_fails_first_check(self):
        (self.repo / "file.txt").write_text("modified\n")
        by_name = self._by_name(RT.run_checks(self.repo))
        self.assertFalse(by_name["working tree clean"]["ok"])

    def test_duplicate_tag_fails_second_check(self):
        git(self.repo, "tag", "-a", f"v{__version__}", "-m", "dup")
        by_name = self._by_name(RT.run_checks(self.repo))
        check = by_name["no duplicate tag for current version"]
        self.assertFalse(check["ok"])
        self.assertIn(f"v{__version__}", check["detail"])

    def test_missing_identity_fails_third_check(self):
        tmp = tempfile.mkdtemp(prefix="candid-noid-test-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = Path(tmp)
        init_repo(repo, with_identity=False)
        by_name = self._by_name(RT.run_checks(repo))
        check = by_name["git identity configured"]
        self.assertFalse(check["ok"])
        self.assertIn("user.name", check["detail"])


if __name__ == "__main__":
    unittest.main()
