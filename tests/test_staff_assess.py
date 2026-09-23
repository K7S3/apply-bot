"""Tests for candid.staff_assess (ambiguity drill + leveling calibration).

Uses a throwaway CANDID_DATA_DIR so no real user data is touched.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Must be set BEFORE importing candid.config so tests never touch real data.
# setdefault (not hard assignment): cooperative with other test modules in a
# shared pytest process.
os.environ.setdefault(
    "CANDID_DATA_DIR", tempfile.mkdtemp(prefix="candid-staff-test-"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import staff_assess as SA  # noqa: E402

STRONG_ANSWER = """
Clarifying questions:
- What does 'done' mean here: traffic cutover, decommission, or both?
- Who asked for this migration and what business outcome does it serve?
- Which two teams are involved, and who currently owns the schedule?
- What does 'stalled' mean: blocked, slow, or deprioritized?

Unknowns I need to resolve:
- Actual migration progress versus the Q3 timeline (unknown to me right now).
- Blockers each team is hitting; I don't know if they are technical or staffing.
- Whether the legacy stack has a hard decommission date - need to find out.

Milestones I would propose:
1. First, write down a shared definition of done and get both teams to sign off.
2. Then publish a current-state audit: what is migrated and what is not.
3. Next, propose a phased cutover plan with rollback criteria and a timeline.
4. Set a weekly 30-minute sync with a single owner until it is done.

