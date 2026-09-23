"""Tests for the managing-up toolkit + 30-60-90 planner (em_toolkit.py).

Run: CANDID_DATA_DIR=/tmp/candid-test-em python -m pytest tests/test_em_toolkit.py
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-em-toolkit")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class WeeklyUpdateTemplateTest(unittest.TestCase):
    def test_template_sections(self):
        from candid import em_toolkit as T
        md = T.weekly_update_template("Casey Lee", "Payments", "W38")
        self.assertIn("Weekly update", md)
        self.assertIn("Payments", md)
        self.assertIn("Casey Lee", md)
        self.assertIn("W38", md)
        for section in ("## Wins this week", "## Risks and blockers",
                        "## Next week", "## Asks of leadership"):
            self.assertIn(section, md)

    def test_template_no_week(self):
        from candid import em_toolkit as T
        md = T.weekly_update_template("Casey Lee", "Payments")
        self.assertIn("Weekly update", md)


class ExecSummaryTest(unittest.TestCase):
    def test_notes_categorized_and_verbatim(self):
        from candid import em_toolkit as T
        notes = (
            "- Shipped the new checkout flow\n"
            "- On-call latency up 20% this week\n"
            "- Hiring pipeline is blocked on panel capacity\n"
            "- Need VP approval for two headcount\n"
            "- Had lunch with the team"
        )
        md = T.exec_summary(notes, name="Casey Lee")
        self.assertIn("Casey Lee", md)
        self.assertIn("## Highlights", md)
        self.assertIn("## Metrics", md)
        self.assertIn("## Risks", md)
        self.assertIn("## Asks", md)
        self.assertIn("## Other notes", md)
        # every note appears verbatim — nothing invented, nothing dropped
        for fragment in ("checkout flow", "latency up 20%", "blocked on panel",
                         "VP approval", "lunch with the team"):
            self.assertIn(fragment, md)
        self.assertIn("TL;DR", md)

    def test_empty_notes_raises(self):
        from candid import em_toolkit as T
        with self.assertRaises(T.EmToolkitError):
            T.exec_summary("   \n  ")


class Plan306090Test(unittest.TestCase):
    def test_plan_sections(self):
        from candid import em_toolkit as T
        md = T.plan_30_60_90("Acme", "Payments", context="Post-launch scale-up")
        self.assertIn("Acme", md)
        self.assertIn("Payments", md)
        self.assertIn("Post-launch scale-up", md)
        for section in ("First 30 days", "Days 31-60", "Days 61-90"):
            self.assertIn(section, md)
        self.assertIn("1:1", md)
        self.assertIn("stakeholder", md.lower())

    def test_plan_includes_profile_background(self):
        from candid import em_toolkit as T
        profile = {"name": "Casey Lee", "years_experience": 8,
                   "experience": [{"title": "Engineering Manager"}]}
        md = T.plan_30_60_90("Acme", "Payments", profile=profile)
        self.assertIn("Casey Lee", md)
        self.assertIn("8 years of experience", md)

    def test_plan_without_profile_has_no_background(self):
        from candid import em_toolkit as T
        md = T.plan_30_60_90("Acme", "Payments")
        self.assertNotIn("Background", md)

    def test_plan_requires_company_and_team(self):
        from candid import em_toolkit as T
        with self.assertRaises(T.EmToolkitError):
            T.plan_30_60_90("", "Payments")
        with self.assertRaises(T.EmToolkitError):
            T.plan_30_60_90("Acme", "")


class EmCliWiringTest(unittest.TestCase):
    def test_parser_has_em_subcommands(self):
        from candid.__main__ import build_parser
        p = build_parser()
        for argv in (
            ["em", "stories"],
            ["em", "stories", "--competency", "hiring_bar"],
            ["em", "stories", "--search", "outage"],
            ["em", "update-template"],
            ["em", "exec-summary"],
            ["em", "plan-30-60-90", "--company", "Acme", "--team", "Payments"],
        ):
            args = p.parse_args(argv)
            self.assertEqual("em", args.cmd, argv)


if __name__ == "__main__":
    unittest.main()
