"""Tests for the equity deep-dives (batch-44).

Covers: type cards, lifecycles, ISO/NSO guide, glossary, vesting math,
cliff math, scenarios, exercise costs, refresh stacking, dilution,
checklist, quiz, and CLI wiring.
"""
import os
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import equity as E  # noqa: E402


class TypesTest(unittest.TestCase):
    def test_all_four_types_present(self):
        for k in ("rsu", "options", "iso", "nso"):
            card = E.get_type(k)
            self.assertIn("name", card)
            self.assertTrue(card["watch_outs"])

    def test_unknown_type_raises(self):
        with self.assertRaises(E.EquityError):
            E.get_type("crypto")

    def test_render_all_contains_disclaimer(self):
        out = E.render_types()
        self.assertIn("RSUs (Restricted Stock Units)", out)
        self.assertIn("Incentive Stock Options", out)
        self.assertIn("not tax", out)

    def test_render_single_kind(self):
        out = E.render_types("iso")
        self.assertIn("Incentive Stock Options", out)
        self.assertNotIn("Restricted Stock Units", out)


class LifecycleTest(unittest.TestCase):
    def test_rsu_lifecycle(self):
        out = E.get_lifecycle("rsu")
        self.assertIn("sell to cover", out.lower())
        self.assertIn("not tax", out)

    def test_options_lifecycle(self):
        out = E.get_lifecycle("options")
        self.assertIn("Exercise", out)
        self.assertIn("post-termination", out)

    def test_unknown_lifecycle_raises(self):
        with self.assertRaises(E.EquityError):
            E.get_lifecycle("warrants")


class IsoNsoTest(unittest.TestCase):
    def test_guide_covers_key_concepts(self):
        out = E.render_iso_nso()
        for phrase in ("qualifying", "disqualifying", "AMT", "2 years",
                       "1 year", "ordinary income"):
            self.assertIn(phrase, out)
        self.assertIn("not advice", out)


class GlossaryTest(unittest.TestCase):
    def test_full_glossary(self):
        g = E.glossary()
        self.assertGreaterEqual(len(g), 12)
        self.assertIn("cliff", g)

    def test_term_lookup(self):
        d = E.glossary("cliff")
        self.assertEqual(list(d), ["cliff"])

    def test_fuzzy_term_lookup(self):
        d = E.glossary("409")
        self.assertIn("409a", d)

    def test_unknown_term_raises(self):
        with self.assertRaises(E.EquityError):
            E.glossary("blockchain")

    def test_render_glossary(self):
        out = E.render_glossary("strike price")
        self.assertIn("strike price", out)


class ParseScheduleTest(unittest.TestCase):
    def test_standard_schedule(self):
        self.assertEqual(E.parse_schedule("25/25/25/25"), [0.25] * 4)

    def test_front_loaded(self):
        self.assertEqual(E.parse_schedule("40/30/20/10"), [0.4, 0.3, 0.2, 0.1])

    def test_bad_sum_raises(self):
        with self.assertRaises(E.EquityError):
            E.parse_schedule("25/25/25")

    def test_unparseable_raises(self):
        with self.assertRaises(E.EquityError):
            E.parse_schedule("a/b/c")

    def test_negative_raises(self):
        with self.assertRaises(E.EquityError):
            E.parse_schedule("50/50/-10/10")


