"""Tests for candid.drafting.revise (deterministic revision rules)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.drafting import revise as R


LONG_BODY = (
    "Hi Jane,\n\n"
    "I hope you are doing well. I am writing to introduce myself and share "
    "my background with you. I have spent the last six years building "
    "machine learning systems for ad ranking at large consumer platforms. "
    "I led a team of four engineers that shipped a new ranking model which "
    "increased revenue by twelve percent year over year. I also built the "
    "offline evaluation pipeline that the whole org now uses for launches. "
    "Before that, I worked on recommendation systems for a video streaming "
    "service with over fifty million monthly active users. I am interested "
    "in the senior ML engineer role at your company because the problems "
    "you describe match my experience closely. I would love to discuss how "
    "my background fits the team.\n\n"
    "Best,\nKeshavan"
)

BASIC_DRAFT = {
    "subject": "Intro",
    "body": "Hi Jane,\n\nI don't think we've met. It's great to connect.\n\nThanks,\nKeshavan",
}


class ReviseTest(unittest.TestCase):
    # --- shorten ---------------------------------------------------------
    def test_shorten_reduces_length(self):
        out = R.revise({"subject": "s", "body": LONG_BODY}, "make it shorter")
        self.assertIn("shorten", out["applied"])
        self.assertLess(len(out["body"].split()),
                        len(LONG_BODY.split()))
        self.assertLessEqual(len(out["body"].split()),
                             R.SHORTEN_TARGET_WORDS)

    def test_shorten_keeps_first_and_last_sentence(self):
        out = R.revise({"subject": "s", "body": LONG_BODY}, "more concise")
        self.assertTrue(out["body"].startswith("Hi Jane,"))
        self.assertTrue(out["body"].rstrip().endswith("Keshavan"))

    def test_shorten_noop_when_already_short(self):
        out = R.revise(BASIC_DRAFT, "shorten this")
        self.assertIn("shorten", out["applied"])
        self.assertEqual(out["body"], BASIC_DRAFT["body"])

    # --- formalize -------------------------------------------------------
    def test_formalize_expands_contractions(self):
        out = R.revise(BASIC_DRAFT, "make it more formal")
        self.assertIn("formalize", out["applied"])
        self.assertIn("do not", out["body"])
        self.assertIn("It is", out["body"])
        self.assertNotIn("don't", out["body"].lower())

    def test_formalize_upgrades_greeting_and_signoff(self):
        out = R.revise(BASIC_DRAFT, "professional tone")
        self.assertTrue(out["body"].startswith("Dear Jane,"))
        self.assertIn("Thank you,", out["body"])

    # --- soften ----------------------------------------------------------
    def test_soften_hedges_verbs(self):
        draft = {"subject": "s",
                 "body": "Hi Jane,\n\nI want to meet. I need a reply ASAP.\n\nBest,\nKeshavan"}
        out = R.revise(draft, "softer tone please")
        self.assertIn("soften", out["applied"])
        self.assertIn("I would like to meet", out["body"])
        self.assertIn("I would appreciate a reply", out["body"])
        self.assertIn("at your earliest convenience", out["body"])

    # --- add_cta ---------------------------------------------------------
    def test_add_cta_appends_question_before_signoff(self):
        out = R.revise(BASIC_DRAFT, "add a clear call to action")
        self.assertIn("add_cta", out["applied"])
        self.assertTrue(out["body"].rstrip().endswith("Keshavan"))
        self.assertIn("?", out["body"])
        cta_pos = out["body"].index("Would you be available")
        signoff_pos = out["body"].index("Thanks,")
        self.assertLess(cta_pos, signoff_pos)

    def test_add_cta_skips_when_already_a_question(self):
        draft = {"subject": "s",
                 "body": "Hi Jane,\n\nAre you free Tuesday?\n\nBest,\nKeshavan"}
        out = R.revise(draft, "add a cta")
        self.assertIn("add_cta", out["applied"])
        self.assertEqual(out["body"].count("?"), 1)

    # --- combined / unknown ----------------------------------------------
    def test_multiple_rules_from_one_instruction(self):
        draft = {"subject": "s",
                 "body": "Hi Jane,\n\nI don't think we've met. "
                         "I want to discuss the role ASAP.\n\nBest,\nKeshavan"}
        out = R.revise(draft, "make it shorter and softer and more formal")
        self.assertEqual(out["applied"], ["shorten", "formalize", "soften"])
        self.assertIn("do not", out["body"])
        self.assertIn("I would like", out["body"])

    def test_unknown_instruction_is_noop(self):
        out = R.revise(BASIC_DRAFT, "make it purple and sparkly")
        self.assertEqual(out["applied"], [])
        self.assertEqual(out["subject"], BASIC_DRAFT["subject"])
        self.assertEqual(out["body"], BASIC_DRAFT["body"])

    def test_empty_instruction_is_noop(self):
        out = R.revise(BASIC_DRAFT, "")
        self.assertEqual(out["applied"], [])
        self.assertEqual(out["body"], BASIC_DRAFT["body"])

    def test_subject_never_modified(self):
        out = R.revise(BASIC_DRAFT,
                       "make it shorter, more formal, softer, add a call to action")
        self.assertEqual(out["subject"], "Intro")


if __name__ == "__main__":
    unittest.main()
