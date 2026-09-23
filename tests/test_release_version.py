"""Tests for candid.release_version. Never touches the real repo's files:
all bump tests run on tmp copies. Only get_version reads the real repo."""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import release_version as RV


def make_repo(path, version="0.2.0", readme=None, changelog=None, extra_py=None):
    """Build a minimal fake repo tree at the given path."""
    root = Path(path)
    (root / "candid").mkdir()
    (root / "candid" / "__init__.py").write_text(
        '"""fake pkg"""\n\n__version__ = "%s"\n' % version, encoding="utf-8"
    )
    if readme is not None:
        (root / "README.md").write_text(readme, encoding="utf-8")
    if changelog is not None:
        (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    for name, content in (extra_py or {}).items():
        (root / "candid" / name).write_text(content, encoding="utf-8")
    return root


def check_by_name(results, name):
    matches = [r for r in results if r["name"] == name]
    assert len(matches) == 1, f"expected one check named {name!r}: {results}"
    return matches[0]


class GetVersionTest(unittest.TestCase):
    def test_real_repo_version(self):
        # Read-only check against the real repo baseline.
        self.assertEqual(RV.get_version(ROOT), "0.2.0")

    def test_tmp_repo_version(self):
        with tempfile.TemporaryDirectory() as d:
            root = make_repo(d, version="1.4.2")
            self.assertEqual(RV.get_version(root), "1.4.2")

    def test_missing_version_raises(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "candid").mkdir()
            (root / "candid" / "__init__.py").write_text("x = 1\n")
            with self.assertRaises(ValueError):
                RV.get_version(root)



class ParseVersionTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(RV.parse_version("0.2.0"), (0, 2, 0))
        self.assertEqual(RV.parse_version("10.20.30"), (10, 20, 30))

    def test_invalid(self):
        for bad in ("0.2", "1.2.3.4", "a.b.c", "1.2.x", "", "v1.2.3",
                    "1.02.3", "1.2.3-rc1", "1..3", " 1.2 ", None):
            with self.assertRaises(ValueError, msg=bad):
                RV.parse_version(bad)


class RunChecksTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)

    def test_all_pass(self):
        root = make_repo(self.td.name,
            version="0.2.0",
            readme="# fake\n\nWorks with v0.2.0 and up.\n",
            changelog="# Changelog\n\n## [0.2.0] - 2026-09-01\n\n- stuff\n",
        )
        results = RV.run_checks(root)
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertIn("name", r)
            self.assertIn("ok", r)
            self.assertIn("detail", r)
        self.assertTrue(check_by_name(results, "version parses as semver")["ok"])
        self.assertTrue(check_by_name(results, "single version source")["ok"])
        self.assertTrue(check_by_name(results, "changelog matches version")["ok"])
        self.assertTrue(
            check_by_name(results, "readme version mentions consistent")["ok"]
        )

    def test_bad_semver(self):
        root = make_repo(self.td.name, version="0.2")
        r = check_by_name(RV.run_checks(root), "version parses as semver")
        self.assertFalse(r["ok"])

    def test_duplicate_version_in_other_file(self):
        root = make_repo(self.td.name,
            extra_py={"extra.py": '__version__ = "9.9.9"\n'},
        )
        r = check_by_name(RV.run_checks(root), "single version source")
        self.assertFalse(r["ok"])
        self.assertIn("extra.py", r["detail"])

    def test_plain_version_assignment_in_other_file(self):
        root = make_repo(self.td.name,
            extra_py={"extra.py": 'version = "9.9.9"\n'},
        )
        r = check_by_name(RV.run_checks(root), "single version source")
        self.assertFalse(r["ok"])

    def test_import_only_is_fine(self):
        root = make_repo(self.td.name,
            extra_py={"cli.py": "from candid import __version__\nprint(__version__)\n"},
        )
        r = check_by_name(RV.run_checks(root), "single version source")
        self.assertTrue(r["ok"])

    def test_kwarg_version_is_fine(self):
        root = make_repo(self.td.name,
            extra_py={"cli.py": 'parser.add_argument("--version", version="1.0")\n'},
        )
        r = check_by_name(RV.run_checks(root), "single version source")
        self.assertTrue(r["ok"])

    def test_no_changelog_skipped(self):
        root = make_repo(self.td.name)
        r = check_by_name(RV.run_checks(root), "changelog matches version")
        self.assertIsNone(r["ok"])
        self.assertIn("no CHANGELOG.md", r["detail"])

    def test_changelog_mismatch(self):
        root = make_repo(self.td.name,
            version="0.2.0",
            changelog="## 0.1.0\n\n- old stuff\n",
        )
        r = check_by_name(RV.run_checks(root), "changelog matches version")
        self.assertFalse(r["ok"])
        self.assertIn("0.1.0", r["detail"])

    def test_changelog_plain_heading_matches(self):
        root = make_repo(self.td.name,
            version="0.2.0",
            changelog="## 0.2.0\n\n- stuff\n",
        )
        r = check_by_name(RV.run_checks(root), "changelog matches version")
        self.assertTrue(r["ok"])

    def test_readme_no_version_skipped(self):
        root = make_repo(self.td.name, readme="# fake\n\nNo versions here.\n")
        r = check_by_name(RV.run_checks(root), "readme version mentions consistent")
        self.assertIsNone(r["ok"])

    def test_readme_mismatch(self):
        root = make_repo(self.td.name, version="0.2.0", readme="Requires 9.9.9 or newer.\n"
        )
        r = check_by_name(RV.run_checks(root), "readme version mentions consistent")
        self.assertFalse(r["ok"])
        self.assertIn("9.9.9", r["detail"])

    def test_readme_match(self):
        root = make_repo(self.td.name, version="0.2.0", readme="Now at v0.2.0.\n"
        )
        r = check_by_name(RV.run_checks(root), "readme version mentions consistent")
        self.assertTrue(r["ok"])

    def test_readme_ip_address_not_a_version(self):
        # 127.0.0.1 must not be treated as a version mention.
        root = make_repo(self.td.name, readme="Serves on 127.0.0.1 only.\n"
        )
        r = check_by_name(RV.run_checks(root), "readme version mentions consistent")
        self.assertIsNone(r["ok"])

    def test_real_repo_checks(self):
        # Read-only: baseline has no CHANGELOG.md and no version strings
        # in README.md, so those two checks skip; the others pass.
        results = RV.run_checks(ROOT)
        self.assertTrue(check_by_name(results, "version parses as semver")["ok"])
        self.assertTrue(check_by_name(results, "single version source")["ok"])
        self.assertIsNone(
            check_by_name(results, "changelog matches version")["ok"]
        )
        self.assertIsNone(
            check_by_name(results, "readme version mentions consistent")["ok"]
        )


class BumpVersionTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)

    def _repo_with_changelog(self, version="0.2.0"):
        return make_repo(self.td.name,
            version=version,
            changelog="# Changelog\n\n## [0.2.0] - 2026-09-01\n\n- old notes\n",
        )

    def test_bump_patch(self):
        root = self._repo_with_changelog("0.2.0")
        old, new = RV.bump_version(root, "patch")
        self.assertEqual((old, new), ("0.2.0", "0.2.1"))
        init_text = (root / "candid" / "__init__.py").read_text()
        self.assertIn('__version__ = "0.2.1"', init_text)
        self.assertNotIn("0.2.0", init_text.split("__version__")[1].split("\n")[0])

    def test_bump_minor(self):
        root = self._repo_with_changelog("0.2.3")
        old, new = RV.bump_version(root, "minor")
        self.assertEqual((old, new), ("0.2.3", "0.3.0"))

    def test_bump_major(self):
        root = self._repo_with_changelog("0.2.3")
        old, new = RV.bump_version(root, "major")
        self.assertEqual((old, new), ("0.2.3", "1.0.0"))

    def test_bump_preserves_rest_of_file(self):
        root = make_repo(self.td.name, version="0.2.0")
        init = root / "candid" / "__init__.py"
        before = init.read_text().splitlines()
        RV.bump_version(root, "patch")
        after = init.read_text().splitlines()
        self.assertEqual(len(before), len(after))
        for b, a in zip(before, after):
            if "__version__" in b:
                self.assertIn("0.2.1", a)
            else:
                self.assertEqual(b, a)

    def test_bump_updates_changelog(self):
        root = self._repo_with_changelog("0.2.0")
        today = date.today().isoformat()
        RV.bump_version(root, "minor")
        text = (root / "CHANGELOG.md").read_text()
        self.assertIn(f"## [0.3.0] - {today}", text)
        # New section goes after the title, before the old entries.
        self.assertLess(
            text.index("## [0.3.0]"), text.index("## [0.2.0]")
        )
        self.assertIn("old notes", text)

    def test_bump_changelog_bullet_placeholder(self):
        root = self._repo_with_changelog("0.2.0")
        RV.bump_version(root, "patch")
        lines = (root / "CHANGELOG.md").read_text().splitlines()
        idx = next(
            i for i, line in enumerate(lines) if line.startswith("## [0.2.1]")
        )
        self.assertEqual(lines[idx + 1], "")
        self.assertEqual(lines[idx + 2], "-")

    def test_bump_without_changelog(self):
        root = make_repo(self.td.name, version="0.2.0")
        old, new = RV.bump_version(root, "patch")
        self.assertEqual((old, new), ("0.2.0", "0.2.1"))
        self.assertFalse((root / "CHANGELOG.md").exists())

    def test_bump_invalid_part(self):
        root = make_repo(self.td.name)
        for bad in ("MINOR", "pre", "", None):
            with self.assertRaises(ValueError, msg=str(bad)):
                RV.bump_version(root, bad)
        # Failed bump leaves the file untouched.
        self.assertIn(
            '__version__ = "0.2.0"',
            (root / "candid" / "__init__.py").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
