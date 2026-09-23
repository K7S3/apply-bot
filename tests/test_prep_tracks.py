"""Tests for role-family prep tracks (candid.prep_tracks + `tracks` CLI).

Data paths are redirected into a temp dir via the CANDID_DATA_DIR env var,
which prep_tracks._data_dir() honors at call time.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import prep_tracks as PT  # noqa: E402
from candid import prep_concepts as PC  # noqa: E402
from candid import __main__ as CLI  # noqa: E402

EXPECTED_IDS = ("mle", "backend", "frontend", "data-science", "pm", "em")


class RegistryTest(unittest.TestCase):
    def test_six_tracks_with_expected_ids(self):
        self.assertEqual([t["id"] for t in PT.list_tracks()], list(EXPECTED_IDS))

    def test_track_summaries_have_counts(self):
        for t in PT.list_tracks():
            for key in ("title", "tagline", "rounds", "concepts", "questions", "drills"):
                self.assertIn(key, t)
            self.assertGreater(t["questions"], 0)
            self.assertGreater(t["concepts"], 0)
            self.assertGreater(t["drills"], 0)

    def test_get_track_unknown_raises(self):
        with self.assertRaises(PT.TrackError):
            PT.get_track("astronaut")

    def test_track_id_normalization(self):
        self.assertEqual(PT.normalize_track_id("data_science"), "data-science")
        self.assertEqual(PT.normalize_track_id(" MLE "), "mle")

    def test_every_concept_tag_resolves(self):
        for tid in EXPECTED_IDS:
            for c in PT.track_concepts(tid):
                self.assertIn(c["tag"], PC.CONCEPTS)
                self.assertTrue(c["why"])
                self.assertTrue(c["deep_dive"].startswith("###"))

    def test_question_rounds_match_loop_rounds(self):
        for tid in EXPECTED_IDS:
            rounds = {r["round"] for r in PT.get_track(tid)["loop"]}
            for q in PT.get_track(tid)["questions"]:
                self.assertIn(q["round"], rounds, f"{tid}: {q['q'][:40]}")
                self.assertIn(q["difficulty"], ("easy", "medium", "hard"))
                self.assertTrue(q["category"])
                self.assertTrue(q["q"].strip())

    def test_drills_have_checklists(self):
        for tid in EXPECTED_IDS:
            for d in PT.track_drills(tid):
                self.assertTrue(d["id"])
                self.assertGreater(d["minutes"], 0)
                self.assertGreaterEqual(len(d["checklist"]), 3)
                self.assertTrue(d["instructions"].strip())

    def test_get_drill_unknown_raises(self):
        with self.assertRaises(PT.TrackError):
            PT.get_drill("mle", "nope")

    def test_total_drill_minutes_positive(self):
        for tid in EXPECTED_IDS:
            self.assertGreater(PT.total_drill_minutes(tid), 0)


class QuestionFilterTest(unittest.TestCase):
    def test_difficulty_filter(self):
        qs = PT.track_questions("mle", difficulty="hard")
        self.assertTrue(qs)
        self.assertTrue(all(q["difficulty"] == "hard" for q in qs))

    def test_bad_difficulty_raises(self):
        with self.assertRaises(PT.TrackError):
            PT.track_questions("mle", difficulty="extreme")

    def test_category_filter(self):
        qs = PT.track_questions("data-science", category="sql")
        self.assertTrue(qs)
        self.assertTrue(all(q["category"] == "sql" for q in qs))

    def test_round_substring_filter(self):
        qs = PT.track_questions("backend", round_name="design")
        self.assertTrue(qs)
        self.assertTrue(all("design" in q["round"].lower() for q in qs))

    def test_questions_numbered_from_one(self):
        qs = PT.track_questions("pm")
        self.assertEqual([q["n"] for q in qs], list(range(1, len(qs) + 1)))

    def test_categories_listed(self):
        cats = PT.question_categories("em")
        self.assertIn("behavioral", cats)
        self.assertEqual(len(cats), len(set(cats)))

    def test_sample_is_deterministic(self):
        a = PT.sample_questions("backend", n=5, seed=3)
        b = PT.sample_questions("backend", n=5, seed=3)
        self.assertEqual([q["n"] for q in a], [q["n"] for q in b])

    def test_sample_different_seeds_differ(self):
        a = [q["n"] for q in PT.sample_questions("backend", n=6, seed=1)]
        b = [q["n"] for q in PT.sample_questions("backend", n=6, seed=2)]
        self.assertNotEqual(a, b)

    def test_sample_clamps_to_pool(self):
        qs = PT.sample_questions("pm", n=999, seed=0)
        self.assertEqual(len(qs), len(PT.track_questions("pm")))

    def test_sample_bad_n_raises(self):
        with self.assertRaises(PT.TrackError):
            PT.sample_questions("pm", n=0)


class DrillFilterTest(unittest.TestCase):
    def test_kind_filter(self):
        ds = PT.track_drills("backend", kind="qna")
        self.assertTrue(ds)
        self.assertTrue(all(d["kind"] == "qna" for d in ds))

    def test_bad_kind_raises(self):
        with self.assertRaises(PT.TrackError):
            PT.track_drills("backend", kind="karaoke")


class PlanTest(unittest.TestCase):
    def test_plan_spans_requested_days(self):
        plan = PT.build_plan("frontend", days=7, hours_per_day=1.0)
        self.assertEqual(len(plan["schedule"]), 7)
        self.assertEqual(plan["track"], "frontend")

    def test_no_day_exceeds_budget(self):
        plan = PT.build_plan("mle", days=14, hours_per_day=1.0)
        for day in plan["schedule"]:
            self.assertLessEqual(day["minutes"], 60, f"day {day['day']} over budget")

    def test_all_drills_scheduled_exactly_once(self):
        plan = PT.build_plan("em", days=10, hours_per_day=2.0)
        refs = [i["ref"] for d in plan["schedule"] for i in d["items"]
                if i["type"] == "drill"]
        expected = [d["id"] for d in PT.track_drills("em")]
        self.assertEqual(sorted(refs), sorted(expected))

    def test_render_plan_has_day_headers(self):
        text = PT.render_plan(PT.build_plan("pm", days=3, hours_per_day=1.0))
        self.assertIn("# 3-day prep plan", text)
        self.assertIn("## Day 1", text)
        self.assertIn("## Day 3", text)

    def test_bad_days_raises(self):
        with self.assertRaises(PT.TrackError):
            PT.build_plan("pm", days=0)

    def test_bad_hours_raises(self):
        with self.assertRaises(PT.TrackError):
            PT.build_plan("pm", days=7, hours_per_day=0)

    def test_oversized_drill_raises(self):
        with self.assertRaises(PT.TrackError):
            PT.build_plan("mle", days=7, hours_per_day=0.1)


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="candid-tracks-")
        self._old = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = self._old

    def test_mark_done_then_coverage(self):
        PT.mark_done("mle", "concept", "ml_system_design")
        PT.mark_done("mle", "question", "q1")
        cov = PT.coverage("mle")
        self.assertEqual(cov["kinds"]["concept"]["done"], 1)
        self.assertEqual(cov["kinds"]["question"]["done"], 1)
        self.assertEqual(cov["done"], 2)
        self.assertGreater(cov["pct"], 0)
        self.assertNotIn("q1", cov["kinds"]["question"]["remaining"])

    def test_mark_done_idempotent(self):
        PT.mark_done("pm", "drill", "pm-sense-45")
        PT.mark_done("pm", "drill", "pm-sense-45")
        cov = PT.coverage("pm")
        self.assertEqual(cov["kinds"]["drill"]["done"], 1)

    def test_mark_undone(self):
        PT.mark_done("pm", "drill", "pm-sense-45")
        PT.mark_undone("pm", "drill", "pm-sense-45")
        self.assertEqual(PT.coverage("pm")["kinds"]["drill"]["done"], 0)

    def test_reset_progress(self):
        PT.mark_done("em", "concept", "star_framework")
        PT.reset_progress("em")
        cov = PT.coverage("em")
        self.assertEqual(cov["done"], 0)
        self.assertEqual(cov["pct"], 0)

    def test_progress_persists_across_calls(self):
        PT.mark_done("backend", "question", "q3")
        # fresh read path (module-level functions re-read the file)
        self.assertEqual(PT.coverage("backend")["kinds"]["question"]["done"], 1)

    def test_bad_kind_raises(self):
        with self.assertRaises(PT.TrackError):
            PT.mark_done("pm", "song", "q1")

    def test_bad_key_raises(self):
        with self.assertRaises(PT.TrackError):
            PT.mark_done("pm", "concept", "nope")

    def test_render_coverage_format(self):
        PT.mark_done("pm", "concept", "metrics_trees")
        text = PT.render_coverage(PT.coverage("pm"))
        self.assertIn("Product Manager", text)
        self.assertIn("concept", text)

    def test_full_completion_is_100(self):
        tid = "frontend"
        keys = PT._item_keys(tid)
        for kind, ks in keys.items():
            for k in ks:
                PT.mark_done(tid, kind, k)
        self.assertEqual(PT.coverage(tid)["pct"], 100)


class MockPresetTest(unittest.TestCase):
    def test_presets_reference_mock_cli(self):
        for tid in EXPECTED_IDS:
            presets = PT.mock_preset(tid)
            self.assertGreaterEqual(len(presets), 2)
            for p in presets:
                self.assertTrue(p["command"].startswith("python -m candid mock"))
                self.assertTrue(p["round"])
                self.assertTrue(p["note"])


class SuggestTest(unittest.TestCase):
    def test_sql_gap_suggests_data_science(self):
        s = PT.suggest_tracks(["Missing must-have skill: sql"])
        self.assertEqual(s[0]["id"], "data-science")

    def test_leadership_gap_suggests_em(self):
        s = PT.suggest_tracks(["Seniority gap: people leadership"])
        self.assertEqual(s[0]["id"], "em")

    def test_llm_gap_suggests_mle(self):
        s = PT.suggest_tracks(["Missing must-have skill: llm"])
        self.assertEqual(s[0]["id"], "mle")

    def test_empty_gaps_returns_empty(self):
        self.assertEqual(PT.suggest_tracks([]), [])


class RenderTest(unittest.TestCase):
    def test_render_track_sections(self):
        text = PT.render_track("data-science")
        self.assertIn("# Prep Track: Data Scientist", text)
        for section in ("## Interview loop", "## Concepts", "## Questions",
                        "## Drills", "## Suggested mock sessions"):
            self.assertIn(section, text)

    def test_render_track_deep_dives(self):
        text = PT.render_track("mle", include_deep_dives=True)
        self.assertIn("### ML System Design", text)


class TracksCLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="candid-tracks-cli-")
        self._old = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = self._old

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1, out.getvalue(), err.getvalue())
            return 0, out.getvalue(), err.getvalue()

    def test_cli_list(self):
        code, out, _ = self.run_cli(["tracks", "list"])
        self.assertEqual(code, 0)
        for tid in EXPECTED_IDS:
            self.assertIn(tid, out)

    def test_cli_show(self):
        code, out, _ = self.run_cli(["tracks", "show", "backend"])
        self.assertEqual(code, 0)
        self.assertIn("Backend / Systems Engineer", out)

    def test_cli_show_unknown_track_friendly_error(self):
        code, out, err = self.run_cli(["tracks", "show", "astronaut"])
        self.assertNotEqual(code, 0)
        self.assertIn("Unknown track", out + err)

    def test_cli_questions_sample(self):
        code, out, _ = self.run_cli(
            ["tracks", "questions", "--track", "mle", "--sample", "2", "--seed", "5"])
        self.assertEqual(code, 0)
        self.assertIn("[", out)

    def test_cli_plan(self):
        code, out, _ = self.run_cli(
            ["tracks", "plan", "--track", "pm", "--days", "3", "--hours", "1"])
        self.assertEqual(code, 0)
        self.assertIn("## Day 3", out)

    def test_cli_done_and_progress(self):
        code, out, _ = self.run_cli(
            ["tracks", "done", "--track", "pm", "--kind", "concept", "--key", "metrics_trees"])
        self.assertEqual(code, 0)
        self.assertIn("1/4", out)
        code, out, _ = self.run_cli(["tracks", "progress", "--track", "pm"])
        self.assertEqual(code, 0)
        self.assertIn("1/4", out)

    def test_cli_suggest(self):
        code, out, _ = self.run_cli(
            ["tracks", "suggest", "--gaps", "Missing must-have skill: sql"])
        self.assertEqual(code, 0)
        self.assertIn("data-science", out)

    def test_cli_mock(self):
        code, out, _ = self.run_cli(["tracks", "mock", "--track", "em"])
        self.assertEqual(code, 0)
        self.assertIn("python -m candid mock", out)

    def test_cli_drills(self):
        code, out, _ = self.run_cli(["tracks", "drills", "--track", "frontend"])
        self.assertEqual(code, 0)
        self.assertIn("Total drill time", out)


if __name__ == "__main__":
    unittest.main()