class VestTest(unittest.TestCase):
    def test_annual_timeline_sums_to_grant(self):
        ev = E.vesting_timeline(200000, 50, "25/25/25/25", "2026-01-01",
                                "annual", 0)
        self.assertEqual(len(ev), 4)
        self.assertEqual(ev[0]["date"], "2027-01-01")
        self.assertAlmostEqual(sum(e["value"] for e in ev), 200000)
        self.assertAlmostEqual(ev[-1]["cumulative_shares"], 4000)

    def test_quarterly_splits_annual_parts(self):
        ev = E.vesting_timeline(120000, 30, "25/25/25/25", "2026-01-01",
                                "quarterly", 0)
        self.assertEqual(len(ev), 16)
        self.assertAlmostEqual(sum(e["value"] for e in ev), 120000)

    def test_monthly_with_cliff_accrues(self):
        ev = E.vesting_timeline(96000, 20, "25/25/25/25", "2026-01-01",
                                "monthly", 12)
        # first event is the 12-month cliff chunk: 25% of 4800 shares
        self.assertEqual(ev[0]["date"], "2027-01-01")
        self.assertAlmostEqual(ev[0]["shares"], 1200)
        self.assertAlmostEqual(sum(e["value"] for e in ev), 96000)

    def test_no_cliff_monthly_first_event(self):
        ev = E.vesting_timeline(96000, 20, "25/25/25/25", "2026-01-01",
                                "monthly", 0)
        self.assertEqual(ev[0]["date"], "2026-02-01")
        self.assertAlmostEqual(ev[0]["shares"], 100)

    def test_invalid_inputs_raise(self):
        with self.assertRaises(E.EquityError):
            E.vesting_timeline(0, 50, "25/25/25/25", "2026-01-01", "annual", 0)
        with self.assertRaises(E.EquityError):
            E.vesting_timeline(200000, 50, "25/25/25/25", "2026-01-01",
                                "weekly", 0)
        with self.assertRaises(E.EquityError):
            E.vesting_timeline(200000, 50, "25/25/25/25", "not-a-date",
                                "annual", 0)

    def test_render_vest(self):
        out = E.render_vest(200000, 50, "25/25/25/25", "2026-01-01",
                            "annual", 0)
        self.assertIn("Vesting timeline", out)
        self.assertIn("$200,000", out)
        self.assertIn("not tax", out)


class CliffTest(unittest.TestCase):
    def test_cliff_event_shape(self):
        ev = E.cliff_table(4000, 48, 12)
        self.assertEqual(ev[0]["month"], 12)
        self.assertAlmostEqual(ev[0]["shares"], 1000)
        self.assertEqual(len(ev), 37)  # cliff chunk + 36 monthly
        self.assertAlmostEqual(sum(e["shares"] for e in ev), 4000)

    def test_no_cliff(self):
        ev = E.cliff_table(1200, 12, 0)
        self.assertEqual(len(ev), 12)
        self.assertAlmostEqual(ev[0]["shares"], 100)

    def test_bad_cliff_raises(self):
        with self.assertRaises(E.EquityError):
            E.cliff_table(4000, 48, 60)

    def test_render_cliff(self):
        out = E.render_cliff(4000, 48, 12)
        self.assertIn("cliff", out.lower())
        self.assertIn("month 11", out.lower())


class ScenariosTest(unittest.TestCase):
    def test_rsu_scales_with_price(self):
        rows = E.scenario_table("rsu", shares=1000, prices=[10, 20])
        self.assertEqual([r["total"] for r in rows], [10000, 20000])

    def test_options_underwater_worth_zero(self):
        rows = E.scenario_table("options", count=1000, strike=25,
                                prices=[10, 25, 30])
        self.assertEqual([r["total"] for r in rows], [0, 0, 5000])

    def test_prices_deduped_and_sorted(self):
        self.assertEqual(E.parse_prices("80,40,40"), [40.0, 80.0])

    def test_bad_prices_raise(self):
        with self.assertRaises(E.EquityError):
            E.parse_prices("")
        with self.assertRaises(E.EquityError):
            E.parse_prices("10,abc")

    def test_render_scenarios(self):
        out = E.render_scenarios("options", 0, 1000, 5, [10, 25])
        self.assertIn("Break-even", out)
        self.assertIn("not tax", out)


class ExerciseTest(unittest.TestCase):
    def test_nso_math(self):
        r = E.exercise_cost(10000, 5, 25, "nso", 0.32)
        self.assertEqual(r["cash_cost"], 50000)
        self.assertEqual(r["spread"], 200000)
        self.assertEqual(r["est_tax_at_exercise"], 64000)
        self.assertEqual(r["total_outlay"], 114000)

    def test_iso_no_regular_tax_at_exercise(self):
        r = E.exercise_cost(10000, 5, 25, "iso", 0.32)
        self.assertEqual(r["est_tax_at_exercise"], 0)
        self.assertEqual(r["total_outlay"], 50000)
        self.assertIn("AMT", r["tax_note"])

    def test_underwater_spread_zero(self):
        r = E.exercise_cost(1000, 30, 20, "nso", 0.32)
        self.assertEqual(r["spread"], 0)
        self.assertEqual(r["est_tax_at_exercise"], 0)

    def test_bad_kind_raises(self):
        with self.assertRaises(E.EquityError):
            E.exercise_cost(100, 5, 25, "rsu")

    def test_bad_rate_raises(self):
        with self.assertRaises(E.EquityError):
            E.exercise_cost(100, 5, 25, "nso", 1.5)

    def test_render_exercise(self):
        out = E.render_exercise(E.exercise_cost(1000, 5, 25, "nso"))
        self.assertIn("Total out-of-pocket", out)
        self.assertIn("placeholder", out)


