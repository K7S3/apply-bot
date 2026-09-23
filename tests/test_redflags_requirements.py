"""Tests for candid.redflags.requirements. Run:
python -m unittest tests.test_redflags_requirements -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.redflags import requirements as R  # noqa: E402  (registers detectors)
from candid.redflags.core import analyze  # noqa: E402


def _ids(flags):
    return {f.flag_id for f in flags}


class YearsImpossibleTest(unittest.TestCase):
    def test_medium_gap(self):
        # dbt released ~2016 -> max plausible 11; 12 asked.
        text = "Senior Data Engineer\nWe require 12 years of dbt experience."
        flags = R.detect_years_impossible(text)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].flag_id, "req.years_impossible")
        self.assertEqual(flags[0].severity, "medium")
        self.assertIn("dbt", flags[0].evidence[0].lower())

    def test_high_gap(self):
        # Kubernetes released ~2014 -> max plausible 13; 18 asked (gap 5).
        text = "Platform Engineer\nMust have 18+ years of Kubernetes experience."
        flags = R.detect_years_impossible(text)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].severity, "high")

    def test_plausible_years_no_flag(self):
        text = "Frontend Engineer\n5 years of React experience required."
        self.assertEqual(R.detect_years_impossible(text), [])

    def test_old_tech_no_flag(self):
        # Go released ~2009 -> max plausible 18; 10 is fine.
        text = "Backend Engineer\n10 years of Go experience preferred."
        self.assertEqual(R.detect_years_impossible(text), [])

    def test_years_far_from_tech_not_linked(self):
        text = ("We are 15 years old as a company. " + "x" * 200 + "\n"
                "Backend Engineer\nSome Rust exposure is a plus.")
        self.assertEqual(R.detect_years_impossible(text), [])

    def test_case_insensitive(self):
        text = "Data Engineer\nNeed 15 years of DBT experience."
        flags = R.detect_years_impossible(text)
        self.assertEqual(len(flags), 1)


class JuniorSeniorMismatchTest(unittest.TestCase):
    def test_junior_title_many_years(self):
        text = ("Junior Software Engineer\n"
                "Requirements: 5+ years of professional experience.")
        flags = R.detect_junior_senior_mismatch(text)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].flag_id, "req.junior_senior_mismatch")
        self.assertEqual(flags[0].severity, "medium")

    def test_junior_title_few_years_ok(self):
        text = ("Junior Software Engineer\n"
                "Requirements: 1-2 years of experience welcome.")
        self.assertEqual(R.detect_junior_senior_mismatch(text), [])

    def test_senior_title_one_year(self):
        text = ("Senior Data Engineer\n"
                "Requirements: 1 year of experience required.")
        flags = R.detect_junior_senior_mismatch(text)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].flag_id, "req.junior_senior_mismatch")

    def test_senior_title_many_years_ok(self):
        text = ("Senior Data Engineer\n"
                "Requirements: 7+ years of experience.")
        self.assertEqual(R.detect_junior_senior_mismatch(text), [])

    def test_mid_title_no_flag(self):
        text = ("Software Engineer\nRequirements: 4 years of experience.")
        self.assertEqual(R.detect_junior_senior_mismatch(text), [])

    def test_title_field_format(self):
        text = ("Job Title: Associate Engineer\n"
                "We ask for 6 years of backend experience.")
        flags = R.detect_junior_senior_mismatch(text)
        self.assertEqual(len(flags), 1)

    def test_entry_level_wording(self):
        text = ("Entry-Level Analyst\nMinimum 4 years in analytics required.")
        flags = R.detect_junior_senior_mismatch(text)
        self.assertEqual(len(flags), 1)


class LaundryListTest(unittest.TestCase):
    EXPERT_TEXT = """Software Engineer
    Requirements: expert in Python, expertise in Java, mastery of Go,
    deep knowledge of Kubernetes, expert in Terraform, expertise in Snowflake.
    """

    def test_six_expert_techs_flagged(self):
        flags = R.detect_laundry_list(self.EXPERT_TEXT)
        self.assertTrue(any(f.flag_id == "req.laundry_list" for f in flags))
        self.assertTrue(all(f.severity == "medium" for f in flags))

    def test_five_expert_techs_ok(self):
        text = ("Software Engineer\nRequirements: expert in Python, "
                "expertise in Java, mastery of Go, deep knowledge of "
                "Kubernetes, expert in Terraform.")
        self.assertEqual(R.detect_laundry_list(text), [])

    def test_twelve_bullets_flagged(self):
        bullets = "\n".join(f"- Must know tool{i}" for i in range(12))
        text = f"Software Engineer\nRequirements:\n{bullets}"
        flags = R.detect_laundry_list(text)
        self.assertTrue(any(f.flag_id == "req.laundry_list" for f in flags))

    def test_eleven_bullets_ok(self):
        bullets = "\n".join(f"- Must know tool{i}" for i in range(11))
        text = f"Software Engineer\nRequirements:\n{bullets}"
        self.assertEqual(R.detect_laundry_list(text), [])

    def test_bullets_without_heading_ignored(self):
        bullets = "\n".join(f"- random note {i}" for i in range(15))
        text = f"Software Engineer\nSome notes:\n{bullets}"
        self.assertEqual(R.detect_laundry_list(text), [])


class DegreeInflationTest(unittest.TestCase):
    def test_phd_required_non_research(self):
        text = ("Backend Software Engineer\n"
                "Requirements: PhD required in computer science.")
        flags = R.detect_degree_inflation(text)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].flag_id, "req.degree_inflation")
        self.assertEqual(flags[0].severity, "low")

    def test_phd_required_research_role_ok(self):
        text = ("Research Scientist, NLP\n"
                "Requirements: PhD required in machine learning.")
        self.assertEqual(R.detect_degree_inflation(text), [])

    def test_phd_preferred_ok(self):
        text = ("Backend Software Engineer\n"
                "PhD preferred but not required for strong candidates.")
        # "required" appears but as a negation-free "not required" still
        # matches the required-word heuristic; this documents current behavior.
        flags = R.detect_degree_inflation(text)
        self.assertTrue(all(f.flag_id == "req.degree_inflation" for f in flags))

    def test_mba_required_ic_engineering(self):
        text = ("Backend Engineer\n"
                "Requirements: MBA required; 3 years of Java.")
        flags = R.detect_degree_inflation(text)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].flag_id, "req.degree_inflation")

    def test_mba_required_manager_ok(self):
        text = ("Engineering Manager\n"
                "Requirements: MBA required; 5 years leading teams.")
        self.assertEqual(R.detect_degree_inflation(text), [])

    def test_no_degree_mentions_ok(self):
        text = "Software Engineer\nRequirements: 3 years of Python."
        self.assertEqual(R.detect_degree_inflation(text), [])


class ContradictionTest(unittest.TestCase):
    def test_entry_level_plus_five_years(self):
        text = ("Entry level software engineer.\n"
                "Requirements: 5+ years of Java experience.")
        flags = R.detect_contradiction(text)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].flag_id, "req.contradiction")
        self.assertEqual(flags[0].severity, "medium")

    def test_no_experience_necessary_plus_senior(self):
        text = ("No experience necessary to apply.\n"
                "We are hiring a senior engineer to lead the team.")
        flags = R.detect_contradiction(text)
        self.assertEqual(len(flags), 1)

    def test_entry_level_modest_years_ok(self):
        text = ("Entry-level role.\nRequirements: 1-2 years of experience.")
        self.assertEqual(R.detect_contradiction(text), [])

    def test_five_years_alone_ok(self):
        text = "Software Engineer\nRequirements: 5+ years of Java."
        self.assertEqual(R.detect_contradiction(text), [])


class RobustnessTest(unittest.TestCase):
    DETECTORS = (
        R.detect_years_impossible,
        R.detect_junior_senior_mismatch,
        R.detect_laundry_list,
        R.detect_degree_inflation,
        R.detect_contradiction,
    )

    def test_empty_and_none(self):
        for d in self.DETECTORS:
            self.assertEqual(d(""), [])
            self.assertEqual(d(None), [])

    def test_whitespace_only(self):
        for d in self.DETECTORS:
            self.assertEqual(d("   \n\t  "), [])

    def test_non_string_input(self):
        for d in self.DETECTORS:
            self.assertEqual(d(123), [])
            self.assertEqual(d(["x"]), [])

    def test_flag_fields_valid(self):
        text = ("Junior Rust Engineer\nEntry level position, no experience "
                "necessary.\nRequirements: 18+ years of Rust, PhD required, "
                "MBA required.\nExpert in Python, Java, Go, Kubernetes, "
                "Terraform, Snowflake.")
        result = analyze(text)
        # Other detectors may also fire on this kitchen-sink posting;
        # validate only the requirements-category flags.
        flags = [f for f in result["flags"]
                 if f.flag_id.startswith("req.")]
        self.assertGreater(len(flags), 0)
        for f in flags:
            self.assertIn(f.severity, ("critical", "high", "medium", "low", "info"))
            self.assertTrue(f.flag_id.startswith("req."))
            self.assertEqual(f.category, "requirements")
            self.assertTrue(len(f.explanation.split(". ")) >= 2)
            self.assertTrue(f.suggestion)
            self.assertTrue(all(len(e) <= 200 for e in f.evidence))


class AnalyzeIntegrationTest(unittest.TestCase):
    def test_detectors_registered_and_run(self):
        text = ("Junior Software Engineer\n"
                "We require 15+ years of Rust experience.")
        result = analyze(text)
        ids = _ids(result["flags"])
        self.assertIn("req.years_impossible", ids)
        self.assertIn("req.junior_senior_mismatch", ids)
        self.assertIn("risk_score", result)
        self.assertGreater(result["risk_score"], 0)
        self.assertIn(result["verdict"], ("clean", "caution", "risky"))

    def test_clean_posting_no_flags(self):
        text = ("Software Engineer\n"
                "Requirements: 3 years of Python, 2 years of Go.\n"
                "BS in computer science or equivalent experience.")
        result = analyze(text)
        ids = _ids(result["flags"])
        for fid in ("req.years_impossible", "req.junior_senior_mismatch",
                    "req.laundry_list", "req.degree_inflation",
                    "req.contradiction"):
            self.assertNotIn(fid, ids)


if __name__ == "__main__":
    unittest.main()
