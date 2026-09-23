"""Tests for candid.em_drills (EM scenario drills + hiring-loop simulator).

Run: CANDID_DATA_DIR=/tmp/candid-test-em python -m pytest tests/test_em_drills.py -q
(also honored when set in-process below).
"""
import os
import shutil
import sys
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-em")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = Path("/tmp/candid-test-em")


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


def _canned(lines: list[str]):
    """input() replacement that replays lines, then raises EOFError."""
    it = iter(lines)

    def _read(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return _read


GOOD_RESPONSE = (
    "Alex, I want to talk specifically about the last two sprints, where we missed "
    "the checkout commitments on both the refund flow and the rate-limit work. I also "
    "hear from reviewers that PR comments are going unaddressed, and the impact was a "
    "slip in the release date. That is not acceptable for our team, and I want to be "
    "straight with you about it. I know this is tough to hear, and I appreciate the "
    "work you did land last quarter. I want to understand your perspective, so tell me "
    "what is going on and how you feel about the last month. Here is my plan: we will "
    "agree on a scope you can commit to for this week, you will update me daily in "
    "standup, and I will help clear anything blocked. Let us check in next Tuesday to "
    "revisit, and keep me posted if anything changes before then."
)

BAD_RESPONSE = (
    "Alex, leadership decided we need you to do better. Try harder and figure it out, "
    "good luck."
)


class ScenarioListTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_lists_four_scenarios(self):
        from candid import em_drills as E
        scenarios = E.list_scenarios()
        self.assertEqual(len(scenarios), 4)
        ids = {s["id"] for s in scenarios}
        self.assertEqual(ids, {"underperformer", "conflict", "skip-level", "postmortem"})

    def test_scenarios_have_setup_and_good(self):
        from candid import em_drills as E
        for s in E.SCENARIOS:
            self.assertTrue(s["setup"])
            self.assertGreaterEqual(len(s["good"]), 3)
            self.assertTrue(s["role"])

    def test_unknown_scenario_raises(self):
        from candid import em_drills as E
        with self.assertRaises(E.EMDrillsError):
            E.get_scenario("nope")

    def test_render_list_mentions_cli(self):
        from candid import em_drills as E
        text = E.render_scenario_list()
        self.assertIn("underperformer", text)
        self.assertIn("candid em drill", text)


class RubricScoringTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_deterministic(self):
        from candid import em_drills as E
        r1 = E.score_response("underperformer", GOOD_RESPONSE)
        r2 = E.score_response("underperformer", GOOD_RESPONSE)
        self.assertEqual(r1, r2)

    def test_good_beats_bad(self):
        from candid import em_drills as E
        good = E.score_response("underperformer", GOOD_RESPONSE)
        bad = E.score_response("underperformer", BAD_RESPONSE)
        self.assertGreater(good["overall"], bad["overall"])

    def test_bad_response_flags_anti_patterns(self):
        from candid import em_drills as E
        bad = E.score_response("underperformer", BAD_RESPONSE)
        directness = next(d for d in bad["dims"] if d["id"] == "directness")
        self.assertIn("leadership decided", directness["anti"])
        action = next(d for d in bad["dims"] if d["id"] == "action_plan")
        self.assertTrue(action["anti"])

    def test_empty_response_scores_minimum(self):
        from candid import em_drills as E
        r = E.score_response("conflict", "   ")
        for d in r["dims"]:
            self.assertEqual(d["score"], 1)

    def test_feedback_quotes_user_words(self):
        from candid import em_drills as E
        result = E.score_response_with_quotes("underperformer", GOOD_RESPONSE)
        scenario = E.get_scenario("underperformer")
        fb = E.render_feedback(result, scenario)
        self.assertIn("Rubric score", fb)
        # quotes the user's own words, not invented facts
        self.assertIn("You said:", fb)
        self.assertNotIn("Alex said", fb)

    def test_overall_bounded(self):
        from candid import em_drills as E
        r = E.score_response("postmortem", GOOD_RESPONSE)
        self.assertGreaterEqual(r["overall"], 1)
        self.assertLessEqual(r["overall"], 5)


class DrillFlowTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_drill_flow_canned_input(self):
        from candid import em_drills as E
        from candid import config as C
        lines = GOOD_RESPONSE.split(". ") + ["EOF"]
        report = E.run_drill("underperformer", input_fn=_canned(lines))
        self.assertEqual(report["track"], "em_drill")
        self.assertEqual(report["item"], "underperformer")
        self.assertEqual(report["outcome"], "completed")
        self.assertGreaterEqual(report["overall"], 3)
        saved = list((C.DATA_DIR / "em_drills").glob("*underperformer*.json"))
        self.assertEqual(len(saved), 1)

    def test_drill_eof_quits(self):
        from candid import em_drills as E
        report = E.run_drill("postmortem", input_fn=_canned([]))
        self.assertEqual(report["outcome"], "completed")
        self.assertEqual(report["overall"], 1.0)


class HiringLoopTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_packet_listing(self):
        from candid import em_drills as E
        packets = E.list_packets()
        self.assertEqual(len(packets), 3)
        self.assertEqual({p["id"] for p in packets}, {"maya", "devon", "priya"})

    def test_unknown_packet_raises(self):
        from candid import em_drills as E
        with self.assertRaises(E.EMDrillsError):
            E.get_packet("nope")

    def test_packet_render_no_calibration_leak(self):
        from candid import em_drills as E
        text = E.render_packet(E.get_packet("maya"))
        self.assertIn("Maya Chen", text)
        self.assertNotIn("calibrated", text.lower())
        self.assertNotIn("Overweighting", text)

    def test_grade_deterministic(self):
        from candid import em_drills as E
        r1 = E.grade_debrief("devon", "no-hire",
                             "No hire. Coding needed heavy hints with an O(n^2) solution. "
                             "System design skipped the failure-mode discussion. Behavioral "
                             "stories were all 'we' with no own contribution, and references "
                             "would not rehire into the same role.")
        r2 = E.grade_debrief("devon", "no-hire",
                             "No hire. Coding needed heavy hints with an O(n^2) solution. "
                             "System design skipped the failure-mode discussion. Behavioral "
                             "stories were all 'we' with no own contribution, and references "
                             "would not rehire into the same role.")
        self.assertEqual(r1, r2)
        self.assertEqual(r1["stated_verdict"], "no-hire")
        self.assertEqual(r1["calibration"], 5)
        self.assertEqual(r1["evidence_use"], 5)

    def test_grade_catches_bad_calibration(self):
        from candid import em_drills as E
        grade = E.grade_debrief("maya", "no-hire",
                                "No hire because the talks over people note is a red flag.")
        self.assertEqual(grade["stated_verdict"], "no-hire")
        self.assertEqual(grade["calibration"], 2)

    def test_grade_catches_cliche_language(self):
        from candid import em_drills as E
        grade = E.grade_debrief("priya", "hire", "Hire. Just feels like a gut feeling hire.")
        self.assertIn("gut feeling", grade["cliches"])

    def test_hiring_loop_flow_canned(self):
        from candid import em_drills as E
        from candid import config as C
        lines = [
            "hire",
            "Hire. Coding was excellent and tested edge cases unprompted. "
            "Design was slow to start but caught the consistency requirement herself. "
            "The no-hire note is only about communication style with no cited "
            "miscommunication, so it does not meet the bar for a veto.",
            "EOF",
        ]
        report = E.run_hiring_loop("priya", input_fn=_canned(lines))
        self.assertEqual(report["track"], "em_hiring_loop")
        self.assertEqual(report["stated_verdict"], "hire")
        self.assertEqual(report["calibrated_verdict"], "hire")
        self.assertGreaterEqual(report["overall"], 4)
        saved = list((C.DATA_DIR / "em_drills").glob("*priya*.json"))
        self.assertEqual(len(saved), 1)

    def test_debrief_feedback_is_grounded(self):
        from candid import em_drills as E
        packet = E.get_packet("devon")
        grade = E.grade_debrief("devon", "no-hire", "No hire. Coding needed heavy hints.")
        fb = E.render_debrief_feedback(grade, packet)
        self.assertIn("Calibrated read", fb)
        self.assertNotIn("the user has 5 years", fb.lower())


class AIFallbackTest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_ai_drill_degrades_offline(self):
        from candid import em_drills as E
        # simulate missing credential path: force the availability check off
        orig = E._gemini_available
        E._gemini_available = lambda: False
        try:
            report = E.ai_drill("underperformer",
                                input_fn=_canned(GOOD_RESPONSE.split(". ") + ["EOF"]))
            self.assertEqual(report["track"], "em_drill")
            self.assertEqual(report["outcome"], "completed")
        finally:
            E._gemini_available = orig

    def test_ai_hiring_loop_degrades_offline(self):
        from candid import em_drills as E
        orig = E._gemini_available
        E._gemini_available = lambda: False
        try:
            report = E.ai_hiring_loop("devon",
                                      input_fn=_canned(["no-hire",
                                                        "No hire. Coding needed heavy hints "
                                                        "with an O(n^2) solution.", "EOF"]))
            self.assertEqual(report["track"], "em_hiring_loop")
        finally:
            E._gemini_available = orig


class CLITest(unittest.TestCase):
    def setUp(self):
        _clean()

    def test_parser_accepts_em_commands(self):
        from candid.__main__ import build_parser
        p = build_parser()
        a = p.parse_args(["em", "drill", "--list"])
        self.assertEqual(a.cmd, "em")
        self.assertEqual(a.what, "drill")
        self.assertTrue(a.list)
        a = p.parse_args(["em", "drill", "--scenario", "conflict"])
        self.assertEqual(a.scenario, "conflict")
        a = p.parse_args(["em", "hiring-loop", "--packet", "maya"])
        self.assertEqual(a.packet, "maya")

    def test_cmd_em_drill_list(self):
        from candid.__main__ import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["em", "drill", "--list"])
        self.assertIn("underperformer", buf.getvalue())

    def test_cmd_em_hiring_loop_list(self):
        from candid.__main__ import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["em", "hiring-loop", "--list"])
        self.assertIn("Maya Chen", buf.getvalue())

    def test_cmd_em_expected_error_clean(self):
        from candid.__main__ import main
        with self.assertRaises(SystemExit) as ctx:
            main(["em", "drill", "--scenario", "nope"])
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
