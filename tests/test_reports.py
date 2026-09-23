"""Tests for candid.reports: trend buckets, custom report builder."""

import csv
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import reports as R  # noqa: E402


def _app(i, company, role, status, added, updated=None,
         source=None, history=None):
    rec = {"id": i, "company": company, "role": role, "jd_link": "",
           "status": status, "notes": "",
           "date_added": added, "date_updated": updated or added,
           "prep_pack": ""}
    if source is not None:
        rec["source"] = source
    if history is not None:
        rec["status_history"] = history
    return rec


class ReportsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-reports-"))
        self._saved = {name: getattr(C, name)
                       for name in ("TRACKER_PATH", "DATA_DIR")}
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.DATA_DIR = self.tmp

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def write_apps(self, apps):
        C.TRACKER_PATH.write_text(json.dumps(apps), encoding="utf-8")

    def row_for(self, rows, period):
        matches = [r for r in rows if r["period"] == period]
        self.assertEqual(len(matches), 1, f"expected one row for {period}")
        return matches[0]

    def this_week_label(self):
        monday = date.today() - timedelta(days=date.today().weekday())
        iso = monday.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"


class TrendTest(ReportsBase):
    def test_weekly_bucketing_with_history(self):
        monday = date.today() - timedelta(days=date.today().weekday())
        two_weeks = monday - timedelta(weeks=2)
        apps = [
            _app(1, "Acme", "DS", "applied", monday.isoformat()),
            _app(2, "Beta", "SWE", "offer", two_weeks.isoformat(),
                 history=[
                     {"status": "applied",
                      "date": two_weeks.isoformat()},
                     {"status": "selected_for_interview",
                      "date": (two_weeks + timedelta(days=3)).isoformat()},
                     {"status": "offer",
                      "date": (two_weeks + timedelta(days=6)).isoformat()},
                 ]),
        ]
        self.write_apps(apps)
        rows = R.trend_report("weekly", n=3)
        self.assertEqual(len(rows), 3)
        now_row = self.row_for(rows, self.this_week_label())
        self.assertEqual(now_row["added"], 1)
        self.assertEqual(now_row["responses"], 0)
        self.assertFalse(now_row["estimated"])
        iso = two_weeks.isocalendar()
        old_row = self.row_for(rows, f"{iso.year}-W{iso.week:02d}")
        self.assertEqual(old_row["added"], 1)
        self.assertEqual(old_row["responses"], 2)   # interview + offer
        self.assertEqual(old_row["interviews"], 2)  # interview + offer
        self.assertEqual(old_row["offers"], 1)
        self.assertFalse(old_row["estimated"])

    def test_estimated_fallback_without_history(self):
        monday = date.today() - timedelta(days=date.today().weekday())
        last_week = monday - timedelta(weeks=1)
        apps = [
            _app(1, "Acme", "DS", "rejected",
                 (monday - timedelta(weeks=10)).isoformat(),
                 updated=(last_week + timedelta(days=2)).isoformat()),
        ]
        self.write_apps(apps)
        rows = R.trend_report("weekly", n=3)
        iso = last_week.isocalendar()
        row = self.row_for(rows, f"{iso.year}-W{iso.week:02d}")
        self.assertEqual(row["responses"], 1)
        self.assertEqual(row["interviews"], 0)
        self.assertEqual(row["offers"], 0)
        self.assertTrue(row["estimated"])
        # the added bucket (10 weeks ago) is outside the window: no added counts
        self.assertEqual(sum(r["added"] for r in rows), 0)

    def test_estimated_fallback_offer_counts_interview(self):
        monday = date.today() - timedelta(days=date.today().weekday())
        apps = [_app(1, "Acme", "DS", "offer", monday.isoformat())]
        self.write_apps(apps)
        rows = R.trend_report("weekly", n=2)
        row = self.row_for(rows, self.this_week_label())
        self.assertEqual(row["responses"], 1)
        self.assertEqual(row["interviews"], 1)
        self.assertEqual(row["offers"], 1)
        self.assertTrue(row["estimated"])

    def test_monthly_bucketing(self):
        today = date.today()
        first_this = date(today.year, today.month, 1)
        first_prev = first_this - timedelta(days=1)
        first_prev = date(first_prev.year, first_prev.month, 1)
        apps = [
            _app(1, "Acme", "DS", "applied", first_this.isoformat()),
            _app(2, "Beta", "SWE", "saved", first_prev.isoformat()),
            _app(3, "Gamma", "PM", "saved", first_prev.isoformat()),
        ]
        self.write_apps(apps)
        rows = R.trend_report("monthly", n=2)
        self.assertEqual(len(rows), 2)
        now_row = self.row_for(rows, f"{today.year}-{today.month:02d}")
        prev_row = self.row_for(rows, f"{first_prev.year}-{first_prev.month:02d}")
        self.assertEqual(now_row["added"], 1)
        self.assertEqual(prev_row["added"], 2)

    def test_defensive_without_optional_fields(self):
        # records missing source/status_history keys entirely must not crash
        bare = {"id": 1, "company": "Acme", "role": "DS",
                "status": "applied",
                "date_added": date.today().isoformat(),
                "date_updated": date.today().isoformat()}
        self.write_apps([bare])
        rows = R.trend_report("weekly", n=2)
        self.assertEqual(sum(r["added"] for r in rows), 1)
        p = R.build_report(out=str(self.tmp / "r.csv"))
        self.assertTrue(p.exists())

    def test_invalid_period_and_n(self):
        self.write_apps([])
        with self.assertRaises(R.ReportsError):
            R.trend_report("daily")
        with self.assertRaises(R.ReportsError):
            R.trend_report("weekly", n=0)
        with self.assertRaises(R.ReportsError):
            R.trend_report("weekly", n="8")

    def test_render_trend_text_and_md(self):
        rows = [
            {"period": "2026-W37", "added": 2, "responses": 1,
             "interviews": 1, "offers": 0, "estimated": False},
            {"period": "2026-W38", "added": 3, "responses": 0,
             "interviews": 0, "offers": 0, "estimated": True},
        ]
        text = R.render_trend(rows, format="text")
        self.assertIn("2026-W37", text)
        self.assertIn("Added", text)
        self.assertIn("2026-W38*", text)  # estimated marker
        md = R.render_trend(rows, format="md")
        self.assertIn("| Period | Added | Responses | Interviews | Offers |",
                      md)
        self.assertIn("2026-W38 *", md)
        with self.assertRaises(R.ReportsError):
            R.render_trend(rows, format="pdf")


