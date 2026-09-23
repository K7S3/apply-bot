"""Tests for the PM track: pm prep packs + teardown templates (worker D).

Run from the worktree root:
    CANDID_DATA_DIR=/tmp/candid-test-pm python3 -m unittest discover -s tests
(also honored when set in-process below). No network.
"""
import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType

TMP = tempfile.mkdtemp(prefix="candid-test-pm-")
os.environ["CANDID_DATA_DIR"] = TMP

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import pm_prep  # noqa: E402
from candid import pm_teardown  # noqa: E402


def _fresh_data_dir(test):
    """Point C.DATA_DIR at a fresh per-test tmpdir (robust to import order)."""
    d = Path(tempfile.mkdtemp(prefix="candid-pm-", dir=TMP))
    test._old_data = C.DATA_DIR
    C.DATA_DIR = d
    return d


def _restore_data_dir(test):
    C.DATA_DIR = test._old_data


class BuildPackShapeTest(unittest.TestCase):
    def setUp(self):
        _fresh_data_dir(self)

    def tearDown(self):
        _restore_data_dir(self)

    def test_pack_has_all_keys(self):
        pack = pm_prep.build_pm_prep("Figma", "Growth PM")
        for key in ("company", "role", "generated", "company_pm_questions",
                    "question_source", "metrics_to_know", "teardown_prompt",
                    "star_story_reminders", "day_before_checklist",
                    "saved_path"):
            self.assertIn(key, pack, f"missing key: {key}")

    def test_pack_echoes_company_and_role(self):
        pack = pm_prep.build_pm_prep("Figma", "Growth PM")
        self.assertEqual(pack["company"], "Figma")
        self.assertEqual(pack["role"], "Growth PM")

    def test_fallback_questions_when_bank_missing(self):
        # candid/pm_questions.py is not in this worktree -> lazy import fails.
        pack = pm_prep.build_pm_prep("Acme", "Product Manager")
        self.assertTrue(pack["company_pm_questions"])
        self.assertIn("generic", pack["question_source"].lower())
        for q in pack["company_pm_questions"]:
            self.assertIn("q", q)
            self.assertIn("category", q)

    def test_bank_used_when_present(self):
        fake = ModuleType("candid.pm_questions")

        def list_questions(category=None, company=None):
            return [{"category": "product_sense",
                     "q": f"Improve onboarding at {company}"}]

        fake.list_questions = list_questions
        sys.modules["candid.pm_questions"] = fake
        try:
            pack = pm_prep.build_pm_prep("Figma", "Product Manager")
            self.assertEqual(pack["question_source"],
                             "candid.pm_questions bank")
            self.assertEqual(len(pack["company_pm_questions"]), 1)
            self.assertIn("Figma", pack["company_pm_questions"][0]["q"])
        finally:
            del sys.modules["candid.pm_questions"]

    def test_bank_returning_nothing_falls_back(self):
        fake = ModuleType("candid.pm_questions")
        fake.list_questions = lambda category=None, company=None: []
        sys.modules["candid.pm_questions"] = fake
        try:
            pack = pm_prep.build_pm_prep("Figma", "Product Manager")
            self.assertTrue(pack["company_pm_questions"])
            self.assertIn("generic", pack["question_source"].lower())
        finally:
            del sys.modules["candid.pm_questions"]

    def test_missing_company_raises(self):
        with self.assertRaises(pm_prep.PMPrepError):
            pm_prep.build_pm_prep("", "Growth PM")

    def test_missing_role_raises(self):
        with self.assertRaises(pm_prep.PMPrepError):
            pm_prep.build_pm_prep("Figma", "")

    def test_pack_written_to_data_dir(self):
        pack = pm_prep.build_pm_prep("Figma", "Growth PM")
        path = Path(pack["saved_path"])
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "pm_prep_Figma.md")
        self.assertEqual(path.parent, C.DATA_DIR)
        content = path.read_text(encoding="utf-8")
        self.assertIn("Growth PM", content)
        self.assertIn("Figma", content)


