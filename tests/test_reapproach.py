"""Tests for candid.reapproach (re-approach tracker).

Run: python -m pytest tests/test_reapproach.py -q

Tests pass explicit tmp data dirs via data_dir= — they never touch the
real CANDID_DATA_DIR.
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
        self.td = tempfile.TemporaryDirectory(prefix="candid-test-ra-")
        self.dd = self.td.name

    def tearDown(self):
        self.td.cleanup()

    def _ra(self):
        from candid import reapproach as R
        return R


class AddTest(Base):
    def test_add_computes_retry_dates(self):
        R = self._ra()
        rec = R.add("Acme", "2026-09-01", reason="hiring freeze lifted",
                    data_dir=self.dd)
        self.assertEqual(rec["retry_6mo"], "2027-03-01")
        self.assertEqual(rec["retry_12mo"], "2027-09-01")
        self.assertEqual(rec["status"], "watching")
        self.assertEqual(rec["reason"], "hiring freeze lifted")

    def test_month_end_clamping(self):
        R = self._ra()
        rec = R.add("Acme", "2025-08-31", data_dir=self.dd)
        self.assertEqual(rec["retry_6mo"], "2026-02-28")  # not Feb 31
        self.assertEqual(rec["retry_12mo"], "2026-08-31")

    def test_duplicate_rejected(self):
        R = self._ra()
        R.add("Acme", "2026-09-01", data_dir=self.dd)
        with self.assertRaises(R.ReapproachError) as cm:
            R.add("acme", "2026-09-02", data_dir=self.dd)
        self.assertIn("python -m candid reapproach", str(cm.exception))

    def test_bad_date_rejected(self):
        R = self._ra()
        with self.assertRaises(R.ReapproachError) as cm:
            R.add("Acme", "last week", data_dir=self.dd)
        self.assertIn("YYYY-MM-DD", str(cm.exception))

    def test_bad_status_rejected(self):
        R = self._ra()
        with self.assertRaises(R.ReapproachError):
            R.add("Acme", "2026-09-01", status="maybe", data_dir=self.dd)

    def test_empty_company_rejected(self):
        R = self._ra()
        with self.assertRaises(R.ReapproachError):
            R.add("  ", "2026-09-01", data_dir=self.dd)


class ListRemoveTest(Base):
    def test_list_sorted_by_retry_date(self):
        R = self._ra()
        R.add("Globex", "2026-09-01", data_dir=self.dd)  # retry 2027-03-01
        R.add("Acme", "2026-01-01", data_dir=self.dd)    # retry 2026-07-01
        companies = [r["company"] for r in R.list_companies(
            data_dir=self.dd)]
        self.assertEqual(companies, ["Acme", "Globex"])

    def test_remove(self):
        R = self._ra()
        rec = R.add("Acme", "2026-09-01", data_dir=self.dd)
        self.assertTrue(R.remove(rec["id"], data_dir=self.dd))
        self.assertEqual(R.list_companies(data_dir=self.dd), [])
        self.assertFalse(R.remove("Acme", data_dir=self.dd))

    def test_render_list(self):
        R = self._ra()
        out = R.render_list(data_dir=self.dd)
        self.assertIn("empty", out)
        R.add("Acme", "2026-09-01", reason="new headcount",
              data_dir=self.dd)
        out = R.render_list(data_dir=self.dd)
        self.assertIn("Acme", out)
        self.assertIn("2027-03-01", out)
        self.assertIn("new headcount", out)


class DueTest(Base):
    def setUp(self):
        super().setUp()
        R = self._ra()
        # 6mo retry arrived (2026-07-01), 12mo pending
        R.add("Acme", "2026-01-01", reason="timing, not fit",
              data_dir=self.dd)
        # nothing arrived yet
        R.add("Globex", "2026-08-01", data_dir=self.dd)
        # both horizons arrived
        R.add("Initech", "2025-01-15", reason="great team",
              data_dir=self.dd)

    def _due(self):
        return self._ra().due(today=TODAY, data_dir=self.dd)

    def test_due_lists_arrived(self):
        names = {e["company"] for e in self._due()}
        self.assertEqual(names, {"Acme", "Initech"})

    def test_due_horizon_and_overdue(self):
        due = {e["company"]: e for e in self._due()}
        self.assertEqual(due["Acme"]["due_horizon"], "6mo")
        self.assertEqual(due["Acme"]["due_date"], "2026-07-01")
        self.assertEqual(due["Acme"]["days_overdue"], 83)
        # Initech's 12mo date (2026-01-15) is the one reported
        self.assertEqual(due["Initech"]["due_horizon"], "12mo")

    def test_due_today_counts(self):
        R = self._ra()
        R.add("Hooli", "2026-03-22", data_dir=self.dd)  # 6mo = today
        due = {e["company"]: e for e in self._due()}
        self.assertIn("Hooli", due)
        self.assertEqual(due["Hooli"]["days_overdue"], 0)

    def test_reapproached_excluded_from_due(self):
        R = self._ra()
        R.mark("Acme", "re-approached", today=TODAY, data_dir=self.dd)
        due = {e["company"] for e in self._due()}
        self.assertNotIn("Acme", due)
        self.assertIn("Initech", due)

    def test_render_due(self):
        R = self._ra()
        out = R.render_due(today=TODAY, data_dir=self.dd)
        self.assertIn("Acme", out)
        self.assertIn("Initech", out)
        self.assertNotIn("Globex", out)
        self.assertIn("re-approached", out)


class MarkTest(Base):
    def setUp(self):
        super().setUp()
        R = self._ra()
        self.rec = R.add("Acme", "2026-01-01", data_dir=self.dd)

    def test_mark_due(self):
        R = self._ra()
        rec = R.mark("Acme", "due", data_dir=self.dd)
        self.assertEqual(rec["status"], "due")

    def test_mark_by_id(self):
        R = self._ra()
        rec = R.mark(self.rec["id"], "due", data_dir=self.dd)
        self.assertEqual(rec["status"], "due")

    def test_mark_reapproached_stamps_date(self):
        R = self._ra()
        rec = R.mark("acme", "re-approached", today=TODAY,
                     data_dir=self.dd)
        self.assertEqual(rec["status"], "re-approached")
        self.assertEqual(rec["reapproached_on"], "2026-09-22")

    def test_mark_unknown(self):
        R = self._ra()
        with self.assertRaises(R.ReapproachError) as cm:
            R.mark("Nope", "due", data_dir=self.dd)
        self.assertIn("python -m candid reapproach", str(cm.exception))

    def test_mark_bad_status(self):
        R = self._ra()
        with self.assertRaises(R.ReapproachError):
            R.mark("Acme", "done", data_dir=self.dd)


if __name__ == "__main__":
    unittest.main()
