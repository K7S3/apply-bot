"""Tests for panel interview prep (batch 41).

Run: CANDID_DATA_DIR=/tmp/candid-test-panel python -m unittest discover -s tests
(also honored when set in-process below).
"""
import io
import os
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

os.environ.setdefault("CANDID_DATA_DIR", "/tmp/candid-test-panel")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DIR = Path("/tmp/candid-test-panel")

_pin_old = None

def _pin_env():
    """Pin CANDID_DATA_DIR per-test so suite import order can't pollute us."""
    global _pin_old
    _pin_old = os.environ.get("CANDID_DATA_DIR")
    os.environ["CANDID_DATA_DIR"] = str(TEST_DIR)
    _clean()


def _unpin_env():
    global _pin_old
    if _pin_old is None:
        os.environ.pop("CANDID_DATA_DIR", None)
    else:
        os.environ["CANDID_DATA_DIR"] = _pin_old
    _pin_old = None


ROUNDS = "Priya Nair:hiring_manager:45,Sam Rao:data_scientist:60,Jo:bar_raiser:45"


def _clean():
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR, ignore_errors=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


class PanelCrudTest(unittest.TestCase):
    def setUp(self):
        _pin_env()
        from candid import panel as P
        self.P = P

    def tearDown(self):
        _unpin_env()

    def test_create_list_get_remove(self):
        p = self.P.create_panel("Acme", "Data Scientist", ROUNDS)
        self.assertEqual(p["id"], "P1")
        self.assertEqual(len(p["rounds"]), 3)
        self.assertEqual(p["rounds"][0]["name"], "Priya Nair")
        self.assertEqual(p["rounds"][0]["archetype"], "hiring_manager")
        self.assertEqual(p["rounds"][0]["duration_min"], 45)
        self.assertEqual(p["rounds"][1]["duration_min"], 60)
        panels = self.P.list_panels()
        self.assertEqual(len(panels), 1)
        got = self.P.get_panel("p1")  # case-insensitive
        self.assertEqual(got["company"], "Acme")
        self.P.remove_panel("P1")
        self.assertEqual(self.P.list_panels(), [])

    def test_ids_increment(self):
        a = self.P.create_panel("A", "R", "X:engineer:30")
        b = self.P.create_panel("B", "R", "Y:engineer:30")
        self.assertEqual((a["id"], b["id"]), ("P1", "P2"))

    def test_unknown_panel_raises(self):
        with self.assertRaises(self.P.PanelError):
            self.P.get_panel("P99")
        with self.assertRaises(self.P.PanelError):
            self.P.remove_panel("P99")

    def test_bad_round_specs_raise(self):
        with self.assertRaises(self.P.PanelError):
            self.P.create_panel("A", "R", "NoColonHere")
        with self.assertRaises(self.P.PanelError):
            self.P.create_panel("A", "R", "X:not_a_role:30")
        with self.assertRaises(self.P.PanelError):
            self.P.create_panel("A", "R", "X:engineer:notanumber")
        with self.assertRaises(self.P.PanelError):
            self.P.create_panel("A", "R", "X:engineer:0")
        with self.assertRaises(self.P.PanelError):
            self.P.create_panel("", "R", "X:engineer:30")
        with self.assertRaises(self.P.PanelError):
            self.P.create_panel("A", "", "X:engineer:30")

    def test_default_minutes(self):
        p = self.P.create_panel("A", "R", "X:engineer")
        self.assertEqual(p["rounds"][0]["duration_min"], 45)

    def test_add_round(self):
        p = self.P.create_panel("A", "R", "X:engineer:30")
        p = self.P.add_round("P1", "Dana", "bar_raiser", minutes=45,
                             title="Director")
        self.assertEqual(len(p["rounds"]), 2)
        self.assertEqual(p["rounds"][1]["title"], "Director")
        with self.assertRaises(self.P.PanelError):
            self.P.add_round("P1", "Zed", "nope")
        with self.assertRaises(self.P.PanelError):
            self.P.add_round("P99", "Zed", "engineer")

    def test_render_helpers(self):
        p = self.P.create_panel("Acme", "Data Scientist", ROUNDS)
        table = self.P.render_panels(self.P.list_panels())
        self.assertIn("P1", table)
        self.assertIn("Acme", table)
        self.assertIn("No panels yet", self.P.render_panels([]))
        detail = self.P.render_panel_detail(p)
        self.assertIn("Priya Nair", detail)
        self.assertIn("Hiring manager", detail)