class BuildReportTest(ReportsBase):
    def setUp(self):
        super().setUp()
        self.write_apps([
            _app(1, "Acme", "Data Scientist", "applied", "2026-09-01",
                 source="referral"),
            _app(2, "Acme Labs", "SWE", "rejected", "2026-09-05",
                 source="linkedin",
                 history=[{"status": "applied", "date": "2026-09-05"},
                          {"status": "rejected", "date": "2026-09-08"}]),
            _app(3, "Beta", "PM", "saved", "2026-08-20"),  # no source key
            _app(4, "Gamma", "Data Scientist", "applied", "2026-09-10",
                 source="referral"),
        ])

    def _ids(self, **kw):
        kw.setdefault("out", str(self.tmp / "r.csv"))
        R.build_report(**kw)
        with open(kw["out"], newline="", encoding="utf-8") as f:
            return [row["id"] for row in csv.DictReader(f)]

    def test_no_filters_returns_all(self):
        # sorted by date_added (app 3 added 2026-08-20 comes first)
        self.assertEqual(self._ids(), ["3", "1", "2", "4"])

    def test_status_filter(self):
        self.assertEqual(self._ids(status="applied"), ["1", "4"])

    def test_source_filter(self):
        self.assertEqual(self._ids(source="Referral"), ["1", "4"])  # case-insensitive

    def test_company_substring_filter(self):
        self.assertEqual(self._ids(company="acme"), ["1", "2"])

    def test_since_until_filters(self):
        self.assertEqual(self._ids(since="2026-09-01"), ["1", "2", "4"])
        self.assertEqual(self._ids(until="2026-09-05"), ["3", "1", "2"])
        self.assertEqual(self._ids(since="2026-09-01", until="2026-09-05"),
                         ["1", "2"])

    def test_filters_anded(self):
        self.assertEqual(self._ids(status="applied", source="referral"), ["1", "4"])
        self.assertEqual(self._ids(company="acme", status="rejected"), ["2"])
        self.assertEqual(self._ids(status="offer"), [])

    def test_csv_format_columns(self):
        p = R.build_report(out=str(self.tmp / "r.csv"))
        self.assertTrue(p.exists())
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.assertEqual(reader.fieldnames, R.REPORT_FIELDS)
            rows = list(reader)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["company"], "Beta")  # sorted by date_added
        self.assertEqual(rows[0]["source"], "")      # missing source -> ""

    def test_md_format(self):
        p = R.build_report(format="md", out=str(self.tmp / "r.md"))
        text = p.read_text(encoding="utf-8")
        self.assertIn("| id | company | role | status | source | notes | "
                      "date_added | date_updated |", text)
        self.assertIn("| 1 | Acme |", text)

    def test_default_out_path(self):
        p = R.build_report()
        self.assertEqual(p.parent, self.tmp)
        self.assertTrue(p.name.startswith("report-"))
        self.assertTrue(p.name.endswith(".csv"))
        p2 = R.build_report(format="md")
        self.assertTrue(p2.name.endswith(".md"))

    def test_invalid_inputs(self):
        with self.assertRaises(R.ReportsError):
            R.build_report(status="hired")
        with self.assertRaises(R.ReportsError) as cm:
            R.build_report(since="09/01/2026")
        self.assertIn("YYYY-MM-DD", str(cm.exception))
        with self.assertRaises(R.ReportsError):
            R.build_report(format="pdf")

    def test_friendly_errors_name_next_command(self):
        try:
            R.build_report(status="hired")
        except R.ReportsError as e:
            self.assertTrue(str(e).rstrip().endswith(
                "Next: run `python -m candid report build --help`"))


if __name__ == "__main__":
    unittest.main()
