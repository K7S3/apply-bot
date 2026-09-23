"""Tests for the EM story bank + team-health storytelling (em_stories.py).

Run: CANDID_DATA_DIR=/tmp/candid-test-em python -m pytest tests/test_em_stories.py
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-em-stories")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = Path("/tmp/candid-test-em-stories")


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


MGMT_PROFILE = {
    "name": "Casey Lee",
    "summary": "Engineering manager.",
    "experience": [
        {
            "title": "Engineering Manager",
            "company": "Acme Corp",
            "dates": "2023-2026",
            "bullets": [
                "Hired and onboarded 6 engineers, growing the team from 4 to 10.",
                "Coached two engineers to promotion through structured 1:1s.",
                "Led incident response for a 3-hour checkout outage, cutting "
                "time-to-mitigate by 40%.",
                "Drove cross-functional alignment with product on the roadmap.",
            ],
        },
        {
            "title": "Senior Software Engineer",
            "company": "Beta Inc",
            "dates": "2020-2023",
            "bullets": [
                "Shipped a caching layer that cut p99 latency by 30%.",
            ],
        },
    ],
}

IC_PROFILE = {
    "name": "Dev Patel",
    "summary": "Software engineer.",
    "experience": [
        {
            "title": "Software Engineer",
            "company": "Gamma LLC",
            "dates": "2022-2026",
            "bullets": [
                "Shipped a feature-flag service used by 12 teams.",
            ],
        },
    ],
}


class EmTaggingTest(unittest.TestCase):
    def test_hiring_bar_tag(self):
        from candid import em_stories as E
        self.assertIn("hiring_bar", E.tag_em_bullet(
            "Hired and onboarded 5 engineers."))

    def test_growing_engineers_tag(self):
        from candid import em_stories as E
        self.assertIn("growing_engineers", E.tag_em_bullet(
            "Mentored junior engineers through weekly 1:1s."))

    def test_incident_leadership_tag(self):
        from candid import em_stories as E
        self.assertIn("incident_leadership", E.tag_em_bullet(
            "Led the Sev-1 war room and wrote the postmortem."))

    def test_managing_up_tag(self):
        from candid import em_stories as E
        self.assertIn("managing_up", E.tag_em_bullet(
            "Got executive buy-in for the roadmap."))

    def test_org_design_tag(self):
        from candid import em_stories as E
        self.assertIn("org_design", E.tag_em_bullet(
            "Managed a team of 8 with direct reports across two time zones."))

    def test_cross_team_influence_tag(self):
        from candid import em_stories as E
        self.assertIn("cross_team_influence", E.tag_em_bullet(
            "Drove cross-functional alignment across three teams."))

    def test_no_em_signal_untagged(self):
        from candid import em_stories as E
        self.assertEqual([], E.tag_em_bullet(
            "Wrote unit tests for the billing module."))

    def test_prompt_keys_known(self):
        from candid import em_stories as E
        for key in ("struggling-team", "raised-the-bar", "managing-up",
                    "incident", "underperformer", "cross-team"):
            self.assertIn(key, E.TEAM_HEALTH_PROMPTS)


class EmStoriesBuildTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_build_only_tags_em_bullets(self):
        from candid import em_stories as E
        stories = E.build_em_stories(MGMT_PROFILE)
        # 4 management bullets, 1 IC bullet -> 4 stories
        self.assertEqual(4, len(stories))
        self.assertTrue(all(s["id"].startswith("e") for s in stories))
        titles = " ".join(s["title"] for s in stories)
        self.assertNotIn("caching layer", titles)

    def test_build_raises_when_no_em_signal(self):
        from candid import em_stories as E
        with self.assertRaises(E.EmStoriesError):
            E.build_em_stories(IC_PROFILE)

    def test_competency_filter(self):
        from candid import em_stories as E
        E.build_em_stories(MGMT_PROFILE)
        stories = E.list_em_stories(competency="hiring_bar")
        self.assertEqual(1, len(stories))
        self.assertIn("hiring_bar", stories[0]["competencies"])

    def test_query_search(self):
        from candid import em_stories as E
        E.build_em_stories(MGMT_PROFILE)
        stories = E.list_em_stories(query="outage")
        self.assertEqual(1, len(stories))
        self.assertIn("incident_leadership", stories[0]["competencies"])

    def test_update_and_get(self):
        from candid import em_stories as E
        E.build_em_stories(MGMT_PROFILE)
        updated = E.update_em_story("e1", "My written version.")
        self.assertEqual("My written version.", updated["user_text"])
        self.assertEqual("My written version.",
                         E.get_em_story("e1")["user_text"])
        with self.assertRaises(E.EmStoriesError):
            E.get_em_story("e99")

    def test_format_renders_star(self):
        from candid import em_stories as E
        E.build_em_stories(MGMT_PROFILE)
        md = E.format_em_story(E.get_em_story("e1"))
        for section in ("## Situation", "## Task", "## Action", "## Result"):
            self.assertIn(section, md)
        self.assertIn("Acme Corp", md)


class TeamHealthNarrativeTest(unittest.TestCase):
    def test_narrative_grounded_in_profile(self):
        from candid import em_stories as E
        result = E.em_narrative(MGMT_PROFILE, "incident")
        self.assertIn("checkout outage", result["narrative"])
        # evidence bullets are quoted verbatim from the profile
        self.assertEqual(2, len(result["evidence"]))
        self.assertIn("3-hour checkout outage",
                      result["evidence"][0]["bullet"])
        self.assertIn("[Describe the team", result["narrative"])

    def test_narrative_flags_gap_for_ic_profile(self):
        from candid import em_stories as E
        result = E.em_narrative(IC_PROFILE, "struggling-team")
        self.assertEqual([], result["evidence"])
        self.assertTrue(result["gaps"])
        gap_text = " ".join(result["gaps"]).lower()
        self.assertIn("no people-management", gap_text)
        # no invented story content
        self.assertIn("Do not invent", result["narrative"])

    def test_narrative_unknown_key(self):
        from candid import em_stories as E
        with self.assertRaises(E.EmStoriesError):
            E.em_narrative(MGMT_PROFILE, "no-such-prompt")

    def test_has_management_evidence(self):
        from candid import em_stories as E
        self.assertTrue(E.has_management_evidence(MGMT_PROFILE))
        self.assertFalse(E.has_management_evidence(IC_PROFILE))

    def test_raised_bar_uses_hiring_growth_evidence(self):
        from candid import em_stories as E
        result = E.em_narrative(MGMT_PROFILE, "raised-the-bar")
        bullets = [e["bullet"] for e in result["evidence"]]
        self.assertTrue(any("Hired" in b for b in bullets))
        self.assertTrue(any("Coached" in b for b in bullets))


if __name__ == "__main__":
    unittest.main()
