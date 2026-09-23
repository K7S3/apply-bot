"""Tests for the vesting schedule visualizer (batch-50).

Run: CANDID_DATA_DIR=/tmp/candid-test-vesting python -m unittest discover -s tests
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-vesting")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import vesting as V  # noqa: E402

TEST_DIR = Path("/tmp/candid-test-vesting")


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


def _grant(**kw):
    base = {"kind": "dollars", "total": 200000, "start": "2026-01-01",
            "years": 4, "freq": "monthly", "cliff_months": 12,
            "schedule": "straight", "label": "Test"}
    base.update(kw)
    return base


class ScheduleBuildTest(unittest.TestCase):
    def test_monthly_straight_cliff_event_count(self):
        ev = V.build_schedule(_grant())
        # months 12..48 -> 37 events
        self.assertEqual(len(ev), 37)
        self.assertEqual(ev[0]["date"], date(2027, 1, 1))
        self.assertTrue(ev[0]["is_cliff"])
        self.assertFalse(any(e["is_cliff"] for e in ev[1:]))

    def test_total_sums_exactly_dollars(self):
        ev = V.build_schedule(_grant(total=200000))
        self.assertAlmostEqual(ev[-1]["cumulative"], 200000.0)

    def test_total_sums_exactly_shares(self):
        ev = V.build_schedule(_grant(kind="shares", total=1000,
                                     grant_price=50))
        self.assertEqual(ev[-1]["cumulative"], 1000)
        self.assertTrue(all(float(e["units"]).is_integer() for e in ev))

    def test_cliff_amount_is_first_year(self):
        ev = V.build_schedule(_grant())
        self.assertAlmostEqual(ev[0]["units"], 50000.0)  # 25% of 200k

    def test_no_cliff(self):
        ev = V.build_schedule(_grant(cliff_months=0))
        self.assertFalse(any(e["is_cliff"] for e in ev))
        self.assertEqual(len(ev), 48)
        self.assertIsNone(V.cliff_summary(ev))

    def test_quarterly_freq(self):
        ev = V.build_schedule(_grant(freq="quarterly"))
        # quarters at months 12,15,...,48 -> 13 events
        self.assertEqual(len(ev), 13)
        self.assertTrue(ev[0]["is_cliff"])

    def test_annual_freq(self):
        ev = V.build_schedule(_grant(freq="annual"))
        self.assertEqual(len(ev), 4)
        self.assertEqual([e["units"] for e in ev],
                         [50000.0, 50000.0, 50000.0, 50000.0])

    def test_amazon_back_loaded(self):
        ev = V.build_schedule(_grant(kind="shares", total=1000,
                                     grant_price=50, freq="annual",
                                     schedule="amazon"))
        self.assertEqual([e["units"] for e in ev], [50, 150, 400, 400])

    def test_front_loaded(self):
        ev = V.build_schedule(_grant(freq="annual", schedule="front"))
        self.assertEqual([e["units"] for e in ev],
                         [80000.0, 60000.0, 40000.0, 20000.0])

    def test_custom_schedule(self):
        ev = V.build_schedule(_grant(freq="annual",
                                     schedule="custom:40/30/20/10"))
        self.assertEqual([e["units"] for e in ev],
                         [80000.0, 60000.0, 40000.0, 20000.0])

    def test_custom_schedule_must_sum_100(self):
        with self.assertRaises(V.VestingError):
            V.build_schedule(_grant(schedule="custom:30/30/30"))

    def test_custom_schedule_years_must_match(self):
        with self.assertRaises(V.VestingError):
            V.build_schedule(_grant(years=3, schedule="custom:25/25/25/25"))

    def test_amazon_preset_wrong_years(self):
        with self.assertRaises(V.VestingError):
            V.build_schedule(_grant(years=3, schedule="amazon"))

    def test_month_end_dates(self):
        self.assertEqual(V._add_months(date(2026, 1, 31), 1),
                         date(2026, 2, 28))
        self.assertEqual(V._add_months(date(2024, 1, 31), 1),
                         date(2024, 2, 29))  # leap year

    def test_cliff_beyond_period_rejected(self):
        with self.assertRaises(V.VestingError):
            V.build_schedule(_grant(years=4, cliff_months=49))

    def test_fractional_shares_rejected(self):
        with self.assertRaises(V.VestingError):
            V.build_schedule(_grant(kind="shares", total=1000.5,
                                    grant_price=50))


class CliffSummaryTest(unittest.TestCase):
    def test_cliff_summary(self):
        ev = V.build_schedule(_grant())
        cs = V.cliff_summary(ev)
        self.assertEqual(cs["date"], date(2027, 1, 1))
        self.assertEqual(cs["month"], 12)
        self.assertAlmostEqual(cs["pct_of_grant"], 25.0)


class PriceScenarioTest(unittest.TestCase):
    def test_price_path_compounds(self):
        p = V.price_path(100.0, 12, 12.0)
        self.assertEqual(len(p), 13)
        self.assertAlmostEqual(p[0], 100.0)
        self.assertAlmostEqual(p[12], 112.0, places=6)

    def test_scenarios_ordered(self):
        ev = V.build_schedule(_grant(kind="shares", total=1000,
                                     grant_price=50))
        s = V.scenario_series(ev, 48, 50.0,
                              {"bear": -10.0, "base": 0.0, "bull": 10.0},
                              grant_price=50.0)
        self.assertLess(s["bear"][-1], s["base"][-1])
        self.assertLess(s["base"][-1], s["bull"][-1])
        self.assertAlmostEqual(s["base"][-1], 50000.0, places=0)

    def test_dollar_grant_scenarios_flat(self):
        ev = V.build_schedule(_grant())
        s = V.scenario_series(ev, 48, 1.0)
        self.assertEqual(s["bear"], s["bull"])


class ChartTableTest(unittest.TestCase):
    def test_chart_renders(self):
        ev = V.build_schedule(_grant())
        series = {"vested $": V.cumulative_value_series(ev, 48)}
        out = V.render_chart(series, 48)
        self.assertIn("Cumulative", out)
        self.assertIn("#", out)
        self.assertIn("mo 48", out)

    def test_table_marks_cliff(self):
        ev = V.build_schedule(_grant())
        out = V.render_table(ev)
        self.assertIn("CLIFF", out)
        self.assertIn("2027-01-01", out)
        self.assertIn("TOTAL", out)


class RefresherTest(unittest.TestCase):
    def test_parse_refresher_month_offset(self):
        r = V.parse_refresher("40000:2:12", date(2026, 1, 1))
        self.assertEqual(r["start"], date(2027, 1, 1))
        self.assertEqual(r["total"], 40000)
        self.assertEqual(r["years"], 2)

    def test_parse_refresher_date(self):
        r = V.parse_refresher("40000:2:2027-06-01", date(2026, 1, 1))
        self.assertEqual(r["start"], date(2027, 6, 1))

    def test_parse_refresher_bad_spec(self):
        with self.assertRaises(V.VestingError):
            V.parse_refresher("40000:2", date(2026, 1, 1))

    def test_stack_totals(self):
        ev = V.add_refreshers(_grant(), ["40000:2:12"])
        self.assertAlmostEqual(ev[-1]["cumulative"], 240000.0)
        grants = {e["grant"] for e in ev}
        self.assertEqual(len(grants), 2)

    def test_refresher_no_cliff(self):
        ev = V.add_refreshers(_grant(), ["40000:2:12"])
        ref = [e for e in ev if e["grant"].startswith("Refresher")]
        self.assertFalse(any(e["is_cliff"] for e in ref))
        self.assertEqual(ref[0]["date"], date(2027, 2, 1))

    def test_summary_mentions_assumption(self):
        ev = V.add_refreshers(_grant(), ["40000:2:12"])
        out = V.render_refresher_summary(_grant(), ["40000:2:12"], ev)
        self.assertIn("no cliff", out)
        self.assertIn("$240,000", out)


class OfferCompareTest(unittest.TestCase):
    def _offers(self):
        return [
            {"company": "Acme", "role": "SWE", "level": "L4",
             "equity_total": 200000, "vest_years": 4,
             "vest_schedule": "25/25/25/25", "start_date": "2026-01-01"},
            {"company": "Beta", "role": "SWE", "level": "L4",
             "equity_total": 200000, "vest_years": 4,
             "vest_schedule": "5/15/40/40", "start_date": "2026-01-01"},
        ]

    def test_compare_values(self):
        rows = V.compare_offers(self._offers())
        acme = next(r for r in rows if r["company"] == "Acme")
        beta = next(r for r in rows if r["company"] == "Beta")
        self.assertAlmostEqual(acme["m12"], 50000.0, places=0)
        self.assertAlmostEqual(beta["m12"], 10000.0, places=0)  # 5% of 200k
        self.assertAlmostEqual(acme["m48"], 200000.0, places=0)
        self.assertAlmostEqual(beta["m48"], 200000.0, places=0)

    def test_render_compare(self):
        out = V.render_offer_vesting_comparison(
            V.compare_offers(self._offers()))
        self.assertIn("Acme", out)
        self.assertIn("Beta", out)
        self.assertIn("Vested mo 12", out)

    def test_compare_empty(self):
        self.assertIn("No offers", V.render_offer_vesting_comparison([]))

    def test_grant_from_offer(self):
        spec = V.grant_from_offer(self._offers()[0])
        self.assertEqual(spec["total"], 200000)
        self.assertEqual(spec["years"], 4)


class DepartureTest(unittest.TestCase):
    def test_departure_math(self):
        ev = V.build_schedule(_grant())
        a = V.departure_analysis(ev, 18)
        self.assertAlmostEqual(a["vested"] + a["forfeited"], 200000.0,
                               places=0)
        self.assertAlmostEqual(a["pct_vested"], 37.5, places=1)

    def test_departure_month_zero(self):
        ev = V.build_schedule(_grant())
        a = V.departure_analysis(ev, 0)
        self.assertEqual(a["vested"], 0)
        self.assertAlmostEqual(a["forfeited"], 200000.0)

    def test_departure_at_end(self):
        ev = V.build_schedule(_grant())
        a = V.departure_analysis(ev, 48)
        self.assertAlmostEqual(a["vested"], 200000.0, places=0)
        self.assertAlmostEqual(a["forfeited"], 0.0)

    def test_departure_negative_rejected(self):
        ev = V.build_schedule(_grant())
        with self.assertRaises(V.VestingError):
            V.departure_analysis(ev, -1)

    def test_render_departure(self):
        ev = V.build_schedule(_grant())
        out = V.render_departure(V.departure_analysis(ev, 18), "Test")
        self.assertIn("Forfeited", out)
        self.assertIn("month 18", out)


class HandcuffsTest(unittest.TestCase):
    def test_curve_monotonic(self):
        ev = V.build_schedule(_grant())
        curve = V.handcuffs(ev, 48)
        self.assertAlmostEqual(curve[0], 200000.0, places=0)
        self.assertAlmostEqual(curve[-1], 0.0, places=0)
        self.assertTrue(all(b <= a for a, b in zip(curve, curve[1:])))

    def test_render_handcuffs(self):
        ev = V.build_schedule(_grant())
        out = V.render_handcuffs(ev, 48, label="Test")
        self.assertIn("handcuffs", out.lower())
        self.assertIn("unvested", out.lower())


class TaxEventsTest(unittest.TestCase):
    def test_tax_sums_to_grant(self):
        ev = V.build_schedule(_grant(kind="shares", total=1000,
                                     grant_price=50))
        te = V.tax_events(ev, grant_price=50.0)
        self.assertAlmostEqual(sum(t["taxable"] for t in te), 50000.0,
                               places=0)

    def test_tax_render_has_disclaimer(self):
        ev = V.build_schedule(_grant())
        out = V.render_tax_events(V.tax_events(ev), "Test")
        self.assertIn("not advice", out)
        self.assertIn("Taxable events", out)


class ExportTest(unittest.TestCase):
    def setUp(self):
        _clean()
        self.td = tempfile.TemporaryDirectory(dir=str(TEST_DIR))

    def tearDown(self):
        self.td.cleanup()

    def test_export_writes_report(self):
        out = Path(self.td.name) / "vesting.md"
        p = V.export_report(_grant(label="Acme"), path=out)
        text = p.read_text()
        self.assertIn("# Vesting report", text)
        self.assertIn("## Cliff", text)
        self.assertIn("## Cumulative vested value", text)
        self.assertIn("## Departure snapshot", text)
        self.assertIn("## Taxable events", text)

    def test_export_with_refreshers(self):
        out = Path(self.td.name) / "v2.md"
        p = V.export_report(_grant(label="Acme"), path=out,
                            refresher_specs=["40000:2:12"])
        self.assertIn("## Refreshers", p.read_text())


class CliSmokeTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def _run(self, argv):
        from candid import __main__ as CLI
        buf = io.StringIO()
        with redirect_stdout(buf):
            CLI.main(argv)
        return buf.getvalue()

    def test_cli_timeline(self):
        out = self._run(["vesting", "timeline", "--value", "200000",
                         "--start", "2026-01-01"])
        self.assertIn("CLIFF", out)

    def test_cli_chart(self):
        out = self._run(["vesting", "chart", "--value", "200000"])
        self.assertIn("Cumulative", out)

    def test_cli_depart(self):
        out = self._run(["vesting", "depart", "--value", "200000",
                         "--at-month", "18"])
        self.assertIn("Forfeited", out)

    def test_cli_handcuffs(self):
        out = self._run(["vesting", "handcuffs", "--value", "200000"])
        self.assertIn("unvested", out.lower())

    def test_cli_tax(self):
        out = self._run(["vesting", "tax", "--value", "200000"])
        self.assertIn("Taxable events", out)

    def test_cli_refresher(self):
        out = self._run(["vesting", "refresher", "--value", "200000",
                         "--refresher", "40000:2:12"])
        self.assertIn("Refresher", out)

    def test_cli_compare_no_offers(self):
        out = self._run(["vesting", "compare"])
        self.assertIn("No offers", out)

    def test_cli_export(self):
        with tempfile.TemporaryDirectory(dir=str(TEST_DIR)) as td:
            outp = str(Path(td) / "r.md")
            out = self._run(["vesting", "export", "--value", "200000",
                             "--out", outp])
            self.assertIn("exported to", out)
            self.assertTrue(Path(outp).exists())

    def test_cli_missing_grant_errors_cleanly(self):
        from candid import __main__ as CLI
        with self.assertRaises(SystemExit):
            with redirect_stdout(io.StringIO()):
                CLI.main(["vesting", "timeline"])


if __name__ == "__main__":
    unittest.main()
