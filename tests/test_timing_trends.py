"""Tests for candid.timing_trends (batch 25): seasonal analysis + follow-up timing.

Data isolation: CANDID_DATA_DIR points at a fresh temp dir before any
candid import, mirroring the pattern in test_ingest_track.py.

Run: CANDID_DATA_DIR=/tmp/candid-test-trends python3 -m unittest tests.test_timing_trends -v
"""
import argparse
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
import unittest

os.environ["CANDID_DATA_DIR"] = tempfile.mkdtemp(prefix="candid-test-trends-")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import timing_trends as TT  # noqa: E402

MS = TT.MIN_SAMPLE  # minimum sample per period (from candid.timing or shim)


def _app(i, status, applied=None, responded=None, posted=None):
    """A tracker record shaped like T.add() output, with timing fields."""
    return {
        "id": i,
        "company": f"Co{i}",
        "role": "Engineer",
        "status": status,
        "notes": "",
        "date_added": applied or "2026-01-01",
        "date_updated": responded or applied or "2026-01-01",
        "applied_date": applied,
        "first_response_date": responded,
        "posted_date": posted,
    }


def _write_tracker(records):
    p = Path(C.DATA_DIR) / "tracker.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(records), encoding="utf-8")


def _write_proposals(proposals):
    p = Path(C.DATA_DIR) / "gmail_proposals.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(proposals), encoding="utf-8")


def _patched(cmd, apps):
    """Run a cmd_* with a controlled app list instead of the tracker."""
    orig = TT.load_applications
    TT.load_applications = lambda: apps
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd(argparse.Namespace(json=False))
        return buf.getvalue()
    finally:
        TT.load_applications = orig


def _run_json(cmd, apps):
    orig = TT.load_applications
    TT.load_applications = lambda: apps
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd(argparse.Namespace(json=True))
        return json.loads(buf.getvalue())
    finally:
        TT.load_applications = orig


class SeasonsTest(unittest.TestCase):
    def test_month_quarter_aggregation_and_year_boundary(self):
        # Dec 2025 -> 2025-Q4, Jan 2026 -> 2026-Q1: the boundary must split.
        apps = [_app(1, "selected_for_interview", applied="2025-12-15",
                     responded="2025-12-20"),
                _app(2, "applied", applied="2025-12-20"),
                _app(3, "offer", applied="2026-01-05", responded="2026-01-12"),
                _app(4, "selected_for_interview", applied="2026-01-18", responded="2026-01-25")]
        s = TT.season_summary(apps)
        month_keys = [r["period"] for r in s["months"]]
        quarter_keys = [r["period"] for r in s["quarters"]]
        self.assertEqual(month_keys, ["2025-12", "2026-01"])
        self.assertEqual(quarter_keys, ["2025-Q4", "2026-Q1"])
        jan = next(r for r in s["months"] if r["period"] == "2026-01")
        self.assertEqual(jan["n"], 2)
        self.assertEqual(jan["positives"], 2)
        self.assertAlmostEqual(jan["response_rate"], 1.0)

    def test_pattern_detected_with_qualified_quarters(self):
        apps = []
        i = 0
        for k in range(MS + 5):  # 2026-Q1: strong quarter
            i += 1
            apps.append(_app(i, "selected_for_interview" if k % 5 != 4 else "applied",
                             applied=f"2026-01-{10 + (k % 15):02d}"))
        for k in range(MS):  # 2026-Q3: weak quarter (1 response)
            i += 1
            apps.append(_app(i, "selected_for_interview" if k == 0 else "applied",
                             applied=f"2026-07-{10 + k:02d}"))
        s = TT.season_summary(apps)
        self.assertTrue(s["pattern"]["detected"])
        self.assertEqual(s["best_quarter"]["period"], "2026-Q1")
        self.assertEqual(s["worst_quarter"]["period"], "2026-Q3")
        self.assertEqual(s["best_month"]["period"], "2026-01")
        self.assertIsNone(s["heuristic"])  # no heuristic when data speaks
        text = TT.render_seasons(s)
        self.assertIn("Best quarter", text)
        self.assertIn("Worst quarter", text)
        self.assertIn("Seasonality signal", text)

    def test_thin_data_honesty(self):
        apps = [_app(1, "applied", applied="2026-02-01"),
                _app(2, "applied", applied="2026-02-10"),
                _app(3, "selected_for_interview", applied="2026-03-01")]
        self.assertLess(len(apps), MS)
        s = TT.season_summary(apps)
        self.assertTrue(s["thin"])
        self.assertIsNone(s["best_quarter"])  # no headlines on thin data
        self.assertIsNone(s["best_month"])
        self.assertFalse(s["pattern"]["detected"])
        self.assertIsNotNone(s["honesty_note"])
        self.assertIsNotNone(s["heuristic"])
        text = TT.render_seasons(s)
        # raw table still printed, no grand claims
        self.assertIn("2026-02", text)
        self.assertNotIn("Best quarter", text)
        self.assertNotIn("Seasonality signal", text)
        self.assertIn("heuristic", text.lower())
        self.assertIn("not from your data", text)

    def test_no_applied_dates(self):
        # record with no date fields at all -> no dated applications
        apps = [{"id": 1, "company": "Co1", "role": "Eng", "status": "saved",
                 "notes": "", "date_added": "", "date_updated": "",
                 "applied_date": "", "first_response_date": "", "posted_date": ""}]
        s = TT.season_summary(apps)
        self.assertEqual(s["n_dated"], 0)
        text = TT.render_seasons(s)
        self.assertIn("No applications with applied dates", text)
        self.assertIn("not from your data", text)

    def test_json_shape(self):
        apps = [_app(1, "selected_for_interview", applied="2026-01-05"),
                _app(2, "applied", applied="2026-02-05")]
        payload = _run_json(TT.cmd_seasons, apps)
        for key in ("months", "quarters", "best_month", "worst_month",
                    "best_quarter", "worst_quarter", "pattern", "honesty_note",
                    "heuristic", "n_dated"):
            self.assertIn(key, payload)
        self.assertEqual(payload["n_dated"], 2)
        self.assertEqual(payload["months"][0]["period"], "2026-01")


