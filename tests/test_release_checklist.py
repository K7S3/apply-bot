"""Tests for candid.release_checklist (unittest style; run under pytest)."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Route any data-dir reads at a throwaway dir (belt and braces).
_TMP = tempfile.mkdtemp(prefix="candid_checklist_test_")
os.environ["CANDID_DATA_DIR"] = _TMP

from candid import release_checklist as RC


def _install_fake(module_name, results=None, explode=False):
    """Register a fake candid.<module_name> checker in sys.modules."""
    full = f"candid.{module_name}"
    mod = types.ModuleType(full)
    if explode:
        def run_checks(repo_root):
            raise RuntimeError("boom")
    else:
        def run_checks(repo_root):
            return results
    mod.run_checks = run_checks
    sys.modules[full] = mod
    return full


class AggregateTest(unittest.TestCase):
    def setUp(self):
        self.orig_checks = RC.CHECKS
        self.added = []

    def tearDown(self):
        RC.CHECKS = self.orig_checks
        for full in self.added:
            sys.modules.pop(full, None)

    def _use(self, *modules):
        RC.CHECKS = list(modules)

    def test_aggregation_with_fake_checkers(self):
        self.added.append(_install_fake("release_fake_a", [
            {"name": "a1", "ok": True, "detail": "fine"},
            {"name": "a2", "ok": False, "detail": "broken"},
        ]))
        self.added.append(_install_fake("release_fake_b", [
            {"name": "b1", "ok": None, "detail": "skipped by design"},
        ]))
        self._use("release_fake_a", "release_fake_b")
        res = RC.run_all_checks(ROOT)
        self.assertEqual(res["passed"], 1)
        self.assertEqual(res["failed"], 1)
        self.assertEqual(res["skipped"], 1)
        self.assertFalse(res["ok"])
        names = [r["name"] for r in res["results"]]
        self.assertIn("release_fake_a:a1", names)
        self.assertIn("release_fake_b:b1", names)
        self.assertEqual(res["version"], "0.2.0")
        self.assertIn("T", res["timestamp"])  # ISO-ish

    def test_missing_module_becomes_skipped(self):
        self._use("release_nope_does_not_exist")
        res = RC.run_all_checks(ROOT)
        self.assertEqual(res["skipped"], 1)
        self.assertEqual(res["passed"], 0)
        self.assertEqual(res["failed"], 0)
        self.assertEqual(res["results"][0]["ok"], None)
        self.assertIn("not available", res["results"][0]["detail"])

    def test_raising_module_becomes_skipped(self):
        self.added.append(_install_fake("release_fake_boom", explode=True))
        self._use("release_fake_boom")
        res = RC.run_all_checks(ROOT)
        self.assertEqual(res["skipped"], 1)
        self.assertIn("not available", res["results"][0]["detail"])
        self.assertIn("boom", res["results"][0]["detail"])

    def test_empty_results_becomes_skipped(self):
        self.added.append(_install_fake("release_fake_empty", []))
        self._use("release_fake_empty")
        res = RC.run_all_checks(ROOT)
        self.assertEqual(res["skipped"], 1)

    def test_all_pass_gives_ok(self):
        self.added.append(_install_fake("release_fake_ok", [
            {"name": "x", "ok": True, "detail": "good"},
        ]))
        self._use("release_fake_ok")
        res = RC.run_all_checks(ROOT)
        self.assertTrue(res["ok"])

    def test_all_skipped_still_ok_per_contract(self):
        # Contract: ok = (failed == 0 and at least one check ran).
        # Nothing failed here, so ok is True even with no passes.
        self.added.append(_install_fake("release_fake_skip", [
            {"name": "x", "ok": None, "detail": "n/a"},
        ]))
        self._use("release_fake_skip")
        res = RC.run_all_checks(ROOT)
        self.assertTrue(res["ok"])

    def test_sibling_checkers_do_not_crash_run(self):
        # The real CHECKS list: sibling modules now exist, so this runs the
        # real checkers. It must complete without raising; individual checks
        # may pass, fail, or skip depending on repo state.
        RC.CHECKS = list(RC.CHECKS)
        res = RC.run_all_checks(ROOT)
        self.assertGreaterEqual(len(res["results"]), len(RC.CHECKS))
        for r in res["results"]:
            self.assertIn(r["ok"], (True, False, None))
            self.assertTrue(
                any(r["name"] == m or r["name"].startswith(m + ":")
                    for m in RC.CHECKS),
                r["name"],
            )

    def test_console_format_content(self):
        res = {
            "version": "0.2.0",
            "timestamp": "2026-09-22T20:00:00+00:00",
            "passed": 2,
            "failed": 1,
            "skipped": 1,
            "ok": False,
            "results": [
                {"name": "m:a", "ok": True, "detail": "fine"},
                {"name": "m:b", "ok": False, "detail": "bad"},
                {"name": "m:c", "ok": None, "detail": "n/a"},
            ],
        }
        out = RC.format_console(res)
        self.assertIn("[PASS] m:a", out)
        self.assertIn("[FAIL] m:b", out)
        self.assertIn("[SKIP] m:c", out)
        self.assertIn("2 passed", out)
        self.assertIn("1 failed", out)
        self.assertIn("1 skipped", out)
        self.assertIn("NOT READY", out)
        # plain ASCII only
        out.encode("ascii")

    def test_console_format_ready(self):
        res = {
            "version": "0.2.0",
            "timestamp": "x",
            "passed": 3,
            "failed": 0,
            "skipped": 0,
            "ok": True,
            "results": [],
        }
        out = RC.format_console(res)
        self.assertIn("READY", out)
        self.assertNotIn("NOT READY", out)


if __name__ == "__main__":
    unittest.main()
