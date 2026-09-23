"""Tests for candid.timing_patterns (batch 25 worker W-patterns).

Covers: cmd_weekday (per-weekday response rates, best-day headline,
time-of-day split when records carry times, thin-data caveats) and
cmd_deadline (deadline-proximity buckets + boundary cases, no-deadline
graceful messaging, early-vs-late guidance).

Runs against the real candid.timing shared module (positive outcomes are
statuses in timing.POSITIVE_STATUSES; rates need timing.MIN_SAMPLE+
applications before claims are made).

Run: CANDID_DATA_DIR=/tmp/candid-test-patterns python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-patterns"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import candid.timing  # noqa: F401  (shared contract: POSITIVE_STATUSES, MIN_SAMPLE, ...)

from candid import config as C  # noqa: E402
from candid import timing_patterns as TP  # noqa: E402


def _seed(apps):
    """Write app records straight to the temp tracker file."""
    C.ensure_data_dirs()
    C.TRACKER_PATH.write_text(json.dumps(apps, indent=2), encoding="utf-8")


def _app(i, company, status, applied=None, deadline=None, added="2026-09-01"):
    rec = {"id": i, "company": company, "role": "Engineer", "status": status,
           "jd_link": "", "notes": "", "date_added": added,
           "date_updated": added, "prep_pack": ""}
    if applied:
        rec["applied_date"] = applied
    if deadline:
        rec["deadline"] = deadline
    return rec


def _this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


class TimingPatternsTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.orig_data, self.orig_tracker = C.DATA_DIR, C.TRACKER_PATH
        C.DATA_DIR = Path(self.td.name)
        C.TRACKER_PATH = Path(self.td.name) / "tracker.json"

    def tearDown(self):
        C.DATA_DIR, C.TRACKER_PATH = self.orig_data, self.orig_tracker
        self.td.cleanup()

    def _run(self, func, as_json=False):
        buf = io.StringIO()
        with redirect_stdout(buf):
            func(SimpleNamespace(json=as_json))
        return buf.getvalue()

    # --- deadline bucket boundaries -----------------------------------
    def test_bucket_deadline_boundaries(self):
        self.assertEqual(TP.bucket_deadline(7), "7+ days early")
        self.assertEqual(TP.bucket_deadline(10), "7+ days early")
        self.assertEqual(TP.bucket_deadline(6), "3-6 days early")
        self.assertEqual(TP.bucket_deadline(3), "3-6 days early")
        self.assertEqual(TP.bucket_deadline(2), "1-2 days early")
        self.assertEqual(TP.bucket_deadline(1), "1-2 days early")
        self.assertEqual(TP.bucket_deadline(0), "last day / late")
        self.assertEqual(TP.bucket_deadline(-2), "last day / late")

    # --- weekday analysis ---------------------------------------------
    def _seed_weekdays(self):
        mon = _this_monday()
        tue = mon + timedelta(days=1)
        wed = mon + timedelta(days=2)
        _seed([
            _app(1, "A", "offer", applied=mon.isoformat()),
            _app(2, "B", "selected_for_interview", applied=mon.isoformat()),
            _app(3, "C", "selected_for_interview", applied=mon.isoformat()),
            _app(4, "D", "applied", applied=mon.isoformat()),
            _app(5, "E", "offer", applied=tue.isoformat()),
            _app(6, "F", "applied", applied=tue.isoformat()),
            _app(7, "G", "applied", applied=wed.isoformat()),
            _app(8, "H", "saved", added="2026-09-05"),  # Saturday date_added
        ])
        self._sat = "Saturday"  # 2026-09-05

    def test_weekday_rates_and_headline(self):
        self._seed_weekdays()
        payload = TP._weekday_payload()
        by_day = {r["weekday"]: r for r in payload["weekdays"]}
        self.assertEqual(by_day["Monday"]["n"], 4)
        self.assertAlmostEqual(by_day["Monday"]["response_rate"], 0.75)
        self.assertEqual(by_day["Tuesday"]["n"], 2)
        self.assertAlmostEqual(by_day["Tuesday"]["response_rate"], 0.5)
        self.assertEqual(by_day["Wednesday"]["n"], 1)
        self.assertAlmostEqual(by_day["Wednesday"]["response_rate"], 0.0)
        self.assertEqual(by_day["Thursday"]["n"], 0)
        self.assertIsNone(by_day["Thursday"]["response_rate"])
        # app H's date_added falls on Saturday and is counted via fallback
        self.assertEqual(by_day["Saturday"]["n"], 1)
        self.assertEqual(payload["best"]["weekday"], "Monday")
        self.assertAlmostEqual(payload["best"]["response_rate"], 0.75)

        out = self._run(TP.cmd_weekday)
        self.assertIn("Your best apply day is Monday at 75.0% (n=4).", out)
        self.assertIn("Monday", out)
        # app with no applied_date still counted in totals
        self.assertIn("n=8 applications", out)

    def test_weekday_json_shape(self):
        self._seed_weekdays()
        out = self._run(TP.cmd_weekday, as_json=True)
        payload = json.loads(out)
        self.assertEqual(len(payload["weekdays"]), 7)
        self.assertEqual(payload["total_applications"], 8)
        row = next(r for r in payload["weekdays"] if r["weekday"] == "Monday")
        self.assertEqual(row["n"], 4)
        self.assertAlmostEqual(row["response_rate"], 0.75)
        self.assertEqual(row["responses"], 3)
        empty = next(r for r in payload["weekdays"] if r["weekday"] == "Friday")
        self.assertIsNone(empty["response_rate"])
        self.assertEqual(payload["best"]["weekday"], "Monday")
        # thin data -> honesty caveat present (fewer than MIN_SAMPLE apps)
        _seed([_app(1, "A", "offer", applied=_this_monday().isoformat())])
        thin = json.loads(self._run(TP.cmd_weekday, as_json=True))
        self.assertIsNotNone(thin["caveat"])

    # --- time-of-day ---------------------------------------------------
    def test_time_of_day_captured(self):
        mon = _this_monday()
        tue = mon + timedelta(days=1)
        wed = mon + timedelta(days=2)
        _seed([
            _app(1, "A", "offer", applied=f"{mon.isoformat()}T09:15"),
            _app(2, "B", "rejected", applied=f"{tue.isoformat()}T14:00"),
            _app(3, "C", "applied", applied=f"{wed.isoformat()}T19:30"),
        ])
        payload = TP._weekday_payload()
        self.assertTrue(payload["time_of_day_captured"])
        by_period = {r["period"]: r for r in payload["time_of_day"]}
        self.assertEqual(by_period["morning"]["n"], 1)
        self.assertEqual(by_period["afternoon"]["n"], 1)
        self.assertEqual(by_period["evening"]["n"], 1)
        out = self._run(TP.cmd_weekday)
        self.assertIn("Time of day", out)
        self.assertIn("morning", out)

        jout = json.loads(self._run(TP.cmd_weekday, as_json=True))
        self.assertTrue(jout["time_of_day_captured"])
        self.assertEqual(len(jout["time_of_day"]), 4)  # 4 buckets

    def test_time_of_day_not_captured(self):
        mon = _this_monday()
        _seed([_app(1, "A", "offer", applied=mon.isoformat())])
        payload = TP._weekday_payload()
        self.assertFalse(payload["time_of_day_captured"])
        self.assertEqual(payload["time_of_day"], [])
        out = self._run(TP.cmd_weekday)
        self.assertIn("Time-of-day data isn't captured yet", out)
        self.assertNotIn("Best time of day", out)
        jout = json.loads(self._run(TP.cmd_weekday, as_json=True))
        self.assertFalse(jout["time_of_day_captured"])
        self.assertEqual(jout["time_of_day"], [])

    # --- deadline analysis ---------------------------------------------
    def _seed_deadlines(self):
        _seed([
            # 7 days before deadline -> "7+ days early" (positive)
            _app(1, "A", "offer", applied="2026-09-01", deadline="2026-09-08"),
            # 3 days before -> "3-6 days early" (positive)
            _app(2, "B", "selected_for_interview", applied="2026-09-05", deadline="2026-09-08"),
            # 1 day before -> "1-2 days early" (negative)
            _app(3, "C", "applied", applied="2026-09-07", deadline="2026-09-08"),
            # 0 days -> "last day / late" (negative)
            _app(4, "D", "applied", applied="2026-09-08", deadline="2026-09-08"),
            # -2 days -> "last day / late" (negative)
            _app(5, "E", "withdrawn", applied="2026-09-10", deadline="2026-09-08"),
            # no deadline recorded
            _app(6, "F", "applied", applied="2026-09-02"),
        ])

    def test_deadline_buckets_and_guidance(self):
        self._seed_deadlines()
        payload = TP._deadline_payload()
        by_b = {b["bucket"]: b for b in payload["buckets"]}
        self.assertEqual(by_b["7+ days early"]["n"], 1)
        self.assertAlmostEqual(by_b["7+ days early"]["response_rate"], 1.0)
        self.assertEqual(by_b["3-6 days early"]["n"], 1)
        self.assertEqual(by_b["1-2 days early"]["n"], 1)
        self.assertEqual(by_b["last day / late"]["n"], 2)
        self.assertAlmostEqual(by_b["last day / late"]["response_rate"], 0.0)
        self.assertEqual(payload["no_deadline"], 1)
        # early = 7+ and 3-6 buckets: 2 apps, both positive -> 100%
        self.assertIn("100.0% (n=2)", payload["guidance"])
        self.assertIn("0.0% (n=2) last-minute", payload["guidance"])

        out = self._run(TP.cmd_deadline)
        self.assertIn("Applying 3+ days before the deadline converts at",
                      out)
        self.assertIn("1 applications have no deadline recorded", out)
        self.assertIn("add --deadline", out)

    def test_deadline_json_shape(self):
        self._seed_deadlines()
        payload = json.loads(self._run(TP.cmd_deadline, as_json=True))
        self.assertEqual(len(payload["buckets"]), 4)
        self.assertEqual(payload["no_deadline"], 1)
        self.assertEqual(payload["with_deadline_and_applied_date"], 5)
        self.assertIn("guidance", payload)

    def test_deadline_none_recorded_graceful(self):
        _seed([_app(1, "A", "applied", applied="2026-09-01"),
               _app(2, "B", "offer", applied="2026-09-02")])
        payload = TP._deadline_payload()
        self.assertEqual(payload["no_deadline"], 2)
        self.assertEqual(payload["with_deadline_and_applied_date"], 0)
        out = self._run(TP.cmd_deadline)
        self.assertIn("2 applications have no deadline recorded", out)
        # no crash on empty buckets; guidance stays honest
        self.assertIn("Not enough", payload["guidance"])

    # --- thin data / honesty -------------------------------------------
    def test_thin_data_honesty_note(self):
        _seed([_app(1, "A", "offer", applied="2026-09-01",
                    deadline="2026-09-08"),
               _app(2, "B", "applied", applied="2026-09-02")])
        out = self._run(TP.cmd_weekday)
        self.assertIn("Not enough data", out)
        out = self._run(TP.cmd_deadline)
        self.assertIn("Not enough data", out)
        payload = TP._weekday_payload()
        self.assertTrue(payload["caveat"])

    def test_empty_tracker(self):
        _seed([])
        self._run(TP.cmd_weekday)   # no crash
        self._run(TP.cmd_deadline)  # no crash
        out = self._run(TP.cmd_weekday)
        self.assertIn("No applications have an applied date yet", out)
        payload = json.loads(self._run(TP.cmd_weekday, as_json=True))
        self.assertIsNone(payload["best"])
        dpayload = json.loads(self._run(TP.cmd_deadline, as_json=True))
        self.assertEqual(dpayload["with_deadline_and_applied_date"], 0)


if __name__ == "__main__":
    unittest.main()