class ArchetypeCatalogTest(unittest.TestCase):
    def test_catalog_shape(self):
        from candid import panel as P
        required = {"label", "description", "evaluates", "styles",
                    "categories", "sample_questions", "watch_for",
                    "ask_them", "prep_tips"}
        self.assertGreaterEqual(len(P.ARCHETYPES), 10)
        for key, arch in P.ARCHETYPES.items():
            self.assertTrue(required <= set(arch), f"{key} missing keys")
            for k in ("evaluates", "sample_questions", "ask_them", "prep_tips"):
                self.assertTrue(arch[k], f"{key}.{k} empty")

    def test_categories_known(self):
        from candid import panel as P
        from candid.prep_questions import GENERIC_BANKS
        known = set()
        for bank in GENERIC_BANKS.values():
            known.update(q.get("category") for q in bank)
        for key, arch in P.ARCHETYPES.items():
            for cat in arch["categories"]:
                self.assertIn(cat, known, f"{key} unknown category {cat}")

    def test_default_loop_order_valid(self):
        from candid import panel as P
        for key in P.DEFAULT_LOOP_ORDER:
            self.assertIn(key, P.ARCHETYPES)


class BriefTest(unittest.TestCase):
    def setUp(self):
        _pin_env()
        from candid import panel as P
        self.P = P
        self.panel = P.create_panel("Acme", "Data Scientist", ROUNDS)

    def tearDown(self):
        _unpin_env()

    def test_brief_covers_every_interviewer(self):
        md = self.P.brief_panel(self.panel)
        for name in ("Priya Nair", "Sam Rao", "Jo"):
            self.assertIn(name, md)
        self.assertIn("Hiring manager", md)
        self.assertIn("What they're evaluating", md)
        self.assertIn("Red flags", md)

    def test_brief_marks_briefed(self):
        self.assertFalse(self.panel["activity"]["briefed"])
        self.P.brief_panel(self.panel)
        self.assertTrue(self.P.get_panel("P1")["activity"]["briefed"])

    def test_brief_shows_background_when_set(self):
        self.P.set_background(self.panel, 1, "Eng manager, ex-Stripe")
        md = self.P.brief_panel(self.P.get_panel("P1"), mark_briefed=False)
        self.assertIn("ex-Stripe", md)

    def test_export_writes_markdown(self):
        path = self.P.export_brief(self.panel)
        self.assertTrue(path.exists())
        self.assertIn("P1", path.name)
        self.assertTrue(path.suffix == ".md")
        text = path.read_text(encoding="utf-8")
        self.assertIn("Panel Brief", text)
        self.assertIn("Priya Nair", text)


class QuestionsAskTest(unittest.TestCase):
    def setUp(self):
        _pin_env()
        from candid import panel as P
        self.P = P
        self.panel = P.create_panel("Acme", "Data Scientist", ROUNDS)

    def tearDown(self):
        _unpin_env()

    def test_questions_labeled(self):
        rnd = self.panel["rounds"][1]  # data_scientist
        qs = self.P.questions_for_round(rnd)
        sources = {q["source"] for q in qs}
        self.assertIn("archetype expectation", sources)
        self.assertIn("general bank", sources)
        # bank-mapped categories come from the archetype's categories
        bank_cats = {q["category"] for q in qs if q["source"] == "general bank"}
        self.assertTrue(bank_cats <= set(self.P.ARCHETYPES["data_scientist"]["categories"]))

    def test_render_questions_all_and_one(self):
        md = self.P.render_questions(self.panel)
        for name in ("Priya Nair", "Sam Rao", "Jo"):
            self.assertIn(name, md)
        one = self.P.render_questions(self.panel, round_no=2)
        self.assertIn("Sam Rao", one)
        self.assertNotIn("Priya Nair", one)
        with self.assertRaises(self.P.PanelError):
            self.P.render_questions(self.panel, round_no=9)

    def test_ask_them(self):
        md = self.P.render_ask(self.panel)
        self.assertIn("Questions to ask your interviewers", md)
        # hiring-manager-specific question present
        self.assertIn("first 6 months", md)


class PlanTest(unittest.TestCase):
    def setUp(self):
        _pin_env()
        from candid import panel as P
        self.P = P
        self.panel = P.create_panel("Acme", "Data Scientist", ROUNDS)

    def tearDown(self):
        _unpin_env()

    def test_timeline_order_and_breaks(self):
        rows = self.P.plan_panel(self.panel, start="10:00", break_min=15)
        kinds = [r["kind"] for r in rows]
        self.assertEqual(kinds[0], "prep")
        self.assertEqual(kinds.count("round"), 3)
        self.assertEqual(kinds.count("break"), 2)
        self.assertEqual(rows[1]["start"], "10:20")
        self.assertEqual(rows[1]["end"], "11:05")  # 45-min round 1
        # monotonic
        times = [r["start"] for r in rows]
        self.assertEqual(times, sorted(times))

    def test_no_breaks(self):
        rows = self.P.plan_panel(self.panel, break_min=0)
        self.assertNotIn("break", [r["kind"] for r in rows])

    def test_bad_start_raises(self):
        with self.assertRaises(self.P.PanelError):
            self.P.plan_panel(self.panel, start="nope")

    def test_render_plan_totals(self):
        md = self.P.render_plan(self.panel)
        self.assertIn("Total interview time: 150 min", md)