class FollowupsTest(unittest.TestCase):
    def _arrival_apps(self):
        # 2026-09-22 is a Tuesday, 2026-09-25 a Friday (see repo date table).
        # Sample counts scale with MIN_SAMPLE so the test holds whatever
        # value candid.timing lands on.
        apps = []
        for i in range(MS + 2):
            apps.append(_app(100 + i, "selected_for_interview",
                             applied="2026-09-01", responded="2026-09-22"))
        for i in range(2):
            apps.append(_app(200 + i, "rejected",
                             applied="2026-09-01", responded="2026-09-25"))
        return apps

    def test_weekday_ranking_from_tracker(self):
        _write_tracker([])  # no gmail proposals -> fallback path
        _write_proposals([])
        t = TT.followup_timing(self._arrival_apps())
        self.assertEqual(t["n_responses"], MS + 4)
        self.assertEqual(t["weekday_ranking"][0]["weekday"], "Tuesday")
        self.assertEqual(t["weekday_ranking"][0]["arrivals"], MS + 2)
        friday = next(r for r in t["weekday_ranking"] if r["weekday"] == "Friday")
        self.assertEqual(friday["arrivals"], 2)
        self.assertIn("tracker", t["data_source"])
        # send window targets the day before the Tuesday peak
        self.assertTrue(any("Monday" in w for w in t["suggested_send_windows"]))
        self.assertTrue(any("approximate" in w.lower()
                            for w in t["suggested_send_windows"])
                        or "approximate" in TT.render_followups(t).lower())

    def test_gmail_honesty_when_outbound_unavailable(self):
        _write_proposals([])
        t = TT.followup_timing(self._arrival_apps())
        self.assertIn("outbound", t["gmail_note"])
        self.assertIn("does not record", t["gmail_note"])
        self.assertIsNone(t["supplemental_gmail_inbound"])

    def test_gmail_proposals_supplemental_inbound(self):
        # gmail.py stores recruiter INBOUND proposals with Date headers.
        _write_proposals([
            {"id": 1, "kind": "recruiter_outreach", "company": "Acme",
             "role": "Eng", "from": "r@acme.com", "subject": "Opportunity",
             "date": "Tue, 22 Sep 2026 10:00:00 -0400", "status": "pending"},
            {"id": 2, "kind": "interview_invite", "company": "Beta",
             "role": "Eng", "from": "h@beta.com", "subject": "Interview",
             "date": "Wed, 23 Sep 2026 09:00:00 -0400", "status": "pending"},
            {"id": 3, "kind": "rejection", "company": "Gamma",
             "role": "Eng", "from": "n/a", "subject": "Update",
             "date": "not a real date", "status": "pending"},  # must not crash
        ])
        t = TT.followup_timing(self._arrival_apps())
        sup = t["supplemental_gmail_inbound"]
        self.assertIsNotNone(sup)
        self.assertEqual(sup["n"], 2)
        by_day = {r["weekday"]: r["messages"] for r in sup["by_weekday"]}
        self.assertEqual(by_day["Tuesday"], 1)
        self.assertEqual(by_day["Wednesday"], 1)

    def test_no_responses_yet(self):
        t = TT.followup_timing([_app(1, "applied", applied="2026-09-01")])
        self.assertEqual(t["n_responses"], 0)
        self.assertIsNotNone(t["honesty_note"])
        text = TT.render_followups(t)
        self.assertIn("No first-response dates", text)

    def test_json_shape(self):
        payload = _run_json(TT.cmd_followups, self._arrival_apps())
        for key in ("n_responses", "weekday_ranking", "suggested_send_windows",
                    "data_source", "gmail_note", "supplemental_gmail_inbound",
                    "honesty_note"):
            self.assertIn(key, payload)
        self.assertEqual(len(payload["weekday_ranking"]), 7)


