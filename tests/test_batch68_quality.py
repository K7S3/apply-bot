"""Tests for candid.outreach_quality (W3): draft scoring + research checklist.

Covers: a strong draft scoring >= 80, a generic spammy draft scoring low
with the right failed checks, LinkedIn over-length failure, placeholder
detection, and checklist update/status roundtrip with isolation.

Run: python3 -m unittest tests.test_batch68_quality -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CANDID_DATA_DIR", str(ROOT / "candid_data"))

from candid import outreach_quality as oq  # noqa: E402

DOSSIER = {
    "id": "hm-7",
    "name": "Priya Natarajan",
    "title": "Director of ML Engineering",
    "company": "Initech",
    "team": "Recommendations",
    "notes": "Gave a RecSys 2024 talk on two-tower retrieval for ranking "
             "infra; team is hiring ranking engineers.",
    "sources": [{"label": "RecSys talk", "url": "https://example.com/recsys"}],
    "interests": ["recommender systems", "mentoring"],
}

STRONG_DRAFT = """Hi Priya,

I watched your RecSys 2024 talk on two-tower retrieval for ranking infra -
the way you framed hard-negative mining for the Recommendations team mapped
exactly onto a problem I hit at Hooli, where I rebuilt our candidate
generation pipeline in PyTorch and cut p99 retrieval latency by 40 percent
while holding recall flat.

I am a machine learning engineer with four years on ranking and retrieval,
and I would love to bring that experience to Initech as you grow the
ranking team. Your notes on mentoring junior engineers also resonated - I
have mentored three interns through their first production launches.

Open to a 15-min chat next week about what you are hiring for?

Best,
Alex"""

SPAMMY_DRAFT = """To whom it may concern,

I am a rockstar engineer and a real game-changer. Your work is SOOO
impressive!!! I would love to pick your brain about SYNERGY opportunities
at your company. Let us circle back and crush it together!

I have amazing skills in many areas. Please let me know a good time.

