"""Tests for candid.release_migrate: commit range listing, heuristic
keyword detection, markdown rendering, and the informational run_checks.
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import release_migrate as RM  # noqa: E402


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=60
    )


def commit(repo, name, subject):
    (repo / name).write_text(subject + "\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", subject)


class MigrateBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="candid-migrate-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = Path(self.tmp)
        git(self.repo, "init")
        git(self.repo, "config", "user.name", "Test User")
        git(self.repo, "config", "user.email", "test@example.com")
        commit(self.repo, "a.txt", "initial commit")
        git(self.repo, "tag", "v0.1.0")
        commit(self.repo, "b.txt", "config: rename data dir option")
        commit(self.repo, "c.txt", "breaking change: drop old schema")
        commit(self.repo, "d.txt", "docs: update readme")
        git(self.repo, "tag", "v0.2.0")


class CommitsBetweenTest(MigrateBase):
    def test_subjects_newest_first(self):
        subjects = RM.commits_between(self.repo, "v0.1.0", "v0.2.0")
        self.assertEqual(
            subjects,
            [
                "docs: update readme",
                "breaking change: drop old schema",
                "config: rename data dir option",
            ],
        )

    def test_empty_range(self):
        self.assertEqual(RM.commits_between(self.repo, "v0.2.0", "v0.2.0"), [])

    def test_bad_ref_returns_empty(self):
        self.assertEqual(RM.commits_between(self.repo, "nope", "alsono"), [])


class DetectMigrationsTest(MigrateBase):
    def test_keyword_hits(self):
        hits = RM.detect_migrations(self.repo, "v0.1.0", "v0.2.0")
        flagged = {h["subject"] for h in hits}
        self.assertIn("config: rename data dir option", flagged)
        self.assertIn("breaking change: drop old schema", flagged)
        self.assertNotIn("docs: update readme", flagged)

    def test_hit_shape_and_keyword_values(self):
        hits = RM.detect_migrations(self.repo, "v0.1.0", "v0.2.0")
        config_hits = [
            h for h in hits if h["subject"] == "config: rename data dir option"
        ]
        self.assertTrue(config_hits)
        keywords = {h["keyword"] for h in config_hits}
        self.assertIn("config", keywords)
        self.assertIn("data dir", keywords)
        for h in hits:
            self.assertEqual(set(h.keys()), {"subject", "hash", "keyword"})
            self.assertEqual(len(h["hash"]), 40)

    def test_detection_is_case_insensitive(self):
        commit(self.repo, "e.txt", "UPGRADE: bump minimum python")
        hits = RM.detect_migrations(self.repo, "v0.2.0", "HEAD")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["keyword"], "upgrade")

    def test_no_hits_on_clean_range(self):
        hits = RM.detect_migrations(self.repo, "v0.2.0", "v0.2.0")
        self.assertEqual(hits, [])


class RenderTest(MigrateBase):
    def test_render_with_hits(self):
        hits = RM.detect_migrations(self.repo, "v0.1.0", "v0.2.0")
        out = RM.render_migration_notes(hits, "v0.1.0", "v0.2.0")
        self.assertIn("## Migration notes (v0.1.0 -> v0.2.0)", out)
        self.assertIn("config: rename data dir option", out)
        self.assertIn("keyword: config", out)
        self.assertIn("`", out)  # short hash in backticks

    def test_render_empty_fallback(self):
        out = RM.render_migration_notes([], "v0.1.0", "v0.2.0")
        self.assertIn("## Migration notes (v0.1.0 -> v0.2.0)", out)
        self.assertIn(
            "No migration-relevant changes detected (heuristic scan).", out
        )


class RunChecksTest(MigrateBase):
    def test_never_fails_and_reports_count(self):
        checks = RM.run_checks(self.repo)
        self.assertEqual(len(checks), 1)
        check = checks[0]
        self.assertEqual(check["name"], "migration notes generatable")
        self.assertTrue(check["ok"])
        hits = RM.detect_migrations(self.repo, "v0.1.0", "v0.2.0")
        self.assertIn(str(len(hits)), check["detail"])

    def test_no_tags_still_ok(self):
        tmp = tempfile.mkdtemp(prefix="candid-migrate-notags-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = Path(tmp)
        git(repo, "init")
        git(repo, "config", "user.name", "Test User")
        git(repo, "config", "user.email", "test@example.com")
        commit(repo, "a.txt", "initial commit")
        checks = RM.run_checks(repo)
        self.assertTrue(checks[0]["ok"])
        self.assertIn("no v* tags", checks[0]["detail"])


if __name__ == "__main__":
    unittest.main()
