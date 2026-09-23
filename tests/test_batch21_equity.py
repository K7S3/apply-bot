"""Tests for the startup equity evaluation module (batch 21).

Notes generation (complete/partial offers), modeler math (hand-checkable
break-even), and assumption labeling in the output.

Run: cd ~/workspace/candid-batch21 && python3 -m pytest tests/test_batch21_equity.py -q
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import offer as O
from candid import startup_equity as SE


def _mk_offer(**fields):
    """Add an offer via offer.py's own store; tmp DATA_DIR keeps it isolated."""
    rec = O.add({"company": fields.pop("company", "Acme"),
                 "role": fields.pop("role", "Engineer"), **fields})
    return rec


class NotesTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = Path(self.td.name) / "offers.json"

    def tearDown(self):
        self.td.cleanup()

    def test_complete_offer_references_values_no_ask_prompts_for_known(self):
        # offer.add -> offer.normalize copies the whole fields dict, so custom
        # startup fields (strike price, share counts, ...) ride along in the
        # same offers.json store without changing offer.py.
        rec = O.add({"company": "StartupCo", "role": "SWE",
                     "base": 150000, "equity_total": 200000,
                     "strike_price": 2.50, "option_shares": 40000,
                     "share_price_409a": 7.50, "valuation_409a_date": "2026-06-01",
                     "total_fully_diluted_shares": 8000000,
                     "equity_type": "ISO", "cliff": "1 year",
                     "post_termination_window": "10 years",
                     "funding_round": "Series B", "vest_years": 4},
                    path=self.path)
        text = SE.equity_notes(rec["id"], path=self.path)
        # stored values are referenced
        self.assertIn("Strike price: $2 per share", text)  # :,.0f of 2.50
        self.assertIn("40,000 shares", text)
        self.assertIn("0.500%", text)  # 40000 / 8000000 ownership
        self.assertIn("$200,000", text)  # paper value 40000 * (7.50 - 2.50)
        # every checklist item has a heading; known ones are marked on record
        self.assertIn("[on record (see above)]", text)
        self.assertNotIn("ASK THE COMPANY", text)

    def test_partial_offer_asks_for_missing_and_invents_nothing(self):
        rec = O.add({"company": "MysteryCo", "role": "SWE", "base": 140000},
                    path=self.path)
        text = SE.equity_notes(rec["id"], path=self.path)
        # missing terms become ask prompts
        self.assertIn("ASK THE COMPANY", text)
        self.assertIn("What is the strike price per share?", text)
        self.assertIn("total fully-diluted share count", text)
        # no invented numbers: the only dollar figure is the entered base
        self.assertIn("$140,000", text)
        self.assertNotIn("ownership", text.split("## Checklist")[0])
        # educational explainers present
        self.assertIn("409A", text)
        self.assertIn("cliff", text.lower())

    def test_missing_offer_id_raises(self):
        with self.assertRaises(SE.StartupEquityError):
            SE.equity_notes(999, path=self.path)


