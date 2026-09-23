"""Tests for candid.redflags.turnover. Run: python -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.redflags import analyze  # noqa: E402
from candid.redflags import compensation  # noqa: E402  (sibling, for analyze integration)
from candid.redflags import turnover as T  # noqa: E402  (registers detectors)
from candid.redflags.core import SEVERITIES  # noqa: E402


def _ids(flags):
    return [f.flag_id for f in flags]


class ChurnLanguageTest(unittest.TestCase):
    JD_CHURN = ("We are a fast-paced environment looking for a self-starter. "
                "You will wear many hats and do more with less. Must hit the "
                "ground running with minimal supervision. Base salary $120k.")

    def test_positive(self):
        flags = T.detect(self.JD_CHURN)
        self.assertIn("turnover.churn_language", _ids(flags))
        flag = next(f for f in flags if f.flag_id == "turnover.churn_language")
        self.assertEqual(flag.severity, "medium")
        self.assertEqual(flag.category, "culture")
        self.assertTrue(len(flag.explanation) > 50)
        self.assertTrue(len(flag.suggestion) > 0)
        self.assertTrue(flag.evidence)

    def test_negative_too_few_phrases(self):
        jd = "Fast-paced environment. Great team. Base salary $120k."
        self.assertNotIn("turnover.churn_language", _ids(T.detect(jd)))

    def test_negative_no_autonomy_phrase(self):
        jd = ("Fast-paced environment. Wear many hats and do more with less. "
              "We provide full training and mentorship. Base salary $120k.")
        self.assertNotIn("turnover.churn_language", _ids(T.detect(jd)))

    def test_negative_clean(self):
        jd = ("Software Engineer. Base salary $150k. Supportive team with "
              "structured onboarding.")
        self.assertNotIn("turnover.churn_language", _ids(T.detect(jd)))


class FamilyClicheTest(unittest.TestCase):
    def test_positive_like_a_family(self):
        jd = "We are like a family here. Join us! Base salary $100k."
        flags = T.detect(jd)
        self.assertIn("turnover.family_cliche", _ids(flags))
        flag = next(f for f in flags if f.flag_id == "turnover.family_cliche")
        self.assertEqual(flag.severity, "low")

    def test_positive_work_hard_play_hard(self):
        jd = "We work hard play hard. Base salary $100k."
        self.assertIn("turnover.family_cliche", _ids(T.detect(jd)))

    def test_negative(self):
        jd = "We have a supportive team culture. Base salary $100k."
        self.assertNotIn("turnover.family_cliche", _ids(T.detect(jd)))


class OvertimeSignalTest(unittest.TestCase):
    def test_positive_nights_weekends(self):
        jd = ("Must be willing to work nights and weekends during launches. "
              "Base salary $130k.")
        flags = T.detect(jd)
        self.assertIn("turnover.overtime_signal", _ids(flags))
        flag = next(f for f in flags if f.flag_id == "turnover.overtime_signal")
        self.assertEqual(flag.severity, "high")

    def test_positive_always_on(self):
        jd = "This is an always-on role supporting global clients. Salary $130k."
        self.assertIn("turnover.overtime_signal", _ids(T.detect(jd)))

    def test_positive_long_hours(self):
        jd = "Expect long hours but great rewards. Salary $130k."
        self.assertIn("turnover.overtime_signal", _ids(T.detect(jd)))

    def test_negative(self):
        jd = ("We protect work-life balance with no on-call. Base salary "
              "$150k - $185k.")
        self.assertNotIn("turnover.overtime_signal", _ids(T.detect(jd)))


class RockstarTest(unittest.TestCase):
    def test_positive_rockstar(self):
        jd = "Looking for a rockstar engineer to join our team. Salary $140k."
        flags = T.detect(jd)
        self.assertIn("turnover.rockstar", _ids(flags))
        flag = next(f for f in flags if f.flag_id == "turnover.rockstar")
        self.assertEqual(flag.severity, "low")

    def test_positive_ninja(self):
        jd = "Seeking a code ninja with 5 years experience. Salary $140k."
        self.assertIn("turnover.rockstar", _ids(T.detect(jd)))

    def test_negative(self):
        jd = "Seeking a senior engineer with 5 years experience. Salary $140k."
        self.assertNotIn("turnover.rockstar", _ids(T.detect(jd)))


class RevolvingDoorTest(unittest.TestCase):
    def test_positive_urgent_plus_fast_paced(self):
        jd = ("Urgent hire: immediate start needed for this fast-paced sales "
              "team. Base plus commission.")
        flags = T.detect(jd)
        self.assertIn("turnover.revolving_door", _ids(flags))
        flag = next(f for f in flags if f.flag_id == "turnover.revolving_door")
        self.assertEqual(flag.severity, "medium")

    def test_positive_backfill(self):
        jd = "Backfill for a fast-paced support team. Immediate interviews."
        self.assertIn("turnover.revolving_door", _ids(T.detect(jd)))

    def test_negative_urgent_without_fast_paced(self):
        jd = "Immediate start available for this stable, growing team. Salary $120k."
        self.assertNotIn("turnover.revolving_door", _ids(T.detect(jd)))

    def test_negative_fast_paced_alone(self):
        jd = "Join our fast-paced team. Planned growth headcount. Salary $120k."
        self.assertNotIn("turnover.revolving_door", _ids(T.detect(jd)))


class EmptyInputTest(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(T.detect(""), [])

    def test_none(self):
        self.assertEqual(T.detect(None), [])

    def test_whitespace(self):
        self.assertEqual(T.detect("   \n  "), [])


class AnalyzeIntegrationTest(unittest.TestCase):
    def test_analyze_flags_churn_and_overtime(self):
        jd = self._bad_jd()
        result = analyze(jd)
        ids = _ids(result["flags"])
        self.assertIn("turnover.churn_language", ids)
        self.assertIn("turnover.overtime_signal", ids)
        self.assertIn("turnover.rockstar", ids)
        self.assertGreaterEqual(result["risk_score"], 25)

    def test_analyze_clean_posting(self):
        jd = ("Software Engineer. Base salary $150,000 - $185,000 per year. "
              "Supportive team, structured onboarding, no on-call.")
        result = analyze(jd)
        culture_ids = [i for i in _ids(result["flags"]) if i.startswith("turnover.")]
        self.assertEqual(culture_ids, [])
        self.assertEqual(result["verdict"], "clean")

    def test_all_flags_have_valid_fields(self):
        for f in T.detect(self._bad_jd()):
            self.assertIn(f.severity, SEVERITIES)
            self.assertEqual(f.category, "culture")
            self.assertTrue(f.flag_id.startswith("turnover."))
            self.assertTrue(len(f.explanation.split(". ")) >= 2)
            self.assertTrue(f.suggestion)

    @staticmethod
    def _bad_jd():
        return ("Rockstar wanted for our fast-paced environment! Wear many hats, "
                "do more with less. Self-starter who hits the ground running "
                "with minimal supervision. Nights and weekends expected. "
                "Immediate start, urgent hire. Base salary $100k.")


if __name__ == "__main__":
    unittest.main()
