"""Tests for candid.offer_deadlines (offer deadline manager).

Run: python -m pytest tests/test_offer_deadlines.py -q

Tests pass explicit tmp data dirs via data_dir=/offers_path= params —
they never touch the real CANDID_DATA_DIR.
"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TODAY = date(2026, 9, 22)


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(prefix="candid-test-od-")
        self.dd = self.td.name
        self.op = str(Path(self.td.name) / "offers.json")

    def tearDown(self):
        self.td.cleanup()

    def _add(self, company, base, **kw):
        from candid import offer as O
        fields = {"company": company, "role": "Engineer", "base": base}
        fields.update(kw)
        return O.add(fields, path=self.op)

    def _dl(self, **kw):
        from candid import offer_deadlines as OD
        return OD


class DeadlineSetGetTest(Base):
    def setUp(self):
        super().setUp()
        self.a = self._add("Acme", 180000)
        self.b = self._add("Globex", 170000)

    def _set(self, oid, dl):
        return self._dl().set_deadline(oid, dl, offers_path=self.op,
                                       data_dir=self.dd)

    def test_set_and_get(self):
        OD = self._dl()
        rec = self._set(self.a["id"], "2026-10-15")
        self.assertEqual(rec["decision_deadline"], "2026-10-15")
        self.assertEqual(rec["company"], "Acme")
        got = OD.get_deadline(self.a["id"], data_dir=self.dd)
        self.assertIsNotNone(got)
        self.assertEqual(got["decision_deadline"], "2026-10-15")

    def test_get_missing_returns_none(self):
        OD = self._dl()
        self.assertIsNone(OD.get_deadline(self.b["id"], data_dir=self.dd))

    def test_set_replaces_existing(self):
        OD = self._dl()
        self._set(self.a["id"], "2026-10-15")
        rec = self._set(self.a["id"], "2026-11-01")
        self.assertEqual(rec["decision_deadline"], "2026-11-01")
        self.assertEqual(len(OD.list_deadlines(today=TODAY,
                                               offers_path=self.op,
                                               data_dir=self.dd)), 1)

    def test_remove(self):
        OD = self._dl()
        self._set(self.a["id"], "2026-10-15")
        self.assertTrue(OD.remove_deadline(self.a["id"], data_dir=self.dd))
        self.assertIsNone(OD.get_deadline(self.a["id"], data_dir=self.dd))
        self.assertFalse(OD.remove_deadline(self.a["id"], data_dir=self.dd))

    def test_bad_date_rejected(self):
        OD = self._dl()
        with self.assertRaises(OD.OfferDeadlineError) as cm:
            self._set(self.a["id"], "Oct 15")
        self.assertIn("YYYY-MM-DD", str(cm.exception))
        self.assertIn("python -m candid offer deadline",
                      str(cm.exception))

    def test_unknown_offer_id(self):
        OD = self._dl()
        with self.assertRaises(OD.OfferDeadlineError) as cm:
            self._set(999, "2026-10-15")
        self.assertIn("python -m candid offer list", str(cm.exception))


class CountdownTest(Base):
    def setUp(self):
        super().setUp()
        self.a = self._add("Acme", 180000)
        self.b = self._add("Globex", 170000)
        self.c = self._add("Initech", 160000)

    def _set(self, oid, dl):
        return self._dl().set_deadline(oid, dl, offers_path=self.op,
                                       data_dir=self.dd)

    def _list(self):
        return self._dl().list_deadlines(today=TODAY, offers_path=self.op,
                                         data_dir=self.dd)

    def test_sorted_by_urgency(self):
        self._set(self.a["id"], "2026-10-22")  # 30d
        self._set(self.b["id"], "2026-09-25")  # 3d
        self._set(self.c["id"], "2026-10-01")  # 9d
        entries = self._list()
        self.assertEqual([e["company"] for e in entries],
                         ["Globex", "Initech", "Acme"])
        self.assertEqual([e["days_left"] for e in entries], [3, 9, 30])

    def test_exploding_flag_under_7_days(self):
        self._set(self.a["id"], "2026-09-28")  # 6d -> exploding
        self._set(self.b["id"], "2026-09-29")  # 7d -> not exploding
        flags = {e["company"]: e["exploding"] for e in self._list()}
        self.assertTrue(flags["Acme"])
        self.assertFalse(flags["Globex"])

    def test_past_deadline_negative_days(self):
        self._set(self.a["id"], "2026-09-20")
        entries = self._list()
        self.assertEqual(entries[0]["days_left"], -2)
        self.assertTrue(entries[0]["exploding"])

    def test_render_countdown(self):
        OD = self._dl()
        out = OD.render_countdown(today=TODAY, offers_path=self.op,
                                  data_dir=self.dd)
        self.assertIn("No decision deadlines", out)
        self._set(self.b["id"], "2026-09-25")
        out = OD.render_countdown(today=TODAY, offers_path=self.op,
                                  data_dir=self.dd)
        self.assertIn("Globex", out)
        self.assertIn("3 days left", out)
        self.assertIn("EXPLODING OFFER", out)


class WeightedDecisionTest(Base):
    def setUp(self):
        super().setUp()
        # b has higher comp, a has the better non-comp story
        self.a = self._add("Acme", 180000, bonus_target_pct=10)
        self.b = self._add("Globex", 150000, bonus_target_pct=10)
        self.weights = {"comp": 1, "growth": 5, "team": 4,
                        "location": 3, "stability": 2}
        self.scores = {
            self.a["id"]: {"growth": 9, "team": 9, "location": 8,
                           "stability": 7},
            self.b["id"]: {"growth": 4, "team": 5, "location": 5,
                           "stability": 6},
        }

    def _score(self, weights, scores=None):
        return self._dl().score_offers(weights, scores=scores,
                                       offers_path=self.op)

    def test_ranking_prefers_weighted_total(self):
        rows = self._score(self.weights, scores=self.scores)
        self.assertEqual(rows[0]["company"], "Acme")
        self.assertEqual(rows[1]["company"], "Globex")
        for r in rows:
            self.assertTrue(0 <= r["total"] <= 10)

    def test_comp_only_weights_follow_normalized_annual(self):
        rows = self._score({"comp": 5, "growth": 0, "team": 0,
                            "location": 0, "stability": 0})
        self.assertEqual(rows[0]["company"], "Acme")  # higher base wins
        self.assertAlmostEqual(rows[0]["raw_scores"]["comp"], 10.0)

    def test_weights_default_to_one(self):
        rows = self._score({"comp": 2}, scores=self.scores)
        self.assertEqual(len(rows), 2)

    def test_unknown_criterion_rejected(self):
        OD = self._dl()
        with self.assertRaises(OD.OfferDeadlineError) as cm:
            self._score({"comp": 1, "vibes": 3})
        self.assertIn("vibes", str(cm.exception))
        self.assertIn("python -m candid offer deadline",
                      str(cm.exception))

    def test_all_zero_weights_rejected(self):
        OD = self._dl()
        with self.assertRaises(OD.OfferDeadlineError):
            self._score({"comp": 0, "growth": 0, "team": 0,
                         "location": 0, "stability": 0})

    def test_score_out_of_range_rejected(self):
        OD = self._dl()
        bad = {self.a["id"]: {"growth": 11, "team": 9, "location": 8,
                              "stability": 7},
               self.b["id"]: {"growth": 4, "team": 5, "location": 5,
                              "stability": 6}}
        with self.assertRaises(OD.OfferDeadlineError) as cm:
            self._score(self.weights, scores=bad)
        self.assertIn("0-10", str(cm.exception))

    def test_single_offer_rejected(self):
        OD = self._dl()
        td = tempfile.TemporaryDirectory(prefix="candid-test-od-solo-")
        self.addCleanup(td.cleanup)
        from candid import offer as O
        solo_op = str(Path(td.name) / "offers.json")
        O.add({"company": "Solo", "role": "Engineer", "base": 180000},
              path=solo_op)
        with self.assertRaises(OD.OfferDeadlineError):
            OD.score_offers({"comp": 1}, offers_path=solo_op)
        td.cleanup()

    def test_render_decision_table(self):
        OD = self._dl()
        out = OD.render_decision(self.weights, scores=self.scores,
                                 today=TODAY, offers_path=self.op,
                                 data_dir=self.dd)
        self.assertIn("Acme", out)
        self.assertIn("Globex", out)
        self.assertIn("What would change my mind", out)
        # gap is large here: no single 0-10 lever closes it
        self.assertIn("wins on the merits", out)

    def test_render_decision_mind_change_levers(self):
        OD = self._dl()
        # narrow race: Globex nearly ties Acme
        weights = {"comp": 4, "growth": 2, "team": 2, "location": 1,
                   "stability": 1}
        scores = {
            self.a["id"]: {"growth": 6, "team": 6, "location": 6,
                           "stability": 6},
            self.b["id"]: {"growth": 7, "team": 7, "location": 7,
                           "stability": 7},
        }
        out = OD.render_decision(weights, scores=scores, today=TODAY,
                                 offers_path=self.op, data_dir=self.dd)
        self.assertIn("Globex beats Acme", out)
        self.assertIn("raise growth", out)

    def test_render_decision_shows_deadlines(self):
        OD = self._dl()
        OD.set_deadline(self.a["id"], "2026-10-15", offers_path=self.op,
                        data_dir=self.dd)
        out = OD.render_decision(self.weights, scores=self.scores,
                                 today=TODAY, offers_path=self.op,
                                 data_dir=self.dd)
        self.assertIn("2026-10-15", out)


if __name__ == "__main__":
    unittest.main()
