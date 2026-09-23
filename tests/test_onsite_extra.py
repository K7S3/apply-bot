"""Tests for the batch-42 follow-up features: move-round rescheduling,
day-runner status, .ics calendar export, and thank-you drafts.

Run: CANDID_DATA_DIR=/tmp/x python3 -m pytest tests/test_onsite_extra.py -q
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = tempfile.mkdtemp(prefix="candid-test-onsite-x-")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import onsite as O  # noqa: E402


def _tmp_json(testcase):
    d = tempfile.mkdtemp(prefix="onsite-x-")
    testcase.addCleanup(__import__("shutil").rmtree, d, True)
    return str(Path(d) / "onsite.json")


def _plan(testcase, **kw):
    kw.setdefault("company", "Acme")
    kw.setdefault("role", "Data Scientist")
    kw.setdefault("date_str", "2026-10-05")
    path = _tmp_json(testcase)
    plan = O.create_plan(path=path, **kw)
    O.add_round(plan["id"], "10:00 coding 45 Coding",
                interviewer="Jane Doe", where="Room 4B", path=path)
    O.add_round(plan["id"], "11:00 behavioral 45", interviewer="John Smith", path=path)
    O.add_round(plan["id"], "13:00 system-design 60", path=path)
    return plan["id"], path


def _run_cli(*argv, path):
    real = O.ONSITE_PATH
    O.ONSITE_PATH = Path(path)
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            CLI.main(["onsite", *argv])
        return buf.getvalue()
    finally:
        O.ONSITE_PATH = real


class TestMoveRound(unittest.TestCase):
    def test_move_start(self):
        pid, path = _plan(self)
        rnd = O.move_round(pid, 1, start="09:30", path=path)
        self.assertEqual(rnd["start"], 9 * 60 + 30)
        self.assertEqual(rnd["minutes"], 45)  # unchanged

    def test_resize_only(self):
        pid, path = _plan(self)
        rnd = O.move_round(pid, 2, minutes=60, path=path)
        self.assertEqual(rnd["start"], 11 * 60)
        self.assertEqual(rnd["minutes"], 60)

    def test_move_and_resize(self):
        pid, path = _plan(self)
        rnd = O.move_round(pid, 3, start="14:00", minutes=90, path=path)
        self.assertEqual((rnd["start"], rnd["minutes"]), (14 * 60, 90))

    def test_back_to_back_is_fine(self):
        pid, path = _plan(self)
        rnd = O.move_round(pid, 2, start="10:45", path=path)
        self.assertEqual(rnd["start"], 10 * 60 + 45)

    def test_overlap_rejected(self):
        pid, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.move_round(pid, 2, start="10:30", path=path)

    def test_resize_into_overlap_rejected(self):
        pid, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.move_round(pid, 1, minutes=90, path=path)

    def test_nothing_to_change(self):
        pid, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.move_round(pid, 1, path=path)

    def test_unknown_round(self):
        pid, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.move_round(pid, 99, start="09:00", path=path)

    def test_bad_time(self):
        pid, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.move_round(pid, 1, start="25:00", path=path)

    def test_keeps_interviewer_and_location(self):
        pid, path = _plan(self)
        rnd = O.move_round(pid, 1, start="09:00", path=path)
        self.assertEqual(rnd["interviewer"], "Jane Doe")
        self.assertEqual(rnd["location"], "Room 4B")

    def test_cli_move_round(self):
        pid, path = _plan(self)
        out = _run_cli("move-round", "--plan-id", str(pid), "--round-id", "2",
                       "--start", "12:00", path=path)
        self.assertIn("12:00-12:45", out)


class TestDayStatus(unittest.TestCase):
    def test_before_first_round(self):
        pid, path = _plan(self)
        out = O.day_status(pid, "08:30", path=path)
        self.assertIn("NEXT: Coding at 10:00 (in 90m)", out)
        self.assertIn("prep --round-id", out)
        self.assertNotIn("NOW:", out)

    def test_during_round(self):
        pid, path = _plan(self)
        out = O.day_status(pid, "10:15", path=path)
        self.assertIn("NOW: Coding (until 10:45)", out)
        self.assertIn("NEXT: Behavioral at 11:00 (in 45m)", out)

    def test_back_to_back_reset_hint(self):
        pid, path = _plan(self)
        O.move_round(pid, 2, start="10:45", path=path)
        out = O.day_status(pid, "10:40", path=path)
        self.assertIn("Back-to-back: 2-minute reset", out)

    def test_exactly_at_start_is_current(self):
        pid, path = _plan(self)
        out = O.day_status(pid, "11:00", path=path)
        self.assertIn("NOW: Behavioral", out)

    def test_after_last_round(self):
        pid, path = _plan(self)
        out = O.day_status(pid, "15:00", path=path)
        self.assertIn("Done for the day", out)
        self.assertIn("onsite notes", out)
        self.assertIn("onsite summary", out)

    def test_no_rounds_errors(self):
        plan, path = _plan(self)  # noqa: F841
        empty = O.create_plan("Solo", "X", "2026-11-01", path=path)
        with self.assertRaises(O.OnsiteError):
            O.day_status(empty["id"], "10:00", path=path)

    def test_bad_time(self):
        pid, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.day_status(pid, "nope", path=path)

    def test_cli_status(self):
        pid, path = _plan(self)
        out = _run_cli("status", "--plan-id", str(pid), "--at", "10:20", path=path)
        self.assertIn("NOW: Coding", out)


class TestExportIcs(unittest.TestCase):
    def test_file_contents(self):
        pid, path = _plan(self)
        dest = O.export_ics(pid, path=path)
        text = Path(dest).read_text(encoding="utf-8")
        self.assertEqual(text.count("BEGIN:VEVENT"), 3)
        self.assertIn("DTSTART:20261005T100000", text)
        self.assertIn("DTEND:20261005T104500", text)
        self.assertIn("UID:candid-onsite-1-1@candid", text)
        self.assertIn("TRIGGER:-PT15M", text)
        self.assertIn("Interviewer: Jane Doe", text)
        self.assertIn("LOCATION:Room 4B", text)
        self.assertTrue(text.startswith("BEGIN:VCALENDAR"))
        self.assertTrue(text.rstrip().endswith("END:VCALENDAR"))

    def test_ics_escaping(self):
        self.assertEqual(O._ics_escape("a;b,c\\d\ne"), "a\\;b\\,c\\\\d\\ne")

    def test_no_rounds_errors(self):
        plan, path = _plan(self)  # noqa: F841
        empty = O.create_plan("Solo", "X", "2026-11-01", path=path)
        with self.assertRaises(O.OnsiteError):
            O.export_ics(empty["id"], path=path)

    def test_custom_out_path(self):
        pid, path = _plan(self)
        out = Path(tempfile.mkdtemp(prefix="ics-")) / "day.ics"
        dest = O.export_ics(pid, out=out, path=path)
        self.assertEqual(dest, out)
        self.assertTrue(out.exists())

    def test_cli_export_ics(self):
        pid, path = _plan(self)
        out = _run_cli("export-ics", "--plan-id", str(pid), path=path)
        self.assertIn("Wrote calendar file", out)


class TestThanks(unittest.TestCase):
    def test_drafts_per_interviewer(self):
        pid, path = _plan(self)
        out = O.thank_you_drafts(pid, path=path)
        self.assertIn("## To: Jane Doe", out)
        self.assertIn("## To: John Smith", out)
        self.assertIn("Hi Jane,", out)
        self.assertIn("Subject: Thank you — Data Scientist interview", out)
        self.assertIn("[Your Name]", out)

    def test_round_notes_woven_in(self):
        pid, path = _plan(self)
        O.set_notes(pid, "Asked about rate limiting", round_id=1, path=path)
        out = O.thank_you_drafts(pid, round_id=1, path=path)
        self.assertIn('Your note to weave in: "Asked about rate limiting"', out)
        self.assertNotIn("John Smith", out)

    def test_no_interviewers_errors(self):
        pid, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.thank_you_drafts(pid, round_id=3, path=path)

    def test_unknown_round(self):
        pid, path = _plan(self)
        with self.assertRaises(O.OnsiteError):
            O.thank_you_drafts(pid, round_id=99, path=path)

    def test_cli_thanks(self):
        pid, path = _plan(self)
        out = _run_cli("thanks", "--plan-id", str(pid), path=path)
        self.assertIn("Thank-you drafts", out)


class TestRegistry(unittest.TestCase):
    def test_subcommands_registered(self):
        for sub in ("move-round", "status", "export-ics", "thanks"):
            self.assertIn(sub, CLI.SUBCOMMANDS["onsite"])


if __name__ == "__main__":
    unittest.main()
