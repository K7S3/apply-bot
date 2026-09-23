"""Tests for candid.sre_guides (sre stories / cheatsheet / quiz / ladder).

Run: CANDID_DATA_DIR=/tmp/candid-test-sre python3 -m pytest tests/test_sre_guides.py -q
No test touches stdin; interactive paths are exercised only through the
non-interactive list paths and the pure grading/saving functions.
"""
import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-sre"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import sre_guides as S  # noqa: E402


def _mini_record(**kw):
    base = dict(
        title="payments outage",
        competencies=["incident-command", "communication"],
        situation="On Black Friday the payments service started returning 500s at 10x normal rate "
                  "while the team was preparing for peak traffic.",
        task="I was the primary on-call and owned getting the service healthy again.",
        action="I declared a sev1, paged the payments team, rolled back the last deploy, "
               "and added a circuit breaker to the checkout path.",
        result="Recovered in 14 minutes with no data loss and wrote the postmortem.",
        metrics="MTTR 14 min, error rate back under 0.1%",
        tags=["on-call"],
    )
    base.update(kw)
    return S.build_story_record(**base)


class TestStoryRecords(unittest.TestCase):
    def test_build_record_schema(self):
        rec = _mini_record()
        for field in S.STORY_SCHEMA_FIELDS:
            self.assertIn(field, rec)
        self.assertEqual(rec["competencies"], ["incident-command", "communication"])
        self.assertEqual(rec["tags"], ["on-call"])
        self.assertTrue(rec["created_at"])

    def test_build_record_filters_unknown_competencies(self):
        rec = _mini_record(competencies=["incident-command", "teleportation"])
        self.assertEqual(rec["competencies"], ["incident-command"])

    def test_validate_good_story(self):
        self.assertEqual(S.validate_story(_mini_record()), [])

    def test_validate_thin_story(self):
        rec = _mini_record(situation="it broke", task="fix it", action="fixed", result="ok")
        problems = S.validate_story(rec)
        self.assertTrue(any("thin" in p for p in problems))
        rec2 = _mini_record(title="")
        self.assertTrue(any("title" in p for p in S.validate_story(rec2)))

    def test_save_and_list_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "stories"
            path = S.save_story(_mini_record(), dest_dir=dest)
            self.assertTrue(path.exists())
            self.assertTrue(path.name.endswith(".json"))
            loaded = json.loads(path.read_text())
            self.assertEqual(loaded["title"], "payments outage")
            listed = S.list_stories(dest_dir=dest)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["metrics"], "MTTR 14 min, error rate back under 0.1%")

    def test_save_dedupes_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            p1 = S.save_story(_mini_record(), dest_dir=dest)
            p2 = S.save_story(_mini_record(), dest_dir=dest)
            self.assertNotEqual(p1, p2)

    def test_list_stories_empty_and_skips_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            self.assertEqual(S.list_stories(dest_dir=dest), [])
            (dest / "junk.json").write_text("not json{{{")
            S.save_story(_mini_record(), dest_dir=dest)
            self.assertEqual(len(S.list_stories(dest_dir=dest)), 1)

    def test_render_story_sections(self):
        text = S.render_story(_mini_record())
        for section in ("Situation", "Task", "Action", "Result", "Metrics"):
            self.assertIn(section, text)
        self.assertIn("incident-command", text)

    def test_cmd_stories_list_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CANDID_DATA_DIR"] = tmp
            try:
                out = io.StringIO()
                args = argparse.Namespace(sre_cmd="stories", tag="on-call", list=True)
                self.assertEqual(S.cmd_stories(args, out=out), 0)
                self.assertIn("No SRE stories", out.getvalue())
                S.save_story(_mini_record())
                out = io.StringIO()
                self.assertEqual(S.cmd_stories(args, out=out), 0)
                self.assertIn("payments outage", out.getvalue())
            finally:
                os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-sre"

    def test_story_prompts_cover_all_competencies(self):
        for comp in S.STORY_COMPETENCIES:
            self.assertIn(comp, S.STORY_PROMPTS)
            self.assertTrue(len(S.STORY_PROMPTS[comp]) >= 2)


class TestCheatsheets(unittest.TestCase):
    def test_all_five_tools_present(self):
        for tool in ["kubectl", "prometheus", "grafana", "linux", "terraform"]:
            self.assertIn(tool, S.list_tools())
            self.assertIn(tool, S.CHEATSHEETS)

    def test_render_cheatsheet_content(self):
        text = S.render_cheatsheet("kubectl")
        self.assertIn("kubectl describe pod", text)
        self.assertIn("kubectl logs", text)
        prom = S.render_cheatsheet("prometheus")
        self.assertIn("histogram_quantile", prom)
        self.assertIn("rate(", prom)
        tf = S.render_cheatsheet("terraform")
        self.assertIn("terraform plan", tf)
        self.assertIn("moved", tf)

    def test_render_cheatsheet_unknown_tool(self):
        with self.assertRaises(ValueError):
            S.render_cheatsheet("ansible")

    def test_cmd_cheatsheet_no_tool_lists(self):
        out = io.StringIO()
        self.assertEqual(S.cmd_cheatsheet(argparse.Namespace(tool=None), out=out), 0)
        self.assertIn("kubectl", out.getvalue())

    def test_cmd_cheatsheet_bad_tool(self):
        out = io.StringIO()
        rc = S.cmd_cheatsheet(argparse.Namespace(tool="ansible"), out=out)
        self.assertEqual(rc, 2)


