"""Tests for the batch-25 timing core: candid/timing.py helpers + dispatch,
candid/timing_curve.py (curve/analyze), additive tracker timing fields, and
CLI smoke tests for `timing curve` / `timing analyze`.

Data isolation: monkeypatch candid.config attributes to a temp dir (same
approach as tests/test_cli_ux.py).

Run: python3 -m pytest tests/test_timing_core.py -q
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import timing as T  # noqa: E402
from candid import tracker as TR  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _app(**kw):
    rec = {"id": 1, "company": "Acme", "role": "Data Scientist",
           "status": "applied", "date_added": "2026-09-10"}
    rec.update(kw)
    return rec


class DateParsingTest(unittest.TestCase):
    def test_posted_date_valid(self):
        self.assertEqual(T.get_posted_date(_app(posted_date="2026-09-08")),
                         date(2026, 9, 8))

    def test_posted_date_missing(self):
        self.assertIsNone(T.get_posted_date(_app()))

    def test_posted_date_invalid(self):
        self.assertIsNone(T.get_posted_date(_app(posted_date="not-a-date")))
        self.assertIsNone(T.get_posted_date(_app(posted_date="2026-02-30")))
        self.assertIsNone(T.get_posted_date(_app(posted_date="")))
        self.assertIsNone(T.get_posted_date(_app(posted_date=None)))

    def test_posted_date_datetime_string(self):
        self.assertEqual(T.get_posted_date(_app(posted_date="2026-09-08T10:30:00")),
                         date(2026, 9, 8))

    def test_applied_date_prefers_applied_date(self):
        a = _app(applied_date="2026-09-09", date_added="2026-09-10")
        self.assertEqual(T.get_applied_date(a), date(2026, 9, 9))

    def test_applied_date_falls_back_to_date_added(self):
        self.assertEqual(T.get_applied_date(_app()), date(2026, 9, 10))

    def test_applied_date_none_when_both_missing(self):
        self.assertIsNone(T.get_applied_date(_app(date_added=None)))

    def test_first_response_and_deadline(self):
        a = _app(first_response_date="2026-09-15", deadline="2026-10-01")
        self.assertEqual(T.get_first_response_date(a), date(2026, 9, 15))
        self.assertEqual(T.get_deadline(a), date(2026, 10, 1))
        self.assertIsNone(T.get_first_response_date(_app()))
        self.assertIsNone(T.get_deadline(_app()))


class PostingAgeTest(unittest.TestCase):
    def test_age_days(self):
        a = _app(posted_date="2026-09-08", applied_date="2026-09-10")
        self.assertEqual(T.posting_age_days(a), 2)

    def test_age_uses_date_added_fallback(self):
        a = _app(posted_date="2026-09-08")  # applied -> date_added 2026-09-10
        self.assertEqual(T.posting_age_days(a), 2)

    def test_age_none_when_posted_missing(self):
        self.assertIsNone(T.posting_age_days(_app()))

    def test_age_none_when_applied_missing(self):
        self.assertIsNone(T.posting_age_days(_app(posted_date="2026-09-08",
                                                  date_added=None)))


class BucketTest(unittest.TestCase):
    def test_boundaries(self):
        cases = {0: "0-3 days", 3: "0-3 days", 4: "4-7 days", 7: "4-7 days",
                 8: "8-14 days", 14: "8-14 days", 15: "15-30 days",
                 30: "15-30 days", 31: "31+ days", 120: "31+ days"}
        for days, want in cases.items():
            self.assertEqual(T.bucket_posting_age(days), want,
                             f"days={days}")

    def test_negative_clamps(self):
        self.assertEqual(T.bucket_posting_age(-2), "0-3 days")

    def test_only_five_buckets(self):
        self.assertEqual(T.BUCKETS, ["0-3 days", "4-7 days", "8-14 days",
                                    "15-30 days", "31+ days"])


class RateTest(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(T.POSITIVE_STATUSES,
                         {"selected_for_interview", "offer"})
        self.assertEqual(T.MIN_SAMPLE, 5)

    def test_is_positive(self):
        self.assertTrue(T.is_positive(_app(status="selected_for_interview")))
        self.assertTrue(T.is_positive(_app(status="offer")))
        self.assertFalse(T.is_positive(_app(status="applied")))
        self.assertFalse(T.is_positive(_app(status="rejected")))

    def test_response_rate(self):
        apps = [_app(status="offer"), _app(status="rejected"),
                _app(status="selected_for_interview"), _app(status="applied")]
        self.assertAlmostEqual(T.response_rate(apps), 0.5)
        self.assertEqual(T.response_rate([_app(status="offer")]), 1.0)

    def test_response_rate_empty(self):
        self.assertIsNone(T.response_rate([]))

    def test_enough_data(self):
        self.assertTrue(T.enough_data([_app()] * 5))
        self.assertFalse(T.enough_data([_app()] * 4))
        self.assertTrue(T.enough_data([_app()] * 2, n=2))


class HonestyNoteTest(unittest.TestCase):
    def test_enough_data_note(self):
        note = T.honesty_note([_app()] * 7)
        self.assertIn("Based on 7 applications", note)
        self.assertIn("not a prediction", note)

    def test_not_enough_note(self):
        note = T.honesty_note([_app()] * 3)
        self.assertIn("Not enough data yet", note)
        self.assertIn("5+", note)
        self.assertIn("3", note)

    def test_empty_note(self):
        self.assertIn("Not enough data yet", T.honesty_note([]))


class LoadApplicationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-timing-"))
        self._saved = C.TRACKER_PATH
        C.TRACKER_PATH = self.tmp / "tracker.json"

    def tearDown(self):
        C.TRACKER_PATH = self._saved

    def test_missing_file_returns_empty(self):
        self.assertEqual(T.load_applications(), [])

    def test_invalid_json_returns_empty(self):
        C.TRACKER_PATH.write_text("{not json")
        self.assertEqual(T.load_applications(), [])

    def test_non_list_returns_empty(self):
        C.TRACKER_PATH.write_text('{"a": 1}')
        self.assertEqual(T.load_applications(), [])

    def test_explicit_path(self):
        p = self.tmp / "other.json"
        p.write_text(json.dumps([_app()]))
        self.assertEqual(len(T.load_applications(path=p)), 1)

    def test_round_trip(self):
        TR.add("Acme", "Data Scientist", posted_date="2026-09-01",
               path=C.TRACKER_PATH)
        apps = T.load_applications()
        self.assertEqual(len(apps), 1)
        self.assertEqual(T.get_posted_date(apps[0]), date(2026, 9, 1))


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.injected = []
        self._saved_tracker = C.TRACKER_PATH
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-timing-dispatch-"))
        C.TRACKER_PATH = self.tmp / "tracker.json"

    def tearDown(self):
        for name in self.injected:
            sys.modules.pop(f"candid.{name}", None)
        C.TRACKER_PATH = self._saved_tracker

    def _inject(self, module_name, func_name):
        calls = []
        mod = ModuleType(f"candid.{module_name}")

        def handler(a):
            calls.append(a)
            return None
        setattr(mod, func_name, handler)
        sys.modules[f"candid.{module_name}"] = mod
        self.injected.append(module_name)
        return calls

    def test_all_nine_routes(self):
        routes = {
            "curve": ("timing_curve", "cmd_curve"),
            "analyze": ("timing_curve", "cmd_analyze"),
            "advise": ("timing_advise", "cmd_advise"),
            "reposts": ("timing_advise", "cmd_reposts"),
            "weekday": ("timing_patterns", "cmd_weekday"),
            "deadline": ("timing_patterns", "cmd_deadline"),
            "calendar": ("timing_calendar", "cmd_calendar"),
            "seasons": ("timing_trends", "cmd_seasons"),
            "followups": ("timing_trends", "cmd_followups"),
        }
        for cmd, (mod_name, func_name) in routes.items():
            if mod_name in ("timing_curve",):
                continue  # real module, exercised below
            calls = self._inject(mod_name, func_name)
            a = SimpleNamespace(timing_cmd=cmd, json=False)
            rc = T.dispatch(a)
            self.assertIsNone(rc, f"timing {cmd}")
            self.assertEqual(len(calls), 1, f"timing {cmd} not routed")

    def test_curve_and_analyze_route_to_real_handlers(self):
        for cmd in ("curve", "analyze"):
            a = SimpleNamespace(timing_cmd=cmd, json=True)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = T.dispatch(a)
            self.assertIsNone(rc, f"timing {cmd}")

    def test_unknown_command_returns_2_and_lists_valid(self):
        a = SimpleNamespace(timing_cmd="nope")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = T.dispatch(a)
        self.assertEqual(rc, 2)
        combined = out.getvalue() + err.getvalue()
        for valid in ("curve", "analyze", "advise", "reposts", "weekday",
                      "deadline", "calendar", "seasons", "followups"):
            self.assertIn(valid, combined)

    def test_missing_timing_cmd_attr(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = T.dispatch(SimpleNamespace())
        self.assertEqual(rc, 2)


# ---------------------------------------------------------------------------
# tracker additive timing fields
# ---------------------------------------------------------------------------

class TrackerTimingFieldsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-timing-tracker-"))
        self.p = self.tmp / "tracker.json"

    def test_add_stores_iso_dates(self):
        rec = TR.add("Acme", "Data Scientist", posted_date="2026-09-01",
                     applied_date="2026-09-03", deadline="2026-10-01",
                     path=self.p)
        self.assertEqual(rec["posted_date"], "2026-09-01")
        self.assertEqual(rec["applied_date"], "2026-09-03")
        self.assertEqual(rec["deadline"], "2026-10-01")
        self.assertEqual(rec["first_response_date"], "")
        # persisted
        again = TR.list_apps(path=self.p)[0]
        self.assertEqual(again["posted_date"], "2026-09-01")

    def test_add_defaults_empty(self):
        rec = TR.add("Acme", "Data Scientist", path=self.p)
        self.assertEqual(rec["posted_date"], "")
        self.assertEqual(rec["applied_date"], "")
        self.assertEqual(rec["deadline"], "")

    def test_add_rejects_bad_date(self):
        with self.assertRaises(TR.TrackerError):
            TR.add("Acme", "Data Scientist", posted_date="yesterday",
                   path=self.p)

    def test_update_sets_first_response_date(self):
        rec = TR.add("Acme", "Data Scientist", path=self.p)
        upd = TR.update(rec["id"], status="selected_for_interview",
                        first_response_date="2026-09-20", path=self.p)
        self.assertEqual(upd["status"], "selected_for_interview")
        self.assertEqual(upd["first_response_date"], "2026-09-20")

    def test_update_leaves_fields_alone_by_default(self):
        rec = TR.add("Acme", "Data Scientist", posted_date="2026-09-01",
                     path=self.p)
        upd = TR.update(rec["id"], status="applied", path=self.p)
        self.assertEqual(upd["posted_date"], "2026-09-01")
        self.assertEqual(upd["first_response_date"], "")

    def test_update_rejects_bad_date(self):
        rec = TR.add("Acme", "Data Scientist", path=self.p)
        with self.assertRaises(TR.TrackerError):
            TR.update(rec["id"], deadline="10/01/2026", path=self.p)

    def test_old_records_without_fields_still_work(self):
        self.p.write_text(json.dumps([{"id": 1, "company": "Acme",
                                       "role": "DS", "status": "applied",
                                       "date_added": "2026-09-10"}]))
        apps = T.load_applications(path=self.p)
        self.assertIsNone(T.get_posted_date(apps[0]))
        self.assertIsNone(T.posting_age_days(apps[0]))
        self.assertEqual(T.get_applied_date(apps[0]), date(2026, 9, 10))


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

def _fixture_tracker(path: Path):
    """12 applications across all five posting-age buckets, mixed outcomes."""
    rows = [
        # bucket 0-3: 3 positive / 4
        ("A1", "DS", "2026-09-18", "2026-09-19", "offer"),
        ("A2", "DS", "2026-09-17", "2026-09-18", "selected_for_interview"),
        ("A3", "DS", "2026-09-16", "2026-09-17", "rejected"),
        ("A4", "DS", "2026-09-15", "2026-09-18", "offer"),
        # bucket 4-7: 1 positive / 3
        ("B1", "DS", "2026-09-10", "2026-09-15", "selected_for_interview"),
        ("B2", "DS", "2026-09-09", "2026-09-14", "rejected"),
        ("B3", "DS", "2026-09-08", "2026-09-15", "rejected"),
        # bucket 8-14: 0 positive / 2
        ("C1", "DS", "2026-09-01", "2026-09-10", "rejected"),
        ("C2", "DS", "2026-08-30", "2026-09-10", "rejected"),
        # bucket 15-30: 1 positive / 2
        ("D1", "DS", "2026-08-15", "2026-09-05", "offer"),
        ("D2", "DS", "2026-08-10", "2026-09-05", "rejected"),
        # bucket 31+: 0 positive / 1
        ("E1", "DS", "2026-06-01", "2026-09-05", "rejected"),
    ]
    apps = []
    for i, (co, role, posted, applied, status) in enumerate(rows, 1):
        apps.append({"id": i, "company": co, "role": role, "status": status,
                     "posted_date": posted, "applied_date": applied,
                     "date_added": applied, "date_updated": applied,
                     "jd_link": "", "notes": "", "prep_pack": ""})
    path.write_text(json.dumps(apps))


class TimingCLISmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-timing-cli-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()
        _fixture_tracker(C.TRACKER_PATH)

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1,
                        out.getvalue(), err.getvalue())
        return 0, out.getvalue(), err.getvalue()

    def test_timing_in_command_inventory(self):
        self.assertIn("timing", CLI.COMMANDS)
        self.assertEqual(CLI.SUBCOMMANDS["timing"],
                         ["curve", "analyze", "advise", "reposts", "weekday",
                          "deadline", "calendar", "seasons", "followups"])

    def test_curve_text(self):
        code, out, _ = self.run_cli(["timing", "curve"])
        self.assertEqual(code, 0)
        for b in ("0-3 days", "4-7 days", "8-14 days", "15-30 days", "31+ days"):
            self.assertIn(b, out)
        self.assertIn("75.0%", out)  # 3/4 in the 0-3 bucket
        self.assertIn("Based on 12 applications", out)

    def test_curve_json(self):
        code, out, _ = self.run_cli(["timing", "curve", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        by_bucket = {b["bucket"]: b for b in data["buckets"]}
        self.assertEqual(by_bucket["0-3 days"]["n"], 4)
        self.assertAlmostEqual(by_bucket["0-3 days"]["response_rate"], 0.75)
        self.assertEqual(by_bucket["31+ days"]["n"], 1)
        self.assertTrue(data["enough_data"])
        self.assertIn("Based on 12 applications", data["honesty_note"])

    def test_curve_small_sample_marks_rates_na(self):
        small = [a for a in json.loads(C.TRACKER_PATH.read_text())[:2]]
        C.TRACKER_PATH.write_text(json.dumps(small))
        code, out, _ = self.run_cli(["timing", "curve"])
        self.assertEqual(code, 0)
        self.assertIn("n/a", out)
        self.assertIn("Not enough data yet", out)
        # counts still shown
        self.assertIn("0-3 days", out)

    def test_analyze_text(self):
        code, out, _ = self.run_cli(["timing", "analyze"])
        self.assertEqual(code, 0)
        self.assertIn("Overall response rate", out)
        self.assertIn("Best window", out)
        self.assertIn("Weakest window", out)
        self.assertIn("0-3 days", out)
        self.assertIn("Guidance:", out)
        # data-grounded claim with sample sizes
        self.assertRegex(out, r"n=\d+.*n=\d+|n=\d+")

    def test_analyze_json(self):
        code, out, _ = self.run_cli(["timing", "analyze", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["best_bucket"]["bucket"], "0-3 days")
        self.assertEqual(data["overall"]["n"], 12)
        self.assertGreaterEqual(len(data["guidance"]), 2)
        self.assertLessEqual(len(data["guidance"]), 4)

    def test_analyze_empty_tracker(self):
        C.TRACKER_PATH.write_text("[]")
        code, out, _ = self.run_cli(["timing", "analyze"])
        self.assertEqual(code, 0)
        self.assertIn("Not enough data yet", out)
        self.assertIn("--posted-date", out)

    def test_track_add_with_timing_flags(self):
        code, out, _ = self.run_cli(
            ["track", "add", "--company", "Zed", "--role", "DS",
             "--posted-date", "2026-09-20", "--deadline", "2026-10-20"])
        self.assertEqual(code, 0)
        recs = [a for a in TR.list_apps() if a["company"] == "Zed"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["posted_date"], "2026-09-20")
        self.assertEqual(recs[0]["deadline"], "2026-10-20")

    def test_track_update_with_first_response_date(self):
        code, out, _ = self.run_cli(["track", "update", "1",
                                     "--first-response-date", "2026-09-25"])
        self.assertEqual(code, 0)
        rec = next(a for a in TR.list_apps() if a["id"] == 1)
        self.assertEqual(rec["first_response_date"], "2026-09-25")

    def test_unknown_timing_subcommand_fails(self):
        code, _, err = self.run_cli(["timing", "bogus"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