class MetricsMappingTest(unittest.TestCase):
    def setUp(self):
        _fresh_data_dir(self)

    def tearDown(self):
        _restore_data_dir(self)

    def test_growth_pm_metrics(self):
        m = pm_prep.metrics_for_role("Growth PM")
        self.assertTrue(any("Activation" in x for x in m))
        self.assertTrue(any("CAC" in x for x in m))

    def test_monetization_pm_metrics(self):
        m = pm_prep.metrics_for_role("Ads Monetization PM")
        self.assertTrue(any("ARPU" in x for x in m))

    def test_search_pm_metrics(self):
        m = pm_prep.metrics_for_role("Search PM")
        self.assertTrue(any("CTR" in x for x in m))

    def test_marketplace_pm_metrics(self):
        m = pm_prep.metrics_for_role("Marketplace PM")
        self.assertTrue(any("GMV" in x for x in m))

    def test_b2b_pm_metrics(self):
        m = pm_prep.metrics_for_role("B2B SaaS PM")
        self.assertTrue(any("NRR" in x for x in m))

    def test_default_metrics_for_unknown_role(self):
        m = pm_prep.metrics_for_role("Platform PM")
        self.assertTrue(any("north-star" in x.lower() for x in m))

    def test_metrics_not_fabricated_as_company_facts(self):
        pack = pm_prep.build_pm_prep("Figma", "Growth PM")
        self.assertNotIn("Figma's metrics", pack["metrics_to_know"][0])

    def test_teardown_prompt_names_company(self):
        prompt = pm_prep.teardown_prompt("Figma")
        self.assertIn("Figma", prompt)

    def test_star_reminders_and_checklist_nonempty(self):
        pack = pm_prep.build_pm_prep("Figma", "Growth PM")
        self.assertGreaterEqual(len(pack["star_story_reminders"]), 5)
        self.assertGreaterEqual(len(pack["day_before_checklist"]), 5)

    def test_render_contains_sections(self):
        pack = pm_prep.build_pm_prep("Figma", "Growth PM")
        md = pm_prep.render_pm_prep(pack)
        for section in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5."):
            self.assertIn(section, md)


