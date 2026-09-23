"""Tests for the SRE question bank + deep-dives (candid.sre_questions).

Run: CANDID_DATA_DIR=/tmp/candid-test-sre python3 -m pytest tests/test_sre_questions.py -q
"""
import argparse
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-sre")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import sre_questions as S  # noqa: E402


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="candid")
    sp = p.add_subparsers(dest="sre_cmd")
    S.register(sp)
    return p


class QuestionBankTest(unittest.TestCase):
    def test_data_file_is_valid_json_with_expected_shape(self):
        data = json.loads(S.DATA_PATH.read_text(encoding="utf-8"))
        self.assertIn("categories", data)
        self.assertEqual(set(data["categories"].keys()), set(S.CATEGORIES))

    def test_every_category_has_verified_questions(self):
        for cat in S.CATEGORIES:
            qs = S.get_questions(cat)
            self.assertGreater(len(qs), 0, f"category {cat} is empty")

    def test_every_question_has_source_label(self):
        for q in S.get_questions():
            self.assertTrue(q.get("q"), "question text missing")
            self.assertTrue(q.get("source"), f"no source label: {q['q'][:40]}")
            self.assertIn(q.get("difficulty"), {"easy", "medium", "hard"})

    def test_no_em_dashes_in_bank(self):
        data = json.loads(S.DATA_PATH.read_text(encoding="utf-8"))
        blob = json.dumps(data)
        self.assertNotIn("\u2014", blob)
        self.assertNotIn("\u2013", blob)

    def test_list_categories_matches_json(self):
        self.assertEqual(S.list_categories(), S.CATEGORIES)

    def test_get_questions_unknown_category_raises(self):
        with self.assertRaises(ValueError):
            S.get_questions("blockchain")

    def test_get_questions_all_returns_everything(self):
        total = sum(len(S.get_questions(c)) for c in S.CATEGORIES)
        self.assertEqual(len(S.get_questions()), total)

    def test_questions_output_renders_and_exit_codes(self):
        code, text = S.questions_output(category="linux")
        self.assertEqual(code, 0)
        self.assertIn("linux", text)
        self.assertIn("Source:", text)

        code, text = S.questions_output(list_categories_flag=True)
        self.assertEqual(code, 0)
        for c in S.CATEGORIES:
            self.assertIn(c, text)

        code, text = S.questions_output(category="bogus")
        self.assertEqual(code, 2)
        self.assertIn("bogus", text)


class DeepdiveTest(unittest.TestCase):
    def test_all_topics_have_markdown(self):
        self.assertEqual(S.list_topics(), S.TOPICS)
        for t in S.TOPICS:
            md = S.get_deepdive(t)
            self.assertTrue(md.startswith("#"))
            self.assertGreater(len(md), 500, t)

    def test_topic_titles_exist(self):
        for t in S.TOPICS:
            self.assertTrue(S.topic_title(t))

    def test_unknown_topic_raises(self):
        with self.assertRaises(ValueError):
            S.get_deepdive("quantum")
        with self.assertRaises(ValueError):
            S.topic_title("quantum")

    def test_no_em_dashes_in_deepdives(self):
        for t in S.TOPICS:
            md = S.get_deepdive(t)
            self.assertNotIn("\u2014", md, t)
            self.assertNotIn("\u2013", md, t)

    def test_deepdive_content_is_technically_grounded(self):
        # Spot checks on well-known facts, not citations.
        slos = S.get_deepdive("slos")
        self.assertIn("99.9%", slos)
        self.assertIn("43m", slos)
        eb = S.get_deepdive("error-budgets")
        self.assertIn("burn", eb.lower())
        cb = S.get_deepdive("circuit-breakers")
        self.assertIn("half-open", cb.lower())
        im = S.get_deepdive("incident-management")
        self.assertIn("blameless", im.lower())

    def test_deepdive_output_exit_codes(self):
        code, text = S.deepdive_output("slos")
        self.assertEqual(code, 0)
        self.assertIn("#", text)
        code, text = S.deepdive_output("nope")
        self.assertEqual(code, 2)

    def test_save_deepdive_writes_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path = S.save_deepdive("slos", base_dir=Path(td))
            self.assertEqual(path, Path(td) / "slos.md")
            self.assertTrue(path.exists())
            self.assertIn("#", path.read_text(encoding="utf-8"))

    def test_save_respects_data_dir_override(self):
        import tempfile
        from candid import config
        with tempfile.TemporaryDirectory() as td:
            orig = config.DATA_DIR
            config.DATA_DIR = Path(td)
            try:
                path = S.save_deepdive("chaos-engineering")
                self.assertEqual(path.parent, Path(td) / "sre")
                self.assertTrue(path.exists())
            finally:
                config.DATA_DIR = orig

    def test_deepdive_output_save_flag(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            code, text = S.deepdive_output("redundancy", save=True, base_dir=Path(td))
            self.assertEqual(code, 0)
            self.assertTrue((Path(td) / "redundancy.md").exists())
            self.assertIn("Saved to", text)


class CLITest(unittest.TestCase):
    def test_register_adds_both_subcommands(self):
        p = make_parser()
        for cmd in ("questions", "deepdive"):
            args = p.parse_args([cmd] if cmd == "questions" else [cmd, "slos"])
            self.assertTrue(callable(args.func))
            self.assertEqual(args.sre_cmd, cmd)

    def test_dispatch_questions_list_categories(self):
        p = make_parser()
        args = p.parse_args(["questions", "--list-categories"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = S.dispatch(args)
        self.assertEqual(rc, 0)
        self.assertIn("kubernetes", buf.getvalue())

    def test_dispatch_questions_category(self):
        p = make_parser()
        args = p.parse_args(["questions", "--category", "observability"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = S.dispatch(args)
        self.assertEqual(rc, 0)
        self.assertIn("Source:", buf.getvalue())

    def test_dispatch_deepdive(self):
        p = make_parser()
        args = p.parse_args(["deepdive", "backpressure"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = S.dispatch(args)
        self.assertEqual(rc, 0)
        self.assertIn("Backpressure", buf.getvalue())

    def test_dispatch_deepdive_save(self):
        import tempfile
        from candid import config
        p = make_parser()
        args = p.parse_args(["deepdive", "circuit-breakers", "--save"])
        with tempfile.TemporaryDirectory() as td:
            orig = config.DATA_DIR
            config.DATA_DIR = Path(td)
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = S.dispatch(args)
            finally:
                config.DATA_DIR = orig
            self.assertEqual(rc, 0)
            self.assertTrue((Path(td) / "sre" / "circuit-breakers.md").exists())

    def test_dispatch_unknown_command_returns_2(self):
        args = argparse.Namespace(sre_cmd="bogus")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = S.dispatch(args)
        self.assertEqual(rc, 2)

    def test_module_docstring_and_future_import(self):
        src = Path(S.__file__).read_text(encoding="utf-8")
        self.assertIn("from __future__ import annotations", src)
        self.assertTrue(S.__doc__ and len(S.__doc__) > 50)


if __name__ == "__main__":
    unittest.main()
