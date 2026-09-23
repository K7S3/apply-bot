"""Tests for the onsite day planner (candid/onsite.py + CLI wiring).

Covers: schedule builder, overlap detection, timeline rendering, logistics
checklist, per-round prep reminders, energy plan, morning-of timeline,
questions bank, notes, and day-summary export.

Run: CANDID_DATA_DIR=/tmp/candid-test-onsite python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = tempfile.mkdtemp(prefix="candid-test-onsite-")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import onsite as O  # noqa: E402


def _tmp_json(testcase):
    d = tempfile.mkdtemp(prefix="onsite-")
    testcase.addCleanup(__import__("shutil").rmtree, d, True)
    return str(Path(d) / "onsite.json")


def _plan(testcase, **kw):
    kw.setdefault("company", "Acme")
    kw.setdefault("role", "Data Scientist")
    kw.setdefault("date_str", "2026-10-05")
    path = _tmp_json(testcase)
    plan = O.create_plan(path=path, **kw)
    return plan, path


def _run_cli(*argv, path):
    """Run the CLI with onsite storage redirected to a temp json file."""
    real = O.ONSITE_PATH
    O.ONSITE_PATH = Path(path)
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            CLI.main(["onsite", *argv])
        return buf.getvalue()
    finally:
        O.ONSITE_PATH = real


class TestPlanCreation(unittest.TestCase):
    def test_create_basic(self):
        plan, _ = _plan(self)
        self.assertEqual(plan["id"], 1)
        self.assertEqual(plan["mode"], "onsite")
        self.assertEqual(plan["date"], "2026-10-05")
        self.assertEqual(plan["rounds"], [])
        self.assertTrue(plan["checklist"])

    def test_create_with_round_specs(self):
        plan, _ = _plan(self, rounds=("10:00 coding 45", "11:00 behavioral 45"))
        self.assertEqual(len(plan["rounds"]), 2)
        self.assertEqual(plan["rounds"][0]["start"], 600)
        self.assertEqual(plan["rounds"][0]["kind"], "coding")

    def test_duplicate_returns_existing(self):
        plan, path = _plan(self)
        dup = O.create_plan("acme", "data scientist", "2026-10-05", path=path)
        self.assertTrue(dup.get("duplicate"))
        self.assertEqual(dup["id"], plan["id"])
        self.assertEqual(len(O.list_plans(path=path)), 1)

    def test_bad_date(self):
        with self.assertRaises(O.OnsiteError):
            O.create_plan("Acme", "DS", "10/05/2026", path=_tmp_json(self))

    def test_bad_mode(self):
        with self.assertRaises(O.OnsiteError):
            O.create_plan("Acme", "DS", "2026-10-05", mode="teleport",
                          path=_tmp_json(self))

    def test_missing_company(self):
        with self.assertRaises(O.OnsiteError):
            O.create_plan("", "DS", "2026-10-05", path=_tmp_json(self))

    def test_bad_commute(self):
        with self.assertRaises(O.OnsiteError):
            O.create_plan("Acme", "DS", "2026-10-05", commute_min=999,
                          path=_tmp_json(self))


class TestChecklist(unittest.TestCase):
    def _labels(self, plan):
        return [i["label"] for i in plan["checklist"]]

    def test_onsite_items(self):
        plan, _ = _plan(self, mode="onsite")
        labels = self._labels(plan)
        self.assertIn("Photo ID for building check-in", labels)
        self.assertIn("Notebook + pen", labels)
        self.assertNotIn("Camera + mic tested in the meeting app", labels)

    def test_virtual_items(self):
        plan, _ = _plan(self, mode="virtual")
        labels = self._labels(plan)
        self.assertIn("Camera + mic tested in the meeting app", labels)
        self.assertNotIn("Photo ID for building check-in", labels)

    def test_hybrid_gets_both(self):
        plan, _ = _plan(self, mode="hybrid")
        labels = self._labels(plan)
        self.assertIn("Photo ID for building check-in", labels)
        self.assertIn("Video links saved for the remote rounds", labels)

    def test_ids_sequential(self):
        plan, _ = _plan(self)
        ids = [i["id"] for i in plan["checklist"]]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_check_and_undo(self):
        plan, path = _plan(self)
        item = O.set_check(plan["id"], 2, True, path=path)
        self.assertTrue(item["done"])
        item = O.set_check(plan["id"], 2, False, path=path)
        self.assertFalse(item["done"])
        rendered = O.render_checklist(plan["id"], path=path)
        self.assertIn("0/", rendered)

    def test_check_invalid_item(self):
        plan, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.set_check(plan["id"], 999, True, path=path)

    def test_render_grouped(self):
        plan, path = _plan(self, mode="virtual")
        out = O.render_checklist(plan["id"], path=path)
        self.assertIn("TECH:", out)
        self.assertIn("[ ] #", out)


class TestRounds(unittest.TestCase):
    def test_add_round(self):
        plan, path = _plan(self)
        rnd = O.add_round(plan["id"], "10:00 coding 45 Coding - Jane",
                          interviewer="Jane Doe", where="Room 4B", path=path)
        self.assertEqual(rnd["title"], "Coding - Jane")
        self.assertEqual(rnd["interviewer"], "Jane Doe")
        self.assertEqual(rnd["location"], "Room 4B")

    def test_overlap_rejected(self):
        plan, path = _plan(self, rounds=("10:00 coding 45",))
        with self.assertRaises(O.OnsiteError) as ctx:
            O.add_round(plan["id"], "10:30 behavioral 45", path=path)
        self.assertIn("overlaps", str(ctx.exception))

    def test_touching_boundaries_ok(self):
        plan, path = _plan(self, rounds=("10:00 coding 45",))
        rnd = O.add_round(plan["id"], "10:45 behavioral 45", path=path)
        self.assertEqual(rnd["start"], 645)

    def test_bad_time_spec(self):
        plan, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.add_round(plan["id"], "25:00 coding 45", path=path)

    def test_unknown_kind(self):
        plan, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.add_round(plan["id"], "10:00 whiteboarding 45", path=path)

    def test_bad_minutes(self):
        plan, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.add_round(plan["id"], "10:00 coding 999", path=path)

    def test_remove_round(self):
        plan, path = _plan(self, rounds=("10:00 coding 45", "11:00 behavioral 45"))
        O.remove_round(plan["id"], 1, path=path)
        self.assertEqual(len(O.get_plan(plan["id"], path=path)["rounds"]), 1)
        with self.assertRaises(O.OnsiteError):
            O.remove_round(plan["id"], 1, path=path)

    def test_delete_plan(self):
        plan, path = _plan(self)
        O.delete_plan(plan["id"], path=path)
        self.assertEqual(O.list_plans(path=path), [])
        with self.assertRaises(O.OnsiteError):
            O.delete_plan(plan["id"], path=path)

    def test_kind_normalization(self):
        plan, path = _plan(self)
        rnd = O.add_round(plan["id"], "10:00 System_Design 60", path=path)
        self.assertEqual(rnd["kind"], "system-design")


class TestTimeline(unittest.TestCase):
    def test_render_end_times_and_span(self):
        plan, path = _plan(self, rounds=("10:00 coding 45", "11:00 behavioral 45"))
        out = O.timeline(plan["id"], path=path)
        self.assertIn("10:00-10:45", out)
        self.assertIn("11:00-11:45", out)
        self.assertIn("Day span: 1h 45m across 2 rounds.", out)

    def test_tight_gap_flag(self):
        plan, path = _plan(self, rounds=("10:00 coding 45", "10:50 behavioral 45"))
        out = O.timeline(plan["id"], path=path)
        self.assertIn("Only 5m between", out)

    def test_no_lunch_flag(self):
        # Back-to-back morning rounds, no gap >= 30 min -> no lunch window.
        plan, path = _plan(self, rounds=("09:00 coding 60", "10:05 behavioral 45"))
        out = O.timeline(plan["id"], path=path)
        self.assertIn("No lunch window", out)

    def test_lunch_round_clears_flag(self):
        plan, path = _plan(self, rounds=("10:00 coding 45", "12:00 lunch 45"))
        out = O.timeline(plan["id"], path=path)
        self.assertNotIn("No lunch window", out)

    def test_midday_gap_clears_lunch_flag(self):
        plan, path = _plan(self, rounds=("10:00 coding 45", "12:00 behavioral 45"))
        out = O.timeline(plan["id"], path=path)
        self.assertNotIn("No lunch window", out)


class TestPrepAndQuestions(unittest.TestCase):
    def test_prep_all_rounds(self):
        plan, path = _plan(self, rounds=("10:00 coding 45", "11:00 behavioral 45"))
        out = O.prep_reminders(plan["id"], path=path)
        self.assertIn("10:00", out)
        self.assertIn("11:00", out)
        self.assertIn("STAR", out)
        self.assertIn("out loud", out)

    def test_prep_single_round(self):
        plan, path = _plan(self, rounds=("10:00 coding 45", "11:00 behavioral 45"))
        out = O.prep_reminders(plan["id"], round_id=2, path=path)
        self.assertNotIn("10:00", out)
        self.assertIn("behavioral", out)

    def test_prep_no_rounds(self):
        plan, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.prep_reminders(plan["id"], path=path)

    def test_questions_by_kind(self):
        out = O.questions(kind="hiring-manager")
        self.assertIn("promotable", out)

    def test_questions_for_plan(self):
        plan, path = _plan(self, rounds=("10:00 coding 45",))
        out = O.questions(plan_id=plan["id"], path=path)
        self.assertIn("code review", out)

    def test_questions_needs_kind_or_plan(self):
        with self.assertRaises(O.OnsiteError):
            O.questions()

    def test_questions_bad_kind(self):
        with self.assertRaises(O.OnsiteError):
            O.questions(kind="telepathy")


class TestEnergyAndMorning(unittest.TestCase):
    def test_energy_sleep_math(self):
        # first round 10:00 onsite -> wake 08:30, bedtime 00:30 previous night
        plan, path = _plan(self, rounds=("10:00 coding 45",))
        out = O.energy_plan(plan["id"], path=path)
        self.assertIn("08:30", out)
        self.assertIn("00:30", out)
        self.assertIn("8h", out)

    def test_energy_lunch_round(self):
        plan, path = _plan(self, rounds=("10:00 coding 45", "12:00 lunch 45"))
        out = O.energy_plan(plan["id"], path=path)
        self.assertIn("Lunch is on the schedule: 12:00-12:45", out)

    def test_energy_midday_gap_lunch(self):
        plan, path = _plan(self, rounds=("10:00 coding 45", "13:00 behavioral 45"))
        out = O.energy_plan(plan["id"], path=path)
        self.assertIn("eat then", out)

    def test_energy_caffeine_cutoff(self):
        plan, path = _plan(self, rounds=("10:00 coding 45",))
        out = O.energy_plan(plan["id"], path=path)
        # bedtime 00:30 -> cutoff 18:30 previous evening
        self.assertIn("18:30", out)

    def test_energy_tight_gap(self):
        plan, path = _plan(self, rounds=("10:00 coding 45", "10:50 behavioral 45"))
        out = O.energy_plan(plan["id"], path=path)
        self.assertIn("back-to-back", out)

    def test_morning_onsite_math(self):
        # first 10:00, commute 40 -> arrive 09:45, leave 08:50, wake 07:20
        plan, path = _plan(self, commute_min=40, rounds=("10:00 coding 45",))
        out = O.morning_plan(plan["id"], path=path)
        self.assertIn("07:20", out)   # wake
        self.assertIn("08:50", out)   # leave
        self.assertIn("09:45", out)   # arrive
        self.assertIn("10:00", out)   # first round

    def test_morning_virtual(self):
        plan, path = _plan(self, mode="virtual", rounds=("10:00 coding 45",))
        out = O.morning_plan(plan["id"], path=path)
        self.assertIn("09:00", out)  # wake = 10:00 - 60
        self.assertIn("Log in early", out)
        self.assertNotIn("Leave", out)


class TestNotesAndSummary(unittest.TestCase):
    def test_day_and_round_notes(self):
        plan, path = _plan(self, rounds=("10:00 coding 45",))
        O.set_notes(plan["id"], "Great vibe overall.", path=path)
        O.set_notes(plan["id"], "Asked about caching.", round_id=1, path=path)
        got = O.get_plan(plan["id"], path=path)
        self.assertEqual(got["day_notes"], "Great vibe overall.")
        self.assertEqual(got["rounds"][0]["notes"], "Asked about caching.")

    def test_blank_notes_rejected(self):
        plan, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.set_notes(plan["id"], "   ", path=path)

    def test_summary_file(self):
        plan, path = _plan(self, rounds=("10:00 coding 45",))
        O.set_notes(plan["id"], "Went well.", path=path)
        O.set_check(plan["id"], 1, True, path=path)
        d = tempfile.mkdtemp(prefix="onsite-sum-")
        self.addCleanup(__import__("shutil").rmtree, d, True)
        out = Path(d) / "day.md"
        dest = O.summary(plan["id"], out=str(out), path=path)
        text = Path(dest).read_text(encoding="utf-8")
        self.assertIn("# Interview day", text)
        self.assertIn("10:00-10:45", text)
        self.assertIn("Went well.", text)
        self.assertIn("thank-you notes within 24 hours", text)
        self.assertIn("- [x]", text)

    def test_summary_default_path(self):
        plan, path = _plan(self, rounds=("10:00 coding 45",))
        dest = O.summary(plan["id"], path=path)
        self.assertTrue(str(dest).endswith(f"onsite_{plan['id']}_summary.md"))
        self.addCleanup(os.remove, str(dest))


class TestListing(unittest.TestCase):
    def test_list_newest_first(self):
        path = _tmp_json(self)
        O.create_plan("Acme", "DS", "2026-10-05", path=path)
        O.create_plan("Beta", "SWE", "2026-10-06", path=path)
        plans = O.list_plans(path=path)
        self.assertEqual([p["company"] for p in plans], ["Beta", "Acme"])
        rendered = O.render_plans(plans)
        self.assertIn("#2", rendered)
        self.assertIn("#1", rendered)

    def test_render_empty(self):
        self.assertEqual(O.render_plans([]), "No day plans yet.")

    def test_latest_plan_empty(self):
        with self.assertRaises(O.OnsiteError):
            O.latest_plan(path=_tmp_json(self))

    def test_unknown_plan_id(self):
        with self.assertRaises(O.OnsiteError):
            O.get_plan(42, path=_tmp_json(self))


class TestCli(unittest.TestCase):
    def test_cli_plan_and_timeline(self):
        path = _tmp_json(self)
        out = _run_cli("plan", "--company", "Acme", "--role", "DS",
                       "--date", "2026-10-05", "--mode", "onsite",
                       "--commute-min", "30",
                       "--round", "10:00 coding 45", path=path)
        self.assertIn("Created day plan #1", out)
        out = _run_cli("timeline", path=path)
        self.assertIn("10:00-10:45", out)
        out = _run_cli("energy", path=path)
        self.assertIn("Energy plan", out)
        out = _run_cli("morning", path=path)
        self.assertIn("Morning of 2026-10-05", out)

    def test_cli_add_round_overlap_is_friendly(self):
        path = _tmp_json(self)
        _run_cli("plan", "--company", "Acme", "--role", "DS",
                 "--date", "2026-10-05", "--round", "10:00 coding 45", path=path)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit):
                _run_cli("add-round", "--round", "10:30 behavioral 45", path=path)
        self.assertIn("overlaps", err.getvalue())
        self.assertIn("onsite --help", err.getvalue())

    def test_cli_checklist_check(self):
        path = _tmp_json(self)
        _run_cli("plan", "--company", "Acme", "--role", "DS",
                 "--date", "2026-10-05", path=path)
        out = _run_cli("check", "--item-id", "1", path=path)
        self.assertIn("marked done", out)
        out = _run_cli("checklist", path=path)
        self.assertIn("[x] #1", out)

    def test_cli_questions_prep_notes_summary(self):
        path = _tmp_json(self)
        _run_cli("plan", "--company", "Acme", "--role", "DS",
                 "--date", "2026-10-05", "--round", "10:00 coding 45", path=path)
        out = _run_cli("questions", "--kind", "coding", path=path)
        self.assertIn("code review", out)
        out = _run_cli("prep", path=path)
        self.assertIn("out loud", out)
        out = _run_cli("notes", "--text", "Solid day.", path=path)
        self.assertIn("Saved notes", out)
        d = tempfile.mkdtemp(prefix="onsite-cli-")
        self.addCleanup(__import__("shutil").rmtree, d, True)
        dest = str(Path(d) / "s.md")
        out = _run_cli("summary", "--out", dest, path=path)
        self.assertIn("Wrote day summary", out)
        self.assertIn("Solid day.", Path(dest).read_text(encoding="utf-8"))

    def test_cli_onsite_in_command_inventory(self):
        self.assertIn("onsite", CLI.COMMANDS)
        self.assertIn("timeline", CLI.SUBCOMMANDS["onsite"])


if __name__ == "__main__":
    unittest.main()
