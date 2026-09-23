"""Tests for candid recruiter pipeline (recruiter/application links,
per-recruiter funnel, stale-thread nudges, reply drafts).

Fictional fixtures only. Run: python3 -m pytest tests/test_recruiter_pipeline.py -q
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ["CANDID_DATA_DIR"] = "/tmp/candid-test-recruiter-pipeline"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import recruiter_pipeline as R  # noqa: E402


def _temp_paths():
    td = tempfile.TemporaryDirectory()
    base = Path(td.name)
    return td, {
        "tracker": base / "tracker.json",
        "links": base / "recruiter_links.json",
    }


def _seed_tracker(p):
    apps = [
        {"id": 1, "company": "Acme", "role": "Data Analyst",
         "status": "applied", "date_updated": "2026-09-01"},
        {"id": 2, "company": "Beta", "role": "ML Engineer",
         "status": "selected_for_interview", "date_updated": "2026-09-02"},
        {"id": 3, "company": "Gamma", "role": "SWE",
         "status": "rejected", "date_updated": "2026-09-03"},
        {"id": 4, "company": "Delta", "role": "SWE",
         "status": "offer", "date_updated": "2026-09-04"},
        {"id": 5, "company": "Epsilon", "role": "Analyst",
         "status": "saved", "date_updated": "2026-09-05"},
    ]
    p.write_text(json.dumps(apps), encoding="utf-8")


def _links(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


class TestLinkRoundTrip(unittest.TestCase):
    def test_link_unlink_round_trip(self):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        p = {"tracker": base / "tracker.json", "links": base / "recruiter_links.json"}
        _seed_tracker(p["tracker"])
        rec = R.link("Dana Recruiter", 1, path=p["links"], tracker_path=p["tracker"])
        self.assertEqual(rec["apps"], [1])
        R.link("Dana Recruiter", 2, path=p["links"], tracker_path=p["tracker"])
        self.assertEqual(R.for_recruiter("Dana Recruiter", path=p["links"]), [1, 2])
        self.assertEqual(R.for_application(1, path=p["links"]), ["Dana Recruiter"])
        # duplicate link is idempotent
        R.link("Dana Recruiter", 1, path=p["links"], tracker_path=p["tracker"])
        self.assertEqual(R.for_recruiter("Dana Recruiter", path=p["links"]), [1, 2])
        R.unlink("Dana Recruiter", 1, path=p["links"])
        self.assertEqual(R.for_recruiter("Dana Recruiter", path=p["links"]), [2])
        self.assertEqual(R.for_application(1, path=p["links"]), [])
        td.cleanup()

    def test_link_invalid_app_id(self):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        p = {"tracker": base / "tracker.json", "links": base / "recruiter_links.json"}
        _seed_tracker(p["tracker"])
        with self.assertRaises(R.RecruiterError):
            R.link("Dana Recruiter", 999, path=p["links"], tracker_path=p["tracker"])
        # nothing was persisted for the bad link
        self.assertEqual(R.for_recruiter("Dana Recruiter", path=p["links"]), [])
        td.cleanup()

    def test_unlink_errors(self):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        p = {"tracker": base / "tracker.json", "links": base / "recruiter_links.json"}
        _seed_tracker(p["tracker"])
        with self.assertRaises(R.RecruiterError):
            R.unlink("Nobody", 1, path=p["links"])
        R.link("Dana Recruiter", 1, path=p["links"], tracker_path=p["tracker"])
        with self.assertRaises(R.RecruiterError):
            R.unlink("Dana Recruiter", 2, path=p["links"])
        td.cleanup()

    def test_never_writes_tracker(self):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        p = {"tracker": base / "tracker.json", "links": base / "recruiter_links.json"}
        _seed_tracker(p["tracker"])
        before = p["tracker"].read_text(encoding="utf-8")
        R.link("Dana Recruiter", 1, path=p["links"], tracker_path=p["tracker"])
        R.link("Dana Recruiter", 2, path=p["links"], tracker_path=p["tracker"])
        R.unlink("Dana Recruiter", 1, path=p["links"])
        self.assertEqual(p["tracker"].read_text(encoding="utf-8"), before)
        td.cleanup()


class TestFunnel(unittest.TestCase):
    def test_funnel_math(self):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        p = {"tracker": base / "tracker.json", "links": base / "recruiter_links.json"}
        _seed_tracker(p["tracker"])
        for a in (1, 2, 3, 4):  # applied, interview, rejected, offer
            R.link("Dana Recruiter", a, path=p["links"], tracker_path=p["tracker"])
        f = R.recruiter_funnel("Dana Recruiter", path=p["links"], tracker_path=p["tracker"])
        self.assertEqual(f["total"], 4)
        self.assertEqual(f["counts"]["applied"], 1)
        self.assertEqual(f["counts"]["selected_for_interview"], 1)
        self.assertEqual(f["counts"]["rejected"], 1)
        self.assertEqual(f["counts"]["offer"], 1)
        self.assertEqual(f["counts"]["saved"], 0)
        # base=4, responses=3 (interview+rejected+offer), interviews=2, offers=1
        self.assertEqual(f["response_rate"], 75.0)
        self.assertEqual(f["interview_rate"], 50.0)
        self.assertEqual(f["offer_rate"], 25.0)
        td.cleanup()

    def test_funnel_zero_base_none_safe(self):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        p = {"tracker": base / "tracker.json", "links": base / "recruiter_links.json"}
        _seed_tracker(p["tracker"])
        R.link("Sam Sourcer", 5, path=p["links"], tracker_path=p["tracker"])  # saved only
        f = R.recruiter_funnel("Sam Sourcer", path=p["links"], tracker_path=p["tracker"])
        self.assertEqual(f["total"], 1)
        self.assertEqual(f["response_rate"], 0.0)
        self.assertEqual(f["interview_rate"], 0.0)
        self.assertEqual(f["offer_rate"], 0.0)
        td.cleanup()

    def test_funnel_unknown_recruiter(self):
        td = tempfile.TemporaryDirectory()
        p = {"links": Path(td.name) / "recruiter_links.json"}
        with self.assertRaises(R.RecruiterError):
            R.recruiter_funnel("Ghost", path=p["links"])
        td.cleanup()


class TestStaleThreads(unittest.TestCase):
    def test_stale_threshold_and_active_excluded(self):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        p = {"tracker": base / "tracker.json", "links": base / "recruiter_links.json"}
        _seed_tracker(p["tracker"])
        old = (date.today() - timedelta(days=30)).isoformat()
        recent = (date.today() - timedelta(days=2)).isoformat()
        # Dana: old touch, linked app rejected (inactive) -> stale
        R.upsert_recruiter("Dana Recruiter", last_touch=old, path=p["links"])
        R.link("Dana Recruiter", 3, path=p["links"], tracker_path=p["tracker"])
        # Sam: old touch, but linked app is applied (active) -> NOT stale
        R.upsert_recruiter("Sam Sourcer", last_touch=old, path=p["links"])
        R.link("Sam Sourcer", 1, path=p["links"], tracker_path=p["tracker"])
        # Leo: recent touch, inactive app -> NOT stale (under threshold)
        R.upsert_recruiter("Leo Agent", last_touch=recent, path=p["links"])
        R.link("Leo Agent", 3, path=p["links"], tracker_path=p["tracker"])
        stale = R.stale_threads(days=14, path=p["links"], tracker_path=p["tracker"])
        names = [s["recruiter"] for s in stale]
        self.assertEqual(names, ["Dana Recruiter"])
        s = stale[0]
        self.assertEqual(s["days_since_touch"], 30)
        self.assertIn("rejected", s["suggestion"].lower() or "no active")
        self.assertIn("Dana", s["suggestion"])
        td.cleanup()

    def test_stale_no_touch_and_no_apps(self):
        td = tempfile.TemporaryDirectory()
        base = Path(td.name)
        p = {"tracker": base / "tracker.json", "links": base / "recruiter_links.json"}
        _seed_tracker(p["tracker"])
        R.upsert_recruiter("Mia Scout", path=p["links"])  # no touch, no apps
        stale = R.stale_threads(path=p["links"], tracker_path=p["tracker"])
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["last_touch"], "never")
        self.assertIn("intro", stale[0]["suggestion"].lower())
        td.cleanup()

    def test_stale_invalid_days(self):
        td = tempfile.TemporaryDirectory()
        with self.assertRaises(R.RecruiterError):
            R.stale_threads(days=-1, path=Path(td.name) / "recruiter_links.json")
        td.cleanup()


class TestReplyDrafts(unittest.TestCase):
    def test_all_kinds_have_subject_name_and_timing(self):
        for kind in ("interested", "not_interested", "need_details", "schedule_call"):
            d = R.reply_draft("Dana Recruiter", kind, "Alex Rivera",
                              role="Data Analyst", company="Acme")
            self.assertTrue(d["subject"], kind)
            self.assertIn("Alex Rivera", d["body"], kind)
            self.assertIn("Dana Recruiter", d["body"], kind)
            self.assertTrue(d["timing"], kind)
            self.assertNotIn("—", d["body"] + d["subject"] + d["timing"])
            self.assertNotIn("—", d["subject"])

    def test_invalid_kind(self):
        with self.assertRaises(R.RecruiterError):
            R.reply_draft("Dana Recruiter", "flirty", "Alex Rivera")

    def test_invalid_inputs(self):
        with self.assertRaises(R.RecruiterError):
            R.reply_draft("", "interested", "Alex Rivera")
        with self.assertRaises(R.RecruiterError):
            R.reply_draft("Dana Recruiter", "interested", "")


class TestValidation(unittest.TestCase):
    def test_bad_last_touch_date(self):
        td = tempfile.TemporaryDirectory()
        with self.assertRaises(R.RecruiterError):
            R.upsert_recruiter("Dana", last_touch="09-01-2026",
                               path=Path(td.name) / "recruiter_links.json")
        td.cleanup()

    def test_empty_recruiter_name(self):
        td = tempfile.TemporaryDirectory()
        with self.assertRaises(R.RecruiterError):
            R.upsert_recruiter("  ", path=Path(td.name) / "recruiter_links.json")
        td.cleanup()


if __name__ == "__main__":
    unittest.main()
