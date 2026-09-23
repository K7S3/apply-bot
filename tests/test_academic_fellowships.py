"""Tests for the academic track (worker-2): postdoc kind in the tracker and
the curated fellowship database.

Zero network: the fellowship data file is read from the package, all
tracker state lives in a tmp file (path=), no CANDID_DATA_DIR side effects.

Run: python3 -m unittest tests.test_academic_fellowships -v
"""
import argparse
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import fellowships as F  # noqa: E402
from candid import nudges as N  # noqa: E402
from candid import tracker as T  # noqa: E402


def _tmp_tracker():
    td = tempfile.TemporaryDirectory()
    return td, Path(td.name) / "tracker.json"


# ---------------------------------------------------------------------------
# tracker.add / update with postdoc fields
# ---------------------------------------------------------------------------

class TestPostdocAddUpdate(unittest.TestCase):
    def test_add_postdoc_roundtrip(self):
        td, p = _tmp_tracker()
        try:
            deadline = (date.today() + timedelta(days=20)).isoformat()
            rec = T.add("MIT", "Postdoc Researcher", kind="postdoc",
                        pi="Dr. Ada Lovelace", lab="AI Lab",
                        funding_source="NIH F32", deadline=deadline,
                        start_date="2027-01-15", path=p)
            self.assertEqual(rec["kind"], "postdoc")
            self.assertEqual(rec["pi"], "Dr. Ada Lovelace")
            self.assertEqual(rec["lab"], "AI Lab")
            self.assertEqual(rec["funding_source"], "NIH F32")
            self.assertEqual(rec["deadline"], deadline)
            self.assertEqual(rec["start_date"], "2027-01-15")
            # persisted
            again = T.list_apps(path=p)[0]
            self.assertEqual(again["pi"], "Dr. Ada Lovelace")
            self.assertEqual(again["deadline"], deadline)
        finally:
            td.cleanup()

    def test_add_defaults_to_industry(self):
        td, p = _tmp_tracker()
        try:
            rec = T.add("Acme", "Data Scientist", path=p)
            self.assertEqual(rec["kind"], "industry")
            self.assertEqual(rec["pi"], "")
            self.assertEqual(rec["deadline"], "")
        finally:
            td.cleanup()

    def test_add_invalid_kind_raises(self):
        td, p = _tmp_tracker()
        try:
            with self.assertRaises(T.TrackerError):
                T.add("Acme", "Data Scientist", kind="moon", path=p)
            self.assertEqual(T.list_apps(path=p), [])
        finally:
            td.cleanup()

    def test_update_postdoc_fields(self):
        td, p = _tmp_tracker()
        try:
            rec = T.add("Stanford", "Postdoc", kind="postdoc", path=p)
            upd = T.update(rec["id"], pi="Dr. Curie", deadline="2026-12-01",
                           funding_source="NSF PRFB", path=p)
            self.assertEqual(upd["pi"], "Dr. Curie")
            self.assertEqual(upd["deadline"], "2026-12-01")
            self.assertEqual(upd["funding_source"], "NSF PRFB")
            # unrelated fields untouched
            self.assertEqual(upd["status"], "saved")
            self.assertEqual(upd["lab"], "")
            # kind change is validated
            upd2 = T.update(rec["id"], kind="industry", path=p)
            self.assertEqual(upd2["kind"], "industry")
            with self.assertRaises(T.TrackerError):
                T.update(rec["id"], kind="moon", path=p)
        finally:
            td.cleanup()