class ModelerMathTest(unittest.TestCase):
    """Hand-checkable numbers.

    Offer A: $100k base, no equity, no bonus -> 4-yr total $400,000 flat.
    Offer B: $80k base + $40k equity straight-line (4 yrs -> $10k/yr vest).

    Year y total for B at rate r: 80,000 + 10,000 * (1+r)^y.
    Break-even: 400,000 = 320,000 + 10,000 * sum((1+r)^y, y=1..4)
      -> sum = 8. At r=0.29 sum=7.8700 (B=$398,700 < A);
         at r=0.30 sum=8.0431 (B=$400,431 > A). So r* ~= 0.296.
    """

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = Path(self.td.name) / "offers.json"
        self.a = O.add({"company": "BigCo", "role": "SWE", "base": 100000,
                        "equity_total": 0, "vest_years": 4}, path=self.path)
        self.b = O.add({"company": "StartupCo", "role": "SWE", "base": 80000,
                        "equity_total": 40000, "vest_years": 4}, path=self.path)

    def tearDown(self):
        self.td.cleanup()

    def test_flat_rate_math(self):
        res = SE.compare_startup(self.a["id"], self.b["id"], growth="low",
                                 path=self.path)
        # r = 0: equity vests at face value, $10k each year
        self.assertEqual(res["selected_totals"]["a_grand_total"], 400000)
        self.assertEqual(res["selected_totals"]["b_grand_total"], 360000)
        y2 = res["years"][1]
        self.assertEqual(y2["b_cash"], 80000)
        self.assertEqual(y2["b_equity"], 10000)
        self.assertEqual(y2["b_total"], 90000)

    def test_base_scenario_hand_check(self):
        res = SE.compare_startup(self.a["id"], self.b["id"], growth="base",
                                 path=self.path)
        # 1.15 + 1.15^2 + 1.15^3 + 1.15^4 = 5.74238125
        expect_eq = round(10000 * 5.74238125, 2)
        self.assertAlmostEqual(res["selected_totals"]["b_equity_total"],
                               expect_eq, places=1)
        self.assertAlmostEqual(res["selected_totals"]["b_grand_total"],
                               320000 + expect_eq, places=1)

    def test_custom_growth_rate_override(self):
        res = SE.compare_startup(self.a["id"], self.b["id"], growth_rate=0.25,
                                 path=self.path)
        # 1.25 + 1.5625 + 1.953125 + 2.44140625 = 7.20703125
        expect_eq = round(10000 * 7.20703125, 2)
        self.assertAlmostEqual(res["selected_totals"]["b_equity_total"],
                               expect_eq, places=1)
        self.assertIn("custom 25%/yr", res["assumptions"]["selected"])

    def test_breakeven_hand_check(self):
        res = SE.compare_startup(self.a["id"], self.b["id"], growth="base",
                                 path=self.path)
        be = res["breakeven"]
        self.assertTrue(be["exists"])
        # hand-computed bracket: 0.29 -> B under, 0.30 -> B over
        self.assertGreater(be["rate"], 0.29)
        self.assertLess(be["rate"], 0.30)
        # self-consistency: totals are equal at the break-even rate
        ra = SE.model_offer(self.a, be["rate"])["grand_total"]
        rb = SE.model_offer(self.b, be["rate"])["grand_total"]
        self.assertAlmostEqual(ra, rb, delta=1.0)

    def test_breakeven_none_when_one_always_wins(self):
        # d beats b at both ends of the modeled range (more cash AND more
        # equity), so no growth rate equalizes them.
        d = O.add({"company": "RichCo", "role": "SWE", "base": 500000,
                   "equity_total": 100000, "vest_years": 4}, path=self.path)
        self.assertIsNone(SE.find_breakeven(self.b, d))

    def test_same_offer_rejected(self):
        with self.assertRaises(SE.StartupEquityError):
            SE.compare_startup(self.a["id"], self.a["id"], path=self.path)

    def test_sign_on_lands_in_year_1(self):
        d = O.add({"company": "SignOnCo", "role": "SWE", "base": 100000,
                   "sign_on": 20000, "equity_total": 0, "vest_years": 4},
                  path=self.path)
        res = SE.compare_startup(self.a["id"], d["id"], growth="low",
                                 path=self.path)
        self.assertEqual(res["years"][0]["b_cash"], 120000)
        self.assertEqual(res["years"][1]["b_cash"], 100000)
        self.assertEqual(res["selected_totals"]["b_cash_total"], 420000)


class LabelingTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = Path(self.td.name) / "offers.json"
        self.a = O.add({"company": "BigCo", "role": "SWE", "base": 100000,
                        "equity_total": 0}, path=self.path)
        self.b = O.add({"company": "StartupCo", "role": "SWE", "base": 80000,
                        "equity_total": 40000}, path=self.path)

    def tearDown(self):
        self.td.cleanup()

    def test_assumption_labels_in_text_output(self):
        res = SE.compare_startup(self.a["id"], self.b["id"], growth="high",
                                 path=self.path)
        text = SE.render_compare(res)
        self.assertIn("Growth assumption (selected): high (40%/yr)", text)
        self.assertIn("low 0%/yr", text)
        self.assertIn("base 15%/yr", text)
        self.assertIn("high 40%/yr", text)
        self.assertIn("assumptions you set, not predictions", text)
        self.assertIn("not tax", text)
        self.assertIn("Illustrative model only", text)

    def test_assumption_labels_in_json_payload(self):
        res = SE.compare_startup(self.a["id"], self.b["id"], path=self.path)
        asm = res["assumptions"]
        self.assertEqual(asm["growth_presets"], {"low": 0.0, "base": 0.15,
                                                 "high": 0.40})
        self.assertTrue(any("not predictions" in n for n in asm["notes"]))
        self.assertIn("disclaimer", res)
        self.assertIn("not tax", res["disclaimer"])

    def test_render_has_year_rows_and_scenarios(self):
        res = SE.compare_startup(self.a["id"], self.b["id"], path=self.path)
        text = SE.render_compare(res)
        for y in ("1", "2", "3", "4"):
            self.assertIn(f"{y}     ", text)  # year column rows present
        self.assertIn("Break-even growth rate", text)
        self.assertIn("4-year totals per growth scenario", text)


if __name__ == "__main__":
    unittest.main()
