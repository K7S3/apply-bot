"""Tests for candid tracker source/status_history additions + analytics module.

Each test isolates data with tempfile.TemporaryDirectory and passes an
explicit path to tracker/analytics, so no real user data is touched.
"""
import json
import tempfile
import unittest
from pathlib import Path

from candid import analytics as A
from candid import config as C
from candid import tracker as T


class AnalyticsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="candid-analytics-")
        self.path = Path(self.tmp.name) / "tracker.json"
        # Guard: the module must never default to real user data here.
        self._orig_tracker = C.TRACKER_PATH
        C.TRACKER_PATH = self.path

    def tearDown(self):
        C.TRACKER_PATH = self._orig_tracker
        self.tmp.cleanup()


class TestSourceField(AnalyticsBase):
    def test_add_stores_source(self):
        rec = T.add("Acme", "Data Scientist", source="linkedin", path=self.path)
        self.assertEqual(rec["source"], "linkedin")

    def test_add_stores_source_stripped(self):
        rec = T.add("Acme", "Data Scientist", source="  referral ", path=self.path)
        self.assertEqual(rec["source"], "referral")

    def test_add_defaults_source_empty(self):
        rec = T.add("Acme", "Data Scientist", path=self.path)
        self.assertEqual(rec["source"], "")

    def test_update_sets_source(self):
        rec = T.add("Acme", "Data Scientist", path=self.path)
        updated = T.update(rec["id"], source="company-site", path=self.path)
        self.assertEqual(updated["source"], "company-site")

    def test_update_without_source_leaves_source_untouched(self):
        rec = T.add("Acme", "Data Scientist", source="linkedin", path=self.path)
        updated = T.update(rec["id"], notes="hello", path=self.path)
        self.assertEqual(updated["source"], "linkedin")

    def test_update_source_persisted(self):
        rec = T.add("Acme", "Data Scientist", path=self.path)
        T.update(rec["id"], source="hired.com", path=self.path)
        reread = T.list_apps(path=self.path)[0]
        self.assertEqual(reread["source"], "hired.com")


class TestStatusHistory(AnalyticsBase):
    def test_status_change_appends_history(self):
        rec = T.add("Acme", "Data Scientist", status="applied", path=self.path)
        updated = T.update(rec["id"], status="rejected", path=self.path)
        hist = updated["status_history"]
        self.assertEqual(len(hist), 2)
        self.assertEqual(hist[0]["status"], "applied")  # seeded previous
        self.assertEqual(hist[1]["status"], "rejected")

    def test_history_seed_uses_previous_date_updated(self):
        rec = T.add("Acme", "Data Scientist", status="applied", path=self.path)
        updated = T.update(rec["id"], status="selected_for_interview", path=self.path)
        self.assertEqual(updated["status_history"][0]["date"], rec["date_updated"])

    def test_history_grows_across_updates(self):
        rec = T.add("Acme", "Data Scientist", status="applied", path=self.path)
        T.update(rec["id"], status="selected_for_interview", path=self.path)
        updated = T.update(rec["id"], status="offer", path=self.path)
        hist = updated["status_history"]
        self.assertEqual([h["status"] for h in hist],
                         ["applied", "selected_for_interview", "offer"])

    def test_no_history_append_when_status_unchanged(self):
        rec = T.add("Acme", "Data Scientist", status="applied", path=self.path)
        updated = T.update(rec["id"], notes="still waiting", path=self.path)
        self.assertNotIn("status_history", updated)

    def test_no_history_append_when_status_repeated(self):
        rec = T.add("Acme", "Data Scientist", status="applied", path=self.path)
        updated = T.update(rec["id"], status="applied", path=self.path)
        self.assertNotIn("status_history", updated)

    def test_old_record_without_history_is_seeded_on_first_update(self):
        # Simulate a record written before status_history existed.
        old = [{
            "id": 1, "company": "Acme", "role": "Data Scientist",
            "jd_link": "", "status": "saved", "notes": "",
            "date_added": "2026-08-01", "date_updated": "2026-08-02",
            "prep_pack": "",
        }]
        T._save(old, self.path)
        updated = T.update(1, status="applied", path=self.path)
        hist = updated["status_history"]
        self.assertEqual(hist[0], {"status": "saved", "date": "2026-08-02"})
        self.assertEqual(hist[1]["status"], "applied")