class TestQuiz(unittest.TestCase):
    def test_five_questions_per_tool(self):
        for tool in S.list_tools():
            self.assertEqual(len(S.QUIZ_BANK[tool]), 5, tool)

    def test_grade_all_correct(self):
        for tool in S.list_tools():
            answers = [q["answer"] for q in S.QUIZ_BANK[tool]]
            res = S.grade_quiz(tool, answers)
            self.assertEqual(res["score"], 5, tool)
            self.assertEqual(res["total"], 5)

    def test_grade_all_wrong_and_empty(self):
        res = S.grade_quiz("kubectl", ["wrong"] * 5)
        self.assertEqual(res["score"], 0)
        res = S.grade_quiz("kubectl", [])
        self.assertEqual(res["score"], 0)
        self.assertEqual(len(res["details"]), 5)

    def test_grade_accepts_option_numbers_and_case(self):
        item = S.QUIZ_BANK["kubectl"][0]
        idx = item["options"].index(item["answer"]) + 1
        res = S.grade_quiz("kubectl", [str(idx)] + ["x"] * 4)
        self.assertTrue(res["details"][0]["correct"])
        res = S.grade_quiz("kubectl", [item["answer"].upper()] + ["x"] * 4)
        self.assertTrue(res["details"][0]["correct"])

    def test_grade_unknown_tool(self):
        with self.assertRaises(ValueError):
            S.grade_quiz("ansible", [])

    def test_cmd_quiz_no_tool_lists(self):
        out = io.StringIO()
        self.assertEqual(S.cmd_quiz(argparse.Namespace(tool=None), out=out), 0)
        self.assertIn("kubectl", out.getvalue())

    def test_each_question_has_why(self):
        for tool, bank in S.QUIZ_BANK.items():
            for q in bank:
                self.assertIn(q["answer"], q["options"], f"{tool}: answer must be an option")
                self.assertTrue(q["why"], f"{tool}: missing explanation")


class TestLadder(unittest.TestCase):
    def test_four_levels(self):
        self.assertEqual(S.LADDER_LEVELS, ["L3", "L4", "L5", "L6"])

    def test_render_all_levels(self):
        text = S.render_ladder()
        for lvl in ["L3", "L4", "L5", "L6"]:
            self.assertIn(lvl, text)
        self.assertIn("General guidance", text)
        for section in ("Scope", "Technical bar", "Leadership", "On call",
                        "Promotion to next", "Interview probes"):
            self.assertIn(section, text)

    def test_render_single_level(self):
        text = S.render_ladder("L5")
        self.assertIn("L5", text)
        self.assertNotIn("## L3", text)
        self.assertIn("error-budget", text)

    def test_render_unknown_level(self):
        with self.assertRaises(ValueError):
            S.render_ladder("L9")

    def test_cmd_ladder(self):
        out = io.StringIO()
        self.assertEqual(S.cmd_ladder(argparse.Namespace(level="L4"), out=out), 0)
        self.assertIn("L4", out.getvalue())
        out = io.StringIO()
        self.assertEqual(S.cmd_ladder(argparse.Namespace(level="L9"), out=out), 2)


class TestRegisterDispatch(unittest.TestCase):
    def _parser(self):
        parser = argparse.ArgumentParser(prog="candid sre")
        sub = parser.add_subparsers(dest="sre_cmd", required=True)
        S.register(sub)
        return parser

    def test_register_adds_four_subcommands(self):
        parser = self._parser()
        for name in ["stories", "cheatsheet", "quiz", "ladder"]:
            args = parser.parse_args([name] + ([] if name == "stories" else []))
            self.assertEqual(args.sre_cmd, name)
            self.assertIs(args.func, S.dispatch)

    def test_register_subcommand_options(self):
        parser = self._parser()
        args = parser.parse_args(["cheatsheet", "kubectl"])
        self.assertEqual(args.tool, "kubectl")
        args = parser.parse_args(["quiz", "--tool", "prometheus"])
        self.assertEqual(args.tool, "prometheus")
        args = parser.parse_args(["ladder", "--level", "L6"])
        self.assertEqual(args.level, "L6")
        args = parser.parse_args(["stories", "--tag", "war-room"])
        self.assertEqual(args.tag, "war-room")
        args = parser.parse_args(["stories", "--list"])
        self.assertTrue(args.list)

    def test_dispatch_cheatsheet_and_ladder_end_to_end(self):
        parser = self._parser()
        args = parser.parse_args(["cheatsheet", "terraform"])
        self.assertEqual(S.dispatch(args), 0)
        args = parser.parse_args(["ladder", "--level", "L3"])
        self.assertEqual(S.dispatch(args), 0)

    def test_dispatch_unknown(self):
        out = io.StringIO()
        old = sys.stdout
        sys.stdout = out
        try:
            rc = S.dispatch(argparse.Namespace(sre_cmd="bogus"))
        finally:
            sys.stdout = old
        self.assertEqual(rc, 2)

    def test_no_em_dashes_in_user_facing_text(self):
        texts = [S.render_ladder(), S.render_cheatsheet("kubectl"),
                 S.render_cheatsheet("prometheus"), S.render_story(_mini_record())]
        texts += [S.render_cheatsheet(t) for t in S.list_tools()]
        for q in (qq for bank in S.QUIZ_BANK.values() for qq in bank):
            texts.append(q["q"] + q["answer"] + q["why"])
        for t in texts:
            self.assertNotIn("\u2014", t, "em dash found in user-facing text")


if __name__ == "__main__":
    unittest.main()
