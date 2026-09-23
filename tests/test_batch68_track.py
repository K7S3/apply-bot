"""Tests for candid.outreach_track (batch 68, W4).

Covers: log/mark_sent/update_status roundtrip, invalid transitions,
nudge_candidates with explicit dates, touch, dossier-ref degradation,
and extract_manager_clues on planted and plain JDs.

Run from repo root: python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import outreach_track as OT  # noqa: E402


def _past(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


class OutreachTrackTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.path = str(Path(self._td.name) / "outreach_log.json")
        self.dossier = {"id": "d1", "name": "Priya Nair", "company": "Acme"}

    def tearDown(self):
        self._td.cleanup()

    # -- log / mark_sent / update_status roundtrip --------------------------
    def test_log_mark_sent_update_roundtrip(self):
        e = OT.log_outreach(self.dossier, "linkedin", notes="intro", path=self.path)
        self.assertEqual(e["status"], "draft")
        self.assertEqual(e["manager_name"], "Priya Nair")
        self.assertEqual(e["company"], "Acme")
        self.assertIsNone(e["sent_at"])
        self.assertEqual(len(e["id"]), 8)

        e = OT.mark_sent(e["id"], path=self.path)
        self.assertEqual(e["status"], "sent")
        self.assertEqual(e["sent_at"], date.today().isoformat())

        e = OT.update_status(e["id"], "no-reply", path=self.path)
        self.assertEqual(e["status"], "no-reply")

        e = OT.update_status(e["id"], "followed-up", path=self.path)
        self.assertEqual(e["status"], "followed-up")

        e = OT.update_status(e["id"], "archived", path=self.path)
        self.assertEqual(e["status"], "archived")

        e = OT.log_outreach(self.dossier, "email", path=self.path)
        OT.mark_sent(e["id"], path=self.path)
        e = OT.update_status(e["id"], "replied", path=self.path)
        self.assertEqual(e["status"], "replied")

        # persisted as JSON list
        raw = json.loads(Path(self.path).read_text(encoding="utf-8"))
        self.assertIsInstance(raw, list)
        self.assertEqual(len(raw), 2)

    def test_mark_sent_with_explicit_date(self):
        e = OT.log_outreach(self.dossier, "email", path=self.path)
        e = OT.mark_sent(e["id"], _past(3), path=self.path)
        self.assertEqual(e["sent_at"], _past(3))
        self.assertEqual(e["last_touch"], _past(3))

    # -- invalid transitions ------------------------------------------------
    def test_invalid_transitions_raise(self):
        e = OT.log_outreach(self.dossier, "linkedin", path=self.path)
        with self.assertRaises(OT.OutreachTrackError):
            OT.update_status(e["id"], "replied", path=self.path)  # draft -> replied
        with self.assertRaises(OT.OutreachTrackError):
            OT.update_status(e["id"], "archived", path=self.path)  # draft -> archived
        with self.assertRaises(OT.OutreachTrackError):
            OT.update_status(e["id"], "bogus", path=self.path)  # unknown status

        OT.mark_sent(e["id"], path=self.path)
        with self.assertRaises(OT.OutreachTrackError):
            OT.update_status(e["id"], "draft", path=self.path)  # sent -> draft
        with self.assertRaises(OT.OutreachTrackError):
            OT.update_status(e["id"], "archived", path=self.path)  # sent -> archived
        with self.assertRaises(OT.OutreachTrackError):
            OT.mark_sent(e["id"], path=self.path)  # sent -> sent is invalid
        with self.assertRaises(OT.OutreachTrackError):
            OT.update_status("nope", "sent", path=self.path)  # unknown entry

    def test_noop_same_status_ok(self):
        e = OT.log_outreach(self.dossier, "linkedin", path=self.path)
        same = OT.update_status(e["id"], "draft", path=self.path)
        self.assertEqual(same["status"], "draft")

    # -- list_outreach --------------------------------------------------------
    def test_list_outreach_filters_and_order(self):
        a = OT.log_outreach({**self.dossier, "id": "a", "company": "Acme"},
                            "email", path=self.path)
        b = OT.log_outreach({**self.dossier, "id": "b", "company": "Globex"},
                            "linkedin", path=self.path)
        OT.mark_sent(a["id"], _past(5), path=self.path)
        OT.mark_sent(b["id"], _past(1), path=self.path)

        rows = OT.list_outreach(path=self.path)
        self.assertEqual([r["id"] for r in rows], [b["id"], a["id"]])  # newest first
        self.assertEqual(len(OT.list_outreach(company="acme", path=self.path)), 1)
        self.assertEqual(len(OT.list_outreach(status="sent", path=self.path)), 2)
        self.assertEqual(OT.list_outreach(status="draft", path=self.path), [])

    # -- nudge_candidates -----------------------------------------------------
    def test_nudge_candidates_flags_stale_only(self):
        stale_sent = OT.log_outreach({**self.dossier, "id": "s1"}, "email", path=self.path)
        OT.mark_sent(stale_sent["id"], _past(10), path=self.path)

        fresh_sent = OT.log_outreach({**self.dossier, "id": "s2"}, "email", path=self.path)
        OT.mark_sent(fresh_sent["id"], _past(3), path=self.path)

        stale_fu = OT.log_outreach({**self.dossier, "id": "f1"}, "linkedin", path=self.path)
        OT.mark_sent(stale_fu["id"], _past(9), path=self.path)
        OT.update_status(stale_fu["id"], "no-reply", path=self.path)
        OT.update_status(stale_fu["id"], "followed-up", path=self.path)
        # followed-up bumps last_touch to today; push it back to a stale date
        entries = OT._load(self.path)
        for en in entries:
            if en["id"] == stale_fu["id"]:
                en["last_touch"] = _past(9)
        OT._save(entries, self.path)

        replied = OT.log_outreach({**self.dossier, "id": "r1"}, "email", path=self.path)
        OT.mark_sent(replied["id"], _past(20), path=self.path)
        OT.update_status(replied["id"], "replied", path=self.path)

        OT.log_outreach({**self.dossier, "id": "d1"}, "email", path=self.path)  # draft

        nudges = OT.nudge_candidates(days=7, path=self.path)
        ids = {n["entry"]["id"] for n in nudges}
        self.assertEqual(ids, {stale_sent["id"], stale_fu["id"]})
        by_id = {n["entry"]["id"]: n for n in nudges}
        self.assertEqual(by_id[stale_sent["id"]]["next_step"], "send follow-up")
        self.assertEqual(by_id[stale_sent["id"]]["days_since_touch"], 10)
        self.assertEqual(by_id[stale_fu["id"]]["next_step"], "send follow-up")

    def test_nudge_escalation_steps(self):
        e1 = OT.log_outreach({**self.dossier, "id": "e1"}, "email", path=self.path)
        OT.mark_sent(e1["id"], _past(15), path=self.path)  # 14 < 15 <= 21
        e2 = OT.log_outreach({**self.dossier, "id": "e2"}, "email", path=self.path)
        OT.mark_sent(e2["id"], _past(12), path=self.path)
        e3 = OT.log_outreach({**self.dossier, "id": "e3"}, "email", path=self.path)
        OT.mark_sent(e3["id"], _past(30), path=self.path)
        by_id = {n["entry"]["id"]: n["next_step"]
                 for n in OT.nudge_candidates(days=7, path=self.path)}
        self.assertEqual(by_id[e1["id"]], "try a different channel")
        self.assertEqual(by_id[e2["id"]], "send follow-up")
        self.assertEqual(by_id[e3["id"]], "archive")

    # -- touch ----------------------------------------------------------------
    def test_touch_bumps_date_and_appends_note(self):
        e = OT.log_outreach(self.dossier, "email", notes="first", path=self.path)
        OT.mark_sent(e["id"], _past(6), path=self.path)
        e = OT.touch(e["id"], "bumped into her at the meetup", path=self.path)
        self.assertEqual(e["last_touch"], date.today().isoformat())
        self.assertIn("first", e["notes"])
        self.assertIn("bumped into her at the meetup", e["notes"])
        # no longer stale after the touch
        self.assertEqual(OT.nudge_candidates(days=7, path=self.path), [])

    # -- dossier ref degradation ----------------------------------------------
    def test_string_dossier_ref_degrades_gracefully(self):
        e = OT.log_outreach("missing-dossier-id", "email", path=self.path)
        self.assertEqual(e["dossier_id"], "missing-dossier-id")
        self.assertIsNone(e["manager_name"])
        self.assertEqual(e["company"], "")

    def test_unknown_entry_id_raises(self):
        with self.assertRaises(OT.OutreachTrackError):
            OT.mark_sent("deadbeef", path=self.path)
        with self.assertRaises(OT.OutreachTrackError):
            OT.touch("deadbeef", path=self.path)


class ExtractManagerCluesTest(unittest.TestCase):
    JD_WITH_CLUES = """\