class MockTest(unittest.TestCase):
    def setUp(self):
        _pin_env()
        from candid import panel as P
        self.P = P
        self.panel = P.create_panel("Acme", "Data Scientist", ROUNDS)

    def tearDown(self):
        _unpin_env()

    def test_mock_deterministic_rotation(self):
        s1 = self.P.mock_round(self.panel, 2)
        s2 = self.P.mock_round(self.P.get_panel("P1"), 2)
        self.assertNotEqual(s1["question"], s2["question"])
        self.assertEqual(s1["interviewer"], "Sam Rao")
        self.assertIn("rubric", s1)
        self.assertEqual(len(s1["rubric"]), len(self.P.MOCK_RUBRIC))

    def test_mock_uses_profile_bullets(self):
        profile = {"experience": [
            {"title": "DS", "company": "X",
             "bullets": ["Cut churn 12% with a survival model."]}]}
        s = self.P.mock_round(self.P.get_panel("P1"), 1, profile=profile)
        self.assertIn("Cut churn 12%", s["talking_points"])

    def test_mock_without_profile(self):
        s = self.P.mock_round(self.P.get_panel("P1"), 1, profile=None)
        self.assertIn("onboard", s["talking_points"])

    def test_score_mock(self):
        self.P.mock_round(self.panel, 2)
        latest = self.P.score_mock(self.P.get_panel("P1"), 2, [4, 3, 5, 4])
        self.assertEqual(latest["total"], 16)
        with self.assertRaises(self.P.PanelError):
            self.P.score_mock(self.P.get_panel("P1"), 2, [5, 5])
        with self.assertRaises(self.P.PanelError):
            self.P.score_mock(self.P.get_panel("P1"), 2, [6, 1, 1, 1])

    def test_score_without_session_raises(self):
        with self.assertRaises(self.P.PanelError):
            self.P.score_mock(self.panel, 3, [3, 3, 3, 3])

    def test_render_mock(self):
        s = self.P.mock_round(self.panel, 1)
        rnd = self.panel["rounds"][0]
        md = self.P.render_mock(s, rnd)
        self.assertIn("Priya Nair", md)
        self.assertIn("self-score", md)


class ResearchTest(unittest.TestCase):
    def setUp(self):
        _pin_env()
        from candid import panel as P
        self.P = P
        self.panel = P.create_panel("Acme", "Data Scientist", ROUNDS)

    def tearDown(self):
        _unpin_env()

    def test_set_background(self):
        p = self.P.set_background(self.panel, 2, "Staff DS, 6 yrs at Acme")
        rnd = p["rounds"][1]
        self.assertEqual(rnd["background"], "Staff DS, 6 yrs at Acme")
        self.assertIn(2, p["activity"]["researched_rounds"])
        with self.assertRaises(self.P.PanelError):
            self.P.set_background(self.P.get_panel("P1"), 2, "  ")

    def test_checklist_export_only(self):
        items = self.P.research_checklist_for_round(self.panel["rounds"][0])
        self.assertTrue(any("LinkedIn" in i for i in items))
        md = self.P.render_research(self.panel, round_no=1)
        self.assertIn("never scrapes", md)


class ConsistencyTest(unittest.TestCase):
    def setUp(self):
        _pin_env()
        from candid import panel as P
        self.P = P
        self.panel = P.create_panel("Acme", "Data Scientist", ROUNDS)

    def tearDown(self):
        _unpin_env()

    def test_flags_conflicting_numbers(self):
        self.P.log_note(self.panel, 1, "said 40% latency cut on ranking")
        self.P.log_note(self.P.get_panel("P1"), 2, "said 50% latency cut on ranking")
        flags = self.P.consistency_check(self.P.get_panel("P1"))
        self.assertEqual(len(flags), 1)
        self.assertIn("40%", flags[0]["detail"])
        self.assertIn("50%", flags[0]["detail"])

    def test_consistent_notes_pass(self):
        self.P.log_note(self.panel, 1, "said 40% latency cut")
        self.P.log_note(self.P.get_panel("P1"), 2, "mentioned the 40% latency cut too")
        self.assertEqual(self.P.consistency_check(self.P.get_panel("P1")), [])

    def test_same_value_not_flagged(self):
        self.P.log_note(self.panel, 1, "team of 5 engineers")
        self.P.log_note(self.P.get_panel("P1"), 2, "team of 5 engineers")
        self.assertEqual(self.P.consistency_check(self.P.get_panel("P1")), [])

    def test_log_validation(self):
        with self.assertRaises(self.P.PanelError):
            self.P.log_note(self.panel, 1, "   ")
        with self.assertRaises(self.P.PanelError):
            self.P.log_note(self.panel, 1, "note", signal="bogus")
        with self.assertRaises(self.P.PanelError):
            self.P.log_note(self.panel, 9, "note")
        e = self.P.log_note(self.panel, 1, "good chat", signal="strong")
        self.assertEqual(e["signal"], "strong")

    def test_render_consistency(self):
        md = self.P.render_consistency(self.panel)
        self.assertIn("No conflicting", md)


