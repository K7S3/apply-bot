"""Tests for the offer scenario modeler (candid.scenarios).

Run: CANDID_DATA_DIR=/tmp/candid-test-scenarios python -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-scenarios")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _offer(**kw):
    base = {
        "company": "Acme", "role": "Data Scientist", "level": "L4",
        "base": 180000, "bonus_target_pct": 15,
        "bonus_first_year_guaranteed": 0, "sign_on": 20000,
        "equity_type": "rsu", "equity_total": 400000,
        "vest_years": 4, "vest_schedule": "",
        "benefits_value": 15000,
    }
    base.update(kw)
    return base


class GrowthParseTest(unittest.TestCase):
    def test_presets(self):
        from candid import scenarios as S
        self.assertEqual(S.parse_growth("bear"), -0.10)
        self.assertEqual(S.parse_growth("flat"), 0.0)
        self.assertEqual(S.parse_growth("base"), 0.08)
        self.assertEqual(S.parse_growth("bull"), 0.20)

    def test_numeric_forms(self):
        from candid import scenarios as S
        self.assertEqual(S.parse_growth("10%"), 0.10)
        self.assertEqual(S.parse_growth("0.1"), 0.10)
        self.assertEqual(S.parse_growth(0.15), 0.15)
        self.assertEqual(S.parse_growth(None), 0.08)

    def test_bad_growth(self):
        from candid import scenarios as S
        with self.assertRaises(S.ScenarioError):
            S.parse_growth("to-the-moon")

    def test_growth_list(self):
        from candid import scenarios as S
        cols = S.parse_growth_list("bear,flat,0.1")
        self.assertEqual([c[0] for c in cols], ["bear", "flat", "0.1"])
        self.assertEqual([c[1] for c in cols], [-0.10, 0.0, 0.10])


class VestingTest(unittest.TestCase):
    def test_straight_line_default(self):
        from candid import scenarios as S
        self.assertEqual(S.vesting_pcts(_offer(), 4), [0.25, 0.25, 0.25, 0.25])

    def test_custom_schedule(self):
        from candid import scenarios as S
        o = _offer(vest_schedule="40/30/20/10")
        self.assertEqual(S.vesting_pcts(o, 4), [0.4, 0.3, 0.2, 0.1])

    def test_cliff_schedule(self):
        from candid import scenarios as S
        o = _offer(vest_schedule="0/34/33/33")
        pcts = S.vesting_pcts(o, 4)
        self.assertEqual(pcts[0], 0.0)
        self.assertAlmostEqual(sum(pcts), 1.0)

    def test_padding_and_truncation(self):
        from candid import scenarios as S
        o = _offer(vest_schedule="50/50")
        self.assertEqual(S.vesting_pcts(o, 4), [0.5, 0.5, 0.0, 0.0])
        self.assertEqual(S.vesting_pcts(o, 1), [0.5])

    def test_bad_schedule_sum(self):
        from candid import scenarios as S
        with self.assertRaises(S.ScenarioError):
            S.vesting_pcts(_offer(vest_schedule="40/30/20"), 4)


class SignonBonusTest(unittest.TestCase):
    def test_amortization_variants(self):
        from candid import scenarios as S
        o = _offer(sign_on=20000)
        self.assertEqual(S.amortize_signon(o, 1), 20000)
        self.assertEqual(S.amortize_signon(o, 2), 10000)
        self.assertEqual(S.amortize_signon(o, 4), 5000)

    def test_bonus_guaranteed_year1(self):
        from candid import scenarios as S
        o = _offer(bonus_first_year_guaranteed=30000)
        self.assertEqual(S.bonus_for_year(o, 1, payout=1.0), 30000)
        self.assertEqual(S.bonus_for_year(o, 2, payout=1.0), 27000)

    def test_bonus_payout_ratio(self):
        from candid import scenarios as S
        o = _offer()
        self.assertEqual(S.bonus_for_year(o, 2, payout=0.8), 21600)
        self.assertEqual(S.bonus_for_year(o, 2, payout=1.2), 32400)


class ProjectionTest(unittest.TestCase):
    def test_year1_matches_simple_math(self):
        from candid import scenarios as S
        o = _offer()
        proj = S.project_comp(o, years=4, growth=0.0, raise_pct=0.0,
                              bonus_payout=1.0, discount=0.05)
        y1 = proj["years"][0]
        # base 180k + bonus 27k + sign-on 20k + equity 100k + benefits 15k
        self.assertEqual(y1["pre_tax"], 342000)
        self.assertEqual(len(proj["years"]), 4)

    def test_growth_compounds_equity(self):
        from candid import scenarios as S
        o = _offer()
        flat = S.project_comp(o, years=4, growth=0.0)["totals"]["total_equity_vest"]
        bull = S.project_comp(o, years=4, growth=0.20)["totals"]["total_equity_vest"]
        self.assertGreater(bull, flat)
        self.assertEqual(flat, 400000)

    def test_raises_compound_base(self):
        from candid import scenarios as S
        o = _offer()
        proj = S.project_comp(o, years=3, growth=0.0, raise_pct=0.10)
        self.assertAlmostEqual(proj["years"][1]["base"], 198000, places=0)
        self.assertAlmostEqual(proj["years"][2]["base"], 217800, places=0)

    def test_totals_consistent(self):
        from candid import scenarios as S
        o = _offer()
        proj = S.project_comp(o, years=4)
        t = proj["totals"]
        self.assertAlmostEqual(
            t["total_pre_tax"],
            sum(r["pre_tax"] for r in proj["years"]), places=0)
        self.assertLessEqual(t["npv"], t["total_pre_tax"])

    def test_options_flagged(self):
        from candid import scenarios as S
        o = _offer(equity_type="options")
        proj = S.project_comp(o)
        self.assertIn("strike", proj["note"])

    def test_jsonable(self):
        from candid import scenarios as S
        import json
        proj = S.project_comp(_offer())
        json.dumps(S.as_jsonable(proj))


class TaxNpvTest(unittest.TestCase):
    def test_after_tax_progressive(self):
        from candid import scenarios as S
        low, high = S.after_tax(50000), S.after_tax(500000)
        self.assertLess(low, 50000)
        # effective rate rises with income
        self.assertGreater(1 - high / 500000, 1 - low / 50000)

    def test_npv_discounts(self):
        from candid import scenarios as S
        self.assertAlmostEqual(S.npv([100, 100], 0.0), 200.0)
        self.assertAlmostEqual(S.npv([100, 100], 0.10), 173.55, places=1)
        self.assertLess(S.npv([100, 100], 0.10), 200.0)

    def test_npv_bad_rate(self):
        from candid import scenarios as S
        with self.assertRaises(S.ScenarioError):
            S.npv([100], -1.5)


class BreakevenTest(unittest.TestCase):
    def _two_offers(self):
        a = _offer(company="CashCow", base=220000, equity_total=100000)
        b = _offer(company="RocketCo", base=160000, equity_total=600000)
        return a, b

    def test_breakeven_year(self):
        from candid import scenarios as S
        a, b = self._two_offers()
        pa = S.project_comp(a, growth=0.20)
        pb = S.project_comp(b, growth=0.20)
        yr = S.breakeven_year(pb, pa)
        self.assertIsNotNone(yr)
        self.assertGreaterEqual(yr, 1)
        self.assertLessEqual(yr, 4)

    def test_breakeven_year_never(self):
        from candid import scenarios as S
        a = _offer(company="A", base=300000, equity_total=0)
        b = _offer(company="B", base=100000, equity_total=0)
        pa = S.project_comp(a, growth=0.0)
        pb = S.project_comp(b, growth=0.0)
        self.assertIsNone(S.breakeven_year(pb, pa))

    def test_breakeven_growth(self):
        from candid import scenarios as S
        a, b = self._two_offers()
        g = S.breakeven_growth(a, b)
        self.assertIsNotNone(g)
        # at the breakeven growth the 4y totals tie (within rounding)
        ta = S.project_comp(a, growth=g)["totals"]["total_pre_tax"]
        tb = S.project_comp(b, growth=g)["totals"]["total_pre_tax"]
        self.assertAlmostEqual(ta, tb, delta=2000)

    def test_breakeven_growth_none_when_dominated(self):
        from candid import scenarios as S
        a = _offer(company="A", base=300000, equity_total=400000)
        b = _offer(company="B", base=100000, equity_total=50000)
        self.assertIsNone(S.breakeven_growth(b, a))


class SensitivityTest(unittest.TestCase):
    def test_ranked_by_swing(self):
        from candid import scenarios as S
        rows = S.sensitivity(_offer())
        self.assertEqual(len(rows), 4)
        swings = [abs(r["swing"]) for r in rows]
        self.assertEqual(swings, sorted(swings, reverse=True))
        names = {r["assumption"] for r in rows}
        self.assertEqual(names, {"growth", "raise_pct", "bonus_payout", "discount"})

    def test_growth_dominates_equity_heavy(self):
        from candid import scenarios as S
        rows = S.sensitivity(_offer(equity_total=800000, base=100000))
        self.assertEqual(rows[0]["assumption"], "growth")


class MatrixTest(unittest.TestCase):
    def test_matrix_shape(self):
        from candid import scenarios as S
        offers = [_offer(company="Acme"), _offer(company="Globex", base=200000)]
        m = S.compare_matrix(offers, growth_specs="flat,base")
        self.assertEqual(len(m["rows"]), 2)
        self.assertEqual(len(m["scenarios"]), 2)
        for row in m["rows"]:
            self.assertEqual(len(row["cells"]), 2)
            self.assertIn(row["best_scenario"], ("flat", "base"))

    def test_matrix_sorted_by_best_npv(self):
        from candid import scenarios as S
        offers = [_offer(company="Low", base=100000, equity_total=0),
                  _offer(company="High", base=300000, equity_total=0)]
        m = S.compare_matrix(offers, growth_specs="flat")
        self.assertEqual(m["rows"][0]["company"], "High")

    def test_render_matrix(self):
        from candid import scenarios as S
        m = S.compare_matrix([_offer()], growth_specs="flat,base")
        text = S.render_matrix(m)
        self.assertIn("Acme", text)
        self.assertIn("flat", text)

    def test_render_projection(self):
        from candid import scenarios as S
        text = S.render_projection(S.project_comp(_offer()))
        self.assertIn("Acme", text)
        self.assertIn("TOTAL", text)
        self.assertIn("NPV", text)

    def test_export_matrix_md(self):
        from candid import scenarios as S
        m = S.compare_matrix([_offer(company="Acme")], growth_specs="flat,base")
        with tempfile.TemporaryDirectory() as td:
            p = S.export_matrix_md(m, path=Path(td) / "m.md")
            text = p.read_text()
        self.assertIn("# Offer Scenario Comparison", text)
        self.assertIn("Acme", text)
        self.assertIn("Assumptions", text)

    def test_export_projection_md(self):
        from candid import scenarios as S
        with tempfile.TemporaryDirectory() as td:
            p = S.export_projection_md(S.project_comp(_offer()),
                                       path=Path(td) / "p.md")
            text = p.read_text()
        self.assertIn("# Offer Scenario", text)
        self.assertIn("Year-by-year", text)


class CliOfferScenarioTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self.td = tempfile.TemporaryDirectory()
        self.orig = C.OFFERS_PATH
        C.OFFERS_PATH = Path(self.td.name) / "offers.json"

    def tearDown(self):
        from candid import config as C
        C.OFFERS_PATH = self.orig
        self.td.cleanup()

    def _run_cli(self, *args):
        import io
        from contextlib import redirect_stdout
        from candid.__main__ import build_parser
        buf = io.StringIO()
        with redirect_stdout(buf):
            build_parser().parse_args(
                ["offer", *args]).func(
                build_parser().parse_args(["offer", *args]))
        return buf.getvalue()

    def test_scenario_cli(self):
        from candid import offer as O
        O.add(_offer())
        out = self._run_cli("scenario", "--company", "Acme", "--growth", "flat")
        self.assertIn("Acme", out)
        self.assertIn("TOTAL", out)

    def test_scenario_cli_json(self):
        import json
        from candid import offer as O
        O.add(_offer())
        out = self._run_cli("scenario", "--company", "Acme", "--json")
        data = json.loads(out)
        self.assertEqual(data["company"], "Acme")
        self.assertEqual(len(data["years"]), 4)

    def test_compare_scenarios_cli(self):
        from candid import offer as O
        O.add(_offer(company="Acme"))
        O.add(_offer(company="Globex", base=200000))
        out = self._run_cli("compare-scenarios", "--growths", "flat,base")
        self.assertIn("Acme", out)
        self.assertIn("Globex", out)

    def test_breakeven_cli(self):
        from candid import offer as O
        O.add(_offer(company="CashCow", base=220000, equity_total=100000))
        O.add(_offer(company="RocketCo", base=160000, equity_total=600000))
        out = self._run_cli("breakeven", "--a", "CashCow", "--b", "RocketCo",
                            "--growth", "bull")
        self.assertIn("CashCow", out)
        self.assertIn("RocketCo", out)

    def test_scenario_no_offers_errors_cleanly(self):
        from candid.__main__ import build_parser
        from candid import offer as O
        args = build_parser().parse_args(["offer", "scenario"])
        with self.assertRaises(O.OfferError):
            args.func(args)


if __name__ == "__main__":
    unittest.main()
