"""Tests for candid.redflags.clarity (vague-role detectors)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.redflags import clarity  # noqa: E402


def _ids(flags):
    return [f.flag_id for f in flags]


class NoResponsibilitiesTest(unittest.TestCase):
    def test_flags_posting_without_duties(self):
        text = (
            "Senior Software Engineer\n\nWe are hiring a great engineer. "
            "Competitive salary and benefits. Apply now."
        )
        flags = clarity.detect_no_responsibilities(text)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual(f.flag_id, "clarity.no_responsibilities")
        self.assertEqual(f.severity, "medium")
        self.assertEqual(f.category, "clarity")
        self.assertTrue(f.suggestion)

    def test_no_flag_when_responsibilities_present(self):
        text = (
            "Backend Engineer\n\nResponsibilities:\n- Build and maintain APIs\n"
            "- Ship features weekly\n\nRequirements: 3+ years of Python."
        )
        self.assertEqual(clarity.detect_no_responsibilities(text), [])

    def test_no_flag_for_what_youll_do_heading(self):
        text = "What you'll do:\n- Own the payments service\n- Debug prod issues"
        self.assertEqual(clarity.detect_no_responsibilities(text), [])

    def test_empty_and_none_return_empty(self):
        self.assertEqual(clarity.detect_no_responsibilities(""), [])
        self.assertEqual(clarity.detect_no_responsibilities(None), [])
        self.assertEqual(clarity.detect_no_responsibilities("   "), [])


class BuzzwordSoupTest(unittest.TestCase):
    SOUPY = (
        "We need a rockstar ninja who can leverage synergies and disrupt the "
        "paradigm. Move fast, deep dive into bleeding edge innovation, and "
        "become a thought leader. Our fast-paced environment rewards go-getters "
        "who wear many hats and move the needle every day. World-class team "
        "seeking self-starters to ideate game changer solutions."
    )
    CLEAN = (
        "Backend Engineer\n\nResponsibilities:\n- Build and ship REST APIs in "
        "Python\n- Design database schemas and review pull requests\n- Debug "
        "production issues and monitor service health\n- Write unit and "
        "integration tests; deploy with CI/CD\n- Mentor junior engineers and "
        "document runbooks\n\nRequirements: 3+ years experience."
    )

    def test_flags_buzzword_soup(self):
        self.assertGreater(len(self.SOUPY), 300)
        flags = clarity.detect_buzzword_soup(self.SOUPY)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual(f.flag_id, "clarity.buzzword_soup")
        self.assertEqual(f.severity, "low")
        self.assertEqual(f.category, "clarity")

    def test_no_flag_for_concrete_posting(self):
        self.assertEqual(clarity.detect_buzzword_soup(self.CLEAN), [])

    def test_short_postings_skipped(self):
        self.assertEqual(clarity.detect_buzzword_soup("rockstar ninja synergy"), [])

    def test_empty_and_none_return_empty(self):
        self.assertEqual(clarity.detect_buzzword_soup(""), [])
        self.assertEqual(clarity.detect_buzzword_soup(None), [])


class DutiesAssignedTest(unittest.TestCase):
    def test_flags_catch_all_with_empty_section(self):
        text = (
            "Junior Analyst\n\nResponsibilities:\n- Other duties as assigned.\n\n"
            "Requirements: Bachelor's degree."
        )
        flags = clarity.detect_duties_assigned(text)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual(f.flag_id, "clarity.duties_assigned")
        self.assertEqual(f.severity, "medium")
        self.assertIn("other duties as assigned", f.evidence[0].lower())

    def test_no_flag_when_real_duties_listed(self):
        duties = (
            "Responsibilities:\n"
            + "\n".join(
                f"- Own reporting pipeline {i}: build dashboards, validate "
                f"data, and ship weekly reports to stakeholders."
                for i in range(4)
            )
            + "\n- Other duties as assigned.\n\nRequirements: Excel."
        )
        self.assertEqual(clarity.detect_duties_assigned(duties), [])

    def test_no_flag_without_catch_all(self):
        text = "Responsibilities:\n- Answer phones.\n\nRequirements: none."
        self.assertEqual(clarity.detect_duties_assigned(text), [])

    def test_empty_and_none_return_empty(self):
        self.assertEqual(clarity.detect_duties_assigned(""), [])
        self.assertEqual(clarity.detect_duties_assigned(None), [])


class NoTeamInfoTest(unittest.TestCase):
    def test_flags_posting_without_team_mention(self):
        text = (
            "Data Scientist\n\nResponsibilities:\n- Build models\n\n"
            "Requirements: Python, SQL. Competitive pay."
        )
        flags = clarity.detect_no_team_info(text)
        self.assertEqual(len(flags), 1)
        f = flags[0]
        self.assertEqual(f.flag_id, "clarity.no_team_info")
        self.assertEqual(f.severity, "low")
        self.assertIn("who you would work with", f.suggestion.lower())

    def test_no_flag_when_team_mentioned(self):
        text = (
            "Data Scientist\n\nYou will join our data team, reporting to the "
            "hiring manager. Responsibilities:\n- Build models."
        )
        self.assertEqual(clarity.detect_no_team_info(text), [])

    def test_empty_and_none_return_empty(self):
        self.assertEqual(clarity.detect_no_team_info(""), [])
        self.assertEqual(clarity.detect_no_team_info(None), [])


class ClarityAnalyzeIntegrationTest(unittest.TestCase):
    def test_analyze_surfaces_clarity_flags(self):
        from candid.redflags.core import analyze

        vague = (
            "Amazing opportunity! We need a rockstar to leverage synergies. "
            "You may be asked to do other things too. Apply now."
        )
        ids = _ids(analyze(vague)["flags"])
        self.assertIn("clarity.no_responsibilities", ids)
        self.assertIn("clarity.no_team_info", ids)

        catch_all = (
            "Junior Analyst\n\nResponsibilities:\n- Other duties as assigned.\n\n"
            "Requirements: Bachelor's degree."
        )
        ids = _ids(analyze(catch_all)["flags"])
        self.assertIn("clarity.duties_assigned", ids)

    def test_analyze_clean_for_good_posting(self):
        from candid.redflags.core import analyze

        text = (
            "Backend Engineer\n\nWhat you'll do:\n- Build and ship REST APIs\n"
            "- Design schemas; review code; debug prod\n\nYou will join our "
            "engineering team, reporting to the hiring manager.\n\n"
            "Requirements: 3+ years Python."
        )
        result = analyze(text)
        clarity_ids = [i for i in _ids(result["flags"]) if i.startswith("clarity.")]
        self.assertEqual(clarity_ids, [])


if __name__ == "__main__":
    unittest.main()
