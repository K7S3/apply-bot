"""Tests for candid.security_star (security behavioral STAR prompts).

Run: cd ~/workspace/candid-batch96 && python -m unittest tests.test_security_star
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import security_star as SS

# Fabricated specifics the module must never invent on its own.
INVENTED_PATTERNS = [
    r"\b\d+%", r"\$\d", r"\b\d+x\b", r"\d{4}-\d{2}-\d{2}",
    r"January \d{1,2}", r"\bQ[1-4]\b",
]


class PromptsTest(unittest.TestCase):
    def test_twelve_prompts(self):
        self.assertEqual(len(SS.PROMPTS), 12)

    def test_prompt_shape(self):
        for p in SS.PROMPTS:
            for key in ("id", "prompt", "competency", "scaffolding"):
                self.assertIn(key, p)
            self.assertEqual(set(p["scaffolding"]), {"situation", "task", "action", "result"})
            for hint in p["scaffolding"].values():
                self.assertIsInstance(hint, str)
                self.assertTrue(len(hint.split()) >= 8, f"hint too short for {p['id']}")

    def test_unique_ids(self):
        ids = [p["id"] for p in SS.PROMPTS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_coverage_of_expected_topics(self):
        ids = {p["id"] for p in SS.PROMPTS}
        for expected in ("found-vulnerability", "handled-incident", "pushback-risky-ship",
                         "security-velocity-tradeoff", "mentored-security", "threat-modeled-feature",
                         "audit-response", "false-positive-flood"):
            self.assertIn(expected, ids)

    def test_scaffolding_hints_not_fabricated_stories(self):
        # Hints must read like guidance, not specific past-tense events with numbers.
        for p in SS.PROMPTS:
            for slot, hint in p["scaffolding"].items():
                for pat in INVENTED_PATTERNS:
                    self.assertIsNone(re.search(pat, hint),
                                      f"prompt {p['id']}/{slot} looks fabricated: {hint!r}")

    def test_get_prompt_ok(self):
        p = SS.get_prompt("handled-incident")
        self.assertIn("incident", p["prompt"].lower())

    def test_get_prompt_unknown_raises(self):
        with self.assertRaises(ValueError):
            SS.get_prompt("does-not-exist")


class BuildStoryTest(unittest.TestCase):
    def test_shape(self):
        story = SS.build_story("handled-incident", "Led response to a credential-stuffing attack on login")
        self.assertEqual(set(story), {"prompt", "bullet", "star", "needs_input"})
        self.assertEqual(set(story["star"]), {"situation", "task", "action", "result"})

    def test_needs_input_lists_all_slots(self):
        story = SS.build_story("mentored-security", "Ran secure-coding workshops for backend team")
        self.assertEqual(sorted(story["needs_input"]), ["action", "result", "situation", "task"])

    def test_star_echoes_bullet(self):
        bullet = "Tuned noisy SIEM rules to cut false positives"
        story = SS.build_story("false-positive-flood", bullet)
        for slot_text in story["star"].values():
            self.assertIn(bullet, slot_text)

    def test_no_invented_numbers(self):
        story = SS.build_story("found-vulnerability", "Found and fixed an IDOR in the billing API")
        blob = " ".join(story["star"].values())
        for pat in INVENTED_PATTERNS:
            self.assertIsNone(re.search(pat, blob),
                              f"build_story invented specifics: {blob!r}")
        self.assertNotIn("e.g.", blob)  # no example numbers masquerading as the user's

    def test_never_fabricates_events(self):
        # The story must not claim outcomes; it should ask the user to add them.
        story = SS.build_story("audit-response", "Prepared evidence for SOC 2 Type II audit")
        self.assertIn("Add:", story["star"]["result"])
        self.assertIn("needs_input", story)
        self.assertTrue(story["needs_input"])

    def test_unknown_prompt_raises(self):
        with self.assertRaises(ValueError):
            SS.build_story("nope", "some bullet")

    def test_empty_bullet_raises(self):
        with self.assertRaises(ValueError):
            SS.build_story("handled-incident", "   ")


if __name__ == "__main__":
    unittest.main()
