"""Tests for candid.variants (resume variant A/B tracking).

Run: cd ~/workspace/candid-batch9 && python3 -m pytest tests/test_variants.py -q

Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_cli_ux.py).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import tracker as TR  # noqa: E402
from candid import variants as V  # noqa: E402


class VariantsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-variants-"))
        self._saved = {}
        for name in ("DATA_DIR", "TRACKER_PATH"):
            self._saved[name] = getattr(C, name)
        C.DATA_DIR = self.tmp
        C.TRACKER_PATH = self.tmp / "tracker.json"
        # two applications + one resume file per app
        self.app1 = TR.add("Acme", "Data Scientist", status="applied")
        self.app2 = TR.add("Beta", "ML Engineer", status="saved")
        self.file1 = self.tmp / "acme-resume.md"
        self.file1.write_text("resume one")
        self.file2 = self.tmp / "beta-resume.md"
        self.file2.write_text("resume two")

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)


class RegisterTest(VariantsBase):
    def test_register_returns_record(self):
        rec = V.register_variant(self.app1["id"], self.file1,
                                 tone="confident", length="one-page",
                                 label="baseline")
        self.assertEqual(rec["variant_id"], "v1")
        self.assertEqual(rec["app_id"], self.app1["id"])
        self.assertEqual(rec["file"], str(self.file1))
        self.assertEqual(rec["tone"], "confident")
        self.assertEqual(rec["length"], "one-page")
        self.assertEqual(rec["label"], "baseline")
        self.assertTrue(rec["created"])  # today iso

    def test_variant_ids_increment_per_app(self):
        V.register_variant(self.app1["id"], self.file1)
        V.register_variant(self.app1["id"], self.file1)
        rec = V.register_variant(self.app1["id"], self.file1)
        self.assertEqual(rec["variant_id"], "v3")

    def test_variant_ids_scoped_per_app(self):
        V.register_variant(self.app1["id"], self.file1)
        rec = V.register_variant(self.app2["id"], self.file2)
        self.assertEqual(rec["variant_id"], "v1")  # fresh sequence for app2

    def test_register_persists_json(self):
        V.register_variant(self.app1["id"], self.file1)
        data = json.loads((C.DATA_DIR / "resume_variants.json").read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["variant_id"], "v1")

    def test_register_unknown_app_raises(self):
        with self.assertRaises(V.VariantsError) as ctx:
            V.register_variant(999, self.file1)
        self.assertIn("python -m candid track list", str(ctx.exception))

    def test_register_missing_file_raises(self):
        with self.assertRaises(V.VariantsError) as ctx:
            V.register_variant(self.app1["id"], self.tmp / "nope.md")
        msg = str(ctx.exception)
        self.assertIn("File not found", msg)
        self.assertTrue(msg.endswith("python -m candid tailor resume --jd jd.txt --company \"Acme\" --role \"Data Scientist\""))


class LinkTest(VariantsBase):
    def test_link_repoints_variant(self):
        rec = V.register_variant(self.app1["id"], self.file1)
        out = V.link_variant(rec["variant_id"], self.app2["id"])
        self.assertEqual(out["app_id"], self.app2["id"])
        self.assertEqual(out["variant_id"], "v1")  # id preserved
        self.assertEqual(V.list_variants(app_id=self.app2["id"])[0]["file"],
                         str(self.file1))

    def test_link_unknown_variant_raises(self):
        with self.assertRaises(V.VariantsError) as ctx:
            V.link_variant("v9", self.app2["id"])
        self.assertIn("python -m candid variants list", str(ctx.exception))

    def test_link_unknown_app_raises(self):
        rec = V.register_variant(self.app1["id"], self.file1)
        with self.assertRaises(V.VariantsError) as ctx:
            V.link_variant(rec["variant_id"], 999)
        self.assertIn("python -m candid track list", str(ctx.exception))

    def test_link_ambiguous_variant_id_raises(self):
        V.register_variant(self.app1["id"], self.file1)  # v1 for app1
        V.register_variant(self.app2["id"], self.file2)  # v1 for app2
        with self.assertRaises(V.VariantsError) as ctx:
            V.link_variant("v1", self.app2["id"])
        self.assertIn("multiple applications", str(ctx.exception))


class ListTest(VariantsBase):
    def test_list_all_and_by_app(self):
        V.register_variant(self.app1["id"], self.file1)
        V.register_variant(self.app2["id"], self.file2)
        self.assertEqual(len(V.list_variants()), 2)
        only = V.list_variants(app_id=self.app1["id"])
        self.assertEqual(len(only), 1)
        self.assertEqual(only[0]["app_id"], self.app1["id"])

    def test_list_empty_registry(self):
        self.assertEqual(V.list_variants(), [])

    def test_explicit_path_arg(self):
        p = self.tmp / "other" / "variants.json"
        V.register_variant(self.app1["id"], self.file1, path=p)
        self.assertTrue(p.exists())
        self.assertEqual(len(V.list_variants(path=p)), 1)
        self.assertEqual(V.list_variants(), [])  # default registry untouched
        self.assertEqual(V.list_variants(app_id=self.app2["id"], path=p), [])


class StatsTest(VariantsBase):
    def test_response_detection_via_status_change(self):
        V.register_variant(self.app1["id"], self.file1, tone="confident")
        stats = V.variant_stats()
        self.assertFalse(stats["variants"][0]["responded"])
        TR.update(self.app1["id"], status="selected_for_interview")
        stats = V.variant_stats()
        row = stats["variants"][0]
        self.assertTrue(row["responded"])
        self.assertTrue(row["interview"])
        self.assertEqual(row["status"], "selected_for_interview")
        self.assertEqual(row["company"], "Acme")
        self.assertEqual(row["role"], "Data Scientist")

    def test_summary_math(self):
        V.register_variant(self.app1["id"], self.file1, tone="confident", length="one-page")
        V.register_variant(self.app2["id"], self.file2, tone="confident", length="detailed")
        TR.update(self.app1["id"], status="rejected")  # response
        stats = V.variant_stats()
        by_tone = stats["summary"]["by_tone"]["confident"]
        self.assertEqual(by_tone["variants"], 2)
        self.assertEqual(by_tone["responses"], 1)
        self.assertEqual(by_tone["response_rate"], 0.5)
        by_len = stats["summary"]["by_length"]
        self.assertEqual(by_len["one-page"]["responses"], 1)
        self.assertEqual(by_len["detailed"]["responses"], 0)
        self.assertEqual(by_len["detailed"]["response_rate"], 0.0)

    def test_unspecified_tone_bucket(self):
        V.register_variant(self.app1["id"], self.file1)  # no tone
        stats = V.variant_stats()
        self.assertIn("unspecified", stats["summary"]["by_tone"])

    def test_deleted_app_graceful(self):
        rec = V.register_variant(self.app1["id"], self.file1)
        TR.remove(self.app1["id"])
        stats = V.variant_stats()
        self.assertEqual(len(stats["variants"]), 1)
        row = stats["variants"][0]
        self.assertEqual(row["status"], "removed")
        self.assertEqual(row["company"], "")
        self.assertEqual(row["role"], "")
        self.assertFalse(row["responded"])
        self.assertFalse(row["interview"])
        self.assertEqual(rec["variant_id"], row["variant_id"])

    def test_stats_empty(self):
        stats = V.variant_stats()
        self.assertEqual(stats["variants"], [])
        self.assertEqual(stats["summary"], {"by_tone": {}, "by_length": {}})


if __name__ == "__main__":
    unittest.main()