Senior ML Engineer, Acme Corp

Join our Data Science team to build ranking models for ads.
You will report to Rahul Menon and collaborate with product.
The Hiring Manager: Priya Nair will reach out after screening.
This role is led by Sara Khan's org.
"""

    PLAIN_JD = """\
Software Engineer

We are looking for a backend engineer with 3+ years of experience.
Python and SQL required. Apply with your resume.
"""

    def test_finds_planted_clues(self):
        clues = OT.extract_manager_clues(self.JD_WITH_CLUES)
        # first manager pattern hit wins: "report to Rahul Menon" appears
        # before the "hiring manager" line in the text? no: patterns are
        # checked in order hiring-manager, reports-to, led-by, so the
        # hiring-manager match wins regardless of position.
        self.assertEqual(clues["manager_name"], "Priya Nair")
        self.assertEqual(clues["team"], "Data Science")
        self.assertIsNotNone(clues["reporting_line"])
        self.assertIn("Priya Nair", clues["reporting_line"])
        self.assertEqual(clues["raw_hits"],
                         ["Hiring Manager: Priya Nair", "Join our Data Science"])

    def test_reports_to_and_led_by(self):
        clues = OT.extract_manager_clues("You will report to Rahul Menon daily.")
        self.assertEqual(clues["manager_name"], "Rahul Menon")
        self.assertIn("Rahul Menon", clues["reporting_line"])
        clues = OT.extract_manager_clues("The team is led by Sara Khan.")
        self.assertEqual(clues["manager_name"], "Sara Khan")

    def test_the_x_team(self):
        clues = OT.extract_manager_clues("You will join the Growth team in New York.")
        self.assertEqual(clues["team"], "Growth")

    def test_plain_jd_returns_clean_empties(self):
        clues = OT.extract_manager_clues(self.PLAIN_JD)
        self.assertEqual(clues, {"manager_name": None, "team": None,
                                 "reporting_line": None, "raw_hits": []})

    def test_empty_and_none_input(self):
        for bad in ("", "   ", None):
            clues = OT.extract_manager_clues(bad)
            self.assertEqual(clues["raw_hits"], [])
            self.assertIsNone(clues["manager_name"])

    def test_never_invents_names(self):
        clues = OT.extract_manager_clues(
            "The hiring manager will contact you after the screen.")
        self.assertIsNone(clues["manager_name"])
        self.assertEqual(clues["raw_hits"], [])


if __name__ == "__main__":
    unittest.main()
