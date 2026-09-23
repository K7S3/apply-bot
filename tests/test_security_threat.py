"""Tests for the STRIDE threat-modeling drills (security interview track).

Run: cd ~/workspace/candid-batch96 && python -m unittest tests.test_security_threat
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _thorough_threats():
    """One keyword-rich threat per STRIDE letter for file-upload-service."""
    from candid import security_threat as ST
    scenario = ST.get_scenario("file-upload-service")
    threats = []
    for letter, hints in scenario["stride_hints"].items():
        threats.append({"letter": letter, "text": hints[0]})
    return threats


class StrideCatalogTest(unittest.TestCase):
    def test_stride_letters(self):
        from candid import security_threat as ST
        self.assertEqual(ST.STRIDE["S"], "Spoofing")
        self.assertEqual(ST.STRIDE["T"], "Tampering")
        self.assertEqual(ST.STRIDE["R"], "Repudiation")
        self.assertEqual(ST.STRIDE["I"], "Information disclosure")
        self.assertEqual(ST.STRIDE["D"], "Denial of service")
        self.assertEqual(ST.STRIDE["E"], "Elevation of privilege")
        self.assertEqual(len(ST.STRIDE), 6)

    def test_scenario_count_and_shape(self):
        from candid import security_threat as ST
        self.assertEqual(len(ST.SCENARIOS), 6)
        ids = [s["id"] for s in ST.SCENARIOS]
        self.assertEqual(len(set(ids)), 6)
        for s in ST.SCENARIOS:
            self.assertTrue(s["title"])
            self.assertTrue(s["description"])
            self.assertGreaterEqual(len(s["assets"]), 3)
            self.assertLessEqual(len(s["assets"]), 6)
            self.assertEqual(set(s["stride_hints"].keys()), set(ST.STRIDE))
            for letter, hints in s["stride_hints"].items():
                self.assertGreaterEqual(len(hints), 2)
                self.assertLessEqual(len(hints), 4)

    def test_get_scenario(self):
        from candid import security_threat as ST
        s = ST.get_scenario("sso-login-flow")
        self.assertEqual(s["title"], "SSO login flow")

    def test_get_scenario_unknown_raises(self):
        from candid import security_threat as ST
        with self.assertRaises(ValueError):
            ST.get_scenario("nope-not-real")


class ScoreThreatsTest(unittest.TestCase):
    def test_thorough_answer_scores_high(self):
        from candid import security_threat as ST
        report = ST.score_threats("file-upload-service", _thorough_threats())
        self.assertTrue(all(report["coverage"].values()))
        self.assertGreaterEqual(report["score"], 95)
        self.assertLessEqual(report["score"], 100)

    def test_empty_input_scores_zero(self):
        from candid import security_threat as ST
        report = ST.score_threats("file-upload-service", [])
        self.assertEqual(report["score"], 0)
        self.assertFalse(any(report["coverage"].values()))
        self.assertEqual(report["matched_hints"], 0)
        self.assertTrue(all(len(m) > 0 for m in report["missed"].values()))

    def test_single_letter_low_score(self):
        from candid import security_threat as ST
        report = ST.score_threats(
            "file-upload-service",
            [{"letter": "T",
              "text": "attacker tampered with upload metadata rows to point "
                      "downloads at malicious files"}],
        )
        self.assertLess(report["score"], 40)
        covered = [l for l, c in report["coverage"].items() if c]
        self.assertEqual(len(covered), 1)

    def test_unknown_scenario_raises(self):
        from candid import security_threat as ST
        with self.assertRaises(ValueError):
            ST.score_threats("bogus", [{"letter": "T", "text": "x"}])

    def test_keyword_overlap_coverage(self):
        from candid import security_threat as ST
        # paraphrase of the first T hint, sharing keywords like
        # "mime", "validation", "upload", "script"
        report = ST.score_threats(
            "file-upload-service",
            [{"letter": "T",
              "text": "client side MIME validation bypass lets attacker "
                      "upload a malicious script as an image"}],
        )
        self.assertTrue(report["coverage"]["T"])
        self.assertGreater(report["matched_hints"], 0)

    def test_volume_covers_letter_without_keyword_match(self):
        from candid import security_threat as ST
        report = ST.score_threats(
            "file-upload-service",
            [{"letter": "D", "text": "first vague denial thing"},
             {"letter": "D", "text": "second vague denial thing"}],
        )
        self.assertTrue(report["coverage"]["D"])

    def test_missed_hints_listed_for_uncovered_letters(self):
        from candid import security_threat as ST
        report = ST.score_threats("file-upload-service", [])
        scenario = ST.get_scenario("file-upload-service")
        for letter in ST.STRIDE:
            self.assertEqual(report["missed"][letter],
                             scenario["stride_hints"][letter])

    def test_report_shape_and_score_bounds(self):
        from candid import security_threat as ST
        report = ST.score_threats("sso-login-flow", _thorough_threats()[:0])
        for key in ("coverage", "score", "matched_hints", "total_hints",
                    "missed", "feedback"):
            self.assertIn(key, report)
        self.assertGreaterEqual(report["score"], 0)
        self.assertLessEqual(report["score"], 100)
        self.assertEqual(len(report["feedback"]), 6)
        # volume bonus never exceeds 100
        many = [{"letter": l, "text": f"threat number {i} here"}
                for i, l in enumerate(list("STRIDE") * 5)]
        capped = ST.score_threats("sso-login-flow", many)
        self.assertLessEqual(capped["score"], 100)


class RunDrillTest(unittest.TestCase):
    def test_run_drill_with_mocked_input(self):
        from candid import security_threat as ST
        hints = ST.get_scenario("public-api-keys")["stride_hints"]
        inputs = [f"{letter}: {hints[letter][0]}" for letter in "STRIDE"] + [""]
        printed = []
        with patch("builtins.input", side_effect=inputs):
            report = ST.run_drill("public-api-keys",
                                  input_fn=input,
                                  print_fn=printed.append)
        self.assertIsNotNone(report)
        self.assertGreaterEqual(report["score"], 95)
        self.assertTrue(any("Score:" in p for p in printed))

    def test_run_drill_lists_scenarios_when_none_given(self):
        from candid import security_threat as ST
        scenario = ST.get_scenario("cicd-pipeline")
        inputs = ["cicd-pipeline",
                  f"T: {scenario['stride_hints']['T'][0]}",
                  ""]
        printed = []
        with patch("builtins.input", side_effect=inputs):
            report = ST.run_drill(input_fn=input, print_fn=printed.append)
        self.assertIsNotNone(report)
        self.assertTrue(report["coverage"]["T"])
        self.assertTrue(any("Pick a scenario" in p for p in printed))

    def test_run_drill_unknown_choice_returns_none(self):
        from candid import security_threat as ST
        printed = []
        with patch("builtins.input", side_effect=["not-a-scenario"]):
            report = ST.run_drill(input_fn=input, print_fn=printed.append)
        self.assertIsNone(report)

    def test_collect_threats_rejects_bad_lines(self):
        from candid import security_threat as ST
        inputs = ["garbage line", "X: not a stride letter",
                  "T: real threat about tampering", ""]
        printed = []
        with patch("builtins.input", side_effect=inputs):
            threats = ST.collect_threats(input_fn=input,
                                         print_fn=printed.append)
        self.assertEqual(len(threats), 1)
        self.assertEqual(threats[0]["letter"], "T")


if __name__ == "__main__":
    unittest.main()
