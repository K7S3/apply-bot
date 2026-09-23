"""Tests for candid.search: full-text search across tracker, prep packs,
tailored files, and debriefs.

Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_cli_ux.py).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import search as S  # noqa: E402


class SearchBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-search-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.DATA_DIR = self.tmp

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def write_tracker(self, apps):
        C.TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        C.TRACKER_PATH.write_text(json.dumps(apps), encoding="utf-8")

    def write_prep(self, name, text):
        C.PREP_PACKS_DIR.mkdir(parents=True, exist_ok=True)
        (C.PREP_PACKS_DIR / name).write_text(text, encoding="utf-8")

    def write_tailored(self, name, text):
        C.TAILOR_DIR.mkdir(parents=True, exist_ok=True)
        (C.TAILOR_DIR / name).write_text(text, encoding="utf-8")

    def write_debrief(self, name, text):
        d = self.tmp / "debriefs"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")


class SearchSemanticsTest(SearchBase):
    def test_and_semantics(self):
        self.write_tracker([
            {"id": 1, "company": "Acme", "role": "ML Engineer",
             "notes": "python role with great team", "status": "applied"},
            {"id": 2, "company": "Beta", "role": "Data Analyst",
             "notes": "python dashboards", "status": "saved"},
        ])
        hits = S.search_all("python ml")
        self.assertEqual([h["ref"] for h in hits], ["1"])

    def test_phrase_search(self):
        self.write_tracker([
            {"id": 1, "company": "Acme", "role": "ML Engineer",
             "notes": "deep experience in machine learning systems",
             "status": "applied"},
            {"id": 2, "company": "Beta", "role": "SRE",
             "notes": "operates the machine that runs the learning pipeline",
             "status": "saved"},
        ])
        hits = S.search_all('"machine learning"')
        self.assertEqual([h["ref"] for h in hits], ["1"])

    def test_case_insensitivity(self):
        self.write_tracker([
            {"id": 1, "company": "Acme", "role": "ML Engineer",
             "notes": "Python and pytorch required", "status": "applied"},
        ])
        hits = S.search_all("PYTHON PYTORCH")
        self.assertEqual(len(hits), 1)

    def test_ranking_title_beats_body(self):
        self.write_tracker([
            {"id": 1, "company": "Acme", "role": "Data Analyst",
             "notes": "ml " * 50, "status": "applied"},
            {"id": 2, "company": "ML Corp", "role": "Backend Engineer",
             "notes": "nothing relevant", "status": "saved"},
        ])
        hits = S.search_all("ml")
        self.assertEqual(len(hits), 2)
        # Title match (ref 2) outranks 50 body mentions (ref 1).
        self.assertEqual(hits[0]["ref"], "2")
        self.assertEqual(hits[1]["ref"], "1")

    def test_snippet_ellision(self):
        filler = "x" * 200
        self.write_tracker([
            {"id": 1, "company": "Acme", "role": "ML Engineer",
             "notes": f"{filler} the keyword zebrafish appears here {filler}",
             "status": "applied"},
        ])
        hits = S.search_all("zebrafish")
        self.assertEqual(len(hits), 1)
        snippet = hits[0]["snippet"]
        self.assertTrue(snippet.startswith("..."), snippet[:20])
        self.assertTrue(snippet.endswith("..."), snippet[-20:])
        self.assertLessEqual(len(snippet), 170)
        self.assertIn("zebrafish", snippet)

    def test_empty_query_returns_nothing(self):
        self.write_tracker([
            {"id": 1, "company": "Acme", "role": "ML Engineer",
             "notes": "python", "status": "applied"},
        ])
        self.assertEqual(S.search_all(""), [])
        self.assertEqual(S.search_all("   "), [])


class SearchKindsTest(SearchBase):
    def test_all_four_kinds(self):
        self.write_tracker([
            {"id": 1, "company": "Acme", "role": "ML Engineer",
             "notes": "applied via referral", "status": "applied"},
        ])
        self.write_prep("acme_ml_engineer.md",
                        "# Acme ML Engineer prep\n\nRounds: coding, system design.")
        self.write_tailored("acme_resume.md",
                            "Resume for Acme: built ML systems at scale.")
        self.write_debrief("acme_round1.md",
                           "# Acme round 1 debrief\n\nBehavioral: tell me about Acme.")

        hits = S.search_all("acme")
        kinds = {h["kind"] for h in hits}
        self.assertEqual(kinds, {"application", "prep_pack", "tailored", "debrief"})
        by_kind = {h["kind"]: h for h in hits}
        self.assertEqual(by_kind["application"]["ref"], "1")
        self.assertEqual(by_kind["prep_pack"]["ref"], "acme_ml_engineer.md")
        self.assertEqual(by_kind["prep_pack"]["title"], "Acme ML Engineer prep")
        self.assertEqual(by_kind["tailored"]["ref"], "acme_resume.md")
        self.assertEqual(by_kind["debrief"]["ref"], "acme_round1.md")

    def test_jd_text_searched(self):
        self.write_tracker([
            {"id": 1, "company": "Acme", "role": "ML Engineer",
             "notes": "", "jd_text": "Requires 5 years of kubernetes ops",
             "status": "applied"},
        ])
        hits = S.search_all("kubernetes")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["ref"], "1")


class SearchRobustnessTest(SearchBase):
    def test_missing_dirs_return_nothing(self):
        # None of the data dirs exist in this fresh temp dir.
        self.assertEqual(S.search_all("python"), [])

    def test_missing_tracker_but_prep_exists(self):
        self.write_prep("pack.md", "# Pack\n\nPython interview questions.")
        hits = S.search_all("python")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["kind"], "prep_pack")

    def test_debriefs_dir_missing_is_skipped(self):
        self.write_tracker([
            {"id": 1, "company": "Acme", "role": "ML Engineer",
             "notes": "python", "status": "applied"},
        ])
        hits = S.search_all("python",
                            debriefs_dir=self.tmp / "no_such_dir")
        self.assertEqual([h["ref"] for h in hits], ["1"])

    def test_unreadable_files_skipped(self):
        C.PREP_PACKS_DIR.mkdir(parents=True, exist_ok=True)
        bad = C.PREP_PACKS_DIR / "bad.md"
        bad.write_bytes(b"\xff\xfe binary \x00\x01")
        self.write_prep("good.md", "# Good\n\nPython notes.")
        hits = S.search_all("python")
        self.assertEqual([h["ref"] for h in hits], ["good.md"])

    def test_render_results(self):
        self.write_tracker([
            {"id": 1, "company": "Acme", "role": "ML Engineer",
             "notes": "python role", "status": "applied"},
        ])
        hits = S.search_all("python")
        out = S.render_results(hits)
        self.assertIn("[application]", out)
        self.assertIn("ML Engineer @ Acme", out)
        self.assertIn("python role", out)
        self.assertEqual(S.render_results([]), "No matches found.")
        # limit respected
        long_out = S.render_results(hits, limit=0)
        self.assertIn("and 1 more", long_out)


if __name__ == "__main__":
    unittest.main()
