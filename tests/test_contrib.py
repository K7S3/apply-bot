"""Contributor-experience checks for candid.

Verifies the docs, scripts, and GitHub templates that make it easy for a new
contributor to get started. Hermetic: reads repo files only, no network, and
only writes inside temp dirs.
"""

import os
import py_compile
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class TestContributorDocs(unittest.TestCase):
    def test_contributing_exists_with_required_sections(self):
        text = read("CONTRIBUTING.md")
        lowered = text.lower()
        self.assertTrue(any(s in lowered for s in
                            ("quickstart", "quick start")))
        self.assertTrue(any(s in lowered for s in
                            ("coding standard", "code style")))
        self.assertTrue(any(s in lowered for s in
                            ("test requirement", "running tests", "testing")))
        self.assertTrue(any(s in lowered for s in
                            ("pull request", "pr process", "## pr")),
                        "CONTRIBUTING.md missing a PR process section")

    def test_code_of_conduct_and_security_exist(self):
        self.assertTrue((ROOT / "CODE_OF_CONDUCT.md").is_file())
        self.assertTrue((ROOT / "SECURITY.md").is_file())

    def test_readme_links_to_contributing(self):
        text = read("README.md")
        self.assertIn("CONTRIBUTING.md", text)
        self.assertIn("## Contributing", text)


class TestContributorScripts(unittest.TestCase):
    def test_dev_setup_exists_executable_and_parses(self):
        path = ROOT / "scripts" / "dev-setup.sh"
        self.assertTrue(path.is_file(), "scripts/dev-setup.sh missing")
        self.assertTrue(os.access(path, os.X_OK),
                        "scripts/dev-setup.sh is not executable")
        result = subprocess.run(["bash", "-n", str(path)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0,
                         f"bash -n failed: {result.stderr}")

    def test_sync_labels_compiles(self):
        path = ROOT / "scripts" / "sync-labels.py"
        self.assertTrue(path.is_file(), "scripts/sync-labels.py missing")
        with tempfile.TemporaryDirectory() as tmp:
            py_compile.compile(str(path), doraise=True,
                               cfile=str(Path(tmp) / "sync_labels.pyc"))

    def test_sync_labels_dry_run_without_token(self):
        # The script's default mode is a dry run: no --apply means no token
        # and no network. Assert the real default dry-run path works.
        path = ROOT / "scripts" / "sync-labels.py"
        self.assertTrue(path.is_file(), "scripts/sync-labels.py missing")
        env = {k: v for k, v in os.environ.items()
               if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
        result = subprocess.run(["python3", str(path)],
                                capture_output=True, text=True, timeout=60,
                                env=env)
        self.assertEqual(result.returncode, 0,
                         f"dry run failed: {result.stderr}")


class TestGithubTemplates(unittest.TestCase):
    def test_issue_templates_exist_with_headings(self):
        bug = read(".github/ISSUE_TEMPLATE/bug_report.md")
        feature = read(".github/ISSUE_TEMPLATE/feature_request.md")
        for text in (bug, feature):
            self.assertRegex(text, r"(?m)^#+ .+",
                             "issue template has no markdown headings")
        lowered = bug.lower()
        self.assertIn("reproduce", lowered,
                      "bug report should have a reproduction section")
        self.assertIn("describe", feature.lower(),
                      "feature request should ask for a description")

    def test_issue_template_config_exists(self):
        self.assertTrue(
            (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").is_file())

    def test_pr_template_exists_with_testing_section(self):
        text = read(".github/PULL_REQUEST_TEMPLATE.md")
        self.assertRegex(text, r"(?m)^#+ .+",
                         "PR template has no markdown headings")
        self.assertIn("test", text.lower(),
                      "PR template should have a testing section")


class TestArchitectureAndDocs(unittest.TestCase):
    # Real modules inside candid/ that docs/architecture.md should mention.
    MODULES = ["match", "tailor", "tracker", "salary", "prep", "mock_judge",
               "dashboard", "offer", "gmail", "linkedin", "coach"]

    def test_architecture_mentions_modules(self):
        text = read("docs/architecture.md")
        lowered = text.lower()
        hits = [m for m in self.MODULES if m in lowered]
        self.assertGreaterEqual(len(hits), 5,
                                f"only {len(hits)} modules mentioned: {hits}")

    def test_testing_doc_mentions_discover_command(self):
        text = read("docs/testing.md")
        self.assertIn("python -m unittest discover", text.replace("python3",
                                                                  "python"))

    def test_labels_doc_mentions_good_first_issue(self):
        text = read("docs/labels.md")
        self.assertIn("good first issue", text.lower())

    def test_adr_0001_and_template_exist(self):
        self.assertTrue((ROOT / "docs" / "adr" / "0001-record-architecture-decisions.md").is_file())
        self.assertTrue((ROOT / "docs" / "adr" / "TEMPLATE.md").is_file())


if __name__ == "__main__":
    unittest.main()
