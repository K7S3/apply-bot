"""Tests for candid.release_docs: CLI docs, module docstrings, module index.

The AST helpers are tested against small fixture trees built in temp
dirs, so nothing depends on the real repo. A final smoke test runs the
checks against the real repo root to prove they execute without crashing.
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import release_docs as RD  # noqa: E402

MINI_MAIN = textwrap.dedent('''\
    """Mini CLI."""
    def _sub(subparsers, name, help, examples=(), **kwargs):
        return subparsers.add_parser(name, help=help)

    def build(sub):
        s = _sub(sub, "foo", "Foo the bars.", ["python -m mini foo"])
        s = _sub(sub, "bar", "Bar the foos.", ["python -m mini bar"])
        ts = s.add_subparsers()
        t = _sub(ts, "add", "Add one.", ["python -m mini foo add"])
        return sub
    ''')

MINI_INIT = textwrap.dedent('''\
    """mini pkg.

    Modules:
        mod_a    does a things
        mod_b    does b things
    """
    ''')

README_OK = "# mini\n\nUse `foo` then `bar`, or `foo add` to add.\n"
README_MISSING = "# mini\n\nOnly `foo` and `bar` here.\n"


def make_fixture(docstrings=("docstring a", None), readme=README_OK, index=MINI_INIT):
    """Build a mini repo tree: candid/__main__.py, __init__.py, modules, README."""
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    pkg = root / "candid"
    pkg.mkdir()
    (pkg / "__main__.py").write_text(MINI_MAIN)
    (pkg / "__init__.py").write_text(index)
    (root / "README.md").write_text(readme)
    names = ("mod_a", "mod_b")
    for name, doc in zip(names, docstrings):
        body = ('"""%s"""\n' % doc) if doc else ""
        (pkg / (name + ".py")).write_text(body + "X = 1\n")
    return td, root


class CliCommandsTest(unittest.TestCase):
    def test_extracts_command_names(self):
        td, root = make_fixture()
        self.addCleanup(td.cleanup)
        self.assertEqual(RD.cli_commands(root), ["foo", "bar", "add"])

    def test_dedupes_repeated_names(self):
        td, root = make_fixture()
        self.addCleanup(td.cleanup)
        main = root / "candid" / "__main__.py"
        main.write_text(main.read_text() + '\n_sub(None, "foo", "dup")\n')
        self.assertEqual(RD.cli_commands(root), ["foo", "bar", "add"])

    def test_real_repo_has_commands(self):
        commands = RD.cli_commands(ROOT)
        self.assertGreater(len(commands), 10)
        for expected in ("onboard", "match", "tailor", "track", "mock", "salary"):
            self.assertIn(expected, commands)


class CommandsDocumentedTest(unittest.TestCase):
    def test_all_documented(self):
        td, root = make_fixture(readme=README_OK)
        self.addCleanup(td.cleanup)
        result = RD.check_commands_documented(root)
        self.assertTrue(result["ok"])
        self.assertIn("3 commands", result["detail"])

    def test_missing_command_detected(self):
        td, root = make_fixture(readme=README_MISSING)
        self.addCleanup(td.cleanup)
        result = RD.check_commands_documented(root)
        self.assertFalse(result["ok"])
        self.assertIn("add", result["detail"])

    def test_case_insensitive(self):
        td, root = make_fixture(readme="# mini\n\nFOO and BAR and ADD.\n")
        self.addCleanup(td.cleanup)
        result = RD.check_commands_documented(root)
        self.assertTrue(result["ok"])

    def test_missing_readme_skips(self):
        td, root = make_fixture()
        self.addCleanup(td.cleanup)
        (root / "README.md").unlink()
        result = RD.check_commands_documented(root)
        self.assertIsNone(result["ok"])


class ModuleDocstringsTest(unittest.TestCase):
    def test_maps_modules(self):
        td, root = make_fixture(docstrings=("doc a", "doc b"))
        self.addCleanup(td.cleanup)
        docs = RD.module_docstrings(root)
        self.assertEqual(sorted(docs), ["mod_a", "mod_b"])
        self.assertTrue(docs["mod_a"].startswith("doc a"))

    def test_missing_docstring_detected(self):
        td, root = make_fixture(docstrings=("doc a", None))
        self.addCleanup(td.cleanup)
        result = RD.check_modules_documented(root)
        self.assertFalse(result["ok"])
        self.assertIn("mod_b", result["detail"])

    def test_all_documented(self):
        td, root = make_fixture(docstrings=("doc a", "doc b"))
        self.addCleanup(td.cleanup)
        result = RD.check_modules_documented(root)
        self.assertTrue(result["ok"])


class ModuleIndexTest(unittest.TestCase):
    def test_parses_modules_list(self):
        td, root = make_fixture()
        self.addCleanup(td.cleanup)
        self.assertEqual(RD.index_entries(root), ["mod_a", "mod_b"])

    def test_wrapped_description_line_does_not_end_section(self):
        td, root = make_fixture(docstrings=("doc a", "doc b"))
        self.addCleanup(td.cleanup)
        init = root / "candid" / "__init__.py"
        init.write_text(
            '"""mini pkg.\n\nModules:\n'
            "    mod_a    does a things (very long\n"
            "             description wrapped)\n"
            "    mod_b    does b things\n"
            '"""\n'
        )
        self.assertEqual(RD.index_entries(root), ["mod_a", "mod_b"])


        td, root = make_fixture(docstrings=("doc a", "doc b"))
        self.addCleanup(td.cleanup)
        result = RD.check_module_index_current(root)
        self.assertTrue(result["ok"])

    def test_missing_from_index_detected(self):
        td, root = make_fixture(docstrings=("doc a", "doc b"))
        self.addCleanup(td.cleanup)
        init = root / "candid" / "__init__.py"
        init.write_text('"""mini pkg.\n\nModules:\n    mod_a    does a things\n"""\n')
        result = RD.check_module_index_current(root)
        self.assertFalse(result["ok"])
        self.assertIn("mod_b", result["detail"])


class RunChecksTest(unittest.TestCase):
    def test_run_checks_shape(self):
        td, root = make_fixture(docstrings=("doc a", "doc b"))
        self.addCleanup(td.cleanup)
        results = RD.run_checks(root)
        self.assertEqual(len(results), 3)
        names = [r["name"] for r in results]
        self.assertEqual(
            names,
            ["cli commands documented", "modules documented", "module index current"],
        )
        for r in results:
            self.assertIn(r["ok"], (True, False, None))
            self.assertIsInstance(r["detail"], str)
        self.assertTrue(all(r["ok"] for r in results))

    def test_real_repo_smoke(self):
        """The checks must execute against the real repo without crashing."""
        results = RD.run_checks(ROOT)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertIn("name", r)
            self.assertIn("ok", r)
            self.assertIn("detail", r)


if __name__ == "__main__":
    unittest.main()
