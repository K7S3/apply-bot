"""Tests for candid.release_tests: pytest gate + coverage gate.

The summary and coverage parsers are tested against synthetic output so
no real pytest run is needed. One small real subprocess run against a
tiny temp tests dir proves the subprocess path works end to end.
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import release_tests as RT  # noqa: E402


class ParseSummaryTest(unittest.TestCase):
    def test_all_passed(self):
        out = "tests/test_a.py ..                                        [100%]\n3 passed in 0.05s"
        self.assertEqual(RT.parse_summary(out), {"passed": 3, "failed": 0, "errors": 0})

    def test_mixed_counts(self):
        out = "F..\n2 passed, 1 failed in 0.10s"
        self.assertEqual(RT.parse_summary(out), {"passed": 2, "failed": 1, "errors": 0})

    def test_errors_count(self):
        out = "E.\n1 failed, 2 passed, 3 errors in 0.20s"
        self.assertEqual(RT.parse_summary(out), {"passed": 2, "failed": 1, "errors": 3})

    def test_no_summary_line(self):
        self.assertEqual(
            RT.parse_summary("collected 0 items / 1 deselected in 0.01s"),
            {"passed": 0, "failed": 0, "errors": 0},
        )

    def test_last_summary_wins(self):
        out = "1 failed, 4 passed in 0.10s\n5 passed in 0.02s"
        self.assertEqual(RT.parse_summary(out), {"passed": 5, "failed": 0, "errors": 0})


class ParseCoverageTest(unittest.TestCase):
    def test_total_line(self):
        out = textwrap.dedent("""\
            Name               Stmts   Miss  Cover
            -------------------------------------
            candid/a.py           10      2    80%
            TOTAL                 10      2    80%
            """)
        self.assertEqual(RT.parse_total_coverage(out), 80.0)

    def test_fractional_total(self):
        out = "TOTAL                 123     45   63.41%"
        self.assertAlmostEqual(RT.parse_total_coverage(out), 63.41)

    def test_no_total_line(self):
        self.assertIsNone(RT.parse_total_coverage("no coverage data collected"))


class CoverageGateTest(unittest.TestCase):
    def test_skipped_when_pytest_cov_missing(self):
        with mock.patch("importlib.util.find_spec", return_value=None):
            result = RT.coverage_gate(ROOT)
        self.assertIsNone(result["ok"])
        self.assertEqual(result["detail"], "pytest-cov not installed, coverage skipped")

    def test_real_env_without_pytest_cov(self):
        # Documents current environment behavior; still deterministic.
        result = RT.coverage_gate(ROOT)
        self.assertIn("ok", result)
        self.assertIn("detail", result)


class RunPytestTest(unittest.TestCase):
    def _make_repo(self, test_body):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "tests").mkdir()
        (root / "tests" / "test_fast.py").write_text(test_body)
        self.addCleanup(td.cleanup)
        return root

    def test_real_green_run(self):
        root = self._make_repo(
            textwrap.dedent("""\
                def test_one():
                    assert 1 + 1 == 2

                def test_two():
                    assert "a".upper() == "A"
                """)
        )
        result = RT.run_pytest(root, timeout=120)
        self.assertTrue(result["ok"], msg=result.get("tail", ""))
        self.assertGreaterEqual(result["passed"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertIsInstance(result["seconds"], float)
        self.assertTrue(result["tail"])

    def test_real_failing_run(self):
        root = self._make_repo("def test_bad():\n    assert False\n")
        result = RT.run_pytest(root, timeout=120)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], 1)

    def test_timeout(self):
        root = self._make_repo(
            "import time\ndef test_slow():\n    time.sleep(30)\n"
        )
        result = RT.run_pytest(root, timeout=3, extra_args=("-x",))
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["detail"])

    def test_extra_args_passed_through(self):
        root = self._make_repo(
            "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n"
        )
        result = RT.run_pytest(root, timeout=120, extra_args=("-k", "test_a"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["passed"], 1)


class RunChecksTest(unittest.TestCase):
    def test_run_checks_shape(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        (root / "tests").mkdir()
        (root / "tests" / "test_fast.py").write_text("def test_ok():\n    assert True\n")
        self.addCleanup(td.cleanup)
        results = RT.run_checks(root)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIn("name", r)
            self.assertIn("ok", r)
            self.assertIn("detail", r)
        self.assertEqual(results[0]["name"], "test suite green")
        self.assertTrue(results[0]["ok"])
        self.assertIn("passed", results[0]["detail"])


if __name__ == "__main__":
    unittest.main()