class DebriefTest(unittest.TestCase):
    def setUp(self):
        _pin_env()
        from candid import panel as P
        self.P = P
        self.panel = P.create_panel("Acme", "Data Scientist", ROUNDS)

    def tearDown(self):
        _unpin_env()

    def test_debrief_aggregates_signals(self):
        self.P.log_note(self.panel, 1, "great rapport", signal="strong")
        self.P.log_note(self.P.get_panel("P1"), 2, "tough deep dive", signal="mixed")
        md = self.P.debrief_panel(self.P.get_panel("P1"))
        self.assertIn("1 strong", md)
        self.assertIn("1 mixed", md)
        self.assertIn("Follow-ups", md)

    def test_debrief_no_signals(self):
        md = self.P.debrief_panel(self.panel)
        self.assertIn("No signals recorded", md)

    def test_debrief_drafts(self):
        self.P.log_note(self.panel, 1, "discussed the ML platform roadmap")
        profile = {"name": "Test Candidate"}
        md = self.P.debrief_panel(self.P.get_panel("P1"), profile=profile,
                                  drafts=True)
        self.assertIn("To Priya Nair", md)
        self.assertIn("Test Candidate", md)
        self.assertIn("ML platform roadmap", md)

    def test_debrief_drafts_without_profile(self):
        md = self.P.debrief_panel(self.panel, profile={}, drafts=True)
        self.assertIn("followup thank-you", md)


class ReadinessTest(unittest.TestCase):
    def setUp(self):
        _pin_env()
        from candid import panel as P
        self.P = P
        self.panel = P.create_panel("Acme", "Data Scientist", ROUNDS)

    def tearDown(self):
        _unpin_env()

    def test_starts_at_zero(self):
        r = self.P.readiness(self.panel)
        self.assertEqual(r["score"], 0)
        self.assertEqual(r["total"], 10)  # 1 briefed + 3 rounds x 3

    def test_full_prep_scores_100(self):
        self.P.brief_panel(self.panel)
        p = self.P.get_panel("P1")
        for i in (1, 2, 3):
            self.P.mock_round(p, i)
            p = self.P.get_panel("P1")
            self.P.set_background(p, i, "notes")
            p = self.P.get_panel("P1")
            self.P.log_note(p, i, "notes")
            p = self.P.get_panel("P1")
        r = self.P.readiness(p)
        self.assertEqual(r["score"], 100)
        md = self.P.render_readiness(p)
        self.assertIn("100/100", md)

    def test_partial_score(self):
        self.P.mock_round(self.panel, 2)
        r = self.P.readiness(self.P.get_panel("P1"))
        self.assertTrue(0 < r["score"] < 100)


class PanelCliTest(unittest.TestCase):
    def setUp(self):
        _pin_env()

    def tearDown(self):
        _unpin_env()

    def _run(self, *argv):
        from candid import __main__ as M
        buf = io.StringIO()
        with redirect_stdout(buf):
            M.main(list(argv))
        return buf.getvalue()

    def test_cli_roundtrip(self):
        out = self._run("panel", "create", "--company", "Acme",
                        "--role", "Data Scientist", "--rounds", ROUNDS)
        self.assertIn("Created panel P1", out)
        out = self._run("panel", "list")
        self.assertIn("P1", out)
        out = self._run("panel", "brief", "--panel", "P1")
        self.assertIn("Priya Nair", out)
        out = self._run("panel", "readiness", "--panel", "P1")
        self.assertIn("Readiness", out)

    def test_cli_expected_error(self):
        from candid import __main__ as M
        with self.assertRaises(SystemExit) as ctx:
            M.main(["panel", "show", "--panel", "P99"])
        self.assertEqual(ctx.exception.code, 1)

    def test_cli_typo_suggests_panel(self):
        from candid import __main__ as M
        with self.assertRaises(SystemExit):
            M.main(["panle"])


if __name__ == "__main__":
    unittest.main()
