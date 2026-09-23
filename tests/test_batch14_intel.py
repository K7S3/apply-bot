"""Batch-14 intel tests: cross-board dedupe, freshness tracking, board-aware
curate filters (--stage / --min-salary / --tech-only), and saved searches.

Hermetic: adapters are mocked; no live network. Run:
    python3 -m unittest tests.test_batch14_intel -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _fake_fetch(payload):
    def _f():
        return payload
    return _f


# Same posting ("Backend Engineer @ Nimbus") on two boards: the builtin copy
# is richer (has salary_text, longer description) and must win.
CROSS_BOARD = [
    {"source": "wellfound", "source_id": "wellfound:1", "title": "Backend Engineer",
     "company": "Nimbus", "location": "Remote", "remote": True,
     "url": "https://wellfound.example/1", "posted_at": "2026-09-20",
     "description": "Short post.", "salary_text": "",
     "extras": {"stage": "seed"}},
    {"source": "builtin", "source_id": "builtin:9", "title": "Backend Engineer",
     "company": "Nimbus", "location": "Remote", "remote": True,
     "url": "https://builtin.example/9", "posted_at": "2026-09-20",
     "description": ("Much longer description with real detail about the role, "
                     "the stack, and the team."),
     "salary_text": "$140k-$170k", "extras": {"stage": "seed"}},
    {"source": "dice", "source_id": "dice:7", "title": "Barista",
     "company": "Coffee Inc", "location": "Austin, TX", "remote": False,
     "url": "https://dice.example/7", "posted_at": "2026-09-20",
     "description": "Pull espresso shots.", "salary_text": ""},
]

PROFILE = {"name": "Alex Rivera",
           "skills": ["python", "machine learning", "sql", "deep learning",
                      "pytorch", "statistics"],
           "seniority": "senior", "years_experience": 6.5,
           "experience": [{"company": "Meridian Financial",
                           "title": "Senior Data Scientist"}]}


class DedupeTest(unittest.TestCase):
    def test_keeps_richest_and_records_also_seen_on(self):
        from candid import jobs as J
        out = J.dedupe_cross_board(CROSS_BOARD)
        self.assertEqual(len(out), 2)  # Nimbus collapsed, Coffee Inc kept
        nimbus = next(j for j in out if j["company"] == "Nimbus")
        self.assertEqual(nimbus["source"], "builtin")
        self.assertEqual(nimbus["source_id"], "builtin:9")
        self.assertEqual(nimbus["also_seen_on"], ["wellfound"])
        coffee = next(j for j in out if j["company"] == "Coffee Inc")
        self.assertEqual(coffee["also_seen_on"], [])

    def test_salary_wins_over_length(self):
        from candid import jobs as J
        jobs = [
            {"source": "a", "source_id": "a:1", "title": "X Eng", "company": "Y",
             "description": "x" * 5000, "salary_text": ""},
            {"source": "b", "source_id": "b:2", "title": "X Eng", "company": "Y",
             "description": "tiny", "salary_text": "$100k-$120k"},
        ]
        out = J.dedupe_cross_board(jobs)
        self.assertEqual(out[0]["source_id"], "b:2")
        self.assertEqual(out[0]["also_seen_on"], ["a"])

    def test_baseline_only_boards_still_work(self):
        from candid import jobs as J
        jobs = [
            {"source": "arbeitnow", "source_id": "arbeitnow:s1",
             "title": "Data Scientist", "company": "Acme",
             "description": "data stuff", "salary_text": ""},
            {"source": "remoteok", "source_id": "remoteok:2",
             "title": "Data Scientist", "company": "Acme",
             "description": "data stuff", "salary_text": ""},
        ]
        out = J.dedupe_cross_board(jobs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "arbeitnow")  # tie → first wins
        self.assertEqual(out[0]["also_seen_on"], ["remoteok"])

    def test_norm_key_variants_collapse(self):
        from candid import jobs as J
        jobs = [
            {"source": "a", "source_id": "a:1", "title": "Senior  Data Scientist!",
             "company": "Acme Corp", "description": "d", "salary_text": ""},
            {"source": "b", "source_id": "b:2", "title": "senior data scientist",
             "company": "acme corp", "description": "d2", "salary_text": ""},
        ]
        out = J.dedupe_cross_board(jobs)
        self.assertEqual(len(out), 1)


class BoardFilterTest(unittest.TestCase):
    def test_min_salary_parsing(self):
        from candid import jobs as J
        self.assertEqual(J._salary_min("$150k-$180k"), 150000)
        self.assertEqual(J._salary_min("$160,000 - $200,000"), 160000)
        self.assertIsNone(J._salary_min(""))
        self.assertIsNone(J._salary_min("competitive salary"))

    def test_salary_ok_ignores_missing_data(self):
        from candid import jobs as J
        self.assertTrue(J._salary_ok({"salary_text": ""}, 150000))
        self.assertTrue(J._salary_ok({}, 150000))
        self.assertTrue(J._salary_ok({"salary_text": "$150k-$180k"}, 140000))
        self.assertFalse(J._salary_ok({"salary_text": "$150k-$180k"}, 160000))

    def test_stage_ok_only_where_metadata_exists(self):
        from candid import jobs as J
        self.assertTrue(J._stage_ok({"extras": {"stage": "seed"}}, "seed"))
        self.assertFalse(J._stage_ok({"extras": {"stage": "seed"}}, "series-a"))
        # no stage metadata → filter silently ignored (job passes)
        self.assertTrue(J._stage_ok({}, "seed"))
        self.assertTrue(J._stage_ok({"extras": {}}, "seed"))
        self.assertTrue(J._stage_ok({"extras": {"stage": "seed"}}, None))

    def test_norm_stage_aliases(self):
        from candid import jobs as J
        self.assertEqual(J._norm_stage("Series A"), "series-a")
        self.assertEqual(J._norm_stage("series_a"), "series-a")
        self.assertEqual(J._norm_stage("Seed"), "seed")

    def test_tech_only(self):
        from candid import jobs as J
        self.assertTrue(J._tech_ok("Senior Data Scientist"))
        self.assertTrue(J._tech_ok("ML Engineer"))
        self.assertTrue(J._tech_ok("DevOps Specialist"))
        self.assertFalse(J._tech_ok("Barista"))
        self.assertFalse(J._tech_ok("Marketing Manager"))

    def test_filter_jobs_tech_only_and_salary(self):
        from candid import jobs as J
        # mirror the curate pipeline: cross-board dedupe runs before filtering
        jobs = J.dedupe_cross_board(CROSS_BOARD)
        self.assertEqual([j["source_id"] for j in jobs],
                         ["builtin:9", "dice:7"])
        out = J.filter_jobs(jobs, "backend engineer", "", remote=True,
                            tech_only=True, limit=25)
        self.assertEqual([j["source_id"] for j in out], ["builtin:9"])
        out = J.filter_jobs(jobs, "backend engineer", "", remote=True,
                            min_salary=160000, limit=25)
        self.assertEqual([j["source_id"] for j in out], [])  # $140k < $160k
        out = J.filter_jobs(jobs, "backend engineer", "", remote=True,
                            min_salary=130000, limit=25)
        self.assertEqual([j["source_id"] for j in out], ["builtin:9"])
        out = J.filter_jobs(jobs, "backend engineer", "", remote=True,
                            stage="seed", limit=25)
        self.assertEqual([j["source_id"] for j in out], ["builtin:9"])
        out = J.filter_jobs(jobs, "backend engineer", "", remote=True,
                            stage="series-a", limit=25)
        self.assertEqual([j["source_id"] for j in out], [])


class FreshnessTest(unittest.TestCase):
    def _state(self):
        return {
            "last_run": "2026-09-22T20:00:00",
            "prev_last_run": "2026-09-21T20:00:00",
            "sightings": {
                "backend engineer|nimbus": {
                    "title": "Backend Engineer", "company": "Nimbus",
                    "first_seen": "2026-09-22T19:30:00",
                    "last_seen": "2026-09-22T19:30:00",
                    "source_id": "builtin:9",
                    "source_ids": ["wellfound:1", "builtin:9"],
                    "reposted_at": "2026-09-22T19:30:00",
                    "also_seen_on": ["wellfound"]},
                "barista|coffee inc": {
                    "title": "Barista", "company": "Coffee Inc",
                    "first_seen": "2026-08-01T10:00:00",
                    "last_seen": "2026-08-01T10:00:00",
                    "source_id": "dice:7", "source_ids": ["dice:7"],
                    "reposted_at": None, "also_seen_on": []},
                "ml engineer|oldco": {
                    "title": "ML Engineer", "company": "OldCo",
                    "first_seen": "2026-09-10T10:00:00",
                    "last_seen": "2026-09-21T21:00:00",
                    "source_id": "remoteok:5", "source_ids": ["remoteok:5"],
                    "reposted_at": None, "also_seen_on": []},
            },
        }

    def test_classification(self):
        from candid import jobs as J
        rep = J.freshness_report(self._state(),
                                 now=datetime(2026, 9, 22, 21, 0, 0))
        self.assertEqual(rep["totals"]["new"], 1)
        self.assertEqual(rep["new"][0]["company"], "Nimbus")
        self.assertEqual(rep["totals"]["reposted"], 1)
        self.assertEqual(rep["reposted"][0]["company"], "Nimbus")
        self.assertEqual(rep["totals"]["stale"], 1)
        self.assertEqual(rep["stale"][0]["company"], "Coffee Inc")

    def test_record_sightings_marks_reposted(self):
        from candid import jobs as J
        state = {"sightings": {}}
        J._record_sightings(
            [{"title": "Backend Engineer", "company": "Nimbus",
              "source_id": "wellfound:1", "also_seen_on": []}],
            state, "2026-09-20T10:00:00")
        J._record_sightings(
            [{"title": "Backend Engineer", "company": "Nimbus",
              "source_id": "builtin:9", "also_seen_on": ["wellfound"]}],
            state, "2026-09-21T10:00:00")
        key = "backend engineer|nimbus"
        rec = state["sightings"][key]
        self.assertEqual(rec["first_seen"], "2026-09-20T10:00:00")
        self.assertEqual(rec["last_seen"], "2026-09-21T10:00:00")
        self.assertEqual(rec["reposted_at"], "2026-09-21T10:00:00")
        self.assertEqual(rec["source_ids"], ["wellfound:1", "builtin:9"])

    def test_render_freshness_sections(self):
        from candid import jobs as J
        text = J.render_freshness(J.freshness_report(
            self._state(), now=datetime(2026, 9, 22, 21, 0, 0)))
        self.assertIn("NEW since last run (1):", text)
        self.assertIn("REPOSTED", text)
        self.assertIn("STALE", text)
        self.assertIn("Nimbus", text)
        self.assertIn("Coffee Inc", text)

    def test_curate_stamps_sightings(self):
        from candid import jobs as J
        from candid import config as C
        td = tempfile.TemporaryDirectory()
        orig_data, orig_tracker = C.DATA_DIR, C.TRACKER_PATH
        C.DATA_DIR = Path(td.name)
        C.TRACKER_PATH = Path(td.name) / "tracker.json"
        try:
            with patch.dict(J.ADAPTERS, {"fake": _fake_fetch(CROSS_BOARD)},
                            clear=True):
                J.curate(PROFILE, "backend engineer", "", remote=True,
                         sources=["fake"])
            state = json.loads((Path(td.name) / "jobs.json").read_text())
            self.assertIn("backend engineer|nimbus", state["sightings"])
            rec = state["sightings"]["backend engineer|nimbus"]
            self.assertTrue(rec["first_seen"])
            self.assertEqual(rec["last_seen"], rec["first_seen"])
        finally:
            C.DATA_DIR = orig_data
            C.TRACKER_PATH = orig_tracker
            td.cleanup()


class SavedSearchTest(unittest.TestCase):
    def setUp(self):
        from candid import config as C
        self.td = tempfile.TemporaryDirectory()
        self.orig_data, self.orig_tracker = C.DATA_DIR, C.TRACKER_PATH
        C.DATA_DIR = Path(self.td.name)
        C.TRACKER_PATH = Path(self.td.name) / "tracker.json"

    def tearDown(self):
        from candid import config as C
        C.DATA_DIR = self.orig_data
        C.TRACKER_PATH = self.orig_tracker
        self.td.cleanup()

    def _adapters(self):
        from candid import jobs as J
        # patch the real "remoteok" key so save_search's source validation
        # passes and run_search's curate hits the fake feed
        return patch.dict(J.ADAPTERS, {"remoteok": _fake_fetch(CROSS_BOARD)},
                          clear=True)

    def test_save_list_round_trip(self):
        from candid import jobs as J
        J.save_search("be-remote", role="backend engineer", remote=True,
                      sources=["remoteok"], min_salary=100000)
        searches = J.list_searches()
        self.assertIn("be-remote", searches)
        p = searches["be-remote"]
        self.assertEqual(p["role"], "backend engineer")
        self.assertTrue(p["remote"])
        self.assertEqual(p["sources"], ["remoteok"])
        self.assertEqual(p["min_salary"], 100000)

    def test_save_rejects_unknown_source(self):
        from candid import jobs as J
        with self.assertRaises(J.JobsError):
            J.save_search("bad", role="x", sources=["nope"])

    def test_save_rejects_empty_name(self):
        from candid import jobs as J
        with self.assertRaises(J.JobsError):
            J.save_search("", role="x")

    def test_run_search_reruns_curate(self):
        from candid import jobs as J
        with self._adapters():
            J.save_search("be-remote", role="backend engineer", remote=True,
                          sources=["remoteok"])
            res = J.run_search("be-remote", PROFILE)
        self.assertEqual(res["fetched"], 2)  # 3 listings in → cross-board dedupe → 2
        self.assertEqual(len(res["added"]), 1)
        self.assertEqual(res["added"][0]["source"], "builtin")
        self.assertEqual(res["added"][0]["also_seen_on"], ["wellfound"])

    def test_run_search_unknown_name(self):
        from candid import jobs as J
        with self.assertRaises(J.JobsError):
            J.run_search("missing", PROFILE)

    def test_delete_search(self):
        from candid import jobs as J
        J.save_search("tmp", role="x")
        self.assertTrue(J.delete_search("tmp"))
        self.assertNotIn("tmp", J.list_searches())
        self.assertFalse(J.delete_search("tmp"))

    def test_cli_search_save_list_freshness_hermetic(self):
        """End-to-end CLI via subprocess with an isolated CANDID_DATA_DIR."""
        env = dict(os.environ,
                   CANDID_DATA_DIR=str(Path(self.td.name) / "cli"))
        for argv in (
            ["jobs", "search-save", "--name", "cli-test",
             "--role", "backend engineer", "--remote",
             "--sources", "remoteok,arbeitnow"],
            ["jobs", "search-list"],
            ["jobs", "freshness"],
            ["jobs", "freshness", "--json"],
        ):
            r = subprocess.run([sys.executable, "-m", "candid", *argv],
                               cwd=str(ROOT), capture_output=True, text=True,
                               timeout=120, env=env)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
        out = subprocess.run(
            [sys.executable, "-m", "candid", "jobs", "search-list", "--json"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120,
            env=env).stdout
        saved = json.loads(out)
        self.assertEqual(saved["cli-test"]["sources"], ["remoteok", "arbeitnow"])


if __name__ == "__main__":
    unittest.main()