class TestOldRecordsCompatibility(AnalyticsBase):
    def test_old_record_without_new_fields_does_not_crash_analytics(self):
        old = [{
            "id": 1, "company": "Acme", "role": "Data Scientist",
            "jd_link": "", "status": "rejected", "notes": "",
            "date_added": "2026-08-01", "date_updated": "2026-08-10",
            "prep_pack": "",
        }]
        T._save(old, self.path)
        funnel = A.funnel_by_source(self.path)
        self.assertIn(A.UNKNOWN_SOURCE, funnel["sources"])
        ttr = A.time_to_response(self.path)
        self.assertEqual(ttr["overall"]["count"], 1)
        self.assertTrue(ttr["estimated"] >= 1)
        rows = A.sources_summary(self.path)
        self.assertEqual(rows[0]["source"], A.UNKNOWN_SOURCE)
        # renderers must not blow up either
        A.render_funnel(funnel)
        A.render_response_times(ttr)
        A.render_sources(rows)


class TestFunnelBySource(AnalyticsBase):
    def _seed(self):
        T.add("Acme", "DS", status="applied", source="linkedin", path=self.path)
        r2 = T.add("Globex", "MLE", status="applied", source="linkedin", path=self.path)
        T.update(r2["id"], status="rejected", path=self.path)
        r3 = T.add("Initech", "DA", status="applied", source="referral", path=self.path)
        T.update(r3["id"], status="selected_for_interview", path=self.path)
        T.update(r3["id"], status="offer", path=self.path)
        T.add("Umbrella", "SWE", status="saved", path=self.path)  # unknown source
        T.add("Hooli", "DS", status="saved", source="linkedin", path=self.path)

    def test_counts_per_source_and_status(self):
        self._seed()
        f = A.funnel_by_source(self.path)
        li = f["sources"]["linkedin"]
        self.assertEqual(li["applications"], 3)
        self.assertEqual(li["counts"]["applied"], 1)
        self.assertEqual(li["counts"]["rejected"], 1)
        self.assertEqual(li["counts"]["saved"], 1)
        ref = f["sources"]["referral"]
        self.assertEqual(ref["applications"], 1)
        self.assertEqual(ref["counts"]["offer"], 1)
        unk = f["sources"][A.UNKNOWN_SOURCE]
        self.assertEqual(unk["applications"], 1)
        self.assertEqual(unk["counts"]["saved"], 1)

    def test_conversion_rates(self):
        self._seed()
        f = A.funnel_by_source(self.path)
        li = f["sources"]["linkedin"]
        # submitted = applied + rejected = 2; response (rejected) = 1
        self.assertEqual(li["submitted"], 2)
        self.assertAlmostEqual(li["response_rate"], 0.5)
        self.assertAlmostEqual(li["interview_rate"], 0.0)
        self.assertAlmostEqual(li["offer_rate"], 0.0)
        ref = f["sources"]["referral"]
        # submitted = offer = 1; offer counts as response + interview + offer
        self.assertAlmostEqual(ref["response_rate"], 1.0)
        self.assertAlmostEqual(ref["interview_rate"], 1.0)
        self.assertAlmostEqual(ref["offer_rate"], 1.0)

    def test_zero_denominator_rates_are_none(self):
        self._seed()
        f = A.funnel_by_source(self.path)
        unk = f["sources"][A.UNKNOWN_SOURCE]
        self.assertEqual(unk["submitted"], 0)
        self.assertIsNone(unk["response_rate"])
        self.assertIsNone(unk["interview_rate"])
        self.assertIsNone(unk["offer_rate"])

    def test_empty_tracker(self):
        f = A.funnel_by_source(self.path)
        self.assertEqual(f["total"], 0)
        self.assertEqual(f["sources"], {})