Risks:
- Declaring victory at partial cutover while the legacy stack quietly stays up.
- One team doing all the work while the other disengages.
- A rushed cutover breaking serving during a revenue-critical period.
- Trade-off: fixing the schedule without addressing why it stalled means it will stall again.
"""

WEAK_ANSWER = "I would just tell the teams to work harder and migrate faster."


class ScenarioTest(unittest.TestCase):
    def test_list_scenarios_shape(self):
        scenarios = SA.list_scenarios()
        self.assertGreaterEqual(len(scenarios), 8)
        ids = [s["id"] for s in scenarios]
        self.assertEqual(len(ids), len(set(ids)), "scenario ids must be unique")
        for s in scenarios:
            self.assertIn("id", s)
            self.assertIn("title", s)

    def test_get_scenario_full_shape(self):
        s = SA.get_scenario("stalled-migration")
        self.assertEqual(s["id"], "stalled-migration")
        self.assertTrue(s["brief"])
        check = s["decomposition_checklist"]
        for dim in ("clarifying_questions", "unknowns", "milestones", "risks"):
            self.assertIn(dim, check)
            self.assertGreaterEqual(len(check[dim]), 3)

    def test_get_scenario_unknown_raises(self):
        with self.assertRaises(SA.StaffError):
            SA.get_scenario("nope-not-real")


class ScoreTest(unittest.TestCase):
    def test_score_structure_and_heuristic_label(self):
        score = SA.score_answer("stalled-migration", STRONG_ANSWER)
        self.assertTrue(score["heuristic"])
        self.assertIn("heuristic", score["heuristic_note"].lower())
        self.assertEqual(score["scenario_id"], "stalled-migration")
        self.assertIn(score["overall"]["band"], ("developing", "solid", "strong"))
        for dim in ("clarifying_questions", "unknowns", "milestones", "risks"):
            d = score["dimensions"][dim]
            self.assertIn("score", d)
            self.assertIn("checklist_hits", d)
            self.assertIn("checklist_misses", d)
            self.assertIn("tip", d)

    def test_strong_beats_weak(self):
        strong = SA.score_answer("stalled-migration", STRONG_ANSWER)
        weak = SA.score_answer("stalled-migration", WEAK_ANSWER)
        self.assertGreater(strong["overall"]["score"], weak["overall"]["score"])
        self.assertEqual(strong["overall"]["band"], "strong")
        self.assertEqual(weak["overall"]["band"], "developing")

    def test_empty_answer_scores_zero_band(self):
        score = SA.score_answer("stalled-migration", "")
        self.assertEqual(score["overall"]["score"], 0.0)
        self.assertEqual(score["overall"]["band"], "developing")
        self.assertEqual(score["structure"]["word_count"], 0)

    def test_score_unknown_scenario_raises(self):
        with self.assertRaises(SA.StaffError):
            SA.score_answer("bogus", "some answer")

    def test_format_score_mentions_heuristic_and_band(self):
        out = SA.format_score(SA.score_answer("build-vs-buy", STRONG_ANSWER))
        self.assertIn("build-vs-buy", out)
        self.assertIn("heuristic", out.lower())
        for label in ("Clarifying questions", "Unknowns surfaced",
                      "Milestones proposed", "Risks named"):
            self.assertIn(label, out)

    def test_no_em_dashes_in_scenarios_or_output(self):
        for s in SA.AMBIGUITY_SCENARIOS:
            blob = s["title"] + s["brief"] + json.dumps(s["decomposition_checklist"])
            self.assertNotIn("\u2014", blob, f"em dash in scenario {s['id']}")
        out = SA.format_score(SA.score_answer("p99-spike", STRONG_ANSWER))
        self.assertNotIn("\u2014", out)
        self.assertNotIn("\u2014", SA.format_scenario(SA.get_scenario("p99-spike")))
        self.assertNotIn("\u2014", SA.format_level_table())


class LevelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-staff-level-"))
        self._old = C.DATA_DIR
        C.DATA_DIR = self.tmp

    def tearDown(self):
        C.DATA_DIR = self._old

    def test_level_table_shape_and_disclaimer(self):
        table = SA.level_table()
        self.assertIn("disclaimer", table)
        self.assertIn("vary", table["disclaimer"].lower())
        for lvl in ("L5", "L6", "L7"):
            self.assertIn(lvl, table["expectations"])
            dims = table["expectations"][lvl]["dimensions"]
            for dim in ("technical_depth", "scope", "influence",
                        "mentorship", "ambiguity"):
                self.assertIn(dim, dims)
                self.assertIn("expectation", dims[dim])
                self.assertIn("min_rating", dims[dim])
        self.assertNotIn("\u2014", table["disclaimer"])

    def test_self_rate_persists_and_finds_gaps(self):
        ratings = {"technical_depth": 3, "scope": 2, "influence": 3,
                   "mentorship": 2, "ambiguity": 3}
        result = SA.self_rate(ratings, target="L6")
        self.assertEqual(result["target"], "L6")
        gap_dims = {g["dimension"] for g in result["gaps"]}
        self.assertEqual(gap_dims, {"scope", "mentorship"})
        for g in result["gaps"]:
            self.assertTrue(g["next_step"])
            self.assertTrue(g["expectation"])
        path = Path(result["saved_to"])
        self.assertTrue(path.exists())
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["ratings"], ratings)
        self.assertEqual(saved["target"], "L6")
        # load_ratings round-trip
        loaded = SA.load_ratings()
        self.assertEqual(loaded["ratings"], ratings)

    def test_self_rate_no_gaps(self):
        result = SA.self_rate({d: 4 for d in SA.DIMENSIONS}, target="L6")
        self.assertEqual(result["gaps"], [])

    def test_self_rate_study_hook_degrades_gracefully(self):
        # candid.study does not exist in this worktree: hook must not raise
        result = SA.self_rate({d: 2 for d in SA.DIMENSIONS}, target="L6")
        hook = result["study_plan"]
        self.assertFalse(hook["consumed"])
        self.assertTrue(hook["reason"])
        self.assertEqual(len(hook["items"]), 5)  # all dims below L6 bar of 3

    def test_self_rate_validation(self):
        good = {d: 3 for d in SA.DIMENSIONS}
        with self.assertRaises(SA.StaffError):
            SA.self_rate(good, target="L9")
        bad = dict(good)
        bad["scope"] = 5
        with self.assertRaises(SA.StaffError):
            SA.self_rate(bad)
        bad = dict(good)
        bad["scope"] = 0
        with self.assertRaises(SA.StaffError):
            SA.self_rate(bad)
        missing = {d: 3 for d in SA.DIMENSIONS if d != "scope"}
        with self.assertRaises(SA.StaffError):
            SA.self_rate(missing)
        extra = dict(good)
        extra["charisma"] = 3
        with self.assertRaises(SA.StaffError):
            SA.self_rate(extra)

    def test_load_ratings_none_when_absent(self):
        self.assertIsNone(SA.load_ratings())


class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-staff-cli-"))
        self._old = C.DATA_DIR
        C.DATA_DIR = self.tmp

    def tearDown(self):
        C.DATA_DIR = self._old

    def _run(self, argv, stdin_text=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            if stdin_text is None:
                code = SA.main(argv)
            else:
                with mock.patch.object(sys, "stdin", io.StringIO(stdin_text)):
                    code = SA.main(argv)
        return code, buf.getvalue()

    def test_ambiguity_list(self):
        code, out = self._run(["ambiguity", "--list"])
        self.assertEqual(code, 0)
        self.assertIn("stalled-migration", out)

    def test_ambiguity_bare_lists(self):
        code, out = self._run(["ambiguity"])
        self.assertEqual(code, 0)
        self.assertIn("stalled-migration", out)

    def test_ambiguity_show_scenario(self):
        code, out = self._run(["ambiguity", "--scenario", "build-vs-buy"])
        self.assertEqual(code, 0)
        self.assertIn("feature store", out)

    def test_ambiguity_unknown_scenario(self):
        code, _ = self._run(["ambiguity", "--scenario", "nope"])
        self.assertNotEqual(code, 0)

    def test_ambiguity_answer_file(self):
        ans = self.tmp / "answer.txt"
        ans.write_text(STRONG_ANSWER, encoding="utf-8")
        code, out = self._run(
            ["ambiguity", "--scenario", "stalled-migration",
             "--answer-file", str(ans)])
        self.assertEqual(code, 0)
        self.assertIn("Overall:", out)
        self.assertIn("strong", out)

    def test_ambiguity_piped_stdin(self):
        code, out = self._run(["ambiguity", "--scenario", "stalled-migration"],
                              stdin_text=WEAK_ANSWER)
        self.assertEqual(code, 0)
        self.assertIn("developing", out)

    def test_level_table(self):
        code, out = self._run(["level", "--table"])
        self.assertEqual(code, 0)
        self.assertIn("DISCLAIMER", out)
        self.assertIn("L6", out)

    def test_level_bare_shows_table(self):
        code, out = self._run(["level"])
        self.assertEqual(code, 0)
        self.assertIn("DISCLAIMER", out)

    def test_level_rate_text(self):
        code, out = self._run([
            "level", "--rate", "technical_depth=3", "--rate", "scope=2",
            "--rate", "influence=3", "--rate", "mentorship=2",
            "--rate", "ambiguity=3", "--target", "L6"])
        self.assertEqual(code, 0)
        self.assertIn("GAP", out)
        self.assertIn("Next step", out)
        self.assertTrue((self.tmp / "staff_level.json").exists())

    def test_level_rate_json(self):
        code, out = self._run([
            "level", "--rate", "technical_depth=3", "scope=3", "influence=3",
            "mentorship=3", "ambiguity=3", "--target", "L6", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["target"], "L6")
        self.assertEqual(parsed["gaps"], [])

    def test_level_rate_bad_value(self):
        code, _ = self._run(["level", "--rate", "scope=9"])
        self.assertNotEqual(code, 0)

    def test_level_rate_bad_dim(self):
        code, _ = self._run(["level", "--rate", "charisma=3"])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
