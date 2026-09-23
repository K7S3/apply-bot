"""Tests for `candid changelog` CLI (generate / check / suggest-bump).

Builds a throwaway git repo with fixture commits and drives the CLI
in-process, mirroring the run_cli pattern from tests/test_cli_ux.py.
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import __version__  # noqa: E402


def git(repo, *args):
    r = subprocess.run(["git", *args], cwd=str(repo),
                       capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout.strip()


class ChangelogCLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-changelog-cli-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init")
        git(self.repo, "config", "user.email", "tester@example.com")
        git(self.repo, "config", "user.name", "Tester")
        self._commit("chore: initial commit")
        git(self.repo, "tag", "v0.1.0")
        self._commit("feat: add salary lookup")
        self._commit("fix: correct LCA range parsing")
        self._commit("docs: update readme badges")

    def _commit(self, message):
        (self.repo / "f.txt").write_text(message + "\n")
        git(self.repo, "add", "f.txt")
        git(self.repo, "commit", "-m", message)

    def run_cli(self, argv):
        """Run the CLI in-process; returns (exit_code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1,
                        out.getvalue(), err.getvalue())
            return 0, out.getvalue(), err.getvalue()

    def base(self, *extra):
        return ["changelog", *extra, "--repo", str(self.repo)]

    # -- generate --------------------------------------------------------

    def test_generate_markdown_default(self):
        code, out, err = self.run_cli(self.base("generate"))
        self.assertEqual(code, 0, err)
        self.assertIn("Features", out)
        self.assertIn("add salary lookup", out)
        self.assertIn("Bug Fixes", out)
        self.assertIn("correct LCA range parsing", out)
        self.assertIn("Documentation", out)
        # the initial commit predates the tag -> excluded by default
        self.assertNotIn("initial commit", out)

    def test_generate_explicit_since(self):
        code, out, err = self.run_cli(
            self.base("generate", "--since", "v0.1.0"))
        self.assertEqual(code, 0, err)
        self.assertIn("add salary lookup", out)
        self.assertNotIn("initial commit", out)

    def test_generate_plain(self):
        code, out, err = self.run_cli(
            self.base("generate", "--format", "plain"))
        self.assertEqual(code, 0, err)
        self.assertIn("add salary lookup", out)
        self.assertIn("correct LCA range parsing", out)

    def test_generate_json_parses(self):
        code, out, err = self.run_cli(
            self.base("generate", "--format", "json"))
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        subjects = [e["subject"] for entries in data["groups"].values()
                    for e in entries]
        self.assertIn("feat: add salary lookup", subjects)
        self.assertIn("fix: correct LCA range parsing", subjects)
        self.assertIn("docs: update readme badges", subjects)
        self.assertEqual(data["version"], __version__)

    def test_generate_github(self):
        code, out, err = self.run_cli(
            self.base("generate", "--format", "github"))
        self.assertEqual(code, 0, err)
        self.assertIn("What's Changed", out)
        self.assertIn("add salary lookup", out)

    def test_generate_no_stats(self):
        code, out, err = self.run_cli(self.base("generate", "--no-stats"))
        self.assertEqual(code, 0, err)
        self.assertNotIn("Stats", out)
        self.assertIn("add salary lookup", out)

    def test_generate_output_writes_file(self):
        dest = self.tmp / "docs" / "CHANGELOG.md"  # nested: dirs created
        code, out, err = self.run_cli(
            self.base("generate", "--output", str(dest)))
        self.assertEqual(code, 0, err)
        self.assertTrue(dest.exists())
        self.assertIn(str(dest), out)
        self.assertIn("add salary lookup", dest.read_text(encoding="utf-8"))

    def test_generate_not_a_git_repo(self):
        code, out, err = self.run_cli(
            ["changelog", "generate", "--repo", str(self.tmp)])
        self.assertEqual(code, 1)
        self.assertIn("not a git repository", err)

    # -- check ------------------------------------------------------------

    def _write_changelog(self):
        dest = self.tmp / "CHANGELOG.md"
        code, out, err = self.run_cli(
            self.base("generate", "--output", str(dest)))
        self.assertEqual(code, 0, err)
        return dest

    def test_check_ok(self):
        dest = self._write_changelog()
        code, out, err = self.run_cli(
            ["changelog", "check", "--file", str(dest),
             "--repo", str(self.repo)])
        self.assertEqual(code, 0, err)
        self.assertIn("OK", out)

    def test_check_missing_entry_exits_1(self):
        dest = self._write_changelog()
        dropped = [line for line in dest.read_text(encoding="utf-8").splitlines()
                   if "correct LCA range parsing" not in line]
        dest.write_text("\n".join(dropped) + "\n", encoding="utf-8")
        code, out, err = self.run_cli(
            ["changelog", "check", "--file", str(dest),
             "--repo", str(self.repo)])
        self.assertEqual(code, 1)
        self.assertIn("fix: correct LCA range parsing", out)

    def test_check_missing_file_exits_1(self):
        code, out, err = self.run_cli(
            ["changelog", "check",
             "--file", str(self.tmp / "NOPE.md"),
             "--repo", str(self.repo)])
        self.assertEqual(code, 1)

    # -- suggest-bump ------------------------------------------------------

    def test_suggest_bump_minor_for_feat(self):
        code, out, err = self.run_cli(self.base("suggest-bump"))
        self.assertEqual(code, 0, err)
        self.assertIn("minor", out)
        # __version__ is 0.2.0 -> minor bump is 0.3.0
        self.assertIn("0.3.0", out)

    def test_suggest_bump_none_when_empty(self):
        git(self.repo, "tag", "v9.9.9")  # at HEAD -> empty commit range
        code, out, err = self.run_cli(
            self.base("suggest-bump", "--since", "v9.9.9"))
        self.assertEqual(code, 0, err)
        self.assertIn("none", out)
        self.assertIn(f"{__version__} -> {__version__}", out)


if __name__ == "__main__":
    unittest.main()
