"""Tests for the benefits comparator (batch-49).

Run: python -m unittest discover -s tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import benefits as B


class HealthPlanTest(unittest.TestCase):
    def test_below_deductible_pays_full_spend(self):
        r = B.health_plan_cost(300, 1500, 0.2, 6000, 800)
        self.assertEqual(r["oop_cost"], 800)
        self.assertEqual(r["total_cost"], 3600 + 800)

    def test_above_deductible_applies_coinsurance(self):
        r = B.health_plan_cost(300, 1500, 0.2, 6000, 8000)
        self.assertAlmostEqual(r["oop_cost"], 1500 + 0.2 * 6500)
        self.assertAlmostEqual(r["total_cost"], 3600 + 2800)

    def test_oop_max_caps_cost(self):
        r = B.health_plan_cost(300, 1500, 0.2, 6000, 200000)
        self.assertEqual(r["oop_cost"], 6000)

    def test_zero_spend_is_just_premiums(self):
        r = B.health_plan_cost(300, 1500, 0.2, 6000, 0)
        self.assertEqual(r["total_cost"], 3600)

    def test_rejects_bad_inputs(self):
        with self.assertRaises(B.BenefitsError):
            B.health_plan_cost(300, 1500, 1.5, 6000, 8000)  # coinsurance > 1
        with self.assertRaises(B.BenefitsError):
            B.health_plan_cost(300, 6000, 0.2, 1500, 8000)  # oop < deductible
        with self.assertRaises(B.BenefitsError):
            B.health_plan_cost(-5, 1500, 0.2, 6000, 8000)


class HealthcareExpectedTest(unittest.TestCase):
    def test_default_scenarios_weighted(self):
        r = B.healthcare_expected_cost(300, 1500, 0.2, 6000)
        self.assertEqual(len(r["scenarios"]), 3)
        manual = sum(p * B.health_plan_cost(300, 1500, 0.2, 6000, s)["total_cost"]
                     for p, s in [(0.5, 1500), (0.35, 6000), (0.15, 25000)])
        self.assertAlmostEqual(r["expected_cost"], manual)

    def test_custom_scenarios(self):
        r = B.healthcare_expected_cost(0, 0, 0, 999999, scenarios=[(1.0, 2000)])
        self.assertAlmostEqual(r["expected_cost"], 0.0)

    def test_probabilities_must_sum_to_one(self):
        with self.assertRaises(B.BenefitsError):
            B.healthcare_expected_cost(300, 1500, 0.2, 6000,
                                       scenarios=[(0.5, 1000), (0.2, 2000)])


class Match401kTest(unittest.TestCase):
    def test_classic_safe_harbor_tiers(self):
        r = B.match_401k(150000, 0.10, "100:3,50:2")
        self.assertAlmostEqual(r["annual_match"], 6000.0)

    def test_contribution_below_first_tier(self):
        r = B.match_401k(150000, 0.02, "100:3,50:2")
        self.assertAlmostEqual(r["annual_match"], 0.02 * 150000)

    def test_parse_formula(self):
        self.assertEqual(B.parse_match_formula("100:3,50:2"), [(1.0, 0.03), (0.5, 0.02)])

    def test_irs_cap_limits_eligible_pay(self):
        r = B.match_401k(1_000_000, 0.10, "100:3,50:2", irs_comp_limit=360000)
        self.assertEqual(r["eligible_pay"], 360000)
        self.assertAlmostEqual(r["annual_match"], 360000 * (0.03 + 0.5 * 0.02))

    def test_bad_formula_raises(self):
        with self.assertRaises(B.BenefitsError):
            B.parse_match_formula("bogus")


class VestingTest(unittest.TestCase):
    def test_cliff_before(self):
        r = B.vesting_value(10000, 2, "cliff:3")
        self.assertEqual(r["vested_pct"], 0.0)
        self.assertEqual(r["vested_value"], 0.0)

    def test_cliff_after(self):
        r = B.vesting_value(10000, 3, "cliff:3")
        self.assertEqual(r["vested_pct"], 1.0)

    def test_graded_midway(self):
        r = B.vesting_value(10000, 3, "graded:6")
        self.assertAlmostEqual(r["vested_pct"], 0.4)

    def test_graded_full(self):
        r = B.vesting_value(10000, 9, "graded:6")
        self.assertEqual(r["vested_pct"], 1.0)

    def test_bad_schedule_raises(self):
        with self.assertRaises(B.BenefitsError):
            B.vesting_value(10000, 2, "weird:3")


class PtoTest(unittest.TestCase):
    def test_pto_valuation(self):
        r = B.pto_value(130000, pto_days=20, sick_days=5, holidays=10)
        self.assertAlmostEqual(r["value"], 130000 / 260 * 35)

    def test_zero_days_zero_value(self):
        self.assertEqual(B.pto_value(130000)["value"], 0.0)


class EsppTest(unittest.TestCase):
    def test_discount_gain(self):
        r = B.espp_value(150000, 0.10, 0.15)
        self.assertAlmostEqual(r["estimated_annual_gain"], 2250.0)

    def test_lookback_boosts_gain(self):
        plain = B.espp_value(150000, 0.10, 0.15, lookback=False)
        lb = B.espp_value(150000, 0.10, 0.15, lookback=True)
        self.assertGreater(lb["estimated_annual_gain"], plain["estimated_annual_gain"])


class HsaFsaTest(unittest.TestCase):
    def test_hsa_seed_plus_tax_savings(self):
        r = B.hsa_value(employer_seed=1000, employee_contribution=3000,
                        marginal_tax_rate=0.24)
        self.assertAlmostEqual(r["total_value"], 1000 + 720)

    def test_fsa_tax_savings(self):
        r = B.fsa_value(3000, 0.24)
        self.assertAlmostEqual(r["tax_savings"], 720)


class CommuteTest(unittest.TestCase):
    def test_pretax_and_subsidy(self):
        r = B.commute_value(monthly_pretax=200, monthly_subsidy=100,
                            marginal_tax_rate=0.25)
        self.assertAlmostEqual(r["tax_savings"], 200 * 12 * 0.25)
        self.assertAlmostEqual(r["subsidy_value"], 1200)
        self.assertAlmostEqual(r["total_value"], 600 + 1200)


class LeaveTest(unittest.TestCase):
    def test_full_pay_weeks(self):
        r = B.leave_value(104000, weeks_full_pay=12)
        self.assertAlmostEqual(r["value"], 2000 * 12)

    def test_partial_pay_weeks(self):
        r = B.leave_value(104000, weeks_partial_pay=8, partial_pct=0.6)
        self.assertAlmostEqual(r["value"], 2000 * 0.6 * 8)


class StipendsTest(unittest.TestCase):
    def test_sums_named_stipends(self):
        r = B.stipends_value({"wellness": 1200, "learning": 3000, "phone": 600})
        self.assertEqual(r["total_value"], 4800)
        self.assertEqual(len(r["stipends"]), 3)


class NormalizeTest(unittest.TestCase):
    def _pkg(self):
        return {
            "name": "Acme",
            "salary": 150000,
            "bonus": 15000,
            "health": {"monthly_premium": 300, "deductible": 1500,
                       "coinsurance": 0.2, "oop_max": 6000, "annual_spend": 8000},
            "match": {"formula": "100:3,50:2", "employee_contrib_pct": 0.10},
            "pto": {"pto_days": 20, "sick_days": 5},
            "espp": {"contribution_pct": 0.10, "discount_pct": 0.15},
            "hsa": {"employer_seed": 1000, "employee_contribution": 3000},
            "commute": {"monthly_subsidy": 100},
            "leave": {"weeks_full_pay": 12},
            "stipends": {"wellness": 1200},
            "other_cash": 500,
        }

    def test_total_adds_up(self):
        r = B.normalize_package(self._pkg())
        total = sum(v for _, v in r["lines"])
        self.assertAlmostEqual(r["total_annual_value"], total)
        labels = [label for label, _ in r["lines"]]
        self.assertIn("401(k) match", labels)
        self.assertIn("Health cost", labels)

    def test_health_is_subtracted(self):
        r = B.normalize_package(self._pkg())
        health_line = [v for label, v in r["lines"] if label == "Health cost"][0]
        self.assertLess(health_line, 0)

    def test_minimal_package(self):
        r = B.normalize_package({"name": "X", "salary": 100000})
        self.assertEqual(r["total_annual_value"], 100000)

    def test_render_normalized(self):
        text = B.render_normalized(B.normalize_package(self._pkg()))
        self.assertIn("Acme", text)
        self.assertIn("TOTAL annual value", text)


class CompareTest(unittest.TestCase):
    def test_compare_ranks_winner(self):
        a = {"name": "A", "salary": 150000,
             "match": {"formula": "100:3,50:2", "employee_contrib_pct": 0.10}}
        b = {"name": "B", "salary": 150000,
             "match": {"formula": "50:6", "employee_contrib_pct": 0.10}}
        comp = B.compare_packages(a, b)
        self.assertEqual(comp["winner"], "A")
        self.assertGreater(comp["delta_total"], 0)
        text = B.render_comparison(comp)
        self.assertIn("Winner on benefits value: A", text)
        self.assertIn("delta (A-B)", text)

    def test_compare_tie_goes_to_a(self):
        a = {"name": "A", "salary": 100000}
        b = {"name": "B", "salary": 100000}
        comp = B.compare_packages(a, b)
        self.assertEqual(comp["winner"], "A")
        self.assertEqual(comp["delta_total"], 0)


class LoadPackageTest(unittest.TestCase):
    def test_load_and_normalize_from_json(self):
        pkg = {"name": "JsonCo", "salary": 120000, "bonus": 10000}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            import json
            json.dump(pkg, f)
            path = f.name
        try:
            loaded = B.load_package(path)
            r = B.normalize_package(loaded)
            self.assertEqual(r["total_annual_value"], 130000)
        finally:
            Path(path).unlink()

    def test_missing_file_raises(self):
        with self.assertRaises(B.BenefitsError):
            B.load_package("/tmp/definitely-not-here-xyz.json")

    def test_bad_json_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not json")
            path = f.name
        try:
            with self.assertRaises(B.BenefitsError):
                B.load_package(path)
        finally:
            Path(path).unlink()


class CliWiringTest(unittest.TestCase):
    def test_benefits_command_registered(self):
        from candid.__main__ import COMMANDS, SUBCOMMANDS
        self.assertIn("benefits", COMMANDS)
        for sub in ("health", "healthcare", "match", "vesting", "pto",
                    "espp", "hsa", "fsa", "commute", "leave", "stipends",
                    "normalize", "compare"):
            self.assertIn(sub, SUBCOMMANDS["benefits"])

    def test_parser_builds(self):
        from candid.__main__ import build_parser
        p = build_parser()
        a = p.parse_args(["benefits", "health", "--premium", "300",
                          "--deductible", "1500", "--coinsurance", "0.2",
                          "--oop-max", "6000", "--spend", "8000"])
        self.assertEqual(a.what, "health")


if __name__ == "__main__":
    unittest.main()
