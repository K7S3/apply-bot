"""Tests for the post-accept milestone tracker.

Run: CANDID_DATA_DIR=/tmp/candid-test-postaccept python -m unittest discover -s tests
"""
import os
import shutil
import sys
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-postaccept")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Clean the dir the module actually writes to (env may be overridden by the
# full-suite runner).
TEST_DIR = Path(os.environ["CANDID_DATA_DIR"])


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


def _record(**kw):
    from candid import postaccept as PA
    args = dict(company="Acme", role="Data Scientist", start_date="2026-10-05",
                base=180000, bonus_target_pct=15, sign_on=20000,
                shares=480, vest_years=4, schedule="25/25/25/25",
                cliff_months=12)
    args.update(kw)
    return PA.record_acceptance(**args)


class DateMathTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_cliff_one_year(self):
        from candid import postaccept as PA
        self.assertEqual(PA.cliff_date(date(2026, 10, 5), 12), date(2027, 10, 5))

    def test_cliff_month_end_clamp(self):
        from candid import postaccept as PA
        # Jan 31 + 1 month -> Feb 28 (2027 not a leap year)
        self.assertEqual(PA.cliff_date("2027-01-31", 1), date(2027, 2, 28))

    def test_add_months_year_rollover(self):
        from candid import postaccept as PA
        self.assertEqual(PA.add_months(date(2026, 11, 15), 3), date(2027, 2, 15))

    def test_cliff_negative_rejected(self):
        from candid import postaccept as PA
        with self.assertRaises(PA.PostAcceptError):
            PA.cliff_date("2026-10-05", -1)

    def test_bad_date_rejected(self):
        from candid import postaccept as PA
        with self.assertRaises(PA.PostAcceptError):
            PA.cliff_date("not-a-date", 12)


class RecordTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_record_round_trip(self):
        from candid import postaccept as PA
        rec = _record()
        self.assertEqual(rec["company"], "Acme")
        self.assertEqual(rec["start_date"], "2026-10-05")
        loaded = PA.load_record()
        self.assertEqual(loaded["role"], "Data Scientist")

    def test_record_requires_company_role(self):
        from candid import postaccept as PA
        with self.assertRaises(PA.PostAcceptError):
            PA.record_acceptance(company="", role="DS", start_date="2026-10-05")
        with self.assertRaises(PA.PostAcceptError):
            PA.record_acceptance(company="Acme", role=" ", start_date="2026-10-05")

    def test_record_rejects_bad_schedule(self):
        from candid import postaccept as PA
        with self.assertRaises(PA.PostAcceptError):
            _record(schedule="50/50")  # sums to 100 but 2 parts vs 4 years
        with self.assertRaises(PA.PostAcceptError):
            _record(schedule="30/30/30/30")  # sums to 120

    def test_record_rejects_negative_money(self):
        from candid import postaccept as PA
        with self.assertRaises(PA.PostAcceptError):
            _record(base=-100)

    def test_load_without_record_raises(self):
        from candid import postaccept as PA
        with self.assertRaises(PA.PostAcceptError):
            PA.load_record()

    def test_rerecord_regenerates_milestones(self):
        from candid import postaccept as PA
        _record()
        PA.mark_milestone_done("day-30")
        _record(start_date="2027-01-04")  # re-record resets template
        ms = {m["id"]: m for m in PA.list_milestones()}
        self.assertFalse(ms["day-30"]["done"])
        self.assertEqual(ms["day-30"]["due"], "2027-02-03")


class VestingTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_total_shares_conserved(self):
        from candid import postaccept as PA
        rec = _record(shares=480)
        events = PA.vesting_events(rec, [])
        self.assertAlmostEqual(sum(e["shares"] for e in events), 480.0, places=2)

    def test_cliff_lump_then_monthly(self):
        from candid import postaccept as PA
        rec = _record(shares=480)  # 120 in year 1, all on the cliff
        events = PA.vesting_events(rec, [])
        first = events[0]
        self.assertEqual(first["date"], "2027-10-05")
        self.assertEqual(first["kind"], "cliff")
        self.assertAlmostEqual(first["shares"], 120.0, places=2)
        # year-2 monthly vesting resumes the month after the cliff
        second = events[1]
        self.assertEqual(second["date"], "2027-11-05")
        self.assertEqual(second["kind"], "vest")
        self.assertAlmostEqual(second["shares"], 10.0, places=2)

    def test_nothing_vests_before_cliff(self):
        from candid import postaccept as PA
        rec = _record(shares=480)
        events = PA.vesting_events(rec, [])
        self.assertTrue(all(e["date"] >= "2027-10-05" for e in events))

    def test_events_sorted(self):
        from candid import postaccept as PA
        rec = _record(shares=100)
        events = PA.vesting_events(rec, [])
        dates = [e["date"] for e in events]
        self.assertEqual(dates, sorted(dates))

    def test_no_cliff_means_monthly_from_start(self):
        from candid import postaccept as PA
        rec = _record(shares=480, cliff_months=0)
        events = PA.vesting_events(rec, [])
        self.assertEqual(events[0]["date"], "2026-10-05")
        self.assertEqual(events[0]["kind"], "vest")

    def test_custom_schedule(self):
        from candid import postaccept as PA
        rec = _record(shares=100, schedule="40/30/20/10")
        events = PA.vesting_events(rec, [])
        cliff = [e for e in events if e["kind"] == "cliff"]
        self.assertEqual(len(cliff), 1)
        self.assertAlmostEqual(cliff[0]["shares"], 40.0, places=2)


class RefresherTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_add_and_list(self):
        from candid import postaccept as PA
        _record()
        r = PA.add_refresher("2027 refresher", "2027-10-05", 150)
        self.assertEqual(r["label"], "2027 refresher")
        self.assertEqual(len(PA.list_refreshers()), 1)

    def test_duplicate_label_rejected(self):
        from candid import postaccept as PA
        _record()
        PA.add_refresher("2027 refresher", "2027-10-05", 150)
        with self.assertRaises(PA.PostAcceptError):
            PA.add_refresher("2027 Refresher", "2028-10-05", 150)

    def test_refresher_vests_without_cliff(self):
        from candid import postaccept as PA
        rec = _record(shares=0)
        PA.add_refresher("2027 refresher", "2027-10-05", 120)
        state_events = PA.vesting_events()
        first_ref = [e for e in state_events
                     if e["source"] == "refresher: 2027 refresher"][0]
        self.assertEqual(first_ref["date"], "2027-10-05")
        self.assertEqual(first_ref["kind"], "vest")
        ref_total = sum(e["shares"] for e in state_events
                        if e["source"].startswith("refresher"))
        self.assertAlmostEqual(ref_total, 120.0, places=2)

    def test_zero_shares_rejected(self):
        from candid import postaccept as PA
        _record()
        with self.assertRaises(PA.PostAcceptError):
            PA.add_refresher("x", "2027-10-05", 0)


class MilestoneTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_template_due_dates(self):
        from candid import postaccept as PA
        ms = PA.first_year_milestones("2026-10-05")
        by_id = {m["id"]: m for m in ms}
        self.assertEqual(len(ms), 5)
        self.assertEqual(by_id["day-30"]["due"], "2026-11-04")
        self.assertEqual(by_id["day-60"]["due"], "2026-12-04")
        self.assertEqual(by_id["day-90"]["due"], "2027-01-03")
        self.assertEqual(by_id["month-6"]["due"], "2027-04-05")
        self.assertEqual(by_id["year-1"]["due"], "2027-10-05")

    def test_auto_created_on_record(self):
        from candid import postaccept as PA
        _record()
        self.assertEqual(len(PA.list_milestones()), 5)

    def test_mark_done(self):
        from candid import postaccept as PA
        _record()
        m = PA.mark_milestone_done("day-30")
        self.assertTrue(m["done"])
        self.assertIsNotNone(m["done_on"])
        with self.assertRaises(PA.PostAcceptError):
            PA.mark_milestone_done("nope")

    def test_add_custom(self):
        from candid import postaccept as PA
        _record()
        m = PA.add_milestone("Finish bootcamp", "2026-10-20", "all modules")
        self.assertTrue(m["id"].startswith("custom-"))
        self.assertEqual(len(PA.list_milestones()), 6)

    def test_sorted_by_due(self):
        from candid import postaccept as PA
        _record()
        PA.add_milestone("Early task", "2026-10-06")
        ms = PA.list_milestones()
        self.assertEqual(ms[0]["title"], "Early task")


class PromoTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_three_checkins(self):
        from candid import postaccept as PA
        cs = PA.promotion_checkins("2026-10-05")
        self.assertEqual(len(cs), 3)
        self.assertEqual(cs[0]["due"], "2027-04-05")
        self.assertEqual(cs[1]["due"], "2027-07-05")
        self.assertEqual(cs[2]["due"], "2027-10-05")
        for c in cs:
            self.assertTrue(c["prompt"])


class ReminderTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_vest_and_milestone_reminders(self):
        from candid import postaccept as PA
        _record(shares=480)
        # 2027-09-20: day-30/60/90/month-6 overdue; cliff 15 days out
        rs = PA.upcoming_reminders("2027-09-20", days=30)
        kinds = {r["kind"] for r in rs}
        self.assertIn("cliff vest", kinds)
        self.assertIn("milestone", kinds)
        self.assertIn("cliff", kinds)
        overdue = [r for r in rs if r["overdue"]]
        self.assertTrue(any(r["kind"] == "milestone" for r in overdue))

    def test_done_milestones_excluded(self):
        from candid import postaccept as PA
        _record(shares=0)
        PA.mark_milestone_done("day-30")
        rs = PA.upcoming_reminders("2026-11-10", days=30)
        self.assertFalse(any("learn the ropes" in r["title"] for r in rs))

    def test_promo_checkin_included(self):
        from candid import postaccept as PA
        _record(shares=0)
        rs = PA.upcoming_reminders("2027-03-20", days=30)
        self.assertTrue(any(r["kind"] == "promo-checkin" for r in rs))

    def test_sorted_by_date(self):
        from candid import postaccept as PA
        _record(shares=480)
        rs = PA.upcoming_reminders("2027-09-20", days=60)
        dates = [r["date"] for r in rs]
        self.assertEqual(dates, sorted(dates))

    def test_no_record_raises(self):
        from candid import postaccept as PA
        with self.assertRaises(PA.PostAcceptError):
            PA.upcoming_reminders("2027-01-01")


class TenureTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_tenure_math(self):
        from candid import postaccept as PA
        t = PA.tenure("2026-10-05", "2026-11-04")
        self.assertEqual(t["days"], 30)
        self.assertTrue(t["started"])

    def test_not_started(self):
        from candid import postaccept as PA
        t = PA.tenure("2026-10-05", "2026-09-01")
        self.assertFalse(t["started"])
        self.assertLess(t["days"], 0)


class CompTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_vested_vs_unvested(self):
        from candid import postaccept as PA
        _record(shares=480)  # cliff 2027-10-05 vests 120
        c = PA.comp_realization(100.0, as_of="2027-10-05")
        self.assertAlmostEqual(c["vested_shares"], 120.0, places=2)
        self.assertAlmostEqual(c["vested_value"], 12000.0, places=2)
        self.assertAlmostEqual(c["unvested_shares"], 360.0, places=2)
        self.assertAlmostEqual(c["total_value"], 48000.0, places=2)

    def test_nothing_vested_before_cliff(self):
        from candid import postaccept as PA
        _record(shares=480)
        c = PA.comp_realization(100.0, as_of="2027-01-01")
        self.assertEqual(c["vested_shares"], 0)
        self.assertEqual(c["unvested_shares"], 480)

    def test_by_year_buckets(self):
        from candid import postaccept as PA
        _record(shares=480)
        c = PA.comp_realization(50.0, as_of="2028-06-01")
        self.assertIn("2027", c["by_year"])
        self.assertIn("2028", c["by_year"])

    def test_bad_price_rejected(self):
        from candid import postaccept as PA
        _record()
        with self.assertRaises(PA.PostAcceptError):
            PA.comp_realization(-5)


class DashboardTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_dashboard_sections(self):
        from candid import postaccept as PA
        _record()
        out = PA.render_dashboard("2026-11-01")
        self.assertIn("Post-accept: Acme", out)
        self.assertIn("Cliff:", out)
        self.assertIn("Milestones (0/5 done)", out)
        self.assertIn("Upcoming (30 days)", out)

    def test_dashboard_marks_done(self):
        from candid import postaccept as PA
        _record()
        PA.mark_milestone_done("day-30")
        out = PA.render_dashboard("2026-11-10")
        self.assertIn("Milestones (1/5 done)", out)


if __name__ == "__main__":
    unittest.main()
