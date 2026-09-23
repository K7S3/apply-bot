"""Tests for the green-flag detectors. Run: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class GreenFlagTest(unittest.TestCase):
    def setUp(self):
        from candid.redflags import greenflags as G
        from candid.redflags.core import analyze
        self.G = G
        self.analyze = analyze

    def _ids(self, text):
        # Green-detector tests must be robust to other batches' detectors:
        # only green flag ids are asserted here.
        return [f.flag_id for f in self.analyze(text)["flags"]
                if f.flag_id.startswith("green.")]

    def test_salary_range_dollar_range(self):
        self.assertIn("green.salary_range",
                      self._ids("Salary: $120k-$150k base, plus bonus."))

    def test_salary_range_comma_range(self):
        self.assertIn("green.salary_range",
                      self._ids("Compensation is $80,000 - $100,000 per year."))

    def test_salary_range_phrase(self):
        self.assertIn("green.salary_range",
                      self._ids("The pay range for this role is posted."))

    def test_salary_range_negative(self):
        self.assertEqual([], self._ids("We pay competitively. Apply now."))

    def test_growth_path_positive(self):
        self.assertIn("green.growth_path",
                      self._ids("We offer mentorship and a learning budget."))

    def test_growth_path_promotion(self):
        self.assertIn("green.growth_path",
                      self._ids("Clear promotion track with career growth."))

    def test_growth_path_negative(self):
        self.assertEqual([], self._ids("Write code. Ship features. Go home."))

    def test_work_life_positive(self):
        self.assertIn("green.work_life",
                      self._ids("Flexible hours and generous PTO."))

    def test_work_life_parental_leave(self):
        self.assertIn("green.work_life",
                      self._ids("Includes parental leave and work-life balance."))

    def test_work_life_negative(self):
        self.assertEqual([], self._ids("Fast-paced environment. Must be available."))

    def test_process_transparency_positive(self):
        self.assertIn(
            "green.process_transparency",
            self._ids("Our process: 4 rounds including an onsite and a take-home."))

    def test_process_transparency_negative(self):
        self.assertEqual([], self._ids("We will be in touch soon."))

    def test_equal_opportunity_positive(self):
        self.assertIn("green.equal_opportunity",
                      self._ids("We are an equal opportunity employer."))

    def test_equal_opportunity_eeo(self):
        self.assertIn("green.equal_opportunity",
                      self._ids("Acme is an EEO employer."))

    def test_equal_opportunity_negative(self):
        self.assertEqual([], self._ids("Apply today, positions filling fast!"))

    def test_benefits_listed_positive(self):
        self.assertIn("green.benefits_listed",
                      self._ids("Benefits: health, dental, vision, and 401k."))

    def test_benefits_listed_equity_counts(self):
        self.assertIn("green.benefits_listed",
                      self._ids("We offer health, vision, 401k, and RSUs."))

    def test_benefits_listed_needs_three(self):
        self.assertEqual([],
                         self._ids("Benefits: health and dental."))

    def test_green_flags_are_info(self):
        from candid.redflags.core import analyze
        text = ("Salary: $120k-$150k. Mentorship program. Flexible hours. "
                "4 rounds with onsite. Equal opportunity employer. "
                "Benefits: health, dental, vision, 401k.")
        flags = analyze(text)["flags"]
        greens = [f for f in flags if f.flag_id.startswith("green.")]
        self.assertEqual(6, len(greens))
        for f in greens:
            self.assertEqual("info", f.severity)
            self.assertEqual("green", f.category)
            self.assertTrue(f.explanation)
            self.assertTrue(f.evidence)
            self.assertLessEqual(max(len(e) for e in f.evidence), 140)

    def test_green_adjustment(self):
        self.assertEqual(0, self.G.green_adjustment(0))
        self.assertEqual(-3, self.G.green_adjustment(1))
        self.assertEqual(-6, self.G.green_adjustment(2))
        self.assertEqual(-15, self.G.green_adjustment(5))
        self.assertEqual(-15, self.G.green_adjustment(10))  # capped
        self.assertEqual(0, self.G.green_adjustment(-2))  # never positive

    def test_empty_input(self):
        for det in ("detect_salary_range", "detect_growth_path",
                    "detect_work_life", "detect_process_transparency",
                    "detect_equal_opportunity", "detect_benefits_listed"):
            fn = getattr(self.G, det)
            self.assertEqual([], fn(""), det)
            self.assertEqual([], fn(None), det)
        self.assertEqual([], self.analyze("")["flags"])
        self.assertEqual([], self.analyze(None)["flags"])

    def test_greens_do_not_raise_score(self):
        text = ("Salary: $120k-$150k. Mentorship. Flexible hours. "
                "Benefits: health, dental, vision, 401k. "
                "Responsibilities: write code and ship features. "
                "You will join the platform team, reporting to the "
                "engineering manager.")
        result = self.analyze(text)
        self.assertEqual(0, result["risk_score"])
        self.assertEqual("clean", result["verdict"])


if __name__ == "__main__":
    unittest.main()
