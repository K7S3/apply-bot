"""Tests for the security-engineer mock interview module (candid.security_mock).

Run: cd ~/workspace/candid-batch96 && python -m unittest tests.test_security_mock
"""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import security_mock as SM  # noqa: E402


QUESTION = {
    "id": "sec-web-1",
    "question": "How would you prevent SQL injection in a web app?",
    "category": "web",
    "expected_points": [
        "Validate and sanitize all user input to prevent SQL injection attacks",
        "Use parameterized queries or an ORM instead of string concatenation",
        "Apply least privilege to the database account",
    ],
}

STRONG_ANSWER = (
    "To stop SQL injection attacks I validate and sanitize all user input. "
    "I use parameterized queries through an ORM rather than building SQL "
    "with string concatenation. The database account gets least privilege "
    "so a successful injection cannot escalate. On the other hand, an ORM "
    "adds latency and cost, so for hot paths we keep hand-tuned queries "
    "with strict review."
)

STUB_QUESTIONS = [
    {"id": "s1", "question": "How do you prevent XSS?", "category": "web",
     "expected_points": ["Encode output", "Use Content Security Policy"]},
    {"id": "s2", "question": "What is network segmentation?", "category": "network",
     "expected_points": ["Split the network into isolated zones"]},
]


def _install_stub():
    stub = types.ModuleType("candid.security_questions")
    stub.QUESTIONS = [dict(q) for q in STUB_QUESTIONS]
    sys.modules["candid.security_questions"] = stub


def _remove_stub():
    sys.modules.pop("candid.security_questions", None)


class RubricShapeTest(unittest.TestCase):
    def test_rubric_has_four_dimensions(self):
        ids = [d["id"] for d in SM.RUBRIC]
        self.assertEqual(ids, ["completeness", "threat-coverage",
                               "tradeoffs", "clarity"])

    def test_rubric_entries_have_name_and_description(self):
        for dim in SM.RUBRIC:
            self.assertTrue(dim["name"])
            self.assertTrue(dim["description"])


class ScoreAnswerTest(unittest.TestCase):
    def test_strong_answer_scores_high_completeness(self):
        res = SM.score_answer(QUESTION, STRONG_ANSWER)
        self.assertEqual(set(res["scores"]), {"completeness", "threat-coverage",
                                              "tradeoffs", "clarity"})
        self.assertGreaterEqual(res["scores"]["completeness"], 4)
        self.assertEqual(len(res["matched_points"]), 3)
        self.assertEqual(res["missed_points"], [])

    def test_empty_answer_scores_low_everywhere(self):
        res = SM.score_answer(QUESTION, "")
        for dim, score in res["scores"].items():
            self.assertLessEqual(score, 1, dim)
        self.assertEqual(res["matched_points"], [])
        self.assertEqual(len(res["missed_points"]), 3)

    def test_partial_answer_matches_some_points(self):
        res = SM.score_answer(QUESTION, "I validate and sanitize all user input.")
        self.assertEqual(len(res["matched_points"]), 1)
        self.assertEqual(len(res["missed_points"]), 2)
        self.assertLess(res["scores"]["completeness"], 5)

    def test_threat_keywords_detected(self):
        ans = "Watch for XSS, injection, SSRF and phishing; enforce MFA, TLS, and encryption."
        res = SM.score_answer({"question": "q"}, ans)
        self.assertGreaterEqual(res["scores"]["threat-coverage"], 3)

    def test_tradeoff_language_detected(self):
        ans = ("I would enable MFA. On the other hand, there is a cost in "
               "usability and added latency; however, it depends on the risk "
               "appetite.")
        res = SM.score_answer({"question": "q"}, ans)
        self.assertGreaterEqual(res["scores"]["tradeoffs"], 3)

    def test_plain_answer_has_low_tradeoffs(self):
        res = SM.score_answer({"question": "q"}, "Use strong passwords.")
        self.assertLessEqual(res["scores"]["tradeoffs"], 1)

    def test_clarity_rewards_structure(self):
        ans = ("1. First, validate input.\n"
               "2. Second, encode output.\n"
               "3. Finally, set a CSP header.")
        res = SM.score_answer({"question": "q"}, ans)
        self.assertGreaterEqual(res["scores"]["clarity"], 3)

    def test_wall_of_text_has_low_clarity(self):
        res = SM.score_answer({"question": "q"}, "words " * 200)
        self.assertLessEqual(res["scores"]["clarity"], 2)

    def test_no_expected_points_uses_length_bands(self):
        short = SM.score_answer({"question": "q"}, "short answer")
        self.assertEqual(short["scores"]["completeness"], 1)
        medium = SM.score_answer({"question": "q"}, "x" * 60)
        self.assertEqual(medium["scores"]["completeness"], 3)
        long = SM.score_answer({"question": "q"}, "x" * 200)
        self.assertEqual(long["scores"]["completeness"], 4)

    def test_question_without_expected_points_key_is_graceful(self):
        res = SM.score_answer({}, "x" * 200)
        self.assertEqual(res["scores"]["completeness"], 4)
        self.assertEqual(res["matched_points"], [])
        self.assertTrue(res["feedback"])

    def test_scores_are_ints_in_range(self):
        res = SM.score_answer(QUESTION, STRONG_ANSWER)
        for dim, score in res["scores"].items():
            self.assertIsInstance(score, int, dim)
            self.assertGreaterEqual(score, 0, dim)
            self.assertLessEqual(score, 5, dim)

    def test_feedback_is_human_readable(self):
        res = SM.score_answer(QUESTION, STRONG_ANSWER)
        self.assertTrue(all(isinstance(f, str) and f for f in res["feedback"]))
        self.assertTrue(any("Completeness" in f for f in res["feedback"]))


