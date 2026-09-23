"""Tests for candid/hm.py (hiring-manager dossier store).

Sample people/companies are clearly fictional ("Alex Rivera" /
"Meridian Financial" per repo convention).

Run: python3 -m unittest tests.test_batch68_hm -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import hm  # noqa: E402


class HmTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_env = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = self.tmp.name
        self.addCleanup(self._restore)

    def _restore(self):
        if self._old_env is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = self._old_env
        self.tmp.cleanup()

    def _dossier(self, **kw):
        base = dict(
            name="Alex Rivera",
            title="VP Engineering",
            company="Meridian Financial",
            team="Core Payments",
            notes="Built the real-time fraud pipeline with machine learning. Likes whiteboard system design.",
            sources=["LinkedIn"],
            interests=["trail running", "espresso"],
            contact_hint="via recruiter Priya",
        )
        base.update(kw)
        return hm.add_dossier(**base)

    # --- add / list / get -----------------------------------------------------

    def test_add_list_get_roundtrip(self):
        rec = self._dossier()
        self.assertEqual(len(rec["id"]), 8)
        self.assertEqual(rec["name"], "Alex Rivera")
        self.assertEqual(rec["sources"], ["LinkedIn"])
        self.assertEqual(rec["interests"], ["trail running", "espresso"])
        self.assertEqual([d["name"] for d in hm.list_dossiers()], ["Alex Rivera"])
        got = hm.get_dossier(rec["id"])
        self.assertEqual(got["name"], "Alex Rivera")
        self.assertEqual(got["company"], "Meridian Financial")

    def test_get_by_name_substring_case_insensitive(self):
        rec = self._dossier()
        self.assertEqual(hm.get_dossier("alex")["id"], rec["id"])
        self.assertEqual(hm.get_dossier("RIVERA")["id"], rec["id"])

    def test_add_requires_name(self):
        with self.assertRaises(hm.HmError):
            hm.add_dossier("")
        with self.assertRaises(hm.HmError):
            hm.add_dossier("   ")
        with self.assertRaises(hm.HmError):
            hm.add_dossier(name=None)  # type: ignore[arg-type]

    def test_get_missing_raises(self):
        with self.assertRaises(hm.HmError):
            hm.get_dossier("no such person")

    def test_get_ambiguous_lists_matches(self):
        a = self._dossier(name="Sam Torres")
        b = self._dossier(name="Sammy Torres")
        with self.assertRaises(hm.HmError) as ctx:
            hm.get_dossier("sam")
        msg = str(ctx.exception)
        self.assertIn(a["name"], msg)
        self.assertIn(b["name"], msg)
        self.assertIn(a["id"], msg)
        # ids still resolve unambiguously
        self.assertEqual(hm.get_dossier(a["id"])["name"], "Sam Torres")
        self.assertEqual(hm.get_dossier(b["id"])["name"], "Sammy Torres")

    # --- update / delete ------------------------------------------------------

    def test_update_roundtrip(self):
        rec = self._dossier()
        updated = hm.update_dossier(rec["id"], title="SVP Engineering",
                                    interests=["trail running"])
        self.assertEqual(updated["title"], "SVP Engineering")
        self.assertEqual(updated["interests"], ["trail running"])
        self.assertEqual(hm.get_dossier(rec["id"])["title"], "SVP Engineering")
        self.assertEqual(updated["id"], rec["id"])  # id is immutable

    def test_update_rejects_unknown_fields(self):
        rec = self._dossier()
        with self.assertRaises(hm.HmError):
            hm.update_dossier(rec["id"], favorite_color="blue")
        with self.assertRaises(hm.HmError):
            hm.update_dossier(rec["id"], id="nope")

    def test_delete_roundtrip(self):
        rec = self._dossier()
        self.assertTrue(hm.delete_dossier(rec["id"]))
        self.assertEqual(hm.list_dossiers(), [])
        with self.assertRaises(hm.HmError):
            hm.get_dossier(rec["id"])

    def test_atomic_write_creates_parent_dirs_and_json_list(self):
        import json
        target = Path(self.tmp.name) / "deep" / "nested"
        old = os.environ["CANDID_DATA_DIR"]
        os.environ["CANDID_DATA_DIR"] = str(target)
        try:
            hm.add_dossier(name="Alex Rivera")
            p = target / "hm_dossiers.json"
            self.assertTrue(p.exists())
            self.assertIsInstance(json.loads(p.read_text(encoding="utf-8")), list)
            # no stray tmp files left behind
            self.assertFalse(list(target.glob("*.tmp")))
        finally:
            os.environ["CANDID_DATA_DIR"] = old

    # --- brief groundedness ---------------------------------------------------

    def test_brief_grounded_only(self):
        rec = self._dossier()
        brief = hm.manager_brief(
            rec["id"],
            jd_text="We need strong machine learning and python skills for fraud detection.")
        self.assertEqual(set(brief), {"summary", "talking_points", "openers",
                                      "questions_to_ask"})
        # grounded content shows up
        self.assertIn("Meridian Financial", brief["summary"])
        all_text = (brief["summary"] + "\n"
                    + "\n".join(brief["talking_points"]) + "\n"
                    + "\n".join(brief["openers"]) + "\n"
                    + "\n".join(brief["questions_to_ask"]))
        for grounded in ["fraud pipeline", "trail running", "LinkedIn",
                         "Core Payments", "Alex"]:
            self.assertIn(grounded, all_text, f"expected grounded token: {grounded}")
        # JD overlap keyword that also appears in notes is reported, and is factual
        overlap = [t for t in brief["talking_points"] if "JD overlap" in t]
        self.assertTrue(any("machine learning" in t for t in overlap),
                        f"expected ML overlap in {overlap}")
        # nothing invented: no facts not traceable to the dossier
        for invented in ["recently promoted", "Series C", "Stanford", "Google",
                         "ex-Meta", "10 years"]:
            self.assertNotIn(invented, all_text)
        # speculative items are explicitly marked
        for item in brief["talking_points"] + brief["openers"]:
            low = item.lower()
            if any(w in low for w in ["re-check", "tailor an opener"]):
                self.assertTrue(item.startswith("verify:"), item)
        # structural counts
        self.assertGreaterEqual(len(brief["talking_points"]), 3)
        self.assertGreaterEqual(len(brief["openers"]), 2)
        self.assertLessEqual(len(brief["openers"]), 3)
        self.assertGreaterEqual(len(brief["questions_to_ask"]), 2)
        self.assertLessEqual(len(brief["questions_to_ask"]), 3)

    def test_brief_sparse_dossier_stays_grounded(self):
        rec = hm.add_dossier(name="Alex Rivera")
        brief = hm.manager_brief(rec["id"])
        self.assertIn("Alex Rivera", brief["summary"])
        self.assertGreaterEqual(len(brief["openers"]), 2)
        self.assertGreaterEqual(len(brief["questions_to_ask"]), 1)
        all_text = "\n".join(brief["openers"] + brief["questions_to_ask"])
        for invented in ["Meridian", "VP", "LinkedIn", "promotion", "team"]:
            self.assertNotIn(invented, all_text)

    def test_brief_missing_dossier_raises(self):
        with self.assertRaises(hm.HmError):
            hm.manager_brief("ghost")


if __name__ == "__main__":
    unittest.main()
