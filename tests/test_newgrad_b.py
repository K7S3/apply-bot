"""Tests for worker B batch 88 (new-grad track).

Covers:
  tracker.py: internship flag on add, return-offer update validation,
    convert() linking, conversion_stats math, old-record compatibility,
    render_conversion_stats output.
  fairs.py: fair CRUD, company-entry parsing, follow-up listing and
    done-marking, draft_followup, JSON persistence round-trip.
  CLI wiring: `convert` and `fair` parse; `track add --internship`,
    `track update --return-offer`, `track conversion-stats` parse.

Run: CANDID_DATA_DIR=/tmp/candid-test-newgrad-b python3 -m unittest tests.test_newgrad_b -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-newgrad-b"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid.__main__ import build_parser  # noqa: E402
from candid import fairs as F  # noqa: E402
from candid import tracker as T  # noqa: E402


def _tmp(name):
    td = tempfile.TemporaryDirectory()
    return td, Path(td.name) / name


# ---------------------------------------------------------------------------
# tracker: internship marking
# ---------------------------------------------------------------------------

class InternshipAddTest(unittest.TestCase):
    def setUp(self):
        self.td, self.p = _tmp("tracker.json")

    def tearDown(self):
        self.td.cleanup()

    def test_add_internship_flag(self):
        rec = T.add("Acme", "SWE Intern", internship=True, path=self.p)
        self.assertTrue(rec["internship"])
        self.assertEqual(rec["return_offer"], "")
        self.assertIsNone(rec["converted_from"])

    def test_add_non_internship_defaults(self):
        rec = T.add("Acme", "SWE I", path=self.p)
        self.assertFalse(rec["internship"])
        self.assertEqual(rec["return_offer"], "")
        self.assertIsNone(rec["converted_from"])

    def test_old_records_without_keys_still_work(self):
        # Simulate a record written before the new-grad fields existed.
        apps = T.add("Acme", "SWE I", path=self.p)
        apps = T._load(self.p)
        del apps[0]["internship"]
        del apps[0]["return_offer"]
        del apps[0]["converted_from"]
        T._save(apps, self.p)
        listed = T.list_apps(path=self.p)
        self.assertEqual(len(listed), 1)
        out = T.render_list(listed)
        self.assertIn("Acme", out)
        s = T.conversion_stats(path=self.p)
        self.assertEqual(s["internships"], 0)
        self.assertEqual(s["accepted"], 0)

    def test_internship_shows_in_render_list(self):
        T.add("Acme", "SWE Intern", internship=True, path=self.p)
        out = T.render_list(T.list_apps(path=self.p))
        self.assertIn("[intern]", out)


# ---------------------------------------------------------------------------
# tracker: return offers
# ---------------------------------------------------------------------------

class ReturnOfferTest(unittest.TestCase):
    def setUp(self):
        self.td, self.p = _tmp("tracker.json")
        self.rec = T.add("Acme", "SWE Intern", internship=True, path=self.p)

    def tearDown(self):
        self.td.cleanup()

    def test_update_return_offer_yes(self):
        rec = T.update(self.rec["id"], return_offer="yes", path=self.p)
        self.assertEqual(rec["return_offer"], "yes")

    def test_update_return_offer_pending(self):
        rec = T.update(self.rec["id"], return_offer="pending", path=self.p)
        self.assertEqual(rec["return_offer"], "pending")

    def test_update_return_offer_invalid_raises(self):
        with self.assertRaises(T.TrackerError):
            T.update(self.rec["id"], return_offer="maybe", path=self.p)

    def test_update_return_offer_unknown_id_raises(self):
        with self.assertRaises(T.TrackerError):
            T.update(999, return_offer="yes", path=self.p)


# ---------------------------------------------------------------------------
# tracker: convert
# ---------------------------------------------------------------------------

class ConvertTest(unittest.TestCase):
    def setUp(self):
        self.td, self.p = _tmp("tracker.json")
        self.intern = T.add("Acme", "SWE Intern", internship=True,
                            status="offer", path=self.p)
        T.update(self.intern["id"], return_offer="yes", path=self.p)

    def tearDown(self):
        self.td.cleanup()

    def test_convert_links_fulltime_app(self):
        rec = T.convert(self.intern["id"], company="Acme", role="SWE I",
                        path=self.p)
        self.assertEqual(rec["converted_from"], self.intern["id"])
        self.assertFalse(rec["internship"])
        self.assertEqual(rec["company"], "Acme")
        self.assertEqual(rec["role"], "SWE I")

    def test_convert_bad_from_id_raises(self):
        with self.assertRaises(T.TrackerError):
            T.convert(999, company="Acme", role="SWE I", path=self.p)

    def test_convert_duplicate_does_not_relink(self):
        T.convert(self.intern["id"], company="Acme", role="SWE I", path=self.p)
        dup = T.convert(self.intern["id"], company="Acme", role="SWE I",
                        path=self.p)
        self.assertTrue(dup.get("duplicate"))
        self.assertEqual(len(T.list_apps(path=self.p)), 2)


# ---------------------------------------------------------------------------
# tracker: conversion stats math
# ---------------------------------------------------------------------------

class ConversionStatsTest(unittest.TestCase):
    def setUp(self):
        self.td, self.p = _tmp("tracker.json")

    def tearDown(self):
        self.td.cleanup()

    def _fixture(self):
        # 4 internships: 2 offers (1 yes + 1 pending return offer),
        # 1 interview-only, 1 applied-only. 1 converted FT app, accepted.
        a = T.add("Acme", "SWE Intern", internship=True, status="offer",
                  path=self.p)
        T.update(a["id"], return_offer="yes", path=self.p)
        b = T.add("Globex", "SWE Intern", internship=True, status="offer",
                  path=self.p)
        T.update(b["id"], return_offer="pending", path=self.p)
        T.add("Initech", "SWE Intern", internship=True,
              status="selected_for_interview", path=self.p)
        T.add("Umbrella", "SWE Intern", internship=True, status="applied",
              path=self.p)
        ft = T.convert(a["id"], company="Acme", role="SWE I", path=self.p)
        T.update(ft["id"], status="offer", path=self.p)
        return a

    def test_funnel_counts(self):
        self._fixture()
        s = T.conversion_stats(path=self.p)
        self.assertEqual(s["internships"], 4)
        self.assertEqual(s["applied"], 4)
        self.assertEqual(s["interviews"], 3)   # 2 offers + 1 selected
        self.assertEqual(s["offers"], 2)
        self.assertEqual(s["return_offers_yes"], 1)
        self.assertEqual(s["return_offers_pending"], 1)
        self.assertEqual(s["converted"], 1)
        self.assertEqual(s["accepted"], 1)

    def test_funnel_rates(self):
        self._fixture()
        s = T.conversion_stats(path=self.p)
        self.assertEqual(s["interview_rate"], 75.0)   # 3/4
        self.assertEqual(s["offer_rate"], 50.0)       # 2/4
        self.assertEqual(s["return_offer_rate"], 50.0)  # 1/2
        self.assertEqual(s["convert_rate"], 100.0)    # 1/1
        self.assertEqual(s["accept_rate"], 100.0)     # 1/1

    def test_empty_tracker_rates_are_zero(self):
        s = T.conversion_stats(path=self.p)
        self.assertEqual(s["internships"], 0)
        for k in ("interview_rate", "offer_rate", "return_offer_rate",
                  "convert_rate", "accept_rate"):
            self.assertEqual(s[k], 0.0)

    def test_render_conversion_stats_mentions_funnel(self):
        self._fixture()
        out = T.render_conversion_stats(T.conversion_stats(path=self.p))
        for label in ("internships", "interviews", "return offers",
                      "converted (FT app)", "accepted (FT offer)"):
            self.assertIn(label, out)

    def test_fulltime_only_apps_not_counted_as_internships(self):
        T.add("Acme", "SWE I", status="offer", path=self.p)
        s = T.conversion_stats(path=self.p)
        self.assertEqual(s["internships"], 0)
        self.assertEqual(s["accepted"], 0)


# ---------------------------------------------------------------------------
# fairs: CRUD
# ---------------------------------------------------------------------------

class FairCrudTest(unittest.TestCase):
    def setUp(self):
        self.td, self.p = _tmp("fairs.json")

    def tearDown(self):
        self.td.cleanup()

    def test_add_fair(self):
        rec = F.add_fair("Fall Career Fair", date_="2026-09-15",
                         school="Rutgers", path=self.p)
        self.assertEqual(rec["id"], 1)
        self.assertEqual(rec["name"], "Fall Career Fair")
        self.assertEqual(rec["date"], "2026-09-15")
        self.assertEqual(rec["school"], "Rutgers")
        self.assertEqual(rec["companies"], [])

    def test_add_fair_requires_name(self):
        with self.assertRaises(F.FairError):
            F.add_fair("", path=self.p)

    def test_add_fair_bad_date_raises(self):
        with self.assertRaises(F.FairError):
            F.add_fair("X", date_="15/09/2026", path=self.p)

    def test_list_fairs_sorted(self):
        F.add_fair("B", path=self.p)
        F.add_fair("A", path=self.p)
        names = [f["name"] for f in F.list_fairs(path=self.p)]
        self.assertEqual([f["id"] for f in F.list_fairs(path=self.p)], [1, 2])
        self.assertEqual(names, ["B", "A"])

    def test_get_fair_unknown_id_raises(self):
        with self.assertRaises(F.FairError):
            F.get_fair(42, path=self.p)

    def test_persistence_round_trip(self):
        F.add_fair("Fall Career Fair", date_="2026-09-15", school="Rutgers",
                   path=self.p)
        F.add_company(1, "Jane Smith, Stripe, jane@x.com, new grad roles",
                      path=self.p)
        reloaded = F.list_fairs(path=self.p)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0]["companies"][0]["person"], "Jane Smith")


# ---------------------------------------------------------------------------
# fairs: company entries + follow-ups
# ---------------------------------------------------------------------------

class FairCompaniesTest(unittest.TestCase):
    def setUp(self):
        self.td, self.p = _tmp("fairs.json")
        F.add_fair("Fall Career Fair", date_="2026-09-15", school="Rutgers",
                   path=self.p)

    def tearDown(self):
        self.td.cleanup()

    def test_add_company_full_parse(self):
        e = F.add_company(1, "Jane Smith, Stripe, jane@x.com, talked about new grad roles",
                          path=self.p)
        self.assertEqual(e["person"], "Jane Smith")
        self.assertEqual(e["company"], "Stripe")
        self.assertEqual(e["contact"], "jane@x.com")
        self.assertEqual(e["notes"], "talked about new grad roles")
        self.assertFalse(e["followup_done"])

    def test_add_company_single_token_is_company(self):
        e = F.add_company(1, "Stripe", path=self.p)
        self.assertEqual(e["company"], "Stripe")
        self.assertEqual(e["person"], "")

    def test_add_company_empty_raises(self):
        with self.assertRaises(F.FairError):
            F.add_company(1, "   ", path=self.p)

    def test_followups_lists_pending_only(self):
        F.add_company(1, "Jane Smith, Stripe, jane@x.com, new grad roles",
                      path=self.p)
        F.add_company(1, "Bob Lee, Acme, bob@acme.com, infra chat", path=self.p)
        F.mark_followup_done(1, "Bob Lee", path=self.p)
        got = F.followups(path=self.p)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["person"], "Jane Smith")
        self.assertEqual(got[0]["fair_name"], "Fall Career Fair")
        # suggested action mentions the contact + company
        action = F.suggested_action(got[0])
        self.assertIn("Stripe", action)
        self.assertIn("jane@x.com", action)

    def test_followups_filtered_by_fair(self):
        F.add_fair("Spring Fair", path=self.p)
        F.add_company(1, "Jane Smith, Stripe, jane@x.com, roles", path=self.p)
        F.add_company(2, "Ann Kim, Acme, ann@acme.com, roles", path=self.p)
        self.assertEqual(len(F.followups(fair_id=1, path=self.p)), 1)
        self.assertEqual(len(F.followups(path=self.p)), 2)

    def test_mark_followup_done_unknown_raises(self):
        with self.assertRaises(F.FairError):
            F.mark_followup_done(1, "Nobody", path=self.p)

    def test_draft_followup_has_subject_and_name(self):
        F.add_company(1, "Jane Smith, Stripe, jane@x.com, new grad roles",
                      path=self.p)
        entry = F.followups(path=self.p)[0]
        draft = F.draft_followup("Alex", entry)
        self.assertIn("Subject:", draft)
        self.assertIn("Jane Smith", draft)
        self.assertIn("Alex", draft)

    def test_render_followups_empty_state(self):
        out = F.render_followups([])
        self.assertIn("No pending follow-ups", out)


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

class CliWiringTest(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_convert_parses(self):
        a = self.parser.parse_args(
            ["convert", "--from", "3", "--company", "Acme", "--role", "SWE I"])
        self.assertEqual(a.cmd, "convert")
        self.assertEqual(a.from_id, 3)
        self.assertEqual(a.company, "Acme")

    def test_fair_subcommands_parse(self):
        a = self.parser.parse_args(
            ["fair", "add", "--name", "Fall Career Fair", "--date", "2026-09-15",
             "--school", "Rutgers"])
        self.assertEqual((a.cmd, a.what), ("fair", "add"))
        a = self.parser.parse_args(
            ["fair", "companies", "--fair", "1", "--add", "Jane, Stripe"])
        self.assertEqual((a.cmd, a.what), ("fair", "companies"))
        self.assertEqual(a.add, "Jane, Stripe")
        a = self.parser.parse_args(["fair", "followup", "--draft", "1"])
        self.assertEqual((a.cmd, a.what, a.draft), ("fair", "followup", 1))

    def test_track_internship_and_return_offer_parse(self):
        a = self.parser.parse_args(
            ["track", "add", "--company", "Acme", "--role", "SWE Intern",
             "--internship"])
        self.assertTrue(a.internship)
        a = self.parser.parse_args(["track", "update", "3", "--return-offer", "yes"])
        self.assertEqual(a.return_offer, "yes")
        a = self.parser.parse_args(["track", "conversion-stats"])
        self.assertEqual(a.what, "conversion-stats")


if __name__ == "__main__":
    unittest.main()
