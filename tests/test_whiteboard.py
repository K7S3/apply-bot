"""Tests for candid.whiteboard — whiteboard practice mode.

Run: python3 -m unittest tests.test_whiteboard -v
(unittest style, matching the repo's full-suite runner)
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import whiteboard as W  # noqa: E402


class WhiteboardBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._patch = mock.patch.dict(os.environ, {"CANDID_DATA_DIR": self.tmp.name})
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def sessions_dir(self):
        return Path(self.tmp.name) / "whiteboard_sessions"

    def narrated(self, drill="url-shortener"):
        return W.narrate(drill, notes=dict(NOTES), echo=False)


NOTES = {
    "requirements": "Shorten URLs, 100M a month, fast reads.",
    "components": "API, ID generator, DB, cache.",
    "dataflow": "POST then GET, cache miss goes to DB.",
    "scale": "Shard by code hash; cache is the bottleneck fix.",
    "tradeoffs": "Counter ranges over KGS for simplicity; give up global ordering.",
}


class TestDrillBank(WhiteboardBase):
    def test_bank_has_ten_drills_with_required_fields(self):
        drills = W.list_drills()
        self.assertEqual(len(drills), 10)
        required = ("id", "title", "prompt", "difficulty", "topics", "minutes",
                    "functional", "non_functional", "expected_components",
                    "followups", "pitfalls")
        for d in drills:
            for key in required:
                self.assertIn(key, d, f"{d['id']} missing {key}")
            self.assertIn(d["difficulty"], ("easy", "medium", "hard"))
            self.assertGreaterEqual(len(d["expected_components"]), 3)
            self.assertGreaterEqual(len(d["followups"]), 2)

    def test_rubric_and_sections_shapes(self):
        self.assertEqual([r["dimension"].lower() for r in W.rubric()], W.DIMENSIONS)
        self.assertEqual(sum(r["weight"] for r in W.rubric()), 10)
        self.assertEqual([s["id"] for s in W.narration_sections()],
                         ["requirements", "components", "dataflow", "scale", "tradeoffs"])

    def test_list_drills_filters(self):
        self.assertTrue(all(d["difficulty"] == "hard"
                            for d in W.list_drills(difficulty="hard")))
        self.assertTrue(W.list_drills(difficulty="easy"))
        by_topic = W.list_drills(topic="caching")
        self.assertTrue(by_topic and all("caching" in d["topics"] for d in by_topic))
        self.assertTrue(W.list_drills(difficulty="easy", topic="caching"))

    def test_list_drills_bad_difficulty(self):
        with self.assertRaises(W.WhiteboardError):
            W.list_drills(difficulty="extreme")

    def test_get_drill_typo_hint(self):
        with self.assertRaises(W.WhiteboardError) as ctx:
            W.get_drill("url-shortner")
        self.assertIn("url-shortener", str(ctx.exception))

    def test_suggest_drill_respects_avoid_and_filters(self):
        ids = [d["id"] for d in W.list_drills()]
        pick = W.suggest_drill(avoid=ids[:-1], seed=1)
        self.assertEqual(pick["id"], ids[-1])
        hard = W.suggest_drill(difficulty="hard", seed=2)
        self.assertEqual(hard["difficulty"], "hard")


class TestPlan(WhiteboardBase):
    def test_plan_minutes_sum_exactly(self):
        for minutes in (15, 30, 45, 60):
            plan = W.plan_drill("chat-system", minutes=minutes)
            self.assertEqual(sum(p["minutes"] for p in plan["phases"]), minutes)
            self.assertEqual([p["id"] for p in plan["phases"]],
                             ["clarify", "highlevel", "deepdive", "wrapup"])

    def test_plan_rejects_short_sessions(self):
        with self.assertRaises(W.WhiteboardError):
            W.plan_drill("chat-system", minutes=5)

    def test_render_plan_shows_phases(self):
        text = W.render_plan(W.plan_drill("kv-store", minutes=30))
        self.assertIn("Deep dive", text)
        self.assertIn("30-minute", text)


class TestNarrate(WhiteboardBase):
    def test_narrate_captures_all_sections(self):
        s = self.narrated()
        self.assertEqual(s["drill_id"], "url-shortener")
        self.assertEqual(s["narration"], NOTES)
        self.assertEqual(s["narration_gaps"], [])
        saved = json.loads((self.sessions_dir() / f"{s['id']}.json").read_text())
        self.assertEqual(saved["narration"]["components"], NOTES["components"])

    def test_narrate_flags_blank_sections(self):
        s = W.narrate("pastebin", notes={"requirements": "x"}, echo=False)
        self.assertEqual(set(s["narration_gaps"]),
                         {"High-level components", "Data flow walkthrough",
                          "Failure and scale", "Tradeoffs and alternatives"})

    def test_render_narration_marks_blanks(self):
        s = W.narrate("pastebin", notes={}, echo=False)
        text = W.render_narration(s)
        self.assertIn("_(blank)_", text)
        self.assertIn("Requirements recap", text)

    def test_narrate_unknown_drill(self):
        with self.assertRaises(W.WhiteboardError):
            W.narrate("nope", notes={}, echo=False)


class TestComponents(WhiteboardBase):
    def test_checklist_names(self):
        names = [c["name"] for c in W.component_checklist("news-feed")]
        self.assertIn("Fanout service", names)

    def test_check_components_full_coverage(self):
        names = [c["name"] for c in W.component_checklist("rate-limiter")]
        r = W.check_components("rate-limiter", names)
        self.assertEqual(r["coverage_pct"], 100)
        self.assertEqual(r["missed"], [])

    def test_check_components_partial_and_prefix_match(self):
        r = W.check_components("url-shortener", ["cache", "API tier"])
        self.assertEqual(r["coverage_pct"], 40)
        self.assertIn("ID generator", r["missed"])

    def test_check_components_unknown_name(self):
        with self.assertRaises(W.WhiteboardError) as ctx:
            W.check_components("url-shortener", ["flux capacitor"])
        self.assertIn("Expected one of", str(ctx.exception))

    def test_check_components_attaches_to_session(self):
        s = self.narrated()
        r = W.check_components("url-shortener", ["cache"], session_id=s["id"])
        self.assertEqual(r["session_id"], s["id"])
        self.assertEqual(W.load_session(s["id"])["component_coverage_pct"], 20)

    def test_render_checklist_marks_checked(self):
        text = W.render_checklist("pastebin", checked=["Cache"])
        self.assertIn("[x] Cache", text)
        self.assertIn("[ ] API tier", text)


class TestOutline(WhiteboardBase):
    def test_reference_outline_contents(self):
        o = W.reference_outline("ticket-booking")
        self.assertTrue(o["scale"] and o["api_sketch"] and o["data_model"])
        self.assertIn("Seat inventory service", o["components"])
        text = W.render_outline(o)
        self.assertIn("Common pitfalls", text)
        self.assertIn("double-booking", text.lower())


class TestFeedback(WhiteboardBase):
    def test_score_feedback_weighted_math(self):
        fb = W.score_feedback({"clarity": 4, "completeness": 3,
                               "depth": 5, "communication": 2})
        # (4*3 + 3*3 + 5*2 + 2*2) / 10 = 35/10
        self.assertEqual(fb["score"], 3.5)
        self.assertEqual(fb["verdict"], "solid")
        self.assertEqual(fb["gaps"], ["communication"])
        self.assertEqual(len(fb["next_steps"]), 1)
        self.assertIn("out loud", fb["next_steps"][0])
        self.assertEqual(fb["strengths"], ["clarity", "depth"])

    def test_score_feedback_verdict_bands(self):
        self.assertEqual(W.score_feedback({d: 5 for d in W.DIMENSIONS})["verdict"],
                         "whiteboard-ready")
        self.assertEqual(W.score_feedback({d: 3 for d in W.DIMENSIONS})["verdict"],
                         "developing")
        self.assertEqual(W.score_feedback({d: 1 for d in W.DIMENSIONS})["verdict"],
                         "needs work")

    def test_score_feedback_perfect_adds_stretch(self):
        fb = W.score_feedback({d: 5 for d in W.DIMENSIONS})
        self.assertEqual(fb["gaps"], [])
        self.assertTrue(any("Stretch" in s for s in fb["next_steps"]))

    def test_score_feedback_no_gaps_still_guides(self):
        fb = W.score_feedback({"clarity": 4, "completeness": 3,
                               "depth": 4, "communication": 4})
        self.assertEqual(fb["gaps"], [])
        self.assertEqual(len(fb["next_steps"]), 1)
        self.assertIn("completeness", fb["next_steps"][0])

    def test_score_feedback_rejects_bad_input(self):
        with self.assertRaises(W.WhiteboardError):
            W.score_feedback({"clarity": 4, "completeness": 3, "depth": 5})  # missing dim
        with self.assertRaises(W.WhiteboardError):
            W.score_feedback({d: 6 for d in W.DIMENSIONS})  # out of range
        with self.assertRaises(W.WhiteboardError):
            W.score_feedback({d: 3 for d in W.DIMENSIONS} | {"charisma": 5})

    def test_attach_feedback_persists(self):
        s = self.narrated()
        updated = W.attach_feedback(s["id"], {d: 4 for d in W.DIMENSIONS}, notes="good pace")
        self.assertEqual(updated["feedback"]["score"], 4.0)
        self.assertEqual(W.load_session(s["id"])["feedback"]["notes"], "good pace")

    def test_render_feedback_layout(self):
        fb = W.score_feedback({"clarity": 2, "completeness": 4,
                               "depth": 4, "communication": 4})
        text = W.render_feedback(fb)
        self.assertIn("3.4/5", text)
        self.assertIn("Gaps: clarity", text)
        self.assertIn("Next steps:", text)


class TestTimedDrill(WhiteboardBase):
    def test_run_drill_saves_session_with_plan(self):
        s = W.run_drill("autocomplete", minutes=20, wait=False, echo=False)
        self.assertEqual(s["kind"], "timed")
        self.assertEqual(sum(p["minutes"] for p in s["plan"]["phases"]), 20)
        self.assertEqual(W.load_session(s["id"])["drill_id"], "autocomplete")


class TestFollowups(WhiteboardBase):
    def test_list_followups_have_why(self):
        fups = W.list_followups("chat-system")
        self.assertGreaterEqual(len(fups), 3)
        self.assertTrue(all(f["q"] and f["why"] for f in fups))

    def test_quiz_followup_by_index_and_answer(self):
        q = W.quiz_followup("kv-store", index=0, answer="W=1 is fast writes.", echo=False)
        self.assertTrue(q["question"].startswith("W=1"))
        self.assertEqual(q["answer"], "W=1 is fast writes.")
        self.assertTrue(q["why"])

    def test_quiz_followup_bad_index(self):
        with self.assertRaises(W.WhiteboardError):
            W.quiz_followup("kv-store", index=99, echo=False)


class TestHistory(WhiteboardBase):
    def test_history_empty(self):
        self.assertEqual(W.session_history(), [])

    def test_history_newest_first_and_filter(self):
        s1 = self.narrated()
        s2 = W.run_drill("pastebin", minutes=10, wait=False, echo=False)
        hist = W.session_history()
        self.assertEqual([s["id"] for s in hist], [s2["id"], s1["id"]])
        self.assertEqual([s["id"] for s in W.session_history(drill_id="pastebin")],
                         [s2["id"]])

    def test_drill_stats_aggregates(self):
        s1 = self.narrated()
        s2 = self.narrated()
        W.attach_feedback(s1["id"], {d: 4 for d in W.DIMENSIONS})
        W.attach_feedback(s2["id"], {d: 2 for d in W.DIMENSIONS})
        st = W.drill_stats()["url-shortener"]
        self.assertEqual(st["sessions"], 2)
        self.assertEqual(st["best_score"], 4.0)
        self.assertEqual(st["avg_score"], 3.0)
        self.assertEqual(st["dimension_avgs"]["clarity"], 3.0)

    def test_render_history_empty_message(self):
        self.assertIn("No whiteboard sessions yet", W.render_history([], {}))


class TestCliWiring(unittest.TestCase):
    def test_cli_has_whiteboard_subcommands(self):
        from candid.__main__ import build_parser
        p = build_parser()
        args = p.parse_args(["whiteboard", "drills", "--difficulty", "hard"])
        self.assertEqual(args.what, "drills")
        self.assertEqual(args.difficulty, "hard")
        args = p.parse_args(["whiteboard", "feedback", "--session", "x",
                             "--clarity", "4", "--completeness", "4",
                             "--depth", "4", "--communication", "4"])
        self.assertEqual(args.what, "feedback")
        cases = {
            "plan": ["--drill", "chat-system"],
            "narrate": ["--drill", "chat-system"],
            "components": ["--drill", "chat-system"],
            "outline": ["--drill", "chat-system"],
            "drill": ["--drill", "chat-system"],
            "followups": ["--drill", "chat-system"],
            "history": [],
            "rubric": [],
            "drills": [],
        }
        for sub, extra in cases.items():
            self.assertEqual(p.parse_args(["whiteboard", sub] + extra).what, sub)


if __name__ == "__main__":
    unittest.main()