class RefreshTest(unittest.TestCase):
    def test_stacking(self):
        grants = E.parse_grants("400000:2026:4,100000:2027:4")
        rows = E.refresh_stack(grants)
        by_year = {r["year"]: r["total"] for r in rows}
        self.assertEqual(by_year[2026], 100000)
        self.assertEqual(by_year[2027], 125000)
        self.assertEqual(by_year[2030], 25000)

    def test_default_years(self):
        grants = E.parse_grants("200000:2026")
        self.assertEqual(grants[0].years, 4)

    def test_bad_grant_raises(self):
        with self.assertRaises(E.EquityError):
            E.parse_grants("bogus")
        with self.assertRaises(E.EquityError):
            E.parse_grants("")

    def test_render_refresh(self):
        out = E.render_refresh(E.parse_grants("400000:2026:4"))
        self.assertIn("Refresh grants", out)
        self.assertIn("2029", out)


class DilutionTest(unittest.TestCase):
    def test_basic_ownership(self):
        r = E.ownership(10000, 10000000)
        self.assertAlmostEqual(r["ownership_pct"], 0.1)
        self.assertNotIn("ownership_after_pct", r)

    def test_pool_increase_dilutes(self):
        r = E.ownership(10000, 10000000, 0.15)
        self.assertLess(r["ownership_after_pct"], r["ownership_pct"])
        self.assertGreater(r["new_shares_issued"], 0)

    def test_over_100_pct_raises(self):
        with self.assertRaises(E.EquityError):
            E.ownership(11_000_000, 10_000_000)

    def test_render_dilution(self):
        out = E.render_dilution(E.ownership(10000, 10000000, 0.15), 10000, 0.15)
        self.assertIn("0.100%", out)
        self.assertIn("not tax", out)


class ChecklistTest(unittest.TestCase):
    def test_twelve_questions(self):
        items = E.get_checklist()
        self.assertEqual(len(items), 12)
        self.assertTrue(all(i["question"] and i["why"] for i in items))

    def test_render_checklist(self):
        out = E.render_checklist()
        self.assertIn("409A", out)
        self.assertIn("not tax", out)

    def test_checklist_json(self):
        import json
        data = json.loads(E.render_checklist(as_json=True))
        self.assertEqual(len(data), 12)


class QuizTest(unittest.TestCase):
    def test_perfect_score(self):
        res = E.quiz_score([1, 2, 1, 1, 1, 2])
        self.assertEqual(res["score"], 6)

    def test_partial_score(self):
        res = E.quiz_score([0, 0, 0, 0, 0, 0])
        self.assertEqual(res["score"], 0)
        self.assertFalse(all(r["correct"] for r in res["results"]))

    def test_parse_answers(self):
        self.assertEqual(E.parse_answers("1,2,1,1,1,2"), [1, 2, 1, 1, 1, 2])

    def test_parse_answers_bad_count_raises(self):
        with self.assertRaises(E.EquityError):
            E.parse_answers("1,2,3")

    def test_render_quiz_questions(self):
        out = E.render_quiz()
        self.assertIn("self-check", out)
        self.assertIn("a)", out)

    def test_render_quiz_scored(self):
        out = E.render_quiz([1, 2, 1, 1, 1, 2])
        self.assertIn("Score: 6/6", out)


class CliWiringTest(unittest.TestCase):
    def test_command_registered(self):
        from candid.__main__ import COMMANDS, SUBCOMMANDS
        self.assertIn("equity", COMMANDS)
        self.assertIn("quiz", SUBCOMMANDS["equity"])
        self.assertEqual(len(SUBCOMMANDS["equity"]), 12)

    def test_parser_builds(self):
        from candid.__main__ import build_parser
        p = build_parser()
        a = p.parse_args(["equity", "vest", "--total", "200000",
                          "--price", "50"])
        self.assertEqual(a.what, "vest")
        self.assertEqual(a.total, 200000)


if __name__ == "__main__":
    unittest.main()
