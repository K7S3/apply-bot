"""Tests for candid.star (STAR stories + interview kit).

CANDID_DATA_DIR is overridden before any candid import so no user data
is touched.
"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def make_win(**over):
    win = {
        "id": "w1",
        "title": "Cut checkout latency",
        "date": "2024-05-01",
        "role": "Senior Engineer",
        "description": "Checkout was timing out during peak traffic. "
        "I was asked to fix the p99 tail latency. "
        "I added caching and parallelized the tax call. "
        "P99 dropped and timeouts stopped.",
        "star": {
            "situation": "Checkout timed out during peak traffic.",
            "task": "Fix the p99 tail latency.",
            "action": "Added caching and parallelized the tax call.",
            "result": "P99 dropped and timeouts stopped.",
        },
        "competencies": ["leadership", "communication"],
        "impacts": [
            {"metric": "p99 latency", "before": 800, "after": 120, "unit": "ms"}
        ],
        "quotes": [],
        "tags": ["performance"],
    }
    win.update(over)
    return win


class QuestionBankTest(unittest.TestCase):
    def test_covers_all_seeded_competencies(self):
        from candid.star import QUESTION_BANK
        from candid import star
        comps = star.COMPETENCIES
        self.assertEqual(len(comps), 18)
        for comp in comps:
            self.assertIn(comp, QUESTION_BANK, comp)
            self.assertGreaterEqual(len(QUESTION_BANK[comp]), 2, comp)
            self.assertLessEqual(len(QUESTION_BANK[comp]), 3, comp)

    def test_prompts_are_behavioral(self):
        from candid.star import QUESTION_BANK
        for comp, prompts in QUESTION_BANK.items():
            for p in prompts:
                self.assertTrue(
                    p.lower().startswith("tell me about a time"),
                    f"{comp}: {p!r}",
                )
                self.assertNotIn("\u2014", p, "no em dashes allowed")


class WinToStarTest(unittest.TestCase):
    def test_uses_filled_star_fields(self):
        from candid.star import win_to_star
        s = win_to_star(make_win())
        self.assertEqual(s["win_id"], "w1")
        self.assertEqual(s["title"], "Cut checkout latency")
        self.assertEqual(s["situation"], "Checkout timed out during peak traffic.")
        self.assertEqual(s["task"], "Fix the p99 tail latency.")
        self.assertEqual(s["action"], "Added caching and parallelized the tax call.")
        self.assertEqual(s["result"], "P99 dropped and timeouts stopped.")
        self.assertEqual(s["competencies"], ["leadership", "communication"])
        self.assertEqual(s["role"], "Senior Engineer")

    def test_fallback_splits_description(self):
        from candid.star import win_to_star
        win = make_win(star={"situation": "", "task": "", "action": "", "result": ""})
        s = win_to_star(win)
        self.assertEqual(s["situation"], "Checkout was timing out during peak traffic.")
        self.assertEqual(s["task"], "I was asked to fix the p99 tail latency.")
        self.assertEqual(s["action"], "I added caching and parallelized the tax call.")
        self.assertEqual(s["result"], "P99 dropped and timeouts stopped.")

    def test_gaps_marked_empty(self):
        from candid.star import win_to_star
        win = make_win(
            star={"situation": "", "task": "", "action": "", "result": ""},
            description="One thing happened.",
        )
        s = win_to_star(win)
        self.assertEqual(s["situation"], "One thing happened.")
        self.assertEqual(s["task"], "")
        self.assertEqual(s["action"], "")
        self.assertEqual(s["result"], "")

    def test_partial_star_not_overwritten_by_fallback(self):
        from candid.star import win_to_star
        win = make_win(
            star={"situation": "The site was down.", "task": "", "action": "", "result": ""}
        )
        s = win_to_star(win)
        self.assertEqual(s["situation"], "The site was down.")
        self.assertEqual(s["task"], "")
        self.assertEqual(s["action"], "")


class AnswerKitTest(unittest.TestCase):
    def _wins(self):
        return [
            make_win(id="w1", competencies=["leadership"]),
            make_win(id="w2", title="Shipped alerts",
                     competencies=["incident-response", "communication"]),
        ]

    def test_entries_grouped_by_win(self):
        from candid.star import answer_kit
        kit = answer_kit(self._wins())
        by_win: dict[str, list] = {}
        for e in kit:
            by_win.setdefault(e["win_id"], []).append(e)
        # w1: leadership has 3 prompts; w2: 2 + 2 prompts
        self.assertEqual(len(by_win["w1"]), 3)
        self.assertEqual(len(by_win["w2"]), 4)
        for e in kit:
            self.assertIn("question", e)
            self.assertIn("story", e)
            self.assertIn("win_id", e)
            self.assertIn("title", e)
            self.assertEqual(e["story"]["win_id"], e["win_id"])

    def test_competency_filter(self):
        from candid.star import answer_kit
        kit = answer_kit(self._wins(), competency="communication")
        self.assertTrue(kit)
        self.assertTrue(all(e["win_id"] == "w2" for e in kit))
        self.assertEqual(len(kit), 2)

    def test_dedupes_repeat_competencies(self):
        from candid.star import answer_kit
        win = make_win(competencies=["leadership", "leadership"])
        kit = answer_kit([win])
        questions = [e["question"] for e in kit]
        self.assertEqual(len(questions), len(set(questions)))
        self.assertEqual(len(questions), 3)

    def test_wins_without_competencies_skipped(self):
        from candid.star import answer_kit
        self.assertEqual(answer_kit([make_win(competencies=[])]), [])


class BulletDraftsTest(unittest.TestCase):
    def test_quantified_only_from_impacts(self):
        from candid.star import bullet_drafts
        bullets = bullet_drafts(make_win())
        self.assertGreaterEqual(len(bullets), 1)
        self.assertLessEqual(len(bullets), 3)
        joined = " ".join(bullets)
        self.assertIn("800", joined)
        self.assertIn("120", joined)
        self.assertIn("p99 latency", joined)

    def test_no_digits_without_impacts(self):
        from candid.star import bullet_drafts
        win = make_win(
            title="Revamped onboarding docs",
            description="New hires were lost in week one.",
            star={
                "situation": "New hires were lost in week one.",
                "task": "Improve onboarding.",
                "action": "I rewrote the onboarding guide so new hires ramp faster.",
                "result": "Ramp time feedback improved.",
            },
            impacts=[],
        )
        bullets = bullet_drafts(win)
        self.assertGreaterEqual(len(bullets), 1)
        self.assertLessEqual(len(bullets), 3)
        for b in bullets:
            self.assertNotRegex(b, r"\d", f"invented number in {b!r}")

    def test_action_verb_led(self):
        from candid.star import bullet_drafts
        win = make_win(impacts=[])
        bullets = bullet_drafts(win)
        base = bullets[-1]
        self.assertFalse(base.lower().startswith("i "))
        self.assertTrue(base[0].isupper())


class StoryBankEntryTest(unittest.TestCase):
    def test_shape(self):
        from candid.star import story_bank_entry
        e = story_bank_entry(make_win())
        self.assertEqual(e["source"], "career-ledger")
        self.assertEqual(e["tags"], ["performance"])
        for key in ("win_id", "title", "situation", "task", "action",
                    "result", "competencies", "role"):
            self.assertIn(key, e)
        self.assertEqual(e["situation"], "Checkout timed out during peak traffic.")


if __name__ == "__main__":
    unittest.main()