class NudgeLinesTest(unittest.TestCase):
    def _rich_apps(self):
        apps = []
        i = 0
        # 2 stale saved (posted 2026-08-01, still untouched)
        for _ in range(2):
            i += 1
            apps.append(_app(i, "saved", applied=None, posted="2026-08-01"))
        # early applications (<=3 days after posting): all convert
        for _ in range(MS + 1):
            i += 1
            apps.append(_app(i, "selected_for_interview",
                             applied="2026-09-02", posted="2026-09-01"))
        # late applications (>=7 days after posting): only 1 converts
        for k in range(MS + 1):
            i += 1
            apps.append(_app(i, "selected_for_interview" if k == 0 else "applied",
                             applied="2026-09-20", posted="2026-09-01"))
        # response arrivals all on Tuesdays -> peak weekday line
        for a in apps:
            if a["status"] in ("selected_for_interview", "offer", "rejected"):
                a["first_response_date"] = "2026-09-22"
        return apps

    def test_nudge_lines_content(self):
        apps = self._rich_apps()
        lines = TT.timing_nudge_lines(apps)
        self.assertIsInstance(lines, list)
        self.assertLessEqual(len(lines), 3)
        joined = " ".join(lines)
        self.assertIn("5+ days old", joined)          # stale saved
        self.assertIn("3 days", joined)               # early-apply uplift
        self.assertIn("Tuesday", joined)              # peak weekday

    def test_nudge_lines_quiet_when_nothing_to_say(self):
        _write_tracker([])
        self.assertEqual(TT.timing_nudge_lines([]), [])
        self.assertEqual(TT.timing_nudge_lines(None), [])  # empty tracker

    def test_nudge_lines_defensive(self):
        # garbage input must never raise
        self.assertIsInstance(TT.timing_nudge_lines(None), list)
        self.assertIsInstance(TT.timing_nudge_lines([None, "x", 42, {}]), list)
        self.assertIsInstance(TT.timing_nudge_lines("notalist"), list)


class CmdDispatchTest(unittest.TestCase):
    """cmd_* accept an argparse Namespace with .json, like __main__ dispatch."""

    def test_cmd_seasons_text_runs(self):
        apps = [_app(1, "applied", applied="2026-04-01")]
        text = _patched(TT.cmd_seasons, apps)
        self.assertIn("Seasonal response rates", text)

    def test_cmd_followups_text_runs(self):
        apps = [_app(1, "selected_for_interview", applied="2026-09-01",
                     responded="2026-09-22")]
        text = _patched(TT.cmd_followups, apps)
        self.assertIn("follow-ups", text)


if __name__ == "__main__":
    unittest.main()