class PrepCLITest(unittest.TestCase):
    def setUp(self):
        _fresh_data_dir(self)

    def tearDown(self):
        _restore_data_dir(self)

    def _parser(self):
        p = argparse.ArgumentParser(prog="candid pm")
        sub = p.add_subparsers(dest="cmd", required=True)
        pm_prep.register_pm(sub)
        return p

    def test_prep_subcommand_registered(self):
        p = self._parser()
        args = p.parse_args(["prep", "--company", "Figma",
                             "--role", "Growth PM"])
        self.assertEqual(args.company, "Figma")
        self.assertTrue(callable(args.func))

    def test_prep_command_runs_and_saves(self):
        p = self._parser()
        args = p.parse_args(["prep", "--company", "Figma",
                             "--role", "Growth PM"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = args.func(args)
        self.assertEqual(rc, 0)
        self.assertIn("Growth PM", buf.getvalue())
        self.assertTrue((C.DATA_DIR / "pm_prep_Figma.md").exists())

    def test_prep_json_output(self):
        p = self._parser()
        args = p.parse_args(["prep", "--company", "Figma",
                             "--role", "Growth PM", "--json"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = args.func(args)
        self.assertEqual(rc, 0)
        pack = json.loads(buf.getvalue())
        self.assertEqual(pack["company"], "Figma")
        self.assertIn("company_pm_questions", pack)


class TeardownTest(unittest.TestCase):
    def setUp(self):
        _fresh_data_dir(self)

    def tearDown(self):
        _restore_data_dir(self)

    def test_new_teardown_creates_file(self):
        path = pm_teardown.new_teardown("Figma", "FigJam")
        self.assertTrue(path.exists())
        self.assertEqual(path.parent, C.DATA_DIR / "teardowns")

    def test_template_has_all_sections(self):
        path = pm_teardown.new_teardown("Figma", "FigJam")
        text = path.read_text(encoding="utf-8")
        for section in ("Product overview", "Target users", "Strengths",
                        "Gaps and pain points", "Opportunities", "RICE",
                        "Interview talking points"):
            self.assertIn(section, text, f"missing section: {section}")

    def test_template_starts_blank(self):
        # The tool must not fabricate product facts: sections are prompts.
        path = pm_teardown.new_teardown("Figma", "FigJam")
        text = path.read_text(encoding="utf-8")
        self.assertIn("TODO", text)
        # No invented facts about FigJam beyond the names we were given.
        self.assertNotIn("vector", text.lower())
        self.assertNotIn("$", text)

    def test_rice_table_present(self):
        path = pm_teardown.new_teardown("Figma", "FigJam")
        text = path.read_text(encoding="utf-8")
        self.assertIn("RICE score = Reach x Impact x Confidence / Effort", text)
        self.assertIn("| Opportunity | Reach (1-10) |", text)

    def test_missing_args_raise(self):
        with self.assertRaises(pm_teardown.TeardownError):
            pm_teardown.new_teardown("", "FigJam")
        with self.assertRaises(pm_teardown.TeardownError):
            pm_teardown.new_teardown("Figma", "")

    def test_list_teardowns_round_trip(self):
        pm_teardown.new_teardown("Figma", "FigJam")
        items = pm_teardown.list_teardowns()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["company"], "Figma")
        self.assertEqual(items[0]["product"], "FigJam")
        self.assertIn("name", items[0])

    def test_show_teardown_round_trip(self):
        path = pm_teardown.new_teardown("Figma", "FigJam")
        content = pm_teardown.show_teardown(path.stem)
        self.assertIn("FigJam", content)

    def test_show_missing_raises(self):
        with self.assertRaises(pm_teardown.TeardownError):
            pm_teardown.show_teardown("nope_does_not_exist")

    def test_list_empty(self):
        self.assertEqual(pm_teardown.list_teardowns(), [])


class TeardownCLITest(unittest.TestCase):
    def setUp(self):
        _fresh_data_dir(self)

    def tearDown(self):
        _restore_data_dir(self)

    def _parser(self):
        p = argparse.ArgumentParser(prog="candid pm")
        sub = p.add_subparsers(dest="cmd", required=True)
        pm_teardown.register_pm(sub)
        return p

    def test_new_action(self):
        p = self._parser()
        args = p.parse_args(["teardown", "new", "--company", "Figma",
                             "--product", "FigJam"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = args.func(args)
        self.assertEqual(rc, 0)
        self.assertIn("Created teardown template", buf.getvalue())

    def test_list_action_empty(self):
        p = self._parser()
        args = p.parse_args(["teardown", "list"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = args.func(args)
        self.assertEqual(rc, 0)
        self.assertIn("No teardowns yet", buf.getvalue())

    def test_list_action_after_new(self):
        p = self._parser()
        args = p.parse_args(["teardown", "new", "--company", "Figma",
                             "--product", "FigJam"])
        args.func(args)
        args = p.parse_args(["teardown", "list"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = args.func(args)
        self.assertEqual(rc, 0)
        self.assertIn("FigJam", buf.getvalue())

    def test_show_action(self):
        p = self._parser()
        args = p.parse_args(["teardown", "new", "--company", "Figma",
                             "--product", "FigJam"])
        args.func(args)
        name = pm_teardown.list_teardowns()[0]["name"]
        args = p.parse_args(["teardown", "show", name])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = args.func(args)
        self.assertEqual(rc, 0)
        self.assertIn("Product Teardown", buf.getvalue())

    def test_show_missing_returns_nonzero(self):
        p = self._parser()
        args = p.parse_args(["teardown", "show", "nope"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = args.func(args)
        self.assertNotEqual(rc, 0)

    def test_new_json(self):
        p = self._parser()
        args = p.parse_args(["teardown", "new", "--company", "Figma",
                             "--product", "FigJam", "--json"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = args.func(args)
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertTrue(Path(out["path"]).exists())


if __name__ == "__main__":
    unittest.main()
