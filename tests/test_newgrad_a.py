"""Tests for the new-grad track (batch 88a): campus timeline + jobs --new-grad.

No network is touched: adapters are mocked and the campus dataset is seeded.
Run: python -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _fake_fetch(payload):
    def _f():
        return payload
    return _f


NEWGRAD_JOBS = [
    {"source": "fake", "source_id": "ng:1", "title": "Software Engineer, New Grad",
     "company": "BigCo", "location": "New York, NY", "remote": False,
     "url": "https://example.com/ng1", "posted_at": "",
     "description": "University graduate role. Entry level, 0-1 years experience.",
     "salary_text": ""},
    {"source": "fake", "source_id": "ng:2", "title": "Senior Software Engineer",
     "company": "BigCo", "location": "New York, NY", "remote": False,
     "url": "https://example.com/ng2", "posted_at": "",
     "description": "5+ years experience required. Lead projects end to end.",
     "salary_text": ""},
    {"source": "fake", "source_id": "ng:3", "title": "Software Engineer",
     "company": "Startup", "location": "Remote", "remote": True,
     "url": "https://example.com/ng3", "posted_at": "",
     "description": "Python backend. Recent graduates welcome.",
     "salary_text": ""},
    {"source": "fake", "source_id": "ng:4", "title": "Engineering Manager",
     "company": "BigCo", "location": "New York, NY", "remote": False,
     "url": "https://example.com/ng4", "posted_at": "",
     "description": "Manage a team of software engineers.", "salary_text": ""},
]

PROFILE = {"name": "New Grad", "skills": ["python"], "seniority": "entry",
           "years_experience": 0, "experience": []}


class CampusDateTest(unittest.TestCase):
    def test_window_dates_current_year(self):
        from candid import campus as CP
        fall = CP.RECRUITING_WINDOWS[0]
        start, end = CP.window_dates(fall, 2026)
        self.assertEqual((start, end), (date(2026, 8, 1), date(2026, 11, 30)))

    def test_next_occurrence_inside_window(self):
        from candid import campus as CP
        fall = CP.RECRUITING_WINDOWS[0]
        start, end = CP.next_occurrence(fall, date(2026, 9, 22))
        self.assertEqual((start, end), (date(2026, 8, 1), date(2026, 11, 30)))

    def test_next_occurrence_rolls_to_next_year(self):
        from candid import campus as CP
        spring = CP.RECRUITING_WINDOWS[1]
        start, end = CP.next_occurrence(spring, date(2026, 12, 15))
        self.assertEqual((start, end), (date(2027, 1, 5), date(2027, 3, 31)))

    def test_window_status_active(self):
        from candid import campus as CP
        fall = CP.RECRUITING_WINDOWS[0]
        st = CP.window_status(fall, date(2026, 9, 22))
        self.assertEqual(st["state"], "active")
        self.assertEqual(st["days"], 0)

    def test_window_status_upcoming_counts_days(self):
        from candid import campus as CP
        spring = CP.RECRUITING_WINDOWS[1]
        st = CP.window_status(spring, date(2026, 12, 15))
        self.assertEqual(st["state"], "upcoming")
        self.assertEqual(st["days"], 21)  # Dec 15 -> Jan 5

    def test_upcoming_events_sorted_and_bounded(self):
        from candid import campus as CP
        events = CP.upcoming_events(90, today=date(2026, 9, 22))
        self.assertTrue(events)
        dates = [e["date"] for e in events]
        self.assertEqual(dates, sorted(dates))
        cutoff = date(2026, 12, 21)
        for e in events:
            self.assertGreaterEqual(e["date"], date(2026, 9, 22))
            self.assertLessEqual(e["date"], cutoff)
        kinds = {e["kind"] for e in events}
        self.assertTrue(kinds <= {"opens", "closes"})

    def test_upcoming_events_zero_days(self):
        from candid import campus as CP
        # Jan 5 2027: spring window opens exactly today
        events = CP.upcoming_events(0, today=date(2027, 1, 5))
        self.assertTrue(any(e["kind"] == "opens" and "Spring" in e["window"]
                            for e in events))

    def test_upcoming_events_negative_days_raises(self):
        from candid import campus as CP
        with self.assertRaises(CP.CampusError):
            CP.upcoming_events(-1, today=date(2026, 9, 22))

    def test_render_timeline_labels_seeded_data(self):
        from candid import campus as CP
        out = CP.render_timeline(today=date(2026, 9, 22))
        self.assertIn("NOT scraped facts", out)
        for w in CP.RECRUITING_WINDOWS:
            self.assertIn(w["name"], out)
        for ctype in CP.COMPANY_TYPE_NOTES:
            self.assertIn(ctype, out)
        self.assertIn("ACTIVE NOW", out)  # fall window is active Sep 22

    def test_render_timeline_bad_school_type(self):
        from candid import campus as CP
        with self.assertRaises(CP.CampusError):
            CP.render_timeline(school_type="ivy-league")

    def test_render_timeline_school_type_tailors_advice(self):
        from candid import campus as CP
        out = CP.render_timeline(school_type="non-target",
                                 today=date(2026, 9, 22))
        self.assertIn("non-target", out)
        self.assertIn("No OCR pipeline", out)

    def test_render_deadlines_empty_period(self):
        from candid import campus as CP
        out = CP.render_deadlines(3, today=date(2026, 12, 25))
        self.assertIn("No window starts or ends", out)


class SeniorEntrySignalTest(unittest.TestCase):
    def test_senior_titles(self):
        from candid import jobs as J
        for title in ("Senior Software Engineer", "Staff Engineer",
                      "Principal Data Scientist", "Engineering Manager",
                      "Director of Engineering", "Team Lead"):
            self.assertTrue(J.is_senior_role(title), title)

    def test_senior_description_signals(self):
        from candid import jobs as J
        self.assertTrue(J.is_senior_role("Software Engineer",
                                         "Requires 5+ years experience."))
        self.assertTrue(J.is_senior_role("Backend Engineer",
                                         "8+ years building distributed systems."))

    def test_senior_word_boundary_no_false_positive(self):
        from candid import jobs as J
        # "leader" must not trip the "lead" signal
        self.assertFalse(J.is_senior_role("Community Builder",
                                          "A recognized leader in open source."))
        self.assertFalse(J.is_senior_role("Software Engineer, New Grad",
                                          "University graduate role."))

    def test_senior_signals_found_lists_hits(self):
        from candid import jobs as J
        hits = J.senior_signals_found("Senior Staff Engineer", "5+ years")
        self.assertIn("senior", hits)
        self.assertIn("staff", hits)
        self.assertIn("5+ years", hits)

    def test_entry_signals_and_boost(self):
        from candid import jobs as J
        self.assertGreater(J.entry_level_boost("Software Engineer",
                                               "New grad, 0-1 years."),
                           0.0)
        self.assertEqual(J.entry_level_boost("Senior Software Engineer",
                                             "5+ years required."), 0.0)
        found = J.entry_signals_found("SWE", "Recent graduate, entry level.")
        self.assertIn("recent graduate", found)
        self.assertIn("entry level", found)

    def test_new_grad_role_appends_signals(self):
        from candid import jobs as J
        role = J.new_grad_role("Software Engineer")
        for sig in J.NEW_GRAD_QUERY_SIGNALS:
            self.assertIn(sig, role)

    def test_new_grad_role_no_duplicates(self):
        from candid import jobs as J
        role = J.new_grad_role("Software Engineer new grad")
        self.assertEqual(role.lower().count("new grad"), 1)


class NewGradFilterTest(unittest.TestCase):
    def test_filter_drops_senior_keeps_entry(self):
        from candid import jobs as J
        out = J.filter_jobs(NEWGRAD_JOBS, "software engineer", "", False,
                            None, 25, new_grad=True)
        ids = [j["source_id"] for j in out]
        self.assertNotIn("ng:2", ids)  # senior
        self.assertNotIn("ng:4", ids)  # manager
        self.assertIn("ng:1", ids)
        self.assertIn("ng:3", ids)

    def test_filter_without_flag_keeps_senior(self):
        from candid import jobs as J
        out = J.filter_jobs(NEWGRAD_JOBS, "software engineer", "", False,
                            None, 25, new_grad=False)
        ids = [j["source_id"] for j in out]
        self.assertIn("ng:2", ids)
        self.assertIn("ng:4", ids)

    def test_entry_boost_ranks_entry_first(self):
        from candid import jobs as J
        pair = [
            {"source": "fake", "source_id": "p:1", "title": "Software Engineer",
             "company": "A", "location": "", "remote": False,
             "description": "Python backend work.", "posted_at": ""},
            {"source": "fake", "source_id": "p:2", "title": "Software Engineer",
             "company": "B", "location": "", "remote": False,
             "description": "Python backend work. New grad friendly.",
             "posted_at": ""},
        ]
        out = J.filter_jobs(pair, "software engineer", "", False, None, 25,
                            new_grad=True)
        self.assertEqual(out[0]["source_id"], "p:2")


class NewGradCurateTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self.td = tempfile.TemporaryDirectory()
        self.orig_data = C.DATA_DIR
        self.orig_tracker = C.TRACKER_PATH
        C.DATA_DIR = Path(self.td.name)
        C.TRACKER_PATH = Path(self.td.name) / "tracker.json"

    def tearDown(self):
        from candid import config as C
        C.DATA_DIR = self.orig_data
        C.TRACKER_PATH = self.orig_tracker
        self.td.cleanup()

    def _score_stub(self, jobs_mod):
        return patch.object(
            jobs_mod, "score_job",
            lambda profile, job: {"score": 70, "verdict": "strong",
                                  "why": "stub", "salary": None,
                                  "breakdown": {}})

    def test_curate_new_grad_excludes_senior(self):
        from candid import jobs as J
        from candid import tracker as T
        with patch.dict(J.ADAPTERS, {"fake": _fake_fetch(NEWGRAD_JOBS)}, clear=True), \
             self._score_stub(J):
            res = J.curate(PROFILE, "software engineer", sources=["fake"],
                           new_grad=True)
        titles = [j["title"] for j in res["added"]]
        self.assertNotIn("Senior Software Engineer", titles)
        self.assertNotIn("Engineering Manager", titles)
        self.assertIn("Software Engineer, New Grad", titles)
        saved = T.list_apps(status="saved")
        self.assertEqual(len(saved), 2)

    def test_curate_plain_keeps_senior(self):
        from candid import jobs as J
        with patch.dict(J.ADAPTERS, {"fake": _fake_fetch(NEWGRAD_JOBS)}, clear=True), \
             self._score_stub(J):
            res = J.curate(PROFILE, "software engineer", sources=["fake"],
                           new_grad=False)
        self.assertEqual(len(res["added"]), 4)

    def test_refresh_passes_new_grad_through(self):
        from candid import jobs as J
        with patch.dict(J.ADAPTERS, {"fake": _fake_fetch(NEWGRAD_JOBS)}, clear=True), \
             self._score_stub(J):
            first = J.curate(PROFILE, "software engineer", sources=["fake"],
                             new_grad=True)
            second = J.refresh(PROFILE, "software engineer", sources=["fake"],
                               new_grad=True)
        self.assertEqual(len(first["added"]), 2)
        self.assertEqual(len(second["added"]), 0)  # deduped, nothing new


class NewGradGuideTest(unittest.TestCase):
    def test_guide_mentions_sources(self):
        from candid import jobs as J
        out = J.render_newgrad_guide()
        self.assertIn("university", out.lower())
        self.assertIn("Simplify", out)
        self.assertIn("--new-grad", out)


class CampusCLITest(unittest.TestCase):
    def _run(self, argv):
        from candid.__main__ import main
        buf = StringIO()
        with redirect_stdout(buf):
            main(argv)
        return buf.getvalue()

    def test_cli_campus_timeline(self):
        out = self._run(["campus", "timeline"])
        self.assertIn("Campus recruiting timeline", out)
        self.assertIn("NOT scraped facts", out)

    def test_cli_campus_timeline_school_type(self):
        out = self._run(["campus", "timeline", "--school-type", "target"])
        self.assertIn("target", out)

    def test_cli_campus_deadlines(self):
        out = self._run(["campus", "deadlines", "--days", "120"])
        self.assertIn("next 120 days", out)

    def test_cli_campus_deadlines_bad_days_clean_error(self):
        from candid.__main__ import main
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            main(["campus", "deadlines", "--days", "-5"])
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("--days must be 0 or more", err.getvalue())

    def test_cli_campus_bad_school_type_clean_error(self):
        from candid.__main__ import main
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            main(["campus", "timeline", "--school-type", "bogus"])
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("Unknown school type", err.getvalue())

    def test_cli_jobs_newgrad_guide(self):
        out = self._run(["jobs", "newgrad-guide"])
        self.assertIn("New-grad job search guide", out)


if __name__ == "__main__":
    unittest.main()
