"""Tests for candid.redflags.compliance (compliance detectors).

Run: python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.redflags import bait as B  # noqa: F401  (registers bait detectors)
from candid.redflags import compliance as C
from candid.redflags.core import SEVERITIES, analyze


def _assert_flag_shape(tc, flag, flag_id, severity):
    tc.assertEqual(flag.flag_id, flag_id)
    tc.assertEqual(flag.severity, severity)
    tc.assertIn(severity, SEVERITIES)
    tc.assertEqual(flag.category, "compliance")
    tc.assertTrue(flag.title)
    # explanation: 2-4 sentences of plain language
    sentences = [s for s in flag.explanation.split(". ") if s.strip()]
    tc.assertGreaterEqual(len(sentences), 2)
    tc.assertLessEqual(len(sentences), 5)
    tc.assertTrue(flag.evidence)
    for snip in flag.evidence:
        tc.assertLessEqual(len(snip), 125)
    tc.assertTrue(flag.suggestion)


class AgeHintsTest(unittest.TestCase):
    def test_young_energetic_candidate(self):
        text = ("Software Engineer\n\nWe are looking for a young, energetic "
                "candidate to join our growing team.")
        flag = C.detect_age_hints(text)
        self.assertIsNotNone(flag)
        _assert_flag_shape(self, flag, "compliance.age_hints", "medium")
        self.assertIn("not legal advice", flag.explanation)

    def test_recent_graduate(self):
        text = "Analyst\n\nThis role is open to recent graduates."
        flag = C.detect_age_hints(text)
        self.assertIsNotNone(flag)
        self.assertEqual(flag.severity, "medium")

    def test_digital_native(self):
        text = "Marketing Associate\n\nWe need a digital native who lives on social media."
        flag = C.detect_age_hints(text)
        self.assertIsNotNone(flag)

    def test_overqualified_dismissive(self):
        text = ("Driver\n\nOverqualified candidates will not be considered. "
                "Do not apply if you have a degree.")
        flag = C.detect_age_hints(text)
        self.assertIsNotNone(flag)

    def test_young_company_no_flag(self):
        # Near miss: "young" describing the company, not the person.
        text = ("Software Engineer\n\nWe are a young startup with an "
                "energetic culture and a fast-paced environment.")
        self.assertIsNone(C.detect_age_hints(text))

    def test_energetic_environment_no_flag(self):
        # Near miss: "energetic" describing the workplace, not the applicant.
        text = "Engineer\n\nJoin our energetic work environment in downtown."
        self.assertIsNone(C.detect_age_hints(text))

    def test_overqualified_neutral_no_flag(self):
        # Near miss: "overqualified" without dismissive context.
        text = ("Engineer\n\nIf you feel overqualified, consider our senior "
                "opening instead.")
        self.assertIsNone(C.detect_age_hints(text))

    def test_empty_input(self):
        self.assertIsNone(C.detect_age_hints(""))
        self.assertIsNone(C.detect_age_hints(None))


class GenderedLanguageTest(unittest.TestCase):
    def test_masculine_cluster(self):
        text = ("Sales Lead\n\nWe need an aggressive, dominant hunter with an "
                "alpha mentality for competitive markets.")
        flag = C.detect_gendered_language(text)
        self.assertIsNotNone(flag)
        _assert_flag_shape(self, flag, "compliance.gendered_language", "low")
        self.assertIn("deter", flag.explanation)

    def test_generic_he_pronoun(self):
        text = ("Engineer\n\nHe will be responsible for the backend and his "
                "team will ship weekly.")
        flag = C.detect_gendered_language(text)
        self.assertIsNotNone(flag)
        self.assertEqual(flag.severity, "low")

    def test_manpower(self):
        text = ("Engineer\n\nHe will manage manpower planning and his team "
                "deliverables.")
        flag = C.detect_gendered_language(text)
        self.assertIsNotNone(flag)

    def test_competitive_alone_no_flag(self):
        # Near miss: "competitive" alone is fine.
        text = "Engineer\n\nWe offer a competitive salary and benefits."
        self.assertIsNone(C.detect_gendered_language(text))

    def test_single_aggressive_no_flag(self):
        # Near miss: one strong word without a cluster is just style.
        text = "Engineer\n\nWe take an aggressive approach to technical debt."
        self.assertIsNone(C.detect_gendered_language(text))

    def test_neutral_posting_no_flag(self):
        text = ("Engineer\n\nYou will build backend services. They will "
                "collaborate with the team.")
        self.assertIsNone(C.detect_gendered_language(text))

    def test_empty_input(self):
        self.assertIsNone(C.detect_gendered_language(""))
        self.assertIsNone(C.detect_gendered_language(None))


class ProtectedInfoTest(unittest.TestCase):
    def test_headshot_and_dob(self):
        text = ("Receptionist\n\nPlease attach a headshot and include your "
                "date of birth with your application.")
        flag = C.detect_protected_info(text)
        self.assertIsNotNone(flag)
        _assert_flag_shape(self, flag, "compliance.protected_info", "high")

    def test_marital_status_and_maiden_name(self):
        text = "Clerk\n\nProvide your marital status and maiden name on the form."
        flag = C.detect_protected_info(text)
        self.assertIsNotNone(flag)

    def test_ssn(self):
        text = "Associate\n\nInclude your SSN with your resume."
        flag = C.detect_protected_info(text)
        self.assertIsNotNone(flag)

    def test_citizenship_beyond_work_auth(self):
        text = "Engineer\n\nApplicants must disclose citizenship status."
        flag = C.detect_protected_info(text)
        self.assertIsNotNone(flag)

    def test_work_authorization_phrasing_no_flag(self):
        # Near miss: confirming work authorization is legitimate.
        text = ("Engineer\n\nMust be authorized to work in the United States. "
                "US citizen or permanent resident welcome.")
        self.assertIsNone(C.detect_protected_info(text))

    def test_photo_of_work_no_flag(self):
        # Near miss: "photo" in an unrelated sense must not flag.
        text = "Photographer\n\nPlease share a portfolio of your photo work."
        self.assertIsNone(C.detect_protected_info(text))

    def test_empty_input(self):
        self.assertIsNone(C.detect_protected_info(""))
        self.assertIsNone(C.detect_protected_info(None))


class MisclassificationTest(unittest.TestCase):
    def test_1099_with_set_hours(self):
        text = ("1099 independent contractor\n\nSet hours 9-5, must attend "
                "daily standup, exclusivity required.")
        flag = C.detect_misclassification(text)
        self.assertIsNotNone(flag)
        _assert_flag_shape(self, flag, "compliance.misclassification", "high")
        self.assertIn("classification", flag.suggestion)
        self.assertIn("benefits", flag.suggestion)

    def test_freelancer_with_noncompete(self):
        text = ("Freelancer wanted\n\nCore hours required and a non-compete "
                "applies for 12 months.")
        flag = C.detect_misclassification(text)
        self.assertIsNotNone(flag)

    def test_contractor_without_control_no_flag(self):
        # Near miss: genuine contractor terms must not flag.
        text = ("Independent contractor\n\nSet your own hours, work remotely, "
                "deliver milestones by the agreed dates.")
        self.assertIsNone(C.detect_misclassification(text))

    def test_employee_with_set_hours_no_flag(self):
        # Near miss: control signals without a contractor label are normal.
        text = ("Full-time employee\n\nSet hours 9-5 with benefits and PTO.")
        self.assertIsNone(C.detect_misclassification(text))

    def test_empty_input(self):
        self.assertIsNone(C.detect_misclassification(""))
        self.assertIsNone(C.detect_misclassification(None))


class OwnEquipmentTest(unittest.TestCase):
    def test_must_have_own_laptop(self):
        text = ("Full-time Support Agent\n\nYou must have your own laptop "
                "and provide your own vehicle for site visits.")
        flag = C.detect_own_equipment(text)
        self.assertIsNotNone(flag)
        _assert_flag_shape(self, flag, "compliance.own_equipment", "low")

    def test_bring_your_own_tools(self):
        text = "Technician\n\nBring your own tools; uniforms provided."
        flag = C.detect_own_equipment(text)
        self.assertIsNotNone(flag)

    def test_contractor_context_no_flag(self):
        # Near miss: providing your own gear is normal for real contractors.
        text = ("Freelancer\n\nMust have your own laptop and software.")
        self.assertIsNone(C.detect_own_equipment(text))

    def test_1099_context_no_flag(self):
        text = "1099 contractor\n\nProvide your own vehicle."
        self.assertIsNone(C.detect_own_equipment(text))

    def test_company_provided_no_flag(self):
        text = "Engineer\n\nWe provide a laptop and home-office stipend."
        self.assertIsNone(C.detect_own_equipment(text))

    def test_empty_input(self):
        self.assertIsNone(C.detect_own_equipment(""))
        self.assertIsNone(C.detect_own_equipment(None))


class ComplianceDetectAggregateTest(unittest.TestCase):
    def test_empty_input_returns_empty_list(self):
        self.assertEqual(C.detect(""), [])
        self.assertEqual(C.detect(None), [])

    def test_detect_aggregates_all_subdetectors(self):
        text = ("1099 contractor\n\nWe want a young, energetic candidate. "
                "Attach a headshot. Must attend daily standup. You must "
                "have your own laptop.")
        flags = C.detect(text)
        ids = {f.flag_id for f in flags}
        self.assertEqual(
            ids,
            {"compliance.age_hints", "compliance.protected_info",
             "compliance.misclassification"},
        )
        # own_equipment is suppressed by the contractor context
        self.assertNotIn("compliance.own_equipment", ids)

    def test_clean_posting_no_flags(self):
        text = ("Software Engineer\n\nBuild features in Python. 3+ years "
                "experience. Must be authorized to work in the US.")
        self.assertEqual(C.detect(text), [])


class ComplianceAnalyzeIntegrationTest(unittest.TestCase):
    def test_analyze_surfaces_compliance_flags(self):
        text = ("Senior Engineer\n\n0-2 years welcome, training provided. "
                "Attach a headshot. We need an aggressive, dominant hire.")
        result = analyze(text)
        ids = [f.flag_id for f in result["flags"]]
        self.assertIn("bait.title_level_mismatch", ids)
        self.assertIn("compliance.protected_info", ids)
        self.assertIn("compliance.gendered_language", ids)
        severities = [f.flag_id for f in result["flags"]]
        # high-severity flags come before low-severity ones
        self.assertLess(severities.index("compliance.protected_info"),
                        severities.index("compliance.gendered_language"))
        self.assertEqual(result["verdict"], "caution")

    def test_analyze_empty(self):
        result = analyze("")
        self.assertEqual(result["flags"], [])
        self.assertEqual(result["verdict"], "clean")

    def test_flags_json_serializable(self):
        import json
        result = analyze("Engineer\n\nAttach a headshot and state your age.")
        json.dumps(result["flags_json"])


if __name__ == "__main__":
    unittest.main()
