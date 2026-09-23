"""Tests for the live-coding practice harness (candid.practice).

Run: CANDID_DATA_DIR=/tmp/candid-test-practice python3 -m unittest tests.test_practice -v
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock as umock

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-practice")

from candid import practice as P  # noqa: E402
from candid import mock as M  # noqa: E402

SYN = {
    "id": "syn-add",
    "title": "Syn Add",
    "topic": "arrays",
    "difficulty": "easy",
    "function": "solve(a, b)",
    "compare": "exact",
    "statement": "Return a + b.",
    "visible_tests": [{"args": [1, 2], "expected": 3}],
    "hidden_tests": [{"args": [10, 20], "expected": 30}],
    "hints": ["Just add them."],
    "reference_solution": "def solve(a, b):\n    return a + b",
    "complexity": "O(1)",
}
GOOD = "def solve(a, b):\n    return a + b"
BAD = "def solve(a, b):\n    return a - b"


def _problem() -> dict:
    return json.loads(json.dumps(SYN))


class FakeIO:
    """Scripted input/output for the interactive runner."""

    def __init__(self, inputs, clock=None):
        self.inputs = list(inputs)
        self.outputs: list[str] = []
        self.clock = clock

    def input(self, prompt=""):
        if self.clock is not None:
            self.clock.advance(5)  # every prompt costs 5 fake seconds
        if prompt:
            self.outputs.append(prompt)
        if not self.inputs:
            raise EOFError
        return self.inputs.pop(0)

    def print(self, *args):
        self.outputs.append(" ".join(str(a) for a in args))

    def text(self) -> str:
        return "\n".join(self.outputs)


class DataDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="candid-practice-")
        self._old = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# timer
# ---------------------------------------------------------------------------

class TimerTest(unittest.TestCase):
    def test_milestones_fire_once_each(self):
        clock = P.FakeClock()
        t = P.SessionTimer(100.0, clock)
        t.start()
        self.assertEqual(t.due_milestones(), [])
        clock.advance(30)
        self.assertEqual(t.due_milestones(), [0.25])
        clock.advance(30)
        self.assertEqual(t.due_milestones(), [0.50])
        clock.advance(35)
        self.assertEqual(t.due_milestones(), [0.75, 0.90])
        self.assertEqual(t.due_milestones(), [])  # never refires

    def test_expiry_and_remaining(self):
        clock = P.FakeClock()
        t = P.SessionTimer(60.0, clock)
        t.start()
        clock.advance(61)
        self.assertTrue(t.expired())
        self.assertEqual(t.remaining(), 0.0)
        self.assertEqual(t.render_remaining(), "00:00 left")

    def test_render_remaining_format(self):
        clock = P.FakeClock()
        t = P.SessionTimer(600.0, clock)
        t.start()
        clock.advance(125)
        self.assertEqual(t.render_remaining(), "07:55 left")

    def test_zero_budget_raises(self):
        with self.assertRaises(P.PracticeError):
            P.SessionTimer(0)


# ---------------------------------------------------------------------------
# phases
# ---------------------------------------------------------------------------

class PhasePlanTest(unittest.TestCase):
    def test_current_phase_by_elapsed(self):
        plan = P.PhasePlan()
        self.assertEqual(plan.current(60, 3600), "plan")     # ~2% in
        self.assertEqual(plan.current(600, 3600), "code")   # ~17% in
        self.assertEqual(plan.current(3000, 3600), "test")  # ~83% in
        self.assertEqual(plan.current(3400, 3600), "review")  # ~94% in
        self.assertEqual(plan.current(9999, 3600), "review")  # past the end

    def test_bounds_cover_budget(self):
        plan = P.PhasePlan()
        bounds = plan.bounds(100.0)
        self.assertAlmostEqual(bounds[0][1], 0.0)
        self.assertAlmostEqual(bounds[-1][2], 100.0)
        for _, s, e in bounds:
            self.assertLess(s, e)

    def test_fractions_must_sum_to_one(self):
        with self.assertRaises(P.PracticeError):
            P.PhasePlan([("plan", 0.5), ("code", 0.6)])

    def test_parse_phases_valid(self):
        split = P.parse_phases("plan:10,code:60,test:20,review:10")
        self.assertEqual([n for n, _ in split], ["plan", "code", "test", "review"])
        self.assertAlmostEqual(sum(f for _, f in split), 1.0)

    def test_parse_phases_rejects_unknown_phase(self):
        with self.assertRaises(P.PracticeError):
            P.parse_phases("plan:10,code:60,test:20,nap:10")

    def test_parse_phases_rejects_partial_cover(self):
        with self.assertRaises(P.PracticeError):
            P.parse_phases("plan:50,code:50")

    def test_parse_phases_none_passthrough(self):
        self.assertIsNone(P.parse_phases(None))

    def test_minutes_per_phase(self):
        plan = P.PhasePlan()
        mins = plan.minutes_per_phase(3600)
        self.assertAlmostEqual(mins["plan"], 6.0)
        self.assertAlmostEqual(mins["code"], 36.0)


# ---------------------------------------------------------------------------
# think-aloud
# ---------------------------------------------------------------------------

class ThinkAloudTest(unittest.TestCase):
    def _session(self, elapsed, entries=()):
        s = P.new_session(_problem(), minutes=45)
        s["_elapsed_s"] = elapsed
        s["think_aloud"] = list(entries)
        return s

    def test_prompt_due_after_interval(self):
        s = self._session(elapsed=700)
        prompt = P.think_aloud_due(s, 600)
        self.assertIsNotNone(prompt)
        self.assertIn(prompt, P.THINK_ALOUD_PROMPTS)

    def test_not_due_before_interval(self):
        s = self._session(elapsed=100)
        self.assertIsNone(P.think_aloud_due(s, 600))

    def test_prompts_cycle(self):
        first = P.think_aloud_due(self._session(700), 600)
        s = self._session(1400, entries=[{"at_s": 700, "prompt": first, "answer": "x"}])
        second = P.think_aloud_due(s, 600)
        self.assertNotEqual(first, second)

    def test_disabled_when_interval_zero(self):
        s = self._session(elapsed=99999)
        self.assertIsNone(P.think_aloud_due(s, 0))


# ---------------------------------------------------------------------------
# focus lock
# ---------------------------------------------------------------------------

class FocusTest(unittest.TestCase):
    def test_focus_blocks_hint_and_solution(self):
        for cmd in ("hint", "solution"):
            ok, reason = P.focus_allows(cmd, focus=True, session_over=False)
            self.assertFalse(ok)
            self.assertIn("locked", reason)

    def test_focus_allows_coding_commands(self):
        for cmd in ("run", "done", "think", "time", "quit"):
            ok, _ = P.focus_allows(cmd, focus=True, session_over=False)
            self.assertTrue(ok)

    def test_no_focus_allows_everything(self):
        ok, _ = P.focus_allows("hint", focus=False, session_over=False)
        self.assertTrue(ok)

    def test_session_over_lifts_lock(self):
        ok, _ = P.focus_allows("solution", focus=True, session_over=True)
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# sessions + judging
# ---------------------------------------------------------------------------

class SessionJudgeTest(DataDirTest):
    def test_new_session_defaults(self):
        s = P.new_session(_problem(), minutes=30)
        self.assertEqual(s["problem"]["id"], "syn-add")
        self.assertEqual(s["budget_s"], 1800.0)
        self.assertTrue(s["focus"])
        self.assertIsNone(s["outcome"])

    def test_new_session_rejects_bad_minutes(self):
        with self.assertRaises(P.PracticeError):
            P.new_session(_problem(), minutes=0)

    def test_mid_session_judge_uses_visible_only(self):
        s = P.new_session(_problem(), minutes=30)
        result = P.judge_attempt(s, _problem(), BAD, final=False)
        self.assertEqual(result["verdict"], "wrong_answer")
        self.assertEqual(len(result["tests"]), 1)  # visible only
        self.assertEqual(len(s["attempts"]), 1)
        self.assertFalse(s["attempts"][0]["final"])

    def test_final_judge_uses_full_suite(self):
        s = P.new_session(_problem(), minutes=30)
        result = P.judge_attempt(s, _problem(), GOOD, final=True)
        self.assertEqual(result["verdict"], "accepted")
        self.assertEqual(len(result["tests"]), 2)  # visible + hidden
        self.assertTrue(s["attempts"][0]["final"])

    def test_final_judge_catches_hidden_only_failure(self):
        s = P.new_session(_problem(), minutes=30)
        code = "def solve(a, b):\n    return 3 if (a, b) == (1, 2) else 0"
        mid = P.judge_attempt(s, _problem(), code, final=False)
        self.assertEqual(mid["verdict"], "accepted")
        final = P.judge_attempt(s, _problem(), code, final=True)
        self.assertEqual(final["verdict"], "wrong_answer")


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------

class ReviewTest(unittest.TestCase):
    def _session(self, **kw):
        s = P.new_session(_problem(), minutes=45)
        s.update(kw)
        return s

    def test_observations_first_try_solve(self):
        s = self._session(outcome="solved", duration_s=600.0, budget_s=2700.0,
                          attempts=[{"n": 1}], hints_used=0,
                          think_aloud=[{"at_s": 1, "prompt": "p", "answer": "a"}])
        obs = P.auto_observations(s)
        self.assertTrue(any("First-attempt" in o for o in obs))

    def test_observations_timed_out(self):
        s = self._session(outcome="timed_out", duration_s=2700.0, budget_s=2700.0)
        obs = P.auto_observations(s)
        self.assertTrue(any("clock" in o for o in obs))

    def test_observations_hint_dependent(self):
        s = self._session(outcome="solved", duration_s=900.0, budget_s=2700.0,
                          attempts=[{"n": 1}, {"n": 2}], hints_used=2)
        obs = P.auto_observations(s)
        self.assertTrue(any("hints" in o for o in obs))

    def test_observations_debug_heavy(self):
        s = self._session(outcome="solved", duration_s=900.0, budget_s=2700.0,
                          attempts=[{"n": i} for i in range(5)])
        obs = P.auto_observations(s)
        self.assertTrue(any("5 attempts" in o for o in obs))

    def test_build_review_shape(self):
        s = self._session(outcome="solved", duration_s=600.0, budget_s=2700.0)
        r = P.build_review(s, {"went_well": "fast start"})
        self.assertIn("observations", r)
        self.assertEqual(r["answers"]["went_well"], "fast start")
        self.assertEqual(r["answers"]["stuck"], "")
        self.assertIn("at", r)

    def test_render_review_shows_qa(self):
        s = self._session(outcome="solved", duration_s=600.0, budget_s=2700.0)
        s["review"] = P.build_review(s, {"went_well": "great"})
        text = P.render_review(s)
        self.assertIn("What went well", text)
        self.assertIn("great", text)


# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------

class TagsTest(unittest.TestCase):
    def test_normalize_tag(self):
        self.assertEqual(P.normalize_tag("  Needs Drill "), "needs-drill")
        self.assertEqual(P.normalize_tag("two_pointers"), "two-pointers")

    def test_normalize_tag_rejects_garbage(self):
        with self.assertRaises(P.PracticeError):
            P.normalize_tag("!!!")

    def test_auto_tags(self):
        self.assertEqual(P.auto_tags(_problem()), ["topic:arrays", "diff:easy"])

    def _session(self, **kw):
        s = P.new_session(_problem(), minutes=45)
        s.update(kw)
        return s

    def test_behavior_first_try(self):
        s = self._session(outcome="solved", duration_s=600.0, budget_s=2700.0,
                          attempts=[{"n": 1}], hints_used=0)
        self.assertIn("first-try-solve", P.behavior_tags(s))

    def test_behavior_hint_dependent(self):
        s = self._session(outcome="solved", duration_s=600.0, budget_s=2700.0,
                          attempts=[{"n": 1}], hints_used=2)
        self.assertIn("hint-dependent", P.behavior_tags(s))

    def test_behavior_debug_heavy(self):
        s = self._session(outcome="solved", duration_s=600.0, budget_s=2700.0,
                          attempts=[{"n": i} for i in range(4)])
        self.assertIn("debug-heavy", P.behavior_tags(s))

    def test_behavior_time_pressure(self):
        s = self._session(outcome="timed_out", duration_s=2800.0, budget_s=2700.0)
        self.assertIn("time-pressure", P.behavior_tags(s))

    def test_behavior_gave_up(self):
        s = self._session(outcome="gave_up", duration_s=600.0, budget_s=2700.0)
        self.assertIn("gave-up-early", P.behavior_tags(s))

    def test_finalize_tags_dedupes_and_merges(self):
        s = self._session(outcome="solved", duration_s=600.0, budget_s=2700.0,
                          attempts=[{"n": 1}], hints_used=0)
        tags = P.finalize_tags(s, _problem(), extra=["needs-drill", "needs-drill"])
        self.assertEqual(len(tags), len(set(tags)))
        self.assertIn("topic:arrays", tags)
        self.assertIn("first-try-solve", tags)
        self.assertIn("needs-drill", tags)

    def test_add_remove_tags(self):
        s = self._session()
        s["tags"] = ["topic:arrays"]
        P.add_tags(s, ["Needs Drill", "topic:arrays"])
        self.assertEqual(s["tags"], ["topic:arrays", "needs-drill"])
        P.remove_tags(s, ["needs-drill"])
        self.assertEqual(s["tags"], ["topic:arrays"])


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

class PersistenceTest(DataDirTest):
    def _finished(self, **kw):
        s = P.new_session(_problem(), minutes=45)
        s["_elapsed_s"] = 600.0
        s["started_at"] = "2026-09-22T10:00:00"
        s["tags"] = P.finalize_tags(s, _problem())
        P.finalize_session(s, _problem(), kw.pop("outcome", "solved"),
                           final_code=kw.pop("final_code", GOOD), **kw)
        return s

    def test_save_and_load_roundtrip(self):
        s = self._finished()
        loaded = P.load_session(s["id"])
        self.assertEqual(loaded["id"], s["id"])
        self.assertEqual(loaded["outcome"], "solved")
        self.assertNotIn("_elapsed_s", loaded)  # scratch keys stripped

    def test_save_unended_raises(self):
        s = P.new_session(_problem(), minutes=45)
        with self.assertRaises(P.PracticeError):
            P.save_session(s)

    def test_load_unknown_raises(self):
        with self.assertRaises(P.PracticeError):
            P.load_session("p20990101_000000")

    def test_list_filters(self):
        s1 = self._finished(outcome="solved")
        s2 = self._finished(outcome="gave_up", final_code=None)
        s2["tags"] = P.finalize_tags(s2, _problem(), extra=["retry-me"])
        P.save_session(s2)  # re-save with the extra tag
        self.assertEqual(len(P.list_sessions()), 2)
        self.assertEqual(len(P.list_sessions(outcome="solved")), 1)
        self.assertEqual(P.list_sessions(outcome="solved")[0]["id"], s1["id"])
        self.assertEqual(len(P.list_sessions(tag="retry-me")), 1)
        self.assertEqual(len(P.list_sessions(problem="syn-add")), 2)
        self.assertEqual(len(P.list_sessions(limit=1)), 1)
        with self.assertRaises(P.PracticeError):
            P.list_sessions(outcome="bogus")

    def test_render_list_empty(self):
        self.assertIn("No practice sessions", P.render_session_list([]))

    def test_render_list_rows(self):
        self._finished()
        text = P.render_session_list(P.list_sessions())
        self.assertIn("Syn Add", text)
        self.assertIn("solved", text)

    def test_render_detail(self):
        s = self._finished()
        text = P.render_session_detail(P.load_session(s["id"]))
        self.assertIn("Syn Add", text)
        self.assertIn("topic:arrays", text)


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

class StatsTest(DataDirTest):
    def _entry(self, outcome, days_ago, tags=(), duration_s=600.0):
        at = (datetime.now() - timedelta(days=days_ago)).isoformat(timespec="seconds")
        return {"id": f"p{days_ago}", "problem_id": "syn-add", "title": "Syn Add",
                "topic": "arrays", "difficulty": "easy", "outcome": outcome,
                "final_verdict": "accepted", "duration_s": duration_s,
                "attempts": 1, "hints_used": 0, "at": at, "tags": list(tags),
                "revisit_next_due": None, "revisit_count": 0}

    def test_compute_stats(self):
        entries = [
            self._entry("solved", 0, tags=["topic:arrays"]),
            self._entry("solved", 1, tags=["topic:arrays"]),
            self._entry("gave_up", 2, tags=["topic:dp"]),
            self._entry("abandoned", 3),
        ]
        st = P.compute_stats(entries)
        self.assertEqual(st["total_sessions"], 3)  # abandoned excluded
        self.assertEqual(st["solved"], 2)
        self.assertAlmostEqual(st["solve_rate"], round(2 / 3, 2))
        self.assertAlmostEqual(st["avg_duration_min"], 10.0)
        self.assertEqual(st["by_tag"]["topic:arrays"]["sessions"], 2)
        self.assertEqual(st["by_tag"]["topic:dp"]["solve_rate"], 0.0)

    def test_streak_counts_consecutive_days(self):
        entries = [self._entry("solved", d) for d in (0, 1, 2)]
        self.assertEqual(P.compute_stats(entries)["streak_days"], 3)

    def test_streak_breaks_on_gap(self):
        entries = [self._entry("solved", d) for d in (0, 2, 3)]
        self.assertEqual(P.compute_stats(entries)["streak_days"], 1)

    def test_streak_empty(self):
        self.assertEqual(P.compute_stats([])["streak_days"], 0)

    def test_render_stats(self):
        st = P.compute_stats([self._entry("solved", 0, tags=["topic:arrays"])])
        text = P.render_stats(st)
        self.assertIn("Sessions: 1", text)
        self.assertIn("topic:arrays", text)
        self.assertIn("streak", text.lower())


# ---------------------------------------------------------------------------
# revisit queue
# ---------------------------------------------------------------------------

class QueueTest(DataDirTest):
    def _session(self, outcome="gave_up", hints=0, attempts=1):
        s = P.new_session(_problem(), minutes=45)
        s["_elapsed_s"] = 600.0
        s["started_at"] = datetime.now().isoformat(timespec="seconds")
        s["outcome"] = outcome
        s["duration_s"] = 600.0
        s["hints_used"] = hints
        s["attempts"] = [{"n": i} for i in range(attempts)]
        s["ended_at"] = datetime.now().isoformat(timespec="seconds")
        return s

    def test_needs_revisit_matrix(self):
        self.assertTrue(P.needs_revisit(self._session("gave_up")))
        self.assertTrue(P.needs_revisit(self._session("timed_out")))
        self.assertFalse(P.needs_revisit(self._session("solved")))
        self.assertTrue(P.needs_revisit(self._session("solved", hints=2)))
        self.assertTrue(P.needs_revisit(self._session("solved", attempts=5)))

    def test_revisit_reasons(self):
        self.assertIn("gave up", P.revisit_reason(self._session("gave_up")))
        self.assertIn("timed out", P.revisit_reason(self._session("timed_out")))
        self.assertIn("hint-dependent", P.revisit_reason(self._session("solved", hints=3)))

    def test_schedule_ladder(self):
        now = datetime(2026, 9, 22, 12, 0, 0)
        s = self._session("gave_up")
        due1 = P.schedule_revisit(s, now=now)
        self.assertEqual(due1[:10], "2026-09-23")  # +1 day
        s["revisit"]["count"] = 1
        due2 = P.schedule_revisit(s, now=now)
        self.assertEqual(due2[:10], "2026-09-25")  # +3 days

    def test_schedule_none_for_clean_solve(self):
        s = self._session("solved")
        self.assertIsNone(P.schedule_revisit(s))
        self.assertIsNone(s["revisit"]["next_due"])

    def test_record_revisit_retires_on_clean_solve(self):
        s = self._session("gave_up")
        s["revisit"] = {"count": 2, "next_due": "2026-09-23T12:00:00"}
        s["outcome"] = "solved"
        s["hints_used"] = 0
        s["attempts"] = [{"n": 1}]
        self.assertIsNone(P.record_revisit(s, "solved"))
        self.assertIsNone(s["revisit"]["next_due"])

    def test_record_revisit_advances_on_weak_retry(self):
        s = self._session("gave_up")
        s["revisit"] = {"count": 0, "next_due": "2026-09-23T12:00:00"}
        nxt = P.record_revisit(s, "gave_up", now=datetime(2026, 9, 23, 12, 0, 0))
        self.assertEqual(s["revisit"]["count"], 1)
        self.assertEqual(nxt[:10], "2026-09-26")

    def test_due_queue_ordering(self):
        now = datetime(2026, 9, 22, 12, 0, 0)
        for days_ago_due, sid in ((5, "pa"), (1, "pb")):
            s = self._session("gave_up")
            s["id"] = "p20260922_" + sid
            s["revisit"] = {"count": 0,
                            "next_due": (now - timedelta(days=days_ago_due)).isoformat()}
            s["tags"] = []
            P.save_session(s)
        q = P.due_queue(now=now)
        self.assertEqual([i["session_id"] for i in q], ["p20260922_pa", "p20260922_pb"])
        self.assertEqual(q[0]["overdue_days"], 5)

    def test_due_queue_skips_future(self):
        s = self._session("gave_up")
        s["revisit"] = {"count": 0,
                        "next_due": (datetime.now() + timedelta(days=3)).isoformat()}
        s["tags"] = []
        P.save_session(s)
        self.assertEqual(P.due_queue(), [])

    def test_render_queue(self):
        self.assertIn("clear", P.render_queue([]))
        q = [{"session_id": "p1", "problem_id": "syn-add", "title": "Syn Add",
              "due": "2026-09-20T12:00:00", "overdue_days": 2, "revisits": 0}]
        text = P.render_queue(q)
        self.assertIn("syn-add", text)
        self.assertIn("2d overdue", text)


# ---------------------------------------------------------------------------
# routines
# ---------------------------------------------------------------------------

class RoutinesTest(DataDirTest):
    def test_builtins_present(self):
        r = P.list_routines()
        for name in ("warmup", "interview-sim", "dp-drill"):
            self.assertIn(name, r)
            self.assertTrue(r[name])

    def test_get_unknown_raises(self):
        with self.assertRaises(P.PracticeError):
            P.get_routine("nope")

    def test_save_get_delete(self):
        with umock.patch.object(M, "get_problem", return_value=_problem()):
            P.save_routine("my-drill", [{"problem": "syn-add", "minutes": 20}])
        self.assertEqual(P.get_routine("my-drill")[0]["problem"], "syn-add")
        P.delete_routine("my-drill")
        with self.assertRaises(P.PracticeError):
            P.get_routine("my-drill")

    def test_save_rejects_builtin_name(self):
        with self.assertRaises(P.PracticeError):
            P.save_routine("warmup", [{"problem": "syn-add", "minutes": 20}])

    def test_save_validates_steps(self):
        with umock.patch.object(M, "get_problem", return_value=_problem()):
            with self.assertRaises(P.PracticeError):
                P.save_routine("bad1", [{"problem": "syn-add", "minutes": 0}])
            with self.assertRaises(P.PracticeError):
                P.save_routine("bad2", [{"minutes": 20}])  # no selector
            with self.assertRaises(P.PracticeError):
                P.save_routine("bad3", [])
        with umock.patch.object(M, "get_problem",
                                side_effect=P.PracticeError("Unknown problem")):
            with self.assertRaises(P.PracticeError):
                P.save_routine("bad4", [{"problem": "nope", "minutes": 20}])

    def test_delete_unknown_raises(self):
        with self.assertRaises(P.PracticeError):
            P.delete_routine("nope")

    def test_parse_steps_spec(self):
        steps = P.parse_steps_spec("syn-add:20, syn-add:25")
        self.assertEqual(steps[0], {"problem": "syn-add", "minutes": 20.0})
        with self.assertRaises(P.PracticeError):
            P.parse_steps_spec("syn-add")

    def test_render_routines(self):
        text = P.render_routines(P.list_routines())
        self.assertIn("warmup", text)
        self.assertIn("built-in", text)


# ---------------------------------------------------------------------------
# interactive runner (scripted I/O, no real waiting)
# ---------------------------------------------------------------------------

class RunnerTest(DataDirTest):
    def _patch_problem(self):
        return umock.patch.object(M, "get_problem", return_value=_problem())

    def test_solved_flow(self):
        io = FakeIO([
            "run", "def solve(a, b):", "    return a + b", "EOF",
            "done",
            "", "", "", "",  # skip the 4 review questions
        ], clock=P.FakeClock())
        with self._patch_problem():
            s = P.run_session(problem_id="syn-add", minutes=45, focus=True,
                              think_every_s=0, input_fn=io.input, print_fn=io.print,
                              clock=io.clock)
        self.assertEqual(s["outcome"], "solved")
        self.assertEqual(s["final_verdict"], "accepted")
        self.assertIn("topic:arrays", s["tags"])
        self.assertIn("first-try-solve", s["tags"])
        self.assertIn("reviewed", s["tags"])
        self.assertTrue((P._sessions_dir() / f"{s['id']}.json").exists())
        self.assertEqual(len(P.list_sessions()), 1)
        out = io.text()
        self.assertIn("visible tests passed", out)
        self.assertIn("Session review", out)

    def test_focus_blocks_hint(self):
        io = FakeIO(["hint", "quit"], clock=P.FakeClock())
        with self._patch_problem():
            s = P.run_session(problem_id="syn-add", minutes=45, focus=True,
                              think_every_s=0, input_fn=io.input, print_fn=io.print,
                              clock=io.clock, skip_review=True)
        self.assertEqual(s["outcome"], "abandoned")
        self.assertIn("locked", io.text())

    def test_no_focus_allows_hint(self):
        io = FakeIO(["hint", "quit"], clock=P.FakeClock())
        with self._patch_problem():
            s = P.run_session(problem_id="syn-add", minutes=45, focus=False,
                              think_every_s=0, input_fn=io.input, print_fn=io.print,
                              clock=io.clock, skip_review=True)
        self.assertEqual(s["hints_used"], 1)
        self.assertNotIn("locked", io.text())

    def test_timeout_finalizes(self):
        clock = P.FakeClock()

        def advancing_input(prompt=""):
            clock.advance(3600)  # blow the budget on the first prompt
            return "time"

        outputs = []
        with self._patch_problem():
            s = P.run_session(problem_id="syn-add", minutes=45, focus=True,
                              think_every_s=0, input_fn=advancing_input,
                              print_fn=lambda *a: outputs.append(" ".join(map(str, a))),
                              clock=clock, skip_review=True)
        self.assertEqual(s["outcome"], "timed_out")
        self.assertIn("time-pressure", s["tags"])
        self.assertIsNotNone(s["revisit"]["next_due"])
        self.assertTrue(any("TIME'S UP" in o for o in outputs))

    def test_think_aloud_prompt_recorded(self):
        io = FakeIO(["think", "my plan is brute force", "quit"], clock=P.FakeClock())
        with self._patch_problem():
            s = P.run_session(problem_id="syn-add", minutes=45, focus=True,
                              think_every_s=0, input_fn=io.input, print_fn=io.print,
                              clock=io.clock, skip_review=True)
        self.assertEqual(len(s["think_aloud"]), 1)
        self.assertEqual(s["think_aloud"][0]["answer"], "my plan is brute force")

    def test_run_routine_two_steps(self):
        io = FakeIO(["quit", "", "quit"], clock=P.FakeClock())
        with self._patch_problem():
            with umock.patch.object(M, "list_problems",
                                    return_value=[{"id": "syn-add"}]):
                P.save_routine("t-drill", [
                    {"problem": "syn-add", "minutes": 20},
                    {"problem": "syn-add", "minutes": 20},
                ])
                sessions = P.run_routine("t-drill", input_fn=io.input,
                                         print_fn=io.print, clock=io.clock,
                                         skip_review=True)
        self.assertEqual(len(sessions), 2)
        self.assertTrue(all(s["outcome"] == "abandoned" for s in sessions))
        self.assertIn("Routine 't-drill' done", io.text())


if __name__ == "__main__":
    unittest.main()