class TestKindFiltering(unittest.TestCase):
    def test_legacy_records_default_to_industry(self):
        td, p = _tmp_tracker()
        try:
            # legacy record: no "kind" key at all
            legacy = {"id": 1, "company": "Old Co", "role": "Engineer",
                      "jd_link": "", "status": "applied", "notes": "",
                      "date_added": "2026-01-01", "date_updated": "2026-01-01",
                      "prep_pack": ""}
            p.write_text(json.dumps([legacy]), encoding="utf-8")
            self.assertEqual(T.kind_of(legacy), "industry")
            self.assertEqual(len(T.list_apps(kind="industry", path=p)), 1)
            self.assertEqual(T.list_apps(kind="postdoc", path=p), [])
            self.assertEqual(len(T.list_apps(path=p)), 1)
        finally:
            td.cleanup()

    def test_kind_filter(self):
        td, p = _tmp_tracker()
        try:
            T.add("Acme", "MLE", kind="industry", path=p)
            T.add("MIT", "Postdoc", kind="postdoc", path=p)
            T.add("Berkeley", "Postdoc", kind="postdoc", path=p)
            postdocs = T.list_apps(kind="postdoc", path=p)
            self.assertEqual(len(postdocs), 2)
            self.assertTrue(all(a["kind"] == "postdoc" for a in postdocs))
            self.assertEqual(len(T.list_apps(kind="industry", path=p)), 1)
            with self.assertRaises(T.TrackerError):
                T.list_apps(kind="moon", path=p)
        finally:
            td.cleanup()

    def test_search_covers_postdoc_fields(self):
        td, p = _tmp_tracker()
        try:
            T.add("MIT", "Postdoc", kind="postdoc", pi="Dr. Curie",
                  lab="Radiation Lab", funding_source="DOE grant", path=p)
            self.assertEqual(len(T.search("curie", path=p)), 1)
            self.assertEqual(len(T.search("radiation", path=p)), 1)
            self.assertEqual(len(T.search("doe grant", path=p)), 1)
        finally:
            td.cleanup()


# ---------------------------------------------------------------------------
# deadline parsing + postdoc hints
# ---------------------------------------------------------------------------

class TestDeadlineParsing(unittest.TestCase):
    def test_good_date(self):
        self.assertEqual(T.parse_deadline("2026-12-01"), date(2026, 12, 1))

    def test_bad_dates_return_none(self):
        for bad in ["", "not-a-date", "2026-13-01", "2026-02-30",
                    "12/01/2026", None]:
            with self.subTest(bad=bad):
                self.assertIsNone(T.parse_deadline(bad))

    def test_deadline_approaching_hint(self):
        near = (date.today() + timedelta(days=10)).isoformat()
        hint = T.postdoc_next_action({"kind": "postdoc", "status": "saved",
                                      "deadline": near, "pi": "", "lab": ""})
        self.assertIn("draft research statement", hint)

    def test_far_deadline_no_statement_hint(self):
        far = (date.today() + timedelta(days=200)).isoformat()
        hint = T.postdoc_next_action({"kind": "postdoc", "status": "saved",
                                      "deadline": far, "pi": "", "lab": ""})
        self.assertNotIn("draft research statement", hint)

    def test_pi_hint(self):
        hint = T.postdoc_next_action({"kind": "postdoc", "status": "saved",
                                      "deadline": "", "pi": "Dr. Curie",
                                      "lab": ""})
        self.assertIn("email PI", hint)
        self.assertIn("Dr. Curie", hint)

    def test_bad_deadline_never_raises(self):
        hint = T.postdoc_next_action({"kind": "postdoc", "status": "saved",
                                      "deadline": "garbage", "pi": "",
                                      "lab": ""})
        self.assertIn("tailor resume + apply", hint)

    def test_industry_render_unchanged(self):
        app = {"id": 1, "company": "Acme", "role": "MLE", "status": "applied",
               "date_updated": "2026-09-22", "kind": "industry",
               "deadline": "2026-12-01", "pi": "Dr. X", "lab": "L"}
        out = T.render_list([app])
        self.assertIn("follow up if quiet > 14d", out)
        self.assertNotIn("draft research statement", out)

    def test_postdoc_render_shows_academic_hint(self):
        near = (date.today() + timedelta(days=5)).isoformat()
        app = {"id": 2, "company": "MIT", "role": "Postdoc",
               "status": "saved", "date_updated": "2026-09-22",
               "kind": "postdoc", "deadline": near, "pi": "Dr. Curie",
               "lab": ""}
        out = T.render_list([app])
        self.assertIn("draft research statement", out)
        self.assertIn("email PI", out)


# ---------------------------------------------------------------------------
# tracker.add_parsers CLI hook
# ---------------------------------------------------------------------------