Best,
A Candidate"""


class ScoreDraftTest(unittest.TestCase):
    def test_strong_draft_scores_high(self):
        result = oq.score_draft(STRONG_DRAFT, dossier=DOSSIER)
        self.assertGreaterEqual(result["score"], 80)
        self.assertEqual(result["grade"], "strong")
        self.assertEqual(len(result["findings"]), 7)
        for finding in result["findings"]:
            self.assertIn("check", finding)
            self.assertIn("passed", finding)
            self.assertIn("detail", finding)
        self.assertTrue(all(f["passed"] for f in result["findings"]))
        self.assertEqual(oq.suggest_fixes(STRONG_DRAFT, dossier=DOSSIER), [])

    def test_spammy_generic_draft_scores_low_with_right_failures(self):
        result = oq.score_draft(SPAMMY_DRAFT, dossier=DOSSIER)
        self.assertLess(result["score"], 50)
        self.assertEqual(result["grade"], "weak")
        failed = {f["check"] for f in result["findings"] if not f["passed"]}
        self.assertIn("names_manager", failed)
        self.assertIn("dossier_specifics", failed)
        self.assertIn("length", failed)
        self.assertIn("clear_cta", failed)
        self.assertIn("no_spammy_phrases", failed)
        self.assertIn("no_generic_flattery", failed)
        fixes = oq.suggest_fixes(SPAMMY_DRAFT, dossier=DOSSIER)
        self.assertTrue(fixes)
        self.assertTrue(all(isinstance(f, str) and "\n" not in f for f in fixes))
        joined = " ".join(fixes).lower()
        self.assertIn("priya", joined)
        self.assertIn("15-min", joined)

    def test_linkedin_over_length_fails(self):
        long_text = "Hi Priya, " + ("I am interested in the ranking role. " * 20)
        self.assertGreater(len(long_text), 300)
        result = oq.score_draft(long_text, dossier=DOSSIER, channel="linkedin")
        length = next(f for f in result["findings"] if f["check"] == "length")
        self.assertFalse(length["passed"])
        self.assertIn("300", length["detail"])

    def test_linkedin_short_ok(self):
        short = "Hi Priya, loved your RecSys talk on ranking infra. Open to a 15-min chat?"
        result = oq.score_draft(short, dossier=DOSSIER, channel="linkedin")
        length = next(f for f in result["findings"] if f["check"] == "length")
        self.assertTrue(length["passed"])

    def test_placeholder_detection(self):
        draft = ("Hi [Name], I would love to join [Company].\n"
                 "TODO: personalize this paragraph. " * 6)
        result = oq.score_draft(draft, dossier=DOSSIER)
        ph = next(f for f in result["findings"] if f["check"] == "no_placeholders")
        self.assertFalse(ph["passed"])
        self.assertIn("[Name]", ph["detail"])
        fixes = oq.suggest_fixes(draft, dossier=DOSSIER)
        self.assertTrue(any("placeholder" in f.lower() for f in fixes))

    def test_no_dossier_skips_dossier_checks_gracefully(self):
        result = oq.score_draft(STRONG_DRAFT)
        skipped = {f["check"]: f for f in result["findings"]}
        self.assertTrue(skipped["names_manager"]["passed"])
        self.assertIn("skipped", skipped["names_manager"]["detail"])
        self.assertTrue(skipped["dossier_specifics"]["passed"])

    def test_dossier_id_string_without_hm_module_falls_back(self):
        # candid.hm does not exist in this tree; a bare id must not raise.
        result = oq.score_draft(STRONG_DRAFT, dossier="hm-7")
        self.assertIn(result["grade"], ("strong", "ok", "weak"))
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_email_word_bounds(self):
        tiny = "Hi."
        result = oq.score_draft(tiny, channel="email")
        length = next(f for f in result["findings"] if f["check"] == "length")
        self.assertFalse(length["passed"])
        huge = "word " * 500
        result = oq.score_draft(huge, channel="email")
        length = next(f for f in result["findings"] if f["check"] == "length")
        self.assertFalse(length["passed"])


class ChecklistTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="candid-quality-")
        self._patcher = mock.patch.object(
            oq, "_research_path",
            return_value=Path(self.tmp.name) / "hm_research.json",
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_template_shape(self):
        items = oq.research_checklist()
        self.assertEqual(len(items), 6)
        keys = {i["key"] for i in items}
        self.assertEqual(
            keys,
            {"recent_posts", "team_page", "publications", "company_news",
             "mutual_connections", "hiring_criteria"},
        )
        for item in items:
            self.assertIn("label", item)
            self.assertIn("hint", item)
            self.assertEqual(item["status"], "todo")

    def test_update_status_roundtrip(self):
        updated = oq.checklist_update("hm-7", "recent_posts", "done",
                                      note="read 3 posts")
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["note"], "read 3 posts")
        self.assertEqual(updated["key"], "recent_posts")

        oq.checklist_update("hm-7", "team_page", "skipped")
        oq.checklist_update("hm-7", "publications", "done")

        status = oq.checklist_status("hm-7")
        self.assertEqual(status["done"], 2)
        self.assertEqual(status["total"], 6)
        by_key = {i["key"]: i for i in status["items"]}
        self.assertEqual(by_key["recent_posts"]["status"], "done")
        self.assertEqual(by_key["recent_posts"]["note"], "read 3 posts")
        self.assertEqual(by_key["team_page"]["status"], "skipped")
        self.assertEqual(by_key["company_news"]["status"], "todo")

        # per-dossier isolation: another ref is untouched
        other = oq.checklist_status("hm-8")
        self.assertEqual(other["done"], 0)

    def test_persistence_file_written(self):
        oq.checklist_update("hm-7", "recent_posts", "done")
        path = Path(self.tmp.name) / "hm_research.json"
        self.assertTrue(path.exists())

    def test_unknown_ref_gives_bare_checklist(self):
        # No candid.hm module here, so the ref cannot resolve: bare, no crash.
        items = oq.research_checklist("hm-7")
        self.assertEqual(len(items), 6)
        self.assertTrue(all(i["status"] == "todo" for i in items))

    def test_invalid_key_and_status_raise(self):
        with self.assertRaises(ValueError):
            oq.checklist_update("hm-7", "not_a_key", "done")
        with self.assertRaises(ValueError):
            oq.checklist_update("hm-7", "recent_posts", "bogus")


if __name__ == "__main__":
    unittest.main()
