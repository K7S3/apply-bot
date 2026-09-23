"""Tests for candid.redflags.bait (bait-and-switch detectors).

Run: python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.redflags import bait as B
from candid.redflags import compliance as C  # noqa: F401  (registers compliance detectors)
from candid.redflags.core import SEVERITIES, analyze


def _assert_flag_shape(tc, flag, flag_id, severity):
    tc.assertEqual(flag.flag_id, flag_id)
    tc.assertEqual(flag.severity, severity)
    tc.assertIn(severity, SEVERITIES)
    tc.assertEqual(flag.category, "bait-and-switch")
    tc.assertTrue(flag.title)
    # explanation: 2-4 sentences of plain language
    sentences = [s for s in flag.explanation.split(". ") if s.strip()]
    tc.assertGreaterEqual(len(sentences), 2)
    tc.assertLessEqual(len(sentences), 5)
    tc.assertTrue(flag.evidence)
    for snip in flag.evidence:
        tc.assertLessEqual(len(snip), 125)
    tc.assertTrue(flag.suggestion)


class TitleLevelMismatchTest(unittest.TestCase):
    def test_senior_title_junior_body(self):
        text = ("Senior Software Engineer\n\nJoin our team! 0-2 years of "
                "experience welcome. Training provided and you will work "
                "under supervision of senior staff.")
        flag = B.detect_title_level_mismatch(text)
        self.assertIsNotNone(flag)
        _assert_flag_shape(self, flag, "bait.title_level_mismatch", "high")

    def test_principal_title_entry_level_body(self):
        text = ("Principal Engineer\n\nThis is an entry-level role. No "
                "experience required; we will train you.")
        flag = B.detect_title_level_mismatch(text)
        self.assertIsNotNone(flag)
        self.assertEqual(flag.severity, "high")

    def test_junior_title_senior_duties(self):
        text = ("Junior Developer\n\nYou will lead a team of five engineers, "
                "own the roadmap, and need 8+ years of experience.")
        flag = B.detect_title_level_mismatch(text)
        self.assertIsNotNone(flag)
        _assert_flag_shape(self, flag, "bait.title_level_mismatch", "high")

    def test_intern_title_architect_duties(self):
        text = ("Engineering Intern\n\nArchitect the new platform and set "
                "the strategy for the org.")
        flag = B.detect_title_level_mismatch(text)
        self.assertIsNotNone(flag)

    def test_senior_title_senior_body_no_flag(self):
        # Near miss: consistent senior posting must not flag.
        text = ("Senior Software Engineer\n\n5+ years of experience building "
                "distributed systems. You will lead projects and mentor "
                "junior engineers.")
        self.assertIsNone(B.detect_title_level_mismatch(text))

    def test_junior_title_junior_body_no_flag(self):
        # Near miss: consistent junior posting must not flag.
        text = ("Junior Developer\n\nEntry-level role. Training provided, "
                "mentorship available, 0-2 years welcome.")
        self.assertIsNone(B.detect_title_level_mismatch(text))

    def test_plain_title_no_flag(self):
        text = "Software Engineer\n\nBuild features in Python. 3+ years experience."
        self.assertIsNone(B.detect_title_level_mismatch(text))

    def test_empty_input(self):
        self.assertIsNone(B.detect_title_level_mismatch(""))
        self.assertIsNone(B.detect_title_level_mismatch(None))


class RoleMismatchTest(unittest.TestCase):
    def test_engineer_title_sales_duties(self):
        text = ("Software Engineer\n\nYou will cold call prospects, close "
                "deals, handle support tickets, answer phones, and upsell "
                "existing accounts to hit quota.")
        flag = B.detect_role_mismatch(text)
        self.assertIsNotNone(flag)
        _assert_flag_shape(self, flag, "bait.role_mismatch", "high")

    def test_data_title_recruiting_duties(self):
        text = ("Data Analyst\n\nSource candidates, screen resumes, recruit "
                "engineers, make outbound calls, and book demos for the "
                "staffing team.")
        flag = B.detect_role_mismatch(text)
        self.assertIsNotNone(flag)

    def test_sales_engineer_title_excluded(self):
        # Near miss: honestly-labeled sales role must not flag.
        text = ("Sales Engineer\n\nYou will cold call prospects, close "
                "deals, handle support tickets, answer phones, and upsell.")
        self.assertIsNone(B.detect_role_mismatch(text))

    def test_support_engineer_title_excluded(self):
        text = ("Customer Support Engineer\n\nHandle tickets, answer phones, "
                "resolve support tickets, and upsell when appropriate.")
        self.assertIsNone(B.detect_role_mismatch(text))

    def test_too_few_duty_signals_no_flag(self):
        # Near miss: one stray sales mention is not "dominated".
        text = ("Software Engineer\n\nBuild backend services in Go. "
                "Collaborate with the sales team on demos. Handle support "
                "tickets during on-call rotation.")
        self.assertIsNone(B.detect_role_mismatch(text))

    def test_nontech_title_no_flag(self):
        text = "Account Executive\n\nCold call prospects and close deals."
        self.assertIsNone(B.detect_role_mismatch(text))

    def test_empty_input(self):
        self.assertIsNone(B.detect_role_mismatch(""))
        self.assertIsNone(B.detect_role_mismatch(None))


class KeywordStuffingTest(unittest.TestCase):
    def test_also_hiring_four_titles(self):
        text = ("Backend Engineer\n\nGreat role. Also hiring: java "
                "developer, python developer, data analyst, project manager. "
                "Apply today!")
        flag = B.detect_keyword_stuffing(text)
        self.assertIsNotNone(flag)
        _assert_flag_shape(self, flag, "bait.keyword_stuffing", "medium")

    def test_six_titles_no_marker(self):
        text = ("Software Engineer\n\nYou will work with our java developer, "
                "python developer, devops engineer, data analyst, qa "
                "engineer, and scrum master across the org on many teams "
                "doing java developer python developer devops engineer data "
                "analyst qa engineer scrum master work.")
        flag = B.detect_keyword_stuffing(text)
        self.assertIsNotNone(flag)

    def test_three_titles_with_marker_no_flag(self):
        # Near miss: below the with-marker threshold.
        text = ("Backend Engineer\n\nAlso hiring: a designer and a product "
                "manager on the same team.")
        self.assertIsNone(B.detect_keyword_stuffing(text))

    def test_few_titles_no_marker_no_flag(self):
        # Near miss: normal "you will work with" lists must not flag.
        text = ("Software Engineer\n\nWork alongside our frontend developer, "
                "backend developer, and product manager to ship features.")
        self.assertIsNone(B.detect_keyword_stuffing(text))

    def test_empty_input(self):
        self.assertIsNone(B.detect_keyword_stuffing(""))
        self.assertIsNone(B.detect_keyword_stuffing(None))


class RemoteBaitTest(unittest.TestCase):
    def test_remote_title_hybrid_body(self):
        text = ("Remote Software Engineer\n\nThis is a hybrid role based in "
                "NYC, 3 days a week in the office.")
        flag = B.detect_remote_bait(text)
        self.assertIsNotNone(flag)
        _assert_flag_shape(self, flag, "bait.remote_bait", "medium")

    def test_remote_ad_must_relocate(self):
        text = ("Software Engineer (Remote)\n\nGreat remote-first culture. "
                "Must relocate to Austin within 30 days of hire.")
        flag = B.detect_remote_bait(text)
        self.assertIsNotNone(flag)

    def test_remote_within_miles(self):
        text = ("Remote Data Analyst\n\nRemote (within 25 miles of Chicago) "
                "only. Apply now.")
        flag = B.detect_remote_bait(text)
        self.assertIsNotNone(flag)

    def test_onsite_five_days(self):
        text = ("Remote Backend Engineer\n\nWe are remote friendly but this "
                "role is onsite 5 days a week in Seattle.")
        flag = B.detect_remote_bait(text)
        self.assertIsNotNone(flag)

    def test_remote_us_only_no_flag(self):
        # Near miss: geographic eligibility is not bait.
        text = ("Remote Software Engineer\n\nRemote (US only). Must be "
                "authorized to work in the United States.")
        self.assertIsNone(B.detect_remote_bait(text))

    def test_hybrid_without_remote_ad_no_flag(self):
        # Near miss: honest hybrid label must not flag.
        text = ("Software Engineer\n\nHybrid role in NYC, 2 days in office.")
        self.assertIsNone(B.detect_remote_bait(text))

    def test_empty_input(self):
        self.assertIsNone(B.detect_remote_bait(""))
        self.assertIsNone(B.detect_remote_bait(None))


class BaitDetectAggregateTest(unittest.TestCase):
    def test_empty_input_returns_empty_list(self):
        self.assertEqual(B.detect(""), [])
        self.assertEqual(B.detect(None), [])

    def test_detect_aggregates_all_subdetectors(self):
        text = ("Remote Senior Engineer\n\n0-2 years welcome, training "
                "provided. Also hiring: java developer, python developer, "
                "data analyst, project manager. Hybrid role, must relocate.")
        flags = B.detect(text)
        ids = {f.flag_id for f in flags}
        self.assertEqual(
            ids,
            {"bait.title_level_mismatch", "bait.keyword_stuffing",
             "bait.remote_bait"},
        )

    def test_clean_posting_no_flags(self):
        text = ("Software Engineer\n\nBuild features in Python. 3+ years "
                "experience. Competitive salary.")
        self.assertEqual(B.detect(text), [])


class BaitAnalyzeIntegrationTest(unittest.TestCase):
    def test_analyze_surfaces_bait_flags_sorted(self):
        text = ("Remote Senior Engineer\n\n0-2 years welcome, training "
                "provided. Please attach a headshot. Hybrid role.")
        result = analyze(text)
        ids = [f.flag_id for f in result["flags"]]
        self.assertIn("bait.title_level_mismatch", ids)
        self.assertIn("bait.remote_bait", ids)
        self.assertIn("compliance.protected_info", ids)
        # worst severity first
        severities = [f.severity for f in result["flags"]]
        self.assertEqual(severities, sorted(
            severities, key=SEVERITIES.index))
        self.assertGreater(result["risk_score"], 0)

    def test_analyze_clean_posting(self):
        # A genuinely clean posting: pay range, responsibilities, team info.
        # Only info-severity (green) flags may fire; no red flags.
        result = analyze(
            "Software Engineer\n"
            "Salary: $120,000 - $150,000 per year.\n"
            "Responsibilities: Build features in Python. "
            "You will join the platform team, "
            "reporting to the engineering manager.")
        self.assertTrue(all(f.severity == "info" for f in result["flags"]))
        self.assertEqual(result["verdict"], "clean")
        self.assertEqual(result["risk_score"], 0)


if __name__ == "__main__":
    unittest.main()
