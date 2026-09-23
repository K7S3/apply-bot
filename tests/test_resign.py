"""Tests for the offer announcement drafts and the resignation module.

Run: cd ~/workspace/candid-batch-8 && python -m pytest tests/test_resign.py -q
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import offer as O
from candid import resign as R


class AnnouncementTest(unittest.TestCase):
    def test_both_variants_present(self):
        d = O.announcement("Keshavan", "Software Engineer", "Acme Corp")
        self.assertIn("linkedin_post", d)
        self.assertIn("network_message", d)

    def test_variants_contain_name_role_company(self):
        d = O.announcement("Keshavan", "Software Engineer", "Acme Corp")
        for variant in ("linkedin_post", "network_message"):
            text = d[variant]
            self.assertIn("Keshavan", text)
            self.assertIn("Software Engineer", text)
            self.assertIn("Acme Corp", text)

    def test_concise_tone(self):
        d = O.announcement("Keshavan", "Software Engineer", "Acme Corp",
                           tone="concise")
        self.assertIn("linkedin_post", d)
        self.assertIn("network_message", d)
        self.assertIn("Software Engineer", d["linkedin_post"])

    def test_start_date_included_when_given(self):
        d = O.announcement("Keshavan", "Software Engineer", "Acme Corp",
                           start_date="October 12")
        self.assertIn("October 12", d["linkedin_post"])
        self.assertIn("October 12", d["network_message"])

    def test_no_comp_numbers_leak(self):
        d = O.announcement("Keshavan", "Software Engineer", "Acme Corp",
                           start_date="October 12")
        for variant in ("linkedin_post", "network_message"):
            text = d[variant]
            self.assertNotIn("$", text)
            # No long number runs (salaries, equity grants, sign-ons).
            self.assertIsNone(re.search(r"\d{5,}", text),
                              f"possible comp number leaked in {variant}")
            self.assertNotIn("bonus", text.lower())
            self.assertNotIn("equity", text.lower())

    def test_invalid_tone_raises(self):
        with self.assertRaises(ValueError):
            O.announcement("Keshavan", "Software Engineer", "Acme Corp",
                           tone="dramatic")

    def test_missing_fields_raise(self):
        with self.assertRaises(ValueError):
            O.announcement("", "Software Engineer", "Acme Corp")

    def test_render_announcement_markdown(self):
        md = O.render_announcement("Keshavan", "Software Engineer", "Acme Corp",
                                   start_date="October 12")
        self.assertIn("# Offer Announcement Drafts", md)
        self.assertIn("## LinkedIn post", md)
        self.assertIn("## Message to your network", md)
        self.assertIn("Acme Corp", md)
        self.assertNotIn("$", md)


class ResignLetterTest(unittest.TestCase):
    def test_gracious_tone(self):
        text = R.letter("Keshavan", "Priya", "Acme Corp", "October 30")
        self.assertIn("Priya", text)
        self.assertIn("Acme Corp", text)
        self.assertIn("October 30", text)
        self.assertIn("Keshavan", text)
        self.assertIn("Thank you", text)
        # Gracious tone offers transition help.
        self.assertIn("transition", text.lower())

    def test_brief_tone(self):
        text = R.letter("Keshavan", "Priya", "Acme Corp", "October 30",
                        tone="brief")
        self.assertIn("October 30", text)
        self.assertIn("Acme Corp", text)
        self.assertIn("Keshavan", text)
        gracious = R.letter("Keshavan", "Priya", "Acme Corp", "October 30")
        self.assertLess(len(text), len(gracious))

    def test_last_day_appears(self):
        text = R.letter("Keshavan", "Priya", "Acme Corp", "November 6",
                        tone="brief")
        self.assertIn("November 6", text)

    def test_reason_kept_to_one_neutral_line(self):
        text = R.letter("Keshavan", "Priya", "Acme Corp", "October 30",
                        reason="a new opportunity\ni am pursuing")
        self.assertIn("a new opportunity i am pursuing", text)
        reason_paragraph = [ln for ln in text.splitlines()
                            if "new opportunity" in ln]
        self.assertEqual(len(reason_paragraph), 1)

    def test_letter_never_badmouths(self):
        for tone in ("gracious", "brief"):
            text = R.letter("Keshavan", "Priya", "Acme Corp", "October 30",
                            tone=tone).lower()
            for word in ("hate", "terrible", "toxic", "awful", "stupid"):
                self.assertNotIn(word, text)

    def test_invalid_tone_raises(self):
        with self.assertRaises(R.ResignError):
            R.letter("Keshavan", "Priya", "Acme Corp", "October 30",
                     tone="furious")

    def test_resign_error_is_value_error(self):
        self.assertTrue(issubclass(R.ResignError, ValueError))
        with self.assertRaises(ValueError):
            R.letter("Keshavan", "Priya", "Acme Corp", "October 30",
                     tone="furious")

    def test_missing_fields_raise(self):
        with self.assertRaises(R.ResignError):
            R.letter("", "Priya", "Acme Corp", "October 30")
        with self.assertRaises(R.ResignError):
            R.letter("Keshavan", "Priya", "Acme Corp", "")


class TalkingPointsTest(unittest.TestCase):
    def test_non_empty(self):
        points = R.talking_points()
        self.assertTrue(isinstance(points, list))
        self.assertGreater(len(points), 0)
        for p in points:
            self.assertTrue(isinstance(p, str))
            self.assertTrue(p.strip())

    def test_covers_key_advice(self):
        points = " ".join(R.talking_points()).lower()
        self.assertIn("manager first", points)
        self.assertIn("counteroffer", points)


if __name__ == "__main__":
    unittest.main()