class TestTrackerAddParsers(unittest.TestCase):
    def _track_subparsers(self):
        p = argparse.ArgumentParser()
        sub = p.add_subparsers(dest="cmd", required=True)
        track = sub.add_parser("track")
        ts = track.add_subparsers(dest="what", required=True)
        add = ts.add_parser("add")
        add.add_argument("--company", default="")
        add.add_argument("--role", default="")
        ts.add_parser("list")
        ts.add_parser("update")
        return p, ts

    def test_add_args(self):
        p, ts = self._track_subparsers()
        T.add_parsers(ts)
        a = p.parse_args(["track", "add", "--company", "MIT", "--role", "Postdoc",
                          "--kind", "postdoc", "--pi", "Dr. Curie",
                          "--lab", "Rad Lab", "--funding-source", "NSF PRFB",
                          "--deadline", "2026-12-01", "--start-date", "2027-02-01"])
        self.assertEqual(a.kind, "postdoc")
        self.assertEqual(a.pi, "Dr. Curie")
        self.assertEqual(a.lab, "Rad Lab")
        self.assertEqual(a.funding_source, "NSF PRFB")
        self.assertEqual(a.deadline, "2026-12-01")
        self.assertEqual(a.start_date, "2027-02-01")

    def test_add_defaults(self):
        p, ts = self._track_subparsers()
        T.add_parsers(ts)
        a = p.parse_args(["track", "add", "--company", "Acme", "--role", "MLE"])
        self.assertEqual(a.kind, "industry")
        self.assertEqual(a.pi, "")
        self.assertEqual(a.deadline, "")

    def test_list_kind_filter(self):
        p, ts = self._track_subparsers()
        T.add_parsers(ts)
        a = p.parse_args(["track", "list", "--kind", "postdoc"])
        self.assertEqual(a.kind, "postdoc")
        a2 = p.parse_args(["track", "list"])
        self.assertIsNone(a2.kind)


# ---------------------------------------------------------------------------
# fellowship database
# ---------------------------------------------------------------------------

class TestFellowshipData(unittest.TestCase):
    def test_json_valid_and_shaped(self):
        fs = F.load_fellowships()
        self.assertGreaterEqual(len(fs), 8)
        names = [f["name"] for f in fs]
        self.assertEqual(len(names), len(set(names)))  # no duplicates
        for f in fs:
            with self.subTest(f=f.get("name")):
                self.assertTrue(f["name"])
                self.assertTrue(f["org"])
                self.assertTrue(f["url"].startswith("https://"))
                self.assertTrue(f["eligibility"])
                self.assertTrue(f["verified_on"])
                for m in f.get("deadline_months", []):
                    self.assertIn(int(m), range(1, 13))

    def test_known_programs_present(self):
        hay = " | ".join(f["name"] + " " + f["org"]
                         for f in F.load_fellowships())
        for needle in ["F32", "PRFB", "HFSP", "EMBO", "Sklodowska-Curie"]:
            self.assertIn(needle, hay)


