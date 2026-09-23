"""Tests for candid.redflags.compensation. Run: python -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.redflags import analyze  # noqa: E402
from candid.redflags import compensation as C  # noqa: E402  (registers detectors)
from candid.redflags import turnover  # noqa: E402  (sibling, for analyze integration)
from candid.redflags.core import SEVERITIES  # noqa: E402


def _ids(flags):
    return [f.flag_id for f in flags]


class NoSalaryTest(unittest.TestCase):
    JD_CLEAN = ("Software Engineer. Base salary $150,000 - $185,000 per year, "
                "plus equity and benefits. Great team, hybrid in NYC.")

    def test_positive(self):
        jd = "Software Engineer. Join our amazing team! Great benefits, 401k, ping pong."
        flags = C.detect(jd)
        self.assertIn("comp.no_salary", _ids(flags))
        flag = next(f for f in flags if f.flag_id == "comp.no_salary")
        self.assertEqual(flag.severity, "medium")
        self.assertEqual(flag.category, "compensation")
        self.assertTrue(len(flag.explanation) > 50)
        self.assertTrue(len(flag.suggestion) > 0)

    def test_negative_with_dollar_range(self):
        self.assertNotIn("comp.no_salary", _ids(C.detect(self.JD_CLEAN)))

    def test_negative_with_salary_word(self):
        jd = "Salary commensurate with experience. Apply now."
        self.assertNotIn("comp.no_salary", _ids(C.detect(jd)))


class VagueCompTest(unittest.TestCase):
    def test_positive_competitive_salary(self):
        jd = "We offer a competitive salary and great benefits. Join us!"
        flags = C.detect(jd)
        self.assertIn("comp.vague_comp", _ids(flags))
        flag = next(f for f in flags if f.flag_id == "comp.vague_comp")
        self.assertEqual(flag.severity, "medium")
        self.assertTrue(flag.evidence)

    def test_positive_doe(self):
        jd = "Pay is DOE. Full-time role with benefits."
        self.assertIn("comp.vague_comp", _ids(C.detect(jd)))

    def test_positive_depends_on_experience(self):
        jd = "Compensation depends on experience. Remote friendly."
        self.assertIn("comp.vague_comp", _ids(C.detect(jd)))

    def test_negative_with_numbers(self):
        jd = "Competitive salary: $120k - $150k DOE."
        self.assertNotIn("comp.vague_comp", _ids(C.detect(jd)))

    def test_negative_no_weasel(self):
        jd = "Base salary $90,000. Apply today."
        self.assertNotIn("comp.vague_comp", _ids(C.detect(jd)))


class EquityOnlyTest(unittest.TestCase):
    def test_positive_equity_only(self):
        jd = ("Early-stage startup seeks founding engineer. This is an equity "
              "only position until we raise our seed round.")
        flags = C.detect(jd)
        self.assertIn("comp.equity_only", _ids(flags))
        flag = next(f for f in flags if f.flag_id == "comp.equity_only")
        self.assertEqual(flag.severity, "critical")

    def test_positive_unpaid(self):
        jd = "Unpaid internship-style role for a for-profit company. Full-time."
        self.assertIn("comp.equity_only", _ids(C.detect(jd)))

    def test_positive_for_exposure(self):
        jd = "Design work for exposure. Great portfolio opportunity!"
        self.assertIn("comp.equity_only", _ids(C.detect(jd)))

    def test_negative_paid_role(self):
        jd = "Software Engineer. Base salary $150,000 - $185,000 plus equity."
        self.assertNotIn("comp.equity_only", _ids(C.detect(jd)))


class CommissionOnlyTest(unittest.TestCase):
    def test_positive_100_percent(self):
        jd = "Sales rep wanted. 100% commission role with uncapped earnings!"
        flags = C.detect(jd)
        self.assertIn("comp.commission_only", _ids(flags))
        flag = next(f for f in flags if f.flag_id == "comp.commission_only")
        self.assertEqual(flag.severity, "high")

    def test_positive_uncapped_no_base(self):
        jd = "Join our team: uncapped commission, be your own boss."
        self.assertIn("comp.commission_only", _ids(C.detect(jd)))

    def test_negative_with_base_salary(self):
        jd = ("Account executive. Base salary $60,000 plus uncapped commission. "
              "OTE $140k.")
        self.assertNotIn("comp.commission_only", _ids(C.detect(jd)))

    def test_negative_no_commission_language(self):
        jd = "Software Engineer. Base salary $150,000 - $185,000."
        self.assertNotIn("comp.commission_only", _ids(C.detect(jd)))


class LowballHintTest(unittest.TestCase):
    def test_positive_below_market(self):
        jd = ("We are a startup so salary is below market, but the mission "
              "is amazing.")
        flags = C.detect(jd)
        self.assertIn("comp.lowball_hint", _ids(flags))
        flag = next(f for f in flags if f.flag_id == "comp.lowball_hint")
        self.assertEqual(flag.severity, "low")

    def test_positive_passion_over_pay(self):
        jd = "We value passion over pay. Modest salary, huge impact."
        self.assertIn("comp.lowball_hint", _ids(C.detect(jd)))

    def test_negative(self):
        jd = "Software Engineer. Base salary $150,000 - $185,000. Great team."
        self.assertNotIn("comp.lowball_hint", _ids(C.detect(jd)))


class EmptyInputTest(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(C.detect(""), [])

    def test_none(self):
        self.assertEqual(C.detect(None), [])

    def test_whitespace(self):
        self.assertEqual(C.detect("   \n  "), [])


class AnalyzeIntegrationTest(unittest.TestCase):
    def test_analyze_flags_no_salary(self):
        result = analyze("Join our amazing team! Great benefits, ping pong.")
        self.assertIn("comp.no_salary", _ids(result["flags"]))

    def test_analyze_clean_paid_posting(self):
        jd = ("Software Engineer. Base salary $150,000 - $185,000 per year. "
              "Friendly team, reasonable hours, hybrid in NYC.")
        result = analyze(jd)
        comp_ids = [i for i in _ids(result["flags"]) if i.startswith("comp.")]
        self.assertEqual(comp_ids, [])
        self.assertEqual(result["verdict"], "clean")

    def test_all_flags_have_valid_fields(self):
        jd = ("Unpaid role. Equity only. 100% commission. We are a startup so "
              "salary is below market, passion over pay!")
        flags = C.detect(jd)
        self.assertTrue(flags)
        for f in flags:
            self.assertIn(f.severity, SEVERITIES)
            self.assertEqual(f.category, "compensation")
            self.assertTrue(f.flag_id.startswith("comp."))
            self.assertTrue(len(f.explanation.split(". ")) >= 2)
            self.assertTrue(f.suggestion)


if __name__ == "__main__":
    unittest.main()
