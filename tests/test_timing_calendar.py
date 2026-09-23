"""Tests for candid.timing_calendar (batch 25): freshness scoring,
annotation, the action calendar, and the `jobs curate --timing` hook.

Data isolation: config paths are redirected into a temp dir per test
(same monkeypatch approach as tests/test_cli_ux.py), so the real
~/candid_data (or CANDID_DATA_DIR) is never touched.
Run: python -m unittest discover -s tests -v
"""
import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import jobs as J  # noqa: E402
from candid import timing as TM  # noqa: E402
from candid import timing_calendar as TC  # noqa: E402
from candid import tracker as T  # noqa: E402


def _iso(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


class TempDataBase(unittest.TestCase):
    """Redirect candid's data paths into a temp dir for each test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-b25-cal-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def seed_tracker(self, apps):
        C.TRACKER_PATH.write_text(json.dumps(apps), encoding="utf-8")

    def run_calendar(self, days=14, as_json=False):
        ns = argparse.Namespace(days=days, json=as_json)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            TC.cmd_calendar(ns)
        return out.getvalue()


# ---------------------------------------------------------------------------
# timing_score
# ---------------------------------------------------------------------------

class TimingScoreTest(unittest.TestCase):
    def test_zero_days_scores_100(self):
        score, note = TC.timing_score({"posted_date": _iso(0)})
        self.assertEqual(score, 100.0)

    def test_three_days_scores_100(self):
        score, _ = TC.timing_score({"posted_date": _iso(3)})
        self.assertEqual(score, 100.0)

    def test_thirty_days_scores_20(self):
        score, note = TC.timing_score({"posted_date": _iso(30)})
        self.assertAlmostEqual(score, 20.0)
        self.assertIn("stale", note)

    def test_old_posting_floors_at_20(self):
        score, _ = TC.timing_score({"posted_date": _iso(90)})
        self.assertEqual(score, 20.0)

    def test_missing_date_scores_50_with_note(self):
        score, note = TC.timing_score({"title": "Data Scientist"})
        self.assertEqual(score, 50.0)
        self.assertIn("age unknown", note)

    def test_alternate_date_keys(self):
        for key in ("date_posted", "published", "posted"):
            score, _ = TC.timing_score({key: _iso(1)})
            self.assertEqual(score, 100.0, key)

    def test_relative_3d_ago_parses(self):
        score, note = TC.timing_score({"posted_date": "3d ago"})
        self.assertEqual(score, 100.0)

    def test_relative_weeks_ago_parses(self):
        score, _ = TC.timing_score({"posted_date": "2 weeks ago"})
        self.assertLess(score, 100.0)
        self.assertGreater(score, 20.0)

    def test_deadline_urgency_note_does_not_change_score(self):
        job = {"posted_date": _iso(5)}
        plain_score, plain_note = TC.timing_score(job)
        with_dl = dict(job, deadline=_iso(-4))  # 4 days out
        dl_score, dl_note = TC.timing_score(with_dl)
        self.assertEqual(dl_score, plain_score)
        self.assertIn("deadline", dl_note)
        self.assertNotIn("deadline", plain_note)

    def test_deadline_passed_note(self):
        _, note = TC.timing_score(
            {"posted_date": _iso(5), "deadline": _iso(2)})  # 2 days past
        self.assertIn("deadline passed", note)

    def test_defensive_on_garbage(self):
        score, note = TC.timing_score(
            {"posted_date": "not a date", "deadline": object()})
        self.assertEqual(score, 50.0)
        self.assertIsInstance(note, str)


# ---------------------------------------------------------------------------
# annotate_timing
# ---------------------------------------------------------------------------

class AnnotateTimingTest(unittest.TestCase):
    def test_sorted_desc_and_inputs_not_mutated(self):
        jobs = [
            {"title": "Old", "posted_date": _iso(40)},
            {"title": "New", "posted_date": _iso(1)},
            {"title": "Unknown"},
        ]
        snapshot = [dict(j) for j in jobs]
        out = TC.annotate_timing(jobs)
        self.assertEqual([j["title"] for j in out],
                         ["New", "Unknown", "Old"])
        for j in out:
            self.assertIn("timing_score", j)
            self.assertIn("timing_note", j)
        # inputs untouched: same order, no added keys
        self.assertEqual(jobs, snapshot)
        self.assertTrue(all("timing_score" not in j for j in jobs))


# ---------------------------------------------------------------------------
# timing shim API sanity (contract W-core owns)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# calendar
# ---------------------------------------------------------------------------

class CalendarTest(TempDataBase):
    def _app(self, i, company, role, status="saved", posted_ago=None,
             deadline_in=None, notes=""):
        rec = {"id": i, "company": company, "role": role, "status": status,
               "jd_link": "", "notes": notes,
               "date_added": _iso(10), "date_updated": _iso(1), "prep_pack": ""}
        if posted_ago is not None:
            rec["posted_date"] = _iso(posted_ago)
            # saved the day it was found: posting age is measured from here
            rec["date_added"] = _iso(posted_ago)
            rec["date_updated"] = _iso(posted_ago)
        if deadline_in is not None:
            rec["deadline"] = _iso(-deadline_in)
        return rec

    def test_deadlines_sorted_and_tagged(self):
        self.seed_tracker([
            self._app(1, "Late Co", "DS", status="applied", deadline_in=20),  # outside window
            self._app(2, "Soon Co", "MLE", status="applied", deadline_in=2),
            self._app(3, "Over Co", "DE", status="selected_for_interview", deadline_in=-3),
            self._app(4, "Week Co", "DS", status="saved", deadline_in=6),
            self._app(5, "Dead Co", "DS", status="rejected", deadline_in=1),  # closed: excluded
        ])
        text = self.run_calendar(days=14)
        urgencies = [l.split("]")[0][3:] for l in text.splitlines()
                     if l.startswith("  [")]
        # deadlines section order: overdue, <=3 days, <=7 days
        self.assertEqual(urgencies[:3], ["overdue", "<=3 days", "<=7 days"])
        self.assertNotIn("Late Co", text)   # outside the window
        self.assertNotIn("Dead Co", text)   # closed status

    def test_empty_tracker_graceful(self):
        self.seed_tracker([])
        text = self.run_calendar()
        self.assertIn("none tracked", text)
        self.assertIn("nothing urgent", text.lower())

    def test_json_shape(self):
        self.seed_tracker([
            self._app(1, "Soon Co", "MLE", status="applied", deadline_in=2),
            self._app(2, "Fresh Co", "DS", status="saved", posted_ago=1),
        ])
        payload = json.loads(self.run_calendar(as_json=True))
        self.assertEqual(set(payload), {"deadlines", "windows", "actions"})
        self.assertEqual(len(payload["deadlines"]), 1)
        self.assertEqual(payload["deadlines"][0]["urgency"], "<=3 days")
        self.assertEqual(len(payload["windows"]), 1)
        self.assertEqual(payload["windows"][0]["bucket"], "0-3 days")
        self.assertTrue(payload["actions"])
        # deadlines come before fresh-posting actions
        self.assertTrue(payload["actions"][0].startswith("[deadline"))

    def test_windows_use_heuristic_without_history(self):
        self.seed_tracker([
            self._app(1, "Fresh Co", "DS", status="saved", posted_ago=1),
        ])
        payload = json.loads(self.run_calendar(as_json=True))
        window = payload["windows"][0]
        self.assertEqual(window["timing_basis"], "heuristic")
        self.assertIn("heuristic", window["timing_note"])
        self.assertIsNone(window["best_weekday"])

    def test_actions_prioritize_deadlines_then_fresh(self):
        self.seed_tracker([
            self._app(1, "Fresh Co", "DS", status="saved", posted_ago=1),
            self._app(2, "Urgent Co", "MLE", status="applied", deadline_in=2),
        ])
        payload = json.loads(self.run_calendar(as_json=True))
        actions = payload["actions"]
        self.assertEqual(len(actions), 2)
        self.assertTrue(actions[0].startswith("[deadline"))
        self.assertTrue(actions[1].startswith("[apply soon]"))
        self.assertIn("submit application", actions[0])
        self.assertIn("tailor resume", actions[1])

    def test_stale_postings_get_verify_guidance(self):
        self.seed_tracker([
            self._app(1, "Old Co", "DS", status="saved", posted_ago=25),
        ])
        payload = json.loads(self.run_calendar(as_json=True))
        self.assertEqual(payload["windows"][0]["bucket"], "15-30 days")
        self.assertIn("verify", payload["windows"][0]["guidance"])


# ---------------------------------------------------------------------------
# jobs curate --timing smoke test
# ---------------------------------------------------------------------------

FAKE_JOBS = [
    {"source": "fake", "source_id": "fake:t1", "title": "Senior Data Scientist",
     "company": "Acme Corp", "location": "New York, NY", "remote": False,
     "url": "https://example.com/1", "posted": _iso(1),
     "description": "Python and machine learning for our ML platform. SQL required.",
     "salary_text": "$150k-$180k"},
    {"source": "fake", "source_id": "fake:t2", "title": "Data Scientist",
     "company": "Beta LLC", "location": "New York, NY", "remote": False,
     "url": "https://example.com/2", "posted": _iso(20),
     "description": "Python, statistics, experimentation with large datasets.",
     "salary_text": ""},
]

PROFILE = {"name": "Alex Rivera",
           "skills": ["python", "machine learning", "sql", "statistics"],
           "seniority": "senior", "years_experience": 6.5,
           "experience": [{"company": "Meridian Financial",
                           "title": "Senior Data Scientist"}]}


class CurateTimingSmokeTest(TempDataBase):
    def test_curate_timing_flag_shows_scores(self):
        C.PROFILE_PATH.write_text(json.dumps(PROFILE), encoding="utf-8")
        J.ADAPTERS["fake"] = lambda: FAKE_JOBS
        try:
            ns = argparse.Namespace(what="curate", role="data scientist",
                                    location="New York", remote=False,
                                    level=None, limit=15, sources=["fake"],
                                    days=None, min_score=0, timing=True, json=False)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                CLI.cmd_jobs(ns)
            text = out.getvalue()
        finally:
            del J.ADAPTERS["fake"]
        self.assertIn("Timing scores", text)
        self.assertIn("/100", text)
        # fresh job outscores the 20-day-old one in display order
        self.assertLess(text.index("Acme Corp"), text.index("Beta LLC"))


if __name__ == "__main__":
    unittest.main()