class TestUpcoming(unittest.TestCase):
    def _mini(self):
        return [
            {"name": "Jan Fellowship", "org": "Org A",
             "url": "https://example.com/a", "eligibility": "E",
             "deadline_months": [1], "deadline_note": "", "rolling": False,
             "verified_on": "2026-09-22"},
            {"name": "Rolling Fellowship", "org": "Org B",
             "url": "https://example.com/b", "eligibility": "E",
             "deadline_months": [], "deadline_note": "rolling",
             "rolling": True, "verified_on": "2026-09-22"},
            {"name": "No Month Fellowship", "org": "Org C",
             "url": "https://example.com/c", "eligibility": "E",
             "deadline_months": [], "deadline_note": "see site",
             "rolling": False, "verified_on": "2026-09-22"},
        ]

    def test_month_projection_is_approximate(self):
        td = tempfile.TemporaryDirectory()
        try:
            p = Path(td.name) / "f.json"
            p.write_text(json.dumps(self._mini()), encoding="utf-8")
            # today 2026-09-22: Jan cycle projects to 2027-01-01 (101 days out)
            items = F.upcoming(days=120, today=date(2026, 9, 22), path=p)
            jan = next(i for i in items
                       if i["fellowship"]["name"] == "Jan Fellowship")
            self.assertEqual(jan["deadline"], date(2027, 1, 1))
            self.assertTrue(jan["approx"])
            self.assertEqual(jan["days_until"], 101)
            # no-month entry cannot be projected -> excluded
            self.assertNotIn("No Month Fellowship",
                             [i["fellowship"]["name"] for i in items])
            # rolling always included
            rolling = next(i for i in items
                           if i["fellowship"]["name"] == "Rolling Fellowship")
            self.assertTrue(rolling["rolling"])
            self.assertIsNone(rolling["deadline"])
        finally:
            td.cleanup()

    def test_window_filters(self):
        td = tempfile.TemporaryDirectory()
        try:
            p = Path(td.name) / "f.json"
            p.write_text(json.dumps(self._mini()), encoding="utf-8")
            items = F.upcoming(days=10, today=date(2026, 9, 22), path=p)
            names = [i["fellowship"]["name"] for i in items]
            self.assertNotIn("Jan Fellowship", names)
            self.assertIn("Rolling Fellowship", names)
        finally:
            td.cleanup()

    def test_real_data_upcoming_shape(self):
        items = F.upcoming(days=120, today=date(2026, 9, 22))
        self.assertTrue(items)
        for it in items:
            self.assertIn("fellowship", it)
            self.assertIn("approx", it)
            if not it["rolling"]:
                self.assertTrue(it["approx"])
                self.assertIsNotNone(it["deadline"])


class TestFellowshipDeadlinesHook(unittest.TestCase):
    def test_hook_shape(self):
        ns = F.fellowship_deadlines(days=120, today=date(2026, 9, 22))
        self.assertTrue(ns)
        for n in ns:
            self.assertEqual(n["kind"], "fellowship_deadline")
            self.assertIn("message", n)
            self.assertIn("action", n)
            self.assertIn("command", n)

    def test_nudges_include_fellowship_deadlines(self):
        apps = [{"id": 1, "company": "Acme", "role": "MLE",
                 "status": "applied",
                 "date_updated": date.today().isoformat(),
                 "kind": "industry", "notes": "", "prep_pack": ""}]
        ns = N.pending_nudges(apps=apps, today=date(2026, 9, 22))
        kinds = [n["kind"] for n in ns]
        self.assertIn("fellowship_deadline", kinds)

    def test_nudges_postdoc_deadline(self):
        apps = [{"id": 7, "company": "MIT", "role": "Postdoc",
                 "status": "saved",
                 "date_updated": date.today().isoformat(),
                 "kind": "postdoc",
                 "deadline": (date(2026, 9, 22) + timedelta(days=5)).isoformat(),
                 "pi": "Dr. Curie", "notes": "", "prep_pack": ""}]
        ns = N.pending_nudges(apps=apps, today=date(2026, 9, 22))
        pd = [n for n in ns if n["kind"] == "postdoc_deadline"]
        self.assertEqual(len(pd), 1)
        self.assertIn("research statement", pd[0]["action"])

    def test_nudges_bad_deadline_never_breaks(self):
        apps = [{"id": 8, "company": "MIT", "role": "Postdoc",
                 "status": "saved", "date_updated": date.today().isoformat(),
                 "kind": "postdoc", "deadline": "garbage",
                 "notes": "", "prep_pack": ""}]
        ns = N.pending_nudges(apps=apps, today=date(2026, 9, 22))
        self.assertNotIn("postdoc_deadline", [n["kind"] for n in ns])


class TestFellowshipsAddParsers(unittest.TestCase):
    def test_commands_parse(self):
        p = argparse.ArgumentParser()
        sub = p.add_subparsers(dest="cmd", required=True)
        F.add_parsers(sub)
        a = p.parse_args(["fellowships", "list"])
        self.assertEqual(a.what, "list")
        b = p.parse_args(["fellowships", "upcoming", "--days", "30"])
        self.assertEqual(b.what, "upcoming")
        self.assertEqual(b.days, 30)
        c = p.parse_args(["fellowships", "upcoming"])
        self.assertEqual(c.days, 60)
        self.assertTrue(callable(a.func))


if __name__ == "__main__":
    unittest.main()
