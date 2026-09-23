"""Tests for the PM track: pm_mock, pm_stories, pm_scores.

Run: CANDID_DATA_DIR=/tmp/candid-test-pm python3 -m unittest tests.test_pm_practice -v

No network, no LLM: LLM-fallback paths are tested against a closed port and
by monkeypatching; interactive sessions use an injected input_fn.
"""
import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-pm")

ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT))


class _IsolatedDataDir(unittest.TestCase):
    """Give every test a fresh, isolated CANDID_DATA_DIR."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self._old = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = self._td.name
        # re-import fresh so _data_dir() picks up the new env value
        for mod in ("candid.pm_mock", "candid.pm_stories", "candid.pm_scores"):
            sys.modules.pop(mod, None)
        from candid import pm_mock as pm_mock
        from candid import pm_stories as pm_stories
        from candid import pm_scores as pm_scores
        self.M = pm_mock
        self.S = pm_stories
        self.Sc = pm_scores

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = self._old
        self._td.cleanup()


# ---------------------------------------------------------------------------
# pm_mock: prompts + scripted follow-ups
# ---------------------------------------------------------------------------

class MockPromptsTest(_IsolatedDataDir):
    def test_list_prompts_nonempty_strings(self):
        prompts = self.M.list_prompts()
        self.assertGreater(len(prompts), 0)
        self.assertTrue(all(isinstance(p, str) and p.strip() for p in prompts))

    def test_pick_prompt_returns_from_bank(self):
        self.assertIn(self.M.pick_prompt(seed=1), self.M.list_prompts())

    def test_pick_prompt_deterministic_with_seed(self):
        self.assertEqual(self.M.pick_prompt(seed=42), self.M.pick_prompt(seed=42))

    def test_depth_order_is_clarification_first(self):
        self.assertEqual(
            self.M.DEPTH_ORDER,
            ["clarification", "tradeoffs", "metrics", "prioritization"])

    def test_scripted_followups_stage_sequence(self):
        stages = [s for s, _ in self.M.scripted_followups(6, seed=7)]
        self.assertEqual(
            stages,
            ["clarification", "tradeoffs", "metrics", "prioritization",
             "clarification", "tradeoffs"])

    def test_scripted_followups_deterministic(self):
        a = self.M.scripted_followups(4, seed=3)
        b = self.M.scripted_followups(4, seed=3)
        self.assertEqual(a, b)

    def test_scripted_followups_zero_rounds(self):
        self.assertEqual(self.M.scripted_followups(0, seed=1), [])

    def test_scripted_followups_negative_rounds_raises(self):
        with self.assertRaises(self.M.PmMockError):
            self.M.scripted_followups(-1)

    def test_scripted_followups_questions_from_bank(self):
        for stage, q in self.M.scripted_followups(8, seed=5):
            self.assertIn(q, self.M.FOLLOWUPS[stage])

    def test_script_session_structure(self):
        s = self.M.script_session("prompt here", 2, seed=9)
        self.assertEqual(s["prompt"], "prompt here")
        self.assertEqual(s["rounds"], 2)
        self.assertEqual(len(s["turns"]), 3)  # prompt + 2 follow-ups
        self.assertEqual(s["turns"][0]["stage"], "prompt")
        self.assertIsNone(s["turns"][0]["answer"])

    def test_script_session_json_serializable(self):
        s = self.M.script_session("p", 3, seed=2)
        json.dumps(s)  # must not raise


class MockSessionsTest(_IsolatedDataDir):
    def test_save_load_round_trip(self):
        session = self.M.script_session("p", 2, seed=1)
        path = self.M.save_session(session)
        self.assertTrue(path.exists())
        loaded = self.M.load_sessions()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["prompt"], "p")
        self.assertEqual(len(loaded[0]["turns"]), 3)

    def test_load_sessions_empty_when_missing(self):
        self.assertEqual(self.M.load_sessions(), [])

    def test_multiple_sessions_accumulate(self):
        self.M.save_session(self.M.script_session("p1", 1, seed=1))
        self.M.save_session(self.M.script_session("p2", 1, seed=2))
        self.assertEqual(len(self.M.load_sessions()), 2)

    def test_corrupt_session_file_raises(self):
        path = self.M._sessions_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json{", encoding="utf-8")
        with self.assertRaises(self.M.PmMockError):
            self.M.load_sessions()

    def test_interactive_session_with_injected_input(self):
        answers = iter(["my answer", "followup answer"])
        session = self.M.interactive_session(
            "prompt?", mode="script", rounds=1, seed=4,
            input_fn=lambda t: next(answers))
        self.assertEqual(session["turns"][0]["answer"], "my answer")
        self.assertEqual(session["turns"][1]["answer"], "followup answer")
        self.assertEqual(session["turns"][1]["stage"], "clarification")


class MockLlmFallbackTest(_IsolatedDataDir):
    CLOSED = "http://127.0.0.1:1/api/generate"  # guaranteed closed port

    def test_ollama_available_false_on_closed_port(self):
        self.assertFalse(self.M.ollama_available(url=self.CLOSED, timeout=1.0))

    def test_llm_followup_falls_back_to_scripted(self):
        q = self.M.llm_followup("some prompt", [], "metrics",
                                url=self.CLOSED, timeout=1.0)
        self.assertIn(q, self.M.FOLLOWUPS["metrics"])

    def test_interactive_llm_mode_falls_back_without_server(self):
        real = self.M.ollama_available
        self.M.ollama_available = lambda *a, **k: False
        try:
            session = self.M.interactive_session(
                "prompt?", mode="llm", rounds=1, seed=6,
                input_fn=lambda t: "")
        finally:
            self.M.ollama_available = real
        self.assertEqual(session["mode"], "script")
        self.assertEqual(session["turns"][1]["stage"], "clarification")


class MockCliTest(_IsolatedDataDir):
    def _parse(self, argv):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        self.M.register_pm(sub)
        return parser.parse_args(argv)

    def test_register_mock_flags(self):
        a = self._parse(["mock", "--script", "--rounds", "2", "--mode", "llm"])
        self.assertTrue(a.script)
        self.assertEqual(a.rounds, 2)
        self.assertEqual(a.mode, "llm")

    def test_register_mock_defaults(self):
        a = self._parse(["mock"])
        self.assertEqual(a.mode, "script")
        self.assertEqual(a.rounds, 4)
        self.assertFalse(a.script)
        self.assertFalse(a.json)
        self.assertIsNone(a.prompt_index)

    def test_register_mock_bad_mode_rejected(self):
        with self.assertRaises(SystemExit):
            self._parse(["mock", "--mode", "gpt"])

    def test_cmd_script_text_output(self):
        a = self._parse(["mock", "--script", "--rounds", "4",
                         "--prompt-index", "0", "--seed", "11"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.M.cmd_pm_mock(a)
        out = buf.getvalue()
        self.assertIn(self.M.PROMPTS[0], out)
        for stage in self.M.DEPTH_ORDER:
            self.assertIn(f"[{stage}]", out)

    def test_cmd_script_json_output(self):
        a = self._parse(["mock", "--script", "--rounds", "2",
                         "--prompt-index", "1", "--seed", "11", "--json"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.M.cmd_pm_mock(a)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["prompt"], self.M.PROMPTS[1])
        self.assertEqual(len(data["turns"]), 3)

    def test_cmd_script_prompt_index_out_of_range(self):
        a = self._parse(["mock", "--script", "--prompt-index", "999"])
        with self.assertRaises(self.M.PmMockError):
            self.M.cmd_pm_mock(a)

    def test_cmd_script_negative_rounds_rejected(self):
        a = self._parse(["mock", "--script", "--rounds", "-2"])
        with self.assertRaises(self.M.PmMockError):
            self.M.cmd_pm_mock(a)


# ---------------------------------------------------------------------------
# pm_stories: PIERL narratives + competency tagger
# ---------------------------------------------------------------------------

FAKE_PROFILE = {
    "name": "Test Person",
    "experience": [
        {"title": "Senior PM", "company": "Acme",
         "bullets": [
             "Launched a new onboarding flow that lifted signup conversion 12% "
             "after A/B testing three variants with the data science team.",
             "Built the Q3 roadmap with engineering and design stakeholders, "
             "prioritizing the backlog via RICE scoring.",
         ]},
        {"title": "PM", "company": "Beta",
         "bullets": ["Ran user interviews that reshaped the mobile checkout journey."]},
    ],
}


class StoriesTaggerTest(_IsolatedDataDir):
    def test_roadmap_tag(self):
        self.assertIn("roadmap", self.S.tag_competencies("owned the quarterly roadmap"))

    def test_multiple_tags(self):
        tags = self.S.tag_competencies(
            "Launched an A/B experiment after user interviews with stakeholders")
        for t in ("launch", "experimentation", "user_empathy", "stakeholder_mgmt"):
            self.assertIn(t, tags)

    def test_no_keywords_no_tags(self):
        self.assertEqual(self.S.tag_competencies("ate lunch quietly"), [])

    def test_case_insensitive(self):
        self.assertIn("prioritization",
                      self.S.tag_competencies("PRIORITIZED the backlog"))

    def test_canonical_order(self):
        tags = self.S.tag_competencies("launch roadmap metrics")
        self.assertEqual(tags, sorted(
            tags, key=list(self.S.COMPETENCY_KEYWORDS).index))

    def test_eight_competencies_defined(self):
        self.assertEqual(
            set(self.S.COMPETENCY_KEYWORDS),
            {"roadmap", "prioritization", "stakeholder_mgmt", "launch",
             "data_driven", "user_empathy", "experimentation", "cross_functional"})


class StoriesBuildTest(_IsolatedDataDir):
    def test_build_narrative_has_pierl_sections(self):
        n = self.S.build_narrative("Senior PM", "Acme", "Shipped X and grew Y 10%.")
        self.assertEqual(set(n["sections"]), {"problem", "insight", "execution",
                                              "result", "lesson"})
        self.assertEqual(set(n["filled"]), {"problem", "insight", "execution",
                                            "result", "lesson"})
        self.assertFalse(any(n["filled"].values()))

    def test_build_narrative_embeds_own_bullet_only(self):
        bullet = "Cut churn 5% by launching win-back emails."
        n = self.S.build_narrative("PM", "Acme", bullet)
        # every scaffold references the bullet verbatim
        for text in n["sections"].values():
            self.assertIn(bullet, text)
        self.assertEqual(n["bullet"], bullet)

    def test_build_narrative_empty_bullet_raises(self):
        with self.assertRaises(self.S.PmStoryError):
            self.S.build_narrative("PM", "Acme", "   ")

    def test_build_from_fake_profile(self):
        stories = self.S.build_from_profile(FAKE_PROFILE, limit=10)
        self.assertEqual(len(stories), 3)
        self.assertEqual(stories[0]["title"], "Senior PM")
        self.assertEqual(stories[0]["company"], "Acme")
        self.assertIn("launch", stories[0]["competencies"])
        self.assertIn("experimentation", stories[0]["competencies"])
        self.assertIn("user_empathy", stories[2]["competencies"])

    def test_build_from_profile_respects_limit(self):
        self.assertEqual(len(self.S.build_from_profile(FAKE_PROFILE, limit=2)), 2)

    def test_build_from_profile_without_experience(self):
        self.assertEqual(self.S.build_from_profile({"name": "x"}), [])
        self.assertEqual(self.S.build_from_profile({}), [])

    def test_save_load_round_trip(self):
        stories = self.S.build_from_profile(FAKE_PROFILE)
        path = self.S.save_stories(stories)
        self.assertTrue(path.exists())
        loaded = self.S.load_stories()
        self.assertEqual(len(loaded), 3)
        self.assertEqual(loaded[1]["bullet"], stories[1]["bullet"])

    def test_load_stories_empty_when_missing(self):
        self.assertEqual(self.S.load_stories(), [])


class StoriesUpdateTest(_IsolatedDataDir):
    def setUp(self):
        super().setUp()
        self.S.save_stories(self.S.build_from_profile(FAKE_PROFILE))

    def test_update_writes_own_text(self):
        story = self.S.update_story(0, "result", "Conversion rose from 8% to 9.2%.")
        self.assertEqual(story["sections"]["result"], "Conversion rose from 8% to 9.2%.")
        self.assertTrue(story["filled"]["result"])
        self.assertFalse(story["filled"]["problem"])
        reloaded = self.S.get_story(0)
        self.assertEqual(reloaded["sections"]["result"], "Conversion rose from 8% to 9.2%.")

    def test_update_bad_section_raises(self):
        with self.assertRaises(self.S.PmStoryError):
            self.S.update_story(0, "situation", "text")

    def test_update_empty_text_raises(self):
        with self.assertRaises(self.S.PmStoryError):
            self.S.update_story(0, "result", "   ")

    def test_update_bad_index_raises(self):
        with self.assertRaises(self.S.PmStoryError):
            self.S.update_story(99, "result", "text")

    def test_get_story_out_of_range(self):
        with self.assertRaises(self.S.PmStoryError):
            self.S.get_story(7)

    def test_render_story_marks_filled(self):
        self.S.update_story(0, "lesson", "Ship smaller.")
        out = self.S.render_story(self.S.get_story(0), index=0)
        self.assertIn("[x] LESSON", out)
        self.assertIn("[ ] PROBLEM", out)
        self.assertIn("Ship smaller.", out)

    def test_render_story_list(self):
        out = self.S.render_story_list(self.S.load_stories())
        self.assertIn("#0", out)
        self.assertIn("#2", out)
        self.assertIn("0/5 filled", out)


class StoriesCliTest(_IsolatedDataDir):
    def _parse(self, argv):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        self.S.register_pm(sub)
        return parser.parse_args(argv)

    def test_register_story_actions(self):
        for action in ("build", "list", "show", "update"):
            a = self._parse(["story", action])
            self.assertEqual(a.action, action)

    def test_register_story_update_flags(self):
        a = self._parse(["story", "update", "--index", "1",
                         "--section", "result", "--text", "grew 10%"])
        self.assertEqual((a.index, a.section, a.text), (1, "result", "grew 10%"))

    def test_cmd_build_uses_profile_loader(self):
        # monkeypatch the loader: no real profile file needed
        self.S.load_profile = lambda path=None: FAKE_PROFILE
        a = self._parse(["story", "build", "--limit", "2"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.S.cmd_pm_story(a)
        self.assertIn("2", buf.getvalue())
        self.assertEqual(len(self.S.load_stories()), 2)

    def test_cmd_build_no_bullets_raises(self):
        self.S.load_profile = lambda path=None: {"name": "empty"}
        a = self._parse(["story", "build"])
        with self.assertRaises(self.S.PmStoryError):
            self.S.cmd_pm_story(a)

    def test_cmd_list_show_update_round_trip(self):
        self.S.save_stories(self.S.build_from_profile(FAKE_PROFILE))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.S.cmd_pm_story(self._parse(["story", "list"]))
        self.assertIn("#0", buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.S.cmd_pm_story(self._parse(["story", "show", "--index", "2"]))
        self.assertIn("RESULT", buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.S.cmd_pm_story(self._parse(
                ["story", "update", "--index", "2", "--section", "insight",
                 "--text", "users hated step 3"]))
        self.assertIn("updated", buf.getvalue())


# ---------------------------------------------------------------------------
# pm_scores: rubric scores + trends
# ---------------------------------------------------------------------------

def _scores(*dicts):
    return [dict(s) for s in dicts]


class ScoresRecordTest(_IsolatedDataDir):
    FULL = {"structure": 4, "user_empathy": 3, "metrics_thinking": 5,
            "prioritization": 4, "communication": 3}

    def test_record_score_valid(self):
        e = self.Sc.record_score(dict(self.FULL), note="good")
        self.assertEqual(e["scores"], self.FULL)
        self.assertEqual(e["average"], 3.8)
        self.assertIn("recorded_at", e)

    def test_record_score_out_of_range(self):
        bad = dict(self.FULL, structure=0)
        with self.assertRaises(self.Sc.PmScoreError):
            self.Sc.record_score(bad)
        bad = dict(self.FULL, structure=6)
        with self.assertRaises(self.Sc.PmScoreError):
            self.Sc.record_score(bad)

    def test_record_score_missing_dimension(self):
        partial = {k: v for k, v in self.FULL.items() if k != "structure"}
        with self.assertRaises(self.Sc.PmScoreError):
            self.Sc.record_score(partial)

    def test_record_score_unknown_dimension(self):
        bad = dict(self.FULL, charisma=5)
        with self.assertRaises(self.Sc.PmScoreError):
            self.Sc.record_score(bad)

    def test_record_score_non_integer_rejected(self):
        bad = dict(self.FULL, structure=4.5)
        with self.assertRaises(self.Sc.PmScoreError):
            self.Sc.record_score(bad)
        bad = dict(self.FULL, structure=True)
        with self.assertRaises(self.Sc.PmScoreError):
            self.Sc.record_score(bad)

    def test_add_score_persists(self):
        entry = self.Sc.add_score(dict(self.FULL), note="n1")
        loaded = self.Sc.load_scores()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["note"], "n1")
        self.assertEqual(loaded[0]["average"], entry["average"])

    def test_load_scores_empty_when_missing(self):
        self.assertEqual(self.Sc.load_scores(), [])

    def test_five_dimensions_defined(self):
        self.assertEqual(
            self.Sc.DIMENSIONS,
            ["structure", "user_empathy", "metrics_thinking",
             "prioritization", "communication"])


class ScoresTrendTest(_IsolatedDataDir):
    def setUp(self):
        super().setUp()
        base = {"structure": 2, "user_empathy": 2, "metrics_thinking": 2,
                "prioritization": 2, "communication": 2}
        self.Sc.add_score(dict(base))
        self.Sc.add_score(dict(base, structure=4, metrics_thinking=5))
        self.Sc.add_score(dict(base, structure=5, metrics_thinking=5,
                               communication=4))

    def test_trend_session_count(self):
        self.assertEqual(self.Sc.trend()["sessions"], 3)

    def test_trend_per_dimension_history(self):
        t = self.Sc.trend()
        self.assertEqual(t["dimensions"]["structure"]["history"], [2, 4, 5])
        self.assertEqual(t["dimensions"]["structure"]["delta"], 3)
        self.assertEqual(t["dimensions"]["structure"]["best"], 5)
        self.assertEqual(t["dimensions"]["user_empathy"]["delta"], 0)

    def test_trend_overall_average_delta(self):
        t = self.Sc.trend()
        # averages: 2.0, 3.0, 3.6 -> delta 1.6
        self.assertAlmostEqual(t["average_history"][0], 2.0)
        self.assertAlmostEqual(t["average_history"][-1], 3.6)
        self.assertAlmostEqual(t["average_delta"], 1.6)

    def test_trend_single_session_delta_zero(self):
        entries = [self.Sc.record_score(
            {"structure": 3, "user_empathy": 3, "metrics_thinking": 3,
             "prioritization": 3, "communication": 3})]
        t = self.Sc.trend(entries)
        self.assertEqual(t["average_delta"], 0)
        self.assertEqual(t["dimensions"]["structure"]["delta"], 0)

    def test_trend_empty_raises(self):
        with self.assertRaises(self.Sc.PmScoreError):
            self.Sc.trend([])

    def test_sparkline_mapping(self):
        self.assertEqual(self.Sc.sparkline([1]), "▁")
        self.assertEqual(self.Sc.sparkline([5]), "█")
        self.assertEqual(self.Sc.sparkline([]), "")
        self.assertEqual(len(self.Sc.sparkline([1, 2, 3, 4, 5])), 5)

    def test_render_trend_text(self):
        out = self.Sc.render_trend(self.Sc.trend())
        for d in self.Sc.DIMENSIONS:
            self.assertIn(d, out)
        self.assertIn("Overall average", out)
        self.assertIn("+", out)  # positive delta sign shown

    def test_best(self):
        b = self.Sc.best()
        self.assertEqual(b["per_dimension"]["structure"]["score"], 5)
        self.assertEqual(b["per_dimension"]["structure"]["session"], 2)
        self.assertEqual(b["per_dimension"]["user_empathy"]["score"], 2)
        self.assertEqual(b["best_session"]["index"], 2)

    def test_best_empty_raises(self):
        with self.assertRaises(self.Sc.PmScoreError):
            self.Sc.best([])


class ScoresCliTest(_IsolatedDataDir):
    def _parse(self, argv):
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers()
        self.Sc.register_pm(sub)
        return parser.parse_args(argv)

    def test_register_score_record_flags(self):
        a = self._parse(["score", "record", "--structure", "4",
                         "--user-empathy", "3", "--metrics-thinking", "5",
                         "--prioritization", "4", "--communication", "3",
                         "--note", "nice"])
        self.assertEqual(a.action, "record")
        self.assertEqual(a.structure, 4)
        self.assertEqual(a.user_empathy, 3)
        self.assertEqual(a.metrics_thinking, 5)
        self.assertEqual(a.note, "nice")

    def test_cmd_record_trend_best_round_trip(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.Sc.cmd_pm_score(self._parse(
                ["score", "record", "--structure", "4", "--user-empathy", "3",
                 "--metrics-thinking", "5", "--prioritization", "4",
                 "--communication", "3"]))
        self.assertIn("avg 3.8", buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.Sc.cmd_pm_score(self._parse(["score", "trend"]))
        self.assertIn("structure", buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.Sc.cmd_pm_score(self._parse(["score", "best", "--json"]))
        data = json.loads(buf.getvalue())
        self.assertEqual(data["per_dimension"]["metrics_thinking"]["score"], 5)

    def test_cmd_record_missing_dimension_raises(self):
        with self.assertRaises(self.Sc.PmScoreError):
            self.Sc.cmd_pm_score(self._parse(["score", "record", "--structure", "4"]))

    def test_cmd_trend_empty_raises(self):
        with self.assertRaises(self.Sc.PmScoreError):
            self.Sc.cmd_pm_score(self._parse(["score", "trend"]))


if __name__ == "__main__":
    unittest.main()
