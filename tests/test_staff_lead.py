"""Tests for candid.staff_lead (staff/principal influence + mentorship prep).

Run: CANDID_DATA_DIR=/tmp/candid-test-staff python -m pytest tests/test_staff_lead.py -q
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-staff")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import staff_lead as SL  # noqa: E402


class InfluenceScenariosTest(unittest.TestCase):
    def test_ten_scenarios(self):
        self.assertEqual(len(SL.INFLUENCE_SCENARIOS), 10)

    def test_scenario_schema(self):
        for s in SL.INFLUENCE_SCENARIOS:
            for key in ("id", "title", "situation", "staff_lens",
                        "strong_moves", "pitfalls"):
                self.assertIn(key, s, f"scenario {s.get('id')} missing {key}")
            self.assertTrue(s["strong_moves"], s["id"])
            self.assertTrue(s["pitfalls"], s["id"])

    def test_unique_ids(self):
        ids = SL.list_influence_scenarios()
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 10)

    def test_get_known_and_unknown(self):
        s = SL.get_influence_scenario("disagree-commit")
        self.assertIn("disagree", s["title"].lower())
        with self.assertRaises(SL.StaffError):
            SL.get_influence_scenario("nope")

    def test_no_em_dashes_in_content(self):
        blob = json.dumps(SL.INFLUENCE_SCENARIOS)
        self.assertNotIn("\u2014", blob)

    def test_format_influence(self):
        s = SL.get_influence_scenario("kill-own-project")
        out = SL.format_influence(s)
        self.assertIn("kill", out.lower())
        self.assertIn("Strong moves", out)
        self.assertIn("Pitfalls", out)
        self.assertIn(SL.SOURCE_LABEL, out)


class MentorTopicsTest(unittest.TestCase):
    EXPECTED_TOPICS = {"growing-engineers", "hiring-bar", "underperformance",
                       "feedback", "team-health"}

    def test_topic_keys(self):
        self.assertEqual(set(SL.list_mentor_topics()), self.EXPECTED_TOPICS)

    def test_topic_schema(self):
        for key, t in SL.MENTOR_TOPICS.items():
            self.assertIn("title", t, key)
            self.assertIn("guiding_principles", t, key)
            self.assertIn("practice_questions", t, key)
            self.assertIn("red_flags", t, key)
            self.assertGreaterEqual(len(t["guiding_principles"]), 3, key)
            self.assertGreaterEqual(len(t["practice_questions"]), 4, key)
            self.assertGreaterEqual(len(t["red_flags"]), 3, key)
            for pq in t["practice_questions"]:
                self.assertIn("q", pq, key)
                self.assertIn("good_signals", pq, key)
                self.assertGreaterEqual(len(pq["good_signals"]), 2, key)

    def test_get_known_and_unknown(self):
        t = SL.get_mentor_topic("feedback")
        self.assertIn("feedback", t["title"].lower())
        with self.assertRaises(SL.StaffError):
            SL.get_mentor_topic("nope")

    def test_no_em_dashes_in_content(self):
        blob = json.dumps(SL.MENTOR_TOPICS)
        self.assertNotIn("\u2014", blob)

    def test_format_mentor(self):
        t = SL.get_mentor_topic("hiring-bar")
        out = SL.format_mentor(t)
        self.assertIn("Guiding principles", out)
        self.assertIn("Practice questions", out)
        self.assertIn("Red flags", out)
        self.assertIn("Good signals", out)
        self.assertIn(SL.SOURCE_LABEL, out)


def _run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = SL.main(argv)
    return code, out.getvalue(), err.getvalue()


class StaffCLITest(unittest.TestCase):
    def test_influence_default_lists(self):
        code, out, _ = _run_cli(["influence"])
        self.assertEqual(code, 0)
        self.assertIn("disagree-commit", out)

    def test_influence_list(self):
        code, out, _ = _run_cli(["influence", "--list"])
        self.assertEqual(code, 0)
        for sid in SL.list_influence_scenarios():
            self.assertIn(sid, out)

    def test_influence_scenario(self):
        code, out, _ = _run_cli(["influence", "--scenario", "decision-no-authority"])
        self.assertEqual(code, 0)
        self.assertIn("no formal authority", out)

    def test_influence_scenario_unknown(self):
        code, out, err = _run_cli(["influence", "--scenario", "bogus"])
        self.assertEqual(code, 2)
        self.assertIn("Unknown influence scenario", err)

    def test_influence_json(self):
        code, out, _ = _run_cli(["influence", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 10)
        self.assertEqual(data[0]["id"], "disagree-commit")
        self.assertIn("source", data[0])

    def test_influence_scenario_json(self):
        code, out, _ = _run_cli(
            ["influence", "--scenario", "kill-own-project", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["id"], "kill-own-project")

    def test_mentor_default_shows_topic(self):
        code, out, _ = _run_cli(["mentor"])
        self.assertEqual(code, 0)
        self.assertIn("Growing engineers", out)

    def test_mentor_list(self):
        code, out, _ = _run_cli(["mentor", "--list"])
        self.assertEqual(code, 0)
        for key in SL.list_mentor_topics():
            self.assertIn(key, out)

    def test_mentor_topic(self):
        code, out, _ = _run_cli(["mentor", "--topic", "team-health"])
        self.assertEqual(code, 0)
        self.assertIn("Team health", out)

    def test_mentor_topic_unknown(self):
        code, out, err = _run_cli(["mentor", "--topic", "bogus"])
        self.assertEqual(code, 2)
        self.assertIn("Unknown mentor topic", err)

    def test_mentor_json(self):
        code, out, _ = _run_cli(["mentor", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("feedback", data)
        self.assertIn("red_flags", data["feedback"])

    def test_mentor_topic_json(self):
        code, out, _ = _run_cli(
            ["mentor", "--topic", "underperformance", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["topic"], "underperformance")

    def test_needs_subcommand(self):
        with self.assertRaises(SystemExit):
            _run_cli([])


if __name__ == "__main__":
    unittest.main()
