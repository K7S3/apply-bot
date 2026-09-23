"""Tests for the career-switcher cover letter and 30-60-90 ramp modules.

candid.switch_letter: switch_paragraph, full_switch_letter.
candid.switch_ramp: build_ramp_plan, ramp_markdown.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.switch_letter import (  # noqa: E402
    SwitchLetterError,
    full_switch_letter,
    switch_paragraph,
)
from candid.switch_ramp import (  # noqa: E402
    SwitchRampError,
    build_ramp_plan,
    ramp_markdown,
)


FULL_PROFILE = {
    "past_role": "Middle School Teacher",
    "past_domain": "K-12 education",
    "years_experience": 7,
    "transferable_skills": ["curriculum design", "data-driven assessment", "stakeholder communication"],
    "target_strengths": ["instructional design", "learner analytics"],
    "motivation": "I kept building tooling for my classroom and realized I want to build learning software full time.",
    "company_note": "its apprenticeship model for new engineers",
}


class SwitchParagraphTest(unittest.TestCase):
    def test_full_profile_covers_all_five_beats(self):
        p = switch_paragraph(FULL_PROFILE, "Learning Experience Designer", "Acme Learn")
        # 1. through-line from past work
        self.assertIn("Middle School Teacher", p)
        self.assertIn("K-12 education", p)
        self.assertIn("7 years", p)
        # 2. transferable skills
        self.assertIn("curriculum design", p)
        self.assertIn("data-driven assessment", p)
        self.assertIn("stakeholder communication", p)
        # 3. motivation verbatim
        self.assertIn("building tooling for my classroom", p)
        # 4. what the switcher brings
        self.assertIn("instructional design", p)
        self.assertIn("learner analytics", p)
        # 5. why this company
        self.assertIn("Acme Learn", p)
        self.assertIn("apprenticeship model", p)
        self.assertIn("Learning Experience Designer", p)

    def test_missing_facts_become_placeholders(self):
        p = switch_paragraph({}, "Data Analyst", "Beta Corp")
        self.assertIn("[PLACEHOLDER]", p)
        # no facts invented: years, past role, skills, motivation, company note
        for invented in ("Teacher", "curriculum", "passion", "years", "because"):
            self.assertNotIn(invented, p)
        self.assertIn("Data Analyst", p)
        self.assertIn("Beta Corp", p)

    def test_partial_profile_placeholders_only_where_missing(self):
        p = switch_paragraph({"past_role": "Nurse"}, "UX Researcher", "Gamma")
        self.assertIn("Nurse", p)
        self.assertIn("UX Researcher", p)
        self.assertIn("[PLACEHOLDER]", p)  # missing domain/skills/motivation/company
        self.assertNotIn("curriculum design", p)

    def test_blank_target_role_raises(self):
        with self.assertRaises(SwitchLetterError):
            switch_paragraph(FULL_PROFILE, "   ", "Acme Learn")

    def test_blank_company_raises(self):
        with self.assertRaises(SwitchLetterError):
            switch_paragraph(FULL_PROFILE, "Designer", "")

    def test_non_dict_profile_raises(self):
        with self.assertRaises(SwitchLetterError):
            switch_paragraph(["not", "a", "dict"], "Designer", "Acme")

    def test_years_not_invented_when_missing(self):
        p = switch_paragraph({"past_role": "Barista", "past_domain": "retail"},
                             "Support Engineer", "Delta Co")
        self.assertIn("After a number of years", p)
        self.assertNotIn("7 years", p)
        self.assertNotIn("10 years", p)

    def test_deterministic(self):
        a = switch_paragraph(FULL_PROFILE, "Learning Experience Designer", "Acme Learn")
        b = switch_paragraph(FULL_PROFILE, "Learning Experience Designer", "Acme Learn")
        self.assertEqual(a, b)


class FullSwitchLetterTest(unittest.TestCase):
    def test_letter_structure(self):
        letter = full_switch_letter(FULL_PROFILE, "Learning Experience Designer",
                                    "Acme Learn", name="Keshavan S",
                                    email="keshavan@example.com", phone="201-555-0100")
        # greeting
        self.assertIn("Dear Hiring Manager", letter)
        # application line names role and company
        self.assertIn("Learning Experience Designer", letter)
        self.assertIn("Acme Learn", letter)
        # switch paragraph embedded
        self.assertIn(switch_paragraph(FULL_PROFILE, "Learning Experience Designer",
                                       "Acme Learn"), letter)
        # closing + signature + contact
        self.assertIn("Sincerely,", letter)
        self.assertIn("Keshavan S", letter)
        self.assertIn("keshavan@example.com", letter)
        self.assertIn("201-555-0100", letter)

    def test_draft_only_note_and_never_sends(self):
        letter = full_switch_letter(FULL_PROFILE, "Designer", "Acme Learn", name="Keshavan S")
        self.assertIn("Draft only", letter)
        self.assertIn("never sent", letter)

    def test_missing_name_is_placeholder(self):
        letter = full_switch_letter(FULL_PROFILE, "Designer", "Acme Learn")
        self.assertIn("[PLACEHOLDER]", letter)

    def test_custom_greeting(self):
        letter = full_switch_letter(FULL_PROFILE, "Designer", "Acme Learn",
                                    name="Keshavan S", greeting="Hello Priya")
        self.assertIn("Hello Priya,", letter)

    def test_invalid_inputs_raise(self):
        with self.assertRaises(SwitchLetterError):
            full_switch_letter(FULL_PROFILE, "", "Acme Learn")
        with self.assertRaises(SwitchLetterError):
            full_switch_letter("nope", "Designer", "Acme Learn")

    def test_no_contact_line_when_missing(self):
        letter = full_switch_letter(FULL_PROFILE, "Designer", "Acme Learn", name="K S")
        self.assertNotIn("@", letter)


class BuildRampPlanTest(unittest.TestCase):
    def test_three_phases_with_all_sections(self):
        plan = build_ramp_plan("Support Engineer", "Delta Co")
        self.assertEqual(plan["target_role"], "Support Engineer")
        self.assertEqual(plan["company"], "Delta Co")
        self.assertEqual(len(plan["phases"]), 3)
        self.assertEqual([p["name"] for p in plan["phases"]],
                         ["Learn", "Contribute", "Own"])
        self.assertEqual([p["days"] for p in plan["phases"]],
                         ["0-30", "30-60", "60-90"])
        for phase in plan["phases"]:
            for key in ("goals", "questions", "relationships", "metrics"):
                self.assertIsInstance(phase[key], list)
                self.assertGreater(len(phase[key]), 0)

    def test_role_personalizes_content(self):
        plan = build_ramp_plan("Support Engineer", "Delta Co")
        joined = " ".join(" ".join(p["goals"]) for p in plan["phases"])
        self.assertIn("Support Engineer", joined)

    def test_known_gaps_become_learning_goals(self):
        plan = build_ramp_plan("Data Analyst", "Beta Corp",
                               known_gaps=["SQL window functions", "dbt basics"])
        learn = plan["phases"][0]
        self.assertEqual(learn["name"], "Learn")
        goal_text = " ".join(learn["goals"])
        self.assertIn("SQL window functions", goal_text)
        self.assertIn("dbt basics", goal_text)
        self.assertIn("Close gap", goal_text)
        # pairing question points at the gaps too
        self.assertIn("SQL window functions", " ".join(learn["questions"]))
        self.assertEqual(plan["known_gaps"], ["SQL window functions", "dbt basics"])

    def test_no_gaps_still_builds(self):
        plan = build_ramp_plan("Data Analyst", "Beta Corp")
        self.assertEqual(plan["known_gaps"], [])
        self.assertNotIn("Close gap", " ".join(plan["phases"][0]["goals"]))

    def test_blank_gap_strings_skipped(self):
        plan = build_ramp_plan("Data Analyst", "Beta Corp",
                               known_gaps=["  ", "SQL"])
        self.assertEqual(plan["known_gaps"], ["SQL"])

    def test_bad_gaps_raise(self):
        with self.assertRaises(SwitchRampError):
            build_ramp_plan("Data Analyst", "Beta Corp", known_gaps=42)
        with self.assertRaises(SwitchRampError):
            build_ramp_plan("Data Analyst", "Beta Corp", known_gaps=["SQL", 5])

    def test_blank_inputs_raise(self):
        with self.assertRaises(SwitchRampError):
            build_ramp_plan("", "Beta Corp")
        with self.assertRaises(SwitchRampError):
            build_ramp_plan("Data Analyst", "   ")

    def test_deterministic(self):
        a = build_ramp_plan("Data Analyst", "Beta Corp", known_gaps=["SQL"])
        b = build_ramp_plan("Data Analyst", "Beta Corp", known_gaps=["SQL"])
        self.assertEqual(a, b)


class RampMarkdownTest(unittest.TestCase):
    def test_renders_all_phases_and_sections(self):
        plan = build_ramp_plan("Support Engineer", "Delta Co",
                               known_gaps=["Linux fundamentals"])
        md = ramp_markdown(plan)
        # title
        self.assertIn("# 30-60-90 Ramp Plan: Support Engineer at Delta Co", md)
        # all three phase headings
        self.assertIn("## Learn (Days 0-30)", md)
        self.assertIn("## Contribute (Days 30-60)", md)
        self.assertIn("## Own (Days 60-90)", md)
        # every section label appears under every phase
        for label in ("Goals", "Key questions to ask", "Relationships to build",
                      "Success metrics"):
            self.assertEqual(md.count(f"### {label}"), 3)
        # gap carried into the markdown
        self.assertIn("Linux fundamentals", md)
        # bullets only, no empty lines of content
        self.assertIn("- ", md)

    def test_gaps_absent_when_none(self):
        md = ramp_markdown(build_ramp_plan("Data Analyst", "Beta Corp"))
        self.assertNotIn("Close gap", md)

    def test_malformed_plan_raises(self):
        with self.assertRaises(SwitchRampError):
            ramp_markdown("not a plan")
        with self.assertRaises(SwitchRampError):
            ramp_markdown({"target_role": "X", "company": "Y"})
        broken = build_ramp_plan("Data Analyst", "Beta Corp")
        broken["phases"][1]["metrics"] = []
        with self.assertRaises(SwitchRampError):
            ramp_markdown(broken)

    def test_deterministic(self):
        plan = build_ramp_plan("Support Engineer", "Delta Co", known_gaps=["git"])
        self.assertEqual(ramp_markdown(plan), ramp_markdown(plan))


if __name__ == "__main__":
    unittest.main()