class SummarizeSessionTest(unittest.TestCase):
    RESULTS = [
        {"scores": {"completeness": 4, "threat-coverage": 2,
                    "tradeoffs": 1, "clarity": 5}},
        {"scores": {"completeness": 2, "threat-coverage": 4,
                    "tradeoffs": 1, "clarity": 3}},
    ]

    def test_averages_correct(self):
        s = SM.summarize_session(self.RESULTS)
        self.assertEqual(s["per_dimension_avg"]["completeness"], 3.0)
        self.assertEqual(s["per_dimension_avg"]["threat-coverage"], 3.0)
        self.assertEqual(s["per_dimension_avg"]["tradeoffs"], 1.0)
        self.assertEqual(s["per_dimension_avg"]["clarity"], 4.0)

    def test_overall_is_mean_of_dimension_avgs(self):
        s = SM.summarize_session(self.RESULTS)
        self.assertAlmostEqual(s["overall"], (3.0 + 3.0 + 1.0 + 4.0) / 4)

    def test_strongest_and_weakest_named(self):
        s = SM.summarize_session(self.RESULTS)
        self.assertEqual(s["strongest"], "clarity")
        self.assertEqual(s["weakest"], "tradeoffs")

    def test_empty_results_is_graceful(self):
        s = SM.summarize_session([])
        self.assertEqual(s["overall"], 0.0)
        self.assertIsNone(s["strongest"])
        self.assertIsNone(s["weakest"])
        self.assertTrue(all(v == 0.0 for v in s["per_dimension_avg"].values()))


class RunMockTest(unittest.TestCase):
    def setUp(self):
        _install_stub()

    def tearDown(self):
        _remove_stub()

    def test_run_mock_scores_each_answer(self):
        inputs = ["Use output encoding and CSP headers.", ".",
                  "Split the network into isolated zones with firewalls.", "."]
        # random.sample shuffles; pin it to keep stub order (s1, s2) so the
        # scripted answers line up with the questions they were written for.
        with mock.patch("random.sample",
                        side_effect=lambda pop, k: list(pop)[:k]), \
             mock.patch("builtins.input", side_effect=inputs):
            results = SM.run_mock(n=2)
        self.assertEqual(len(results), 2)
        for res in results:
            self.assertEqual(set(res["scores"]),
                             {"completeness", "threat-coverage",
                              "tradeoffs", "clarity"})
            self.assertIn("question_id", res)
        # the network answer matches its single expected point
        by_id = {r["question_id"]: r for r in results}
        self.assertGreaterEqual(by_id["s2"]["scores"]["completeness"], 4)

    def test_run_mock_category_filter(self):
        inputs = ["Isolate zones.", "."]
        with mock.patch("builtins.input", side_effect=inputs):
            results = SM.run_mock(n=5, category="network")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["question_id"], "s2")

    def test_run_mock_unknown_category_returns_empty(self):
        results = SM.run_mock(n=5, category="forensics")
        self.assertEqual(results, [])


class MissingBankTest(unittest.TestCase):
    def test_clear_error_when_module_missing(self):
        # None in sys.modules makes the import raise ImportError even if a
        # real security_questions module exists on disk.
        sys.modules["candid.security_questions"] = None
        try:
            with self.assertRaises(RuntimeError) as ctx:
                SM.run_mock(n=1)
            self.assertIn("security_questions", str(ctx.exception))
        finally:
            _remove_stub()


if __name__ == "__main__":
    unittest.main()