class TestTimeToResponse(AnalyticsBase):
    def _seed_history(self):
        apps = [
            {"id": 1, "company": "Acme", "role": "DS", "jd_link": "",
             "status": "rejected", "notes": "", "source": "linkedin",
             "date_added": "2026-09-01", "date_updated": "2026-09-11",
             "prep_pack": "",
             "status_history": [
                 {"status": "applied", "date": "2026-09-01"},
                 {"status": "rejected", "date": "2026-09-11"},
             ]},
            {"id": 2, "company": "Acme", "role": "MLE", "jd_link": "",
             "status": "selected_for_interview", "notes": "", "source": "linkedin",
             "date_added": "2026-09-02", "date_updated": "2026-09-05",
             "prep_pack": "",
             "status_history": [
                 {"status": "applied", "date": "2026-09-02"},
                 {"status": "selected_for_interview", "date": "2026-09-05"},
             ]},
            {"id": 3, "company": "Globex", "role": "DA", "jd_link": "",
             "status": "applied", "notes": "", "source": "referral",
             "date_added": "2026-09-01", "date_updated": "2026-09-20",
             "prep_pack": ""},
        ]
        T._save(apps, self.path)

    def test_response_times_from_history(self):
        self._seed_history()
        ttr = A.time_to_response(self.path)
        ov = ttr["overall"]
        self.assertEqual(ov["count"], 2)
        self.assertEqual(ov["avg_days"], 6.5)   # 10 and 3 days
        self.assertEqual(ov["median_days"], 6.5)
        self.assertEqual(ov["min_days"], 3)
        self.assertEqual(ov["max_days"], 10)

    def test_first_response_status_used_not_last(self):
        # History with interview then rejection: first response wins.
        T._save([{
            "id": 1, "company": "Acme", "role": "DS", "jd_link": "",
            "status": "rejected", "notes": "", "source": "",
            "date_added": "2026-09-01", "date_updated": "2026-09-20",
            "prep_pack": "",
            "status_history": [
                {"status": "applied", "date": "2026-09-01"},
                {"status": "selected_for_interview", "date": "2026-09-06"},
                {"status": "rejected", "date": "2026-09-20"},
            ],
        }], self.path)
        ttr = A.time_to_response(self.path)
        self.assertEqual(ttr["overall"]["avg_days"], 5.0)

    def test_estimated_fallback_when_no_history(self):
        T._save([{
            "id": 1, "company": "Acme", "role": "DS", "jd_link": "",
            "status": "rejected", "notes": "", "source": "",
            "date_added": "2026-09-01", "date_updated": "2026-09-11",
            "prep_pack": "",
        }], self.path)
        ttr = A.time_to_response(self.path)
        self.assertEqual(ttr["overall"]["count"], 1)
        self.assertEqual(ttr["overall"]["avg_days"], 10.0)
        self.assertEqual(ttr["estimated"], 1)
        self.assertEqual(ttr["unknown"], 0)

    def test_unknown_bucket_for_unanswered(self):
        self._seed_history()  # includes one applied-with-no-response record
        ttr = A.time_to_response(self.path)
        self.assertEqual(ttr["unknown"], 1)

    def test_by_company(self):
        self._seed_history()
        ttr = A.time_to_response(self.path)
        by = ttr["by_company"]
        self.assertEqual(by["Acme"]["count"], 2)
        self.assertEqual(by["Acme"]["avg_days"], 6.5)
        self.assertNotIn("Globex", by)

    def test_empty_tracker(self):
        ttr = A.time_to_response(self.path)
        self.assertEqual(ttr["overall"]["count"], 0)
        self.assertIsNone(ttr["overall"]["avg_days"])


class TestSourcesSummary(AnalyticsBase):
    def test_rows_sorted_and_fields(self):
        T.add("A1", "R", status="applied", source="linkedin", path=self.path)
        r = T.add("A2", "R", status="applied", source="linkedin", path=self.path)
        T.update(r["id"], status="rejected", path=self.path)
        T.add("B1", "R", status="applied", source="referral", path=self.path)
        rows = A.sources_summary(self.path)
        self.assertEqual([r_["source"] for r_ in rows], ["linkedin", "referral"])
        top = rows[0]
        self.assertEqual(top["applications"], 2)
        self.assertEqual(top["responses"], 1)
        self.assertEqual(top["interviews"], 0)
        self.assertEqual(top["offers"], 0)
        self.assertAlmostEqual(top["response_rate"], 0.5)
        self.assertEqual(rows[1]["applications"], 1)
        self.assertAlmostEqual(rows[1]["response_rate"], 0.0)


class TestRenderers(AnalyticsBase):
    def test_render_funnel_empty(self):
        out = A.render_funnel(A.funnel_by_source(self.path))
        self.assertIn("No applications tracked yet", out)

    def test_render_sources_empty(self):
        out = A.render_sources(A.sources_summary(self.path))
        self.assertIn("No applications tracked yet", out)

    def test_render_response_times_empty(self):
        out = A.render_response_times(A.time_to_response(self.path))
        self.assertIn("No responses recorded", out)

    def test_renderers_produce_tables(self):
        T.add("Acme", "DS", status="applied", source="linkedin", path=self.path)
        r = T.add("Globex", "MLE", status="applied", source="referral", path=self.path)
        T.update(r["id"], status="offer", path=self.path)
        f_out = A.render_funnel(A.funnel_by_source(self.path))
        self.assertIn("linkedin", f_out)
        self.assertIn("referral", f_out)
        t_out = A.render_response_times(A.time_to_response(self.path))
        self.assertIn("overall", t_out)
        s_out = A.render_sources(A.sources_summary(self.path))
        self.assertIn("linkedin", s_out)

    def test_renderers_accept_missing_keys(self):
        # Old callers / hand-built dicts should not crash the renderers.
        A.render_funnel({})
        A.render_response_times({})
        A.render_sources([])


if __name__ == "__main__":
    unittest.main()
