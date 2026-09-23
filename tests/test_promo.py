"""Tests for candid.promo: evidence bank, coverage, checklist, gaps,
timeline, rubric, and packet building.

Run: CANDID_DATA_DIR=/tmp/candid-test-promo python3 -m unittest tests.test_promo -v
"""
import os

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-promo"

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import promo as P


def _mini_profile(**kw):
    prof = {
        "name": "Test User",
        "years_experience": 6.0,
        "experience": [
            {"title": "Software Engineer", "company": "Initech",
             "bullets": [
                 "Led migration of the ads ranking pipeline across two teams, cutting p99 latency 20%",
                 "Set the team's technical direction for streaming infra and mentored 3 engineers",
             ]},
        ],
    }
    prof.update(kw)
    return prof


class EvidenceBankTest(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp/candid-test-promo-ev.json")
        if self.path.exists():
            self.path.unlink()

    def test_add_and_list(self):
        rec = P.add_evidence("Shipped X", company="meta", criterion="impact",
                             path=self.path)
        self.assertEqual(rec["id"], 1)
        items = P.list_evidence(path=self.path)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "Shipped X")

    def test_add_requires_text(self):
        with self.assertRaises(P.PromoError):
            P.add_evidence("   ", path=self.path)

    def test_ids_increment(self):
        P.add_evidence("one", path=self.path)
        rec = P.add_evidence("two", path=self.path)
        self.assertEqual(rec["id"], 2)

    def test_list_filter_company(self):
        P.add_evidence("one", company="meta", path=self.path)
        P.add_evidence("two", company="google", path=self.path)
        self.assertEqual(len(P.list_evidence(company="meta", path=self.path)), 1)
        self.assertEqual(len(P.list_evidence(path=self.path)), 2)

    def test_remove(self):
        P.add_evidence("one", path=self.path)
        removed = P.remove_evidence(1, path=self.path)
        self.assertEqual(removed["id"], 1)
        self.assertEqual(P.list_evidence(path=self.path), [])

    def test_remove_missing_raises(self):
        with self.assertRaises(P.PromoError):
            P.remove_evidence(99, path=self.path)

    def test_bad_json_raises(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(P.PromoError):
            P._load_evidence(self.path)


class KeywordsTest(unittest.TestCase):
    def test_stopwords_dropped(self):
        kw = P.criterion_keywords("Impact at team-plus scope")
        self.assertIn("impact", kw)
        self.assertIn("team-plus", kw)
        self.assertNotIn("at", kw)

    def test_tag(self):
        tag = P.criterion_tag("Technical leadership: others follow your designs")
        self.assertEqual(tag, "technical-leadership-others-follow")


class CoverageTest(unittest.TestCase):
    def test_evidence_hit_scores_one(self):
        prof = _mini_profile()
        ev = [{"id": 1, "text": "Led the ads ranking migration with impact across two teams",
               "criterion": "", "company": "", "date": ""}]
        cov = P.coverage(prof, ["Impact at team-plus scope: outcomes felt outside own team"], ev)
        self.assertEqual(cov[0]["score"], 1.0)
        self.assertEqual(len(cov[0]["evidence_hits"]), 1)

    def test_bullet_hit_scores_partial(self):
        prof = _mini_profile()
        cov = P.coverage(prof, ["Technical leadership and mentoring engineers"], [])
        self.assertEqual(cov[0]["score"], 0.6)
        self.assertTrue(cov[0]["bullet_hits"])

    def test_no_match_scores_zero(self):
        prof = _mini_profile()
        cov = P.coverage(prof, ["Quantum cryptography research publications"], [])
        self.assertEqual(cov[0]["score"], 0.0)

    def test_none_profile_ok(self):
        cov = P.coverage(None, ["Impact at team-plus scope"], [])
        self.assertEqual(cov[0]["score"], 0.0)


class ChecklistTest(unittest.TestCase):
    def test_verdict_ready(self):
        from candid import leveling as L
        tgt = L.normalize_level("startup", "IC2")
        criteria = tgt["promo_criteria"]
        ev = [{"id": i + 1, "text": c, "criterion": "", "company": "", "date": ""}
              for i, c in enumerate(criteria)]
        prof = _mini_profile(years_experience=3.0)
        res = P.checklist(prof, "startup", "IC1", "IC2", evidence=ev)
        self.assertEqual(res["verdict"], "ready")
        self.assertTrue(all(i["status"] == "done" for i in res["items"]))

    def test_verdict_building_when_gaps(self):
        prof = _mini_profile(years_experience=1.0)
        res = P.checklist(prof, "meta", "E3", "E5", evidence=[])
        self.assertEqual(res["verdict"], "building")
        self.assertTrue(any(i["status"] == "todo" for i in res["items"]))

    def test_experience_partial_band(self):
        prof = _mini_profile(years_experience=4.0)  # E5 wants ~5+
        res = P.checklist(prof, "meta", "E4", "E5", evidence=[])
        exp = next(i for i in res["items"] if i["item"].startswith("Experience"))
        self.assertEqual(exp["status"], "partial")

    def test_render(self):
        prof = _mini_profile()
        out = P.render_checklist(P.checklist(prof, "meta", "E4", "E5", evidence=[]))
        self.assertIn("E4 -> E5", out)
        self.assertIn("Verdict", out)


class GapsTest(unittest.TestCase):
    def test_gaps_have_suggestions(self):
        res = P.gaps(_mini_profile(), "meta", "E5", evidence=[])
        self.assertTrue(res["gaps"])
        for g in res["gaps"]:
            self.assertIn("promo evidence add", g["suggestion"])
            self.assertTrue(g["tag"])

    def test_no_gaps_when_covered(self):
        from candid import leveling as L
        criteria = L.normalize_level("meta", "E5")["promo_criteria"]
        ev = [{"id": i + 1, "text": c, "criterion": "", "company": "", "date": ""}
              for i, c in enumerate(criteria)]
        res = P.gaps(_mini_profile(), "meta", "E5", evidence=ev)
        self.assertEqual(res["gaps"], [])
        self.assertEqual(res["covered"], res["total"])

    def test_render_no_gaps(self):
        res = {"company": "Meta", "target": "E5", "gaps": [], "covered": 5, "total": 5}
        self.assertIn("No gaps", P.render_gaps(res))


class TimelineTest(unittest.TestCase):
    def test_returns_range(self):
        res = P.timeline(_mini_profile(), "meta", "E5", current="E4",
                         months_at_level=20, evidence=[])
        self.assertLessEqual(res["low_months"], res["high_months"])
        self.assertGreater(res["low_months"], 0)

    def test_strong_coverage_shortens(self):
        from candid import leveling as L
        criteria = L.normalize_level("meta", "E5")["promo_criteria"]
        ev = [{"id": i + 1, "text": c, "criterion": "", "company": "", "date": ""}
              for i, c in enumerate(criteria)]
        weak = P.timeline(_mini_profile(), "meta", "E5", current="E4", evidence=[])
        strong = P.timeline(_mini_profile(), "meta", "E5", current="E4", evidence=ev)
        self.assertLess(strong["low_months"], weak["low_months"])

    def test_unknown_current_still_works(self):
        res = P.timeline(_mini_profile(), "meta", "E5", evidence=[])
        self.assertIn("low_months", res)

    def test_render(self):
        out = P.render_timeline(P.timeline(_mini_profile(), "meta", "E5",
                                           current="E4", evidence=[]))
        self.assertIn("months", out)
        self.assertIn("Heuristic", out)


class RubricTest(unittest.TestCase):
    def test_rows(self):
        res = P.rubric_rows("meta", "E4", "E5")
        self.assertEqual(res["current"]["code"], "E4")
        self.assertEqual(res["target"]["code"], "E5")

    def test_render(self):
        out = P.render_rubric(P.rubric_rows("google", "L4", "L5"))
        self.assertIn("L4", out)
        self.assertIn("L5", out)
        self.assertIn("Promotion criteria", out)


class PacketTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path("/tmp/candid-test-promo-packets")
        self.dir.mkdir(parents=True, exist_ok=True)
        for f in self.dir.glob("*.md"):
            f.unlink()

    def test_build_writes_file(self):
        out = self.dir / "packet.md"
        md, path = P.build_packet(_mini_profile(), "meta", "E5", current="E4",
                                  evidence=[], out=out)
        self.assertEqual(path, out)
        self.assertTrue(out.exists())
        self.assertIn("Promotion packet outline", md)
        self.assertIn("E5", md)

    def test_evidence_mapped(self):
        ev = [{"id": 1, "date": "2026-01-01", "company": "meta", "level": "",
               "criterion": "",
               "text": "Led the ads ranking migration with impact across two teams"}]
        md, _ = P.build_packet(_mini_profile(), "meta", "E5", evidence=ev,
                               out=self.dir / "p2.md")
        self.assertIn("covered", md)

    def test_no_invented_wins_without_profile(self):
        md, _ = P.build_packet(None, "meta", "E5",
                               out=self.dir / "p3.md")
        self.assertIn("Your Name", md)
        self.assertIn("[fill in]", md)

    def test_render_evidence_empty(self):
        out = P.render_evidence_list([])
        self.assertIn("promo evidence add", out)

    def test_render_evidence_list(self):
        items = [{"id": 1, "date": "2026-01-01", "company": "meta",
                  "criterion": "impact", "text": "Shipped X"}]
        out = P.render_evidence_list(items)
        self.assertIn("#1", out)
        self.assertIn("Shipped X", out)


if __name__ == "__main__":
    unittest.main()
