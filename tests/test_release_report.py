"""Tests for candid.release_report (unittest style; run under pytest)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import release_report as RR


def sample_results():
    return {
        "version": "0.2.0",
        "timestamp": "2026-09-22T20:00:00+00:00",
        "passed": 2,
        "failed": 1,
        "skipped": 1,
        "ok": False,
        "results": [
            {"name": "release_tests:unit", "ok": True, "detail": "120 passed"},
            {"name": "release_docs:readme", "ok": False, "detail": "missing section"},
            {"name": "release_secrets:scan", "ok": None, "detail": "not available"},
        ],
    }


class RenderTest(unittest.TestCase):
    def test_render_markdown_structure(self):
        md = RR.render_markdown(sample_results())
        self.assertIn("# Release Readiness Report - v0.2.0", md)
        self.assertIn("2026-09-22T20:00:00+00:00", md)
        self.assertIn("| Passed | 2 |", md)
        self.assertIn("| Failed | 1 |", md)
        self.assertIn("| Skipped | 1 |", md)
        self.assertIn("| Verdict | NOT READY |", md)
        self.assertIn("### [PASS] release_tests:unit", md)
        self.assertIn("### [FAIL] release_docs:readme", md)
        self.assertIn("### [SKIP] release_secrets:scan", md)

    def test_render_markdown_empty_results(self):
        res = sample_results()
        res["results"] = []
        md = RR.render_markdown(res)
        self.assertIn("No checks ran.", md)

    def test_render_json_roundtrip(self):
        res = sample_results()
        back = json.loads(RR.render_json(res))
        self.assertEqual(back, res)


class WritePruneTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp(prefix="candid_report_test_")
        os.environ["CANDID_DATA_DIR"] = self.td

    def test_write_markdown_default_dir(self):
        path = RR.write_report(sample_results(), fmt="markdown")
        self.assertTrue(path.exists())
        self.assertTrue(str(path).startswith(str(Path(self.td) / "release_reports")))
        self.assertTrue(path.name.startswith("release-0.2.0-"))
        self.assertTrue(path.name.endswith(".md"))
        text = path.read_text()
        self.assertIn("Release Readiness Report", text)
        self.assertIn("120 passed", text)

    def test_write_json(self):
        path = RR.write_report(sample_results(), fmt="json")
        self.assertTrue(path.name.endswith(".json"))
        back = json.loads(path.read_text())
        self.assertEqual(back["version"], "0.2.0")
        self.assertEqual(len(back["results"]), 3)

    def test_write_explicit_out_dir(self):
        out = Path(self.td) / "custom"
        path = RR.write_report(sample_results(), out_dir=out)
        self.assertEqual(path.parent, out)
        self.assertTrue(path.exists())

    def test_prune_keeps_newest_ten(self):
        out = Path(self.td) / "reports"
        out.mkdir(parents=True)
        for i in range(12):
            (out / f"release-0.2.0-2026-09-22-20-00-{i:02d}.md").write_text("x")
        (out / "unrelated.txt").write_text("keep me")
        deleted = RR.prune_reports(out, keep=10)
        remaining = sorted(p.name for p in out.glob("release-*"))
        self.assertEqual(len(remaining), 10)
        self.assertEqual(len(deleted), 2)
        # newest kept (indices 02..11), oldest deleted (00, 01)
        self.assertIn("release-0.2.0-2026-09-22-20-00-11.md", remaining)
        self.assertNotIn("release-0.2.0-2026-09-22-20-00-00.md", remaining)
        self.assertTrue((out / "unrelated.txt").exists())

    def test_prune_fewer_than_keep_deletes_nothing(self):
        out = Path(self.td) / "few"
        out.mkdir(parents=True)
        for i in range(3):
            (out / f"release-0.2.0-x-{i}.md").write_text("x")
        deleted = RR.prune_reports(out, keep=10)
        self.assertEqual(deleted, [])
        self.assertEqual(len(list(out.glob("release-*"))), 3)


if __name__ == "__main__":
    unittest.main()
