"""Tests for the SRE drills + war-room simulator (candid.sre_drills).

All tests run non-interactively (--auto / scripted mode); nothing here
blocks on stdin.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TEST_DIR = Path(tempfile.mkdtemp(prefix="candid-test-sre-"))
os.environ["CANDID_DATA_DIR"] = str(TEST_DIR)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import sre_drills as S  # noqa: E402


def _best_answers(name):
    sc = S.get_scenario(name)
    return [S.best_choice_index(s) + 1 for s in sc["steps"]]


class ScenarioDataTest(unittest.TestCase):
    def test_four_scenarios_present(self):
        self.assertEqual(
            S.list_scenarios(),
            ["latency-spike", "disk-full-cascade", "bad-deploy", "dns-outage"],
        )

    def test_unknown_scenario_raises(self):
        with self.assertRaises(S.SreDrillsError):
            S.get_scenario("meteor-strike")

    def test_unknown_warroom_raises(self):
        with self.assertRaises(S.SreDrillsError):
            S.get_warroom("meteor-strike")

    def test_tree_shape(self):
        for name in S.list_scenarios():
            sc = S.get_scenario(name)
            self.assertGreaterEqual(len(sc["steps"]), 3, name)
            ids = {s["id"] for s in sc["steps"]}
            for s in sc["steps"]:
                self.assertIn("situation", s)
                self.assertGreaterEqual(len(s["choices"]), 3)
                for c in s["choices"]:
                    self.assertIn("text", c)
                    self.assertIn("points", c)
                    self.assertIn("explain", c)
                    self.assertIn("next", c)
                    if c["next"] is not None:
                        self.assertIn(c["next"], ids, f"{name}: dangling next")

    def test_every_step_has_best_choice(self):
        for name in S.list_scenarios():
            for s in S.get_scenario(name)["steps"]:
                best = max(c["points"] for c in s["choices"])
                self.assertEqual(best, 100, f"{name}/{s['id']}")

    def test_terminal_choices_end_drill(self):
        for name in S.list_scenarios():
            sc = S.get_scenario(name)
            last = sc["steps"][-1]
            self.assertTrue(all(c["next"] is None for c in last["choices"]),
                            name)

    def test_no_em_dashes_in_user_text(self):
        blobs = []
        for sc in S.SCENARIOS.values():
            blobs += [sc["title"], sc["intro"]]
            for s in sc["steps"]:
                blobs.append(s["situation"])
                for c in s["choices"]:
                    blobs += [c["text"], c["explain"]]
        for w in S.WARROOMS.values():
            blobs += [w["title"], w["brief"], w["resolution"]]
            for b in w["beats"]:
                blobs += [b["say"], b["hint"], b["good"]]
        for b in blobs:
            self.assertNotIn("\u2014", b)

    def test_warroom_beats_have_expect_and_good(self):
        for name in S.list_warroom_scenarios():
            beats = S.get_warroom(name)["beats"]
            self.assertGreaterEqual(len(beats), 3, name)
            for b in beats:
                self.assertTrue(b["expect"])
                self.assertTrue(b["good"])
                self.assertTrue(b["hint"])


class GradeTest(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(S.grade(95), "A")
        self.assertEqual(S.grade(90), "A")
        self.assertEqual(S.grade(89.9), "B")
        self.assertEqual(S.grade(75), "B")
        self.assertEqual(S.grade(60), "C")
        self.assertEqual(S.grade(40), "D")
        self.assertEqual(S.grade(39.9), "F")
        self.assertEqual(S.grade(0), "F")


class DrillEngineTest(unittest.TestCase):
    def test_perfect_run(self):
        r = S.run_drill_scripted("latency-spike", _best_answers("latency-spike"))
        self.assertEqual(r["pct"], 100.0)
        self.assertEqual(r["grade"], "A")
        self.assertEqual(r["score"], r["max_score"])
        self.assertEqual(len(r["steps"]), 4)
        self.assertFalse(r["gaps"])
        self.assertTrue(r["strengths"])

    def test_terrible_run(self):
        r = S.run_drill_scripted("bad-deploy", [3, 3, 2, 4])
        self.assertLess(r["pct"], 40)
        self.assertEqual(r["grade"], "F")
        self.assertTrue(r["gaps"])

    def test_partial_credit_mid_answers(self):
        r = S.run_drill_scripted("dns-outage", [1, 2, 2, 1])
        self.assertGreater(r["pct"], 0)
        self.assertLess(r["pct"], 100)
        self.assertTrue(r["gaps"])
        self.assertTrue(r["strengths"])

    def test_timeout_sentinel(self):
        r = S.run_drill_scripted("latency-spike", [1, 0, 1, 1])
        self.assertEqual(r["timed_out_steps"], 1)
        self.assertEqual(len(r["steps"]), 4)
        self.assertLess(r["pct"], 100.0)

    def test_invalid_answers_clamp_to_first_choice(self):
        r = S.run_drill_scripted("latency-spike", [99, -5, 1, 1])
        self.assertEqual(len(r["steps"]), 4)
        self.assertEqual(r["steps"][0]["points"], 100)  # clamped to choice 1

    def test_short_answer_list_defaults_to_first_choice(self):
        r = S.run_drill_scripted("latency-spike", [1])
        self.assertEqual(len(r["steps"]), 4)

    def test_result_has_debrief_fields(self):
        r = S.run_drill_scripted("disk-full-cascade",
                                 _best_answers("disk-full-cascade"))
        for k in ("kind", "scenario", "title", "finished_at", "steps",
                  "score", "max_score", "pct", "grade",
                  "timed_out_steps", "strengths", "gaps"):
            self.assertIn(k, r)
        self.assertEqual(r["kind"], "drill")

    def test_save_result_writes_json(self):
        r = S.run_drill_scripted("dns-outage", _best_answers("dns-outage"))
        path = S.save_result(r)
        self.assertTrue(path.exists())
        self.assertEqual(path.parent.name, "sre_drills")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["pct"], 100.0)
        self.assertEqual(loaded["scenario"], "dns-outage")


class WarroomEngineTest(unittest.TestCase):
    def test_score_reply_full_and_empty(self):
        s = S.score_reply("check the dns nameservers with dig", ["dns", "dig"])
        self.assertEqual(s["pct"], 100.0)
        s = S.score_reply("hello world", ["dns", "dig"])
        self.assertEqual(s["pct"], 0.0)
        self.assertEqual(s["missed"], ["dns", "dig"])

    def test_score_reply_partial(self):
        s = S.score_reply("dns looks fine", ["dns", "dig", "ttl"])
        self.assertAlmostEqual(s["pct"], 33.3, places=1)

    def test_model_replies_score_A(self):
        for name in S.list_warroom_scenarios():
            beats = S.get_warroom(name)["beats"]
            r = S.run_warroom_scripted(name, [b["good"] for b in beats])
            self.assertEqual(r["score_pct"], 100.0, name)
            self.assertEqual(r["grade"], "A", name)

    def test_empty_replies_score_zero(self):
        r = S.run_warroom_scripted("bad-deploy", [])
        self.assertEqual(r["score_pct"], 0.0)
        self.assertEqual(r["grade"], "F")
        self.assertTrue(all(t["hint"] for t in r["transcript"]))

    def test_transcript_shape(self):
        r = S.run_warroom_scripted("dns-outage", ["dns dig nameserver"])
        self.assertEqual(r["kind"], "warroom")
        self.assertIn("resolution", r)
        t = r["transcript"][0]
        for k in ("from", "said", "you_replied", "score_pct",
                  "hits", "missed", "hint", "model_reply"):
            self.assertIn(k, t)

    def test_save_transcript(self):
        r = S.run_warroom_scripted("bad-deploy", ["rollback now"])
        path = S.save_result(r)
        self.assertTrue(path.exists())
        self.assertIn("warroom-bad-deploy", path.name)

    def test_ai_commander_falls_back_when_unavailable(self):
        with mock.patch.object(S, "_gemini_chat",
                               side_effect=S.SreDrillsError("no network")):
            self.assertIsNone(S.ai_commander_line(["hello"]))


class CLITest(unittest.TestCase):
    def _parser(self):
        p = argparse.ArgumentParser(prog="candid sre")
        sub = p.add_subparsers(dest="sre_cmd", required=True)
        S.register(sub)
        return p

    def test_register_adds_both_subcommands(self):
        p = self._parser()
        for cmd in ("drill", "warroom"):
            a = p.parse_args([cmd])
            self.assertEqual(a.sre_cmd, cmd)
            self.assertIs(a.func, S.dispatch)

    def test_drill_args(self):
        a = self._parser().parse_args(
            ["drill", "--scenario", "dns-outage", "--no-timer", "--auto",
             "--answers", "1,2,3"])
        self.assertEqual(a.scenario, "dns-outage")
        self.assertTrue(a.no_timer)
        self.assertTrue(a.auto)
        self.assertEqual(a.answers, "1,2,3")

    def test_warroom_args(self):
        a = self._parser().parse_args(
            ["warroom", "--scenario", "bad-deploy", "--auto"])
        self.assertEqual(a.scenario, "bad-deploy")
        self.assertTrue(a.auto)

    def test_dispatch_unknown_raises(self):
        with self.assertRaises(S.SreDrillsError):
            S.dispatch(argparse.Namespace(sre_cmd="nope"))

    def test_cmd_drill_list(self):
        a = self._parser().parse_args(["drill", "--list"])
        self.assertEqual(S.cmd_drill(a), 0)

    def test_cmd_drill_auto_best(self):
        a = self._parser().parse_args(["drill", "--auto"])
        self.assertEqual(S.cmd_drill(a), 0)
        files = list((S._drills_dir()).glob("drill-latency-spike-*.json"))
        self.assertTrue(files)
        r = json.loads(files[-1].read_text(encoding="utf-8"))
        self.assertEqual(r["pct"], 100.0)

    def test_cmd_drill_auto_with_answers(self):
        a = self._parser().parse_args(
            ["drill", "--scenario", "disk-full-cascade", "--auto",
             "--answers", "2,3,4"])
        self.assertEqual(S.cmd_drill(a), 0)

    def test_cmd_drill_unknown_scenario(self):
        with self.assertRaises(S.SreDrillsError):
            S.cmd_drill(argparse.Namespace(scenario="nope", list=False,
                                           no_timer=True, auto=True,
                                           answers=""))

    def test_cmd_warroom_auto(self):
        a = self._parser().parse_args(["warroom", "--auto"])
        self.assertEqual(S.cmd_warroom(a), 0)
        files = list((S._drills_dir()).glob("warroom-latency-spike-*.json"))
        self.assertTrue(files)

    def test_cmd_warroom_auto_with_replies(self):
        a = self._parser().parse_args(
            ["warroom", "--scenario", "dns-outage", "--auto",
             "--replies", "dns dig|||fail over|||verify zone"])
        self.assertEqual(S.cmd_warroom(a), 0)

    def test_dispatch_routes(self):
        d = self._parser().parse_args(["drill", "--list"])
        self.assertEqual(S.dispatch(d), 0)
        w = self._parser().parse_args(["warroom", "--auto"])
        self.assertEqual(S.dispatch(w), 0)


def tearDownModule():
    shutil.rmtree(TEST_DIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
