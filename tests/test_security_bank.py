"""Tests for the security-engineer interview question bank.

Run: cd ~/workspace/candid-batch96 && python -m unittest tests.test_security_bank
(also honored when set in-process below).
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-security-bank")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED_KEYS = {"q", "category", "source", "url", "reported"}


class SecurityBankShapeTest(unittest.TestCase):
    def setUp(self):
        from candid import security_questions as S
        self.S = S

    def test_question_count_in_range(self):
        self.assertGreaterEqual(len(self.S.SECURITY_QUESTIONS), 30)
        self.assertLessEqual(len(self.S.SECURITY_QUESTIONS), 50)

    def test_every_question_has_required_keys(self):
        for i, q in enumerate(self.S.SECURITY_QUESTIONS):
            self.assertTrue(REQUIRED_KEYS <= set(q),
                            f"question {i} missing keys: {REQUIRED_KEYS - set(q)}")
            self.assertTrue(q["q"].strip(), f"question {i} has empty q")
            self.assertTrue(q["source"].strip(), f"question {i} has empty source")
            self.assertTrue(q["reported"].strip(), f"question {i} has empty reported")

    def test_every_question_has_valid_url(self):
        for i, q in enumerate(self.S.SECURITY_QUESTIONS):
            url = q["url"]
            self.assertTrue(url.startswith("http://") or url.startswith("https://"),
                            f"question {i} has bad url: {url!r}")

    def test_categories_all_in_categories(self):
        for i, q in enumerate(self.S.SECURITY_QUESTIONS):
            self.assertIn(q["category"], self.S.CATEGORIES,
                          f"question {i} has unknown category {q['category']!r}")

    def test_categories_are_unique_and_nonempty(self):
        self.assertTrue(self.S.CATEGORIES)
        self.assertEqual(len(self.S.CATEGORIES), len(set(self.S.CATEGORIES)))

    def test_all_categories_represented(self):
        present = {q["category"] for q in self.S.SECURITY_QUESTIONS}
        self.assertEqual(present, set(self.S.CATEGORIES))

    def test_expected_points_shape(self):
        seen = 0
        for i, q in enumerate(self.S.SECURITY_QUESTIONS):
            if "expected_points" in q:
                seen += 1
                pts = q["expected_points"]
                self.assertIsInstance(pts, list, f"question {i} expected_points not a list")
                self.assertTrue(pts, f"question {i} expected_points empty")
                for p in pts:
                    self.assertIsInstance(p, str, f"question {i} expected_points item not str")
                    self.assertTrue(p.strip(), f"question {i} expected_points has empty item")
        self.assertGreater(seen, 0, "no question carried expected_points")

    def test_no_em_dashes(self):
        text = Path(self.S.__file__).read_text(encoding="utf-8")
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2013", text)


class SecurityBankApiTest(unittest.TestCase):
    def setUp(self):
        from candid import security_questions as S
        self.S = S

    def test_by_category_returns_only_that_category(self):
        for cat in self.S.CATEGORIES:
            got = self.S.by_category(cat)
            self.assertTrue(got, f"by_category({cat!r}) returned nothing")
            self.assertTrue(all(q["category"] == cat for q in got),
                            f"by_category({cat!r}) leaked another category")

    def test_by_category_raises_on_unknown(self):
        with self.assertRaises(ValueError):
            self.S.by_category("not-a-category")

    def test_search_finds_known_term(self):
        got = self.S.search("ransomware")
        self.assertTrue(got, "search('ransomware') found nothing")
        self.assertTrue(any("ransomware" in q["q"].lower() for q in got))

    def test_search_is_case_insensitive(self):
        lower = self.S.search("ransomware")
        upper = self.S.search("RANSOMWARE")
        self.assertEqual([q["q"] for q in lower], [q["q"] for q in upper])

    def test_search_no_match_returns_empty(self):
        self.assertEqual(self.S.search("zzz-no-such-term-zzz"), [])

    def test_search_substring(self):
        got = self.S.search("jwt")
        self.assertTrue(any("jwt" in q["q"].lower() for q in got))


if __name__ == "__main__":
    unittest.main()
