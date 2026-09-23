"""Wiring tests for batch 20: remote-work deep sources integration.

Covers: adapter registry (new sources resolvable), --remote-only curate path,
timezone notes in curated tracker entries, and CLI flag plumbing. Network
adapters are mocked; no real HTTP is made.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _job(source, sid, title, company, location, remote, description=""):
    return {"source": source, "source_id": sid, "title": title,
            "company": company, "location": location, "remote": remote,
            "url": f"https://example.com/{sid}", "posted_at": "",
            "description": description or "Python machine learning role.",
            "salary_text": ""}


FAKE_REMOTE = [
    _job("weworkremotely", "weworkremotely:1", "Senior ML Engineer", "Acme",
         "Worldwide", True, "remote-first team, async communication, Python"),
    _job("jobspresso", "jobspresso:1", "Data Scientist", "Beta",
         "New York, NY", False),
]

PROFILE = {"name": "Alex Rivera",
           "skills": ["python", "machine learning", "sql"],
           "seniority": "senior", "years_experience": 6.5,
           "experience": [{"company": "Meridian", "title": "Senior Data Scientist"}]}


class RemoteWiringTest(unittest.TestCase):
    def test_all_adapters_includes_remote_sources(self):
        from candid import jobs as J
        adapters = J._all_adapters()
        for name in ("arbeitnow", "remoteok", "weworkremotely", "himalayas",
                     "jobspresso", "remotive"):
            self.assertIn(name, adapters, name)
            self.assertTrue(callable(adapters[name]))

    def test_curate_unknown_source_lists_all(self):
        from candid import jobs as J
        with self.assertRaises(J.JobsError) as ctx:
            J.curate(PROFILE, "x", sources=["nope"])
        self.assertIn("weworkremotely", str(ctx.exception))

    def test_curate_remote_only_drops_onsite(self):
        from candid import jobs as J
        from candid import config as C
        td = tempfile.TemporaryDirectory()
        orig_data, orig_tracker = C.DATA_DIR, C.TRACKER_PATH
        C.DATA_DIR = Path(td.name)
        C.TRACKER_PATH = Path(td.name) / "tracker.json"
        try:
            with patch.dict(J.ADAPTERS, {"fake": lambda: FAKE_REMOTE}, clear=True):
                res = J.curate(PROFILE, "ml engineer", "", sources=["fake"],
                               remote_only=True)
            self.assertEqual(res["fetched"], 2)
            self.assertEqual([j["source_id"] for j in res["added"]],
                             ["weworkremotely:1"])
        finally:
            C.DATA_DIR, C.TRACKER_PATH = orig_data, orig_tracker
            td.cleanup()

    def test_curate_adds_tz_note(self):
        from candid import jobs as J
        from candid import tracker as T
        from candid import config as C
        td = tempfile.TemporaryDirectory()
        orig_data, orig_tracker = C.DATA_DIR, C.TRACKER_PATH
        C.DATA_DIR = Path(td.name)
        C.TRACKER_PATH = Path(td.name) / "tracker.json"
        try:
            with patch.dict(J.ADAPTERS, {"fake": lambda: FAKE_REMOTE}, clear=True):
                J.curate(PROFILE, "ml engineer", "", sources=["fake"],
                         remote_only=True, home_tz="America/New_York")
            apps = T.list_apps(path=C.TRACKER_PATH)
            self.assertEqual(len(apps), 1)
            self.assertIn("tz overlap", apps[0]["notes"])
        finally:
            C.DATA_DIR, C.TRACKER_PATH = orig_data, orig_tracker
            td.cleanup()

    def test_curate_bad_home_tz_still_works(self):
        from candid import jobs as J
        from candid import config as C
        td = tempfile.TemporaryDirectory()
        orig_data, orig_tracker = C.DATA_DIR, C.TRACKER_PATH
        C.DATA_DIR = Path(td.name)
        C.TRACKER_PATH = Path(td.name) / "tracker.json"
        try:
            with patch.dict(J.ADAPTERS, {"fake": lambda: FAKE_REMOTE}, clear=True):
                res = J.curate(PROFILE, "ml engineer", "", sources=["fake"],
                               home_tz="Not/AZone")
            self.assertEqual(len(res["added"]), 1)
        finally:
            C.DATA_DIR, C.TRACKER_PATH = orig_data, orig_tracker
            td.cleanup()

    def test_refresh_passes_remote_only_through(self):
        from candid import jobs as J
        from candid import config as C
        td = tempfile.TemporaryDirectory()
        orig_data, orig_tracker = C.DATA_DIR, C.TRACKER_PATH
        C.DATA_DIR = Path(td.name)
        C.TRACKER_PATH = Path(td.name) / "tracker.json"
        try:
            with patch.dict(J.ADAPTERS, {"fake": lambda: FAKE_REMOTE}, clear=True):
                res = J.refresh(PROFILE, "ml engineer", "", sources=["fake"],
                                remote_only=True)
            self.assertEqual([j["source_id"] for j in res["added"]],
                             ["weworkremotely:1"])
        finally:
            C.DATA_DIR, C.TRACKER_PATH = orig_data, orig_tracker
            td.cleanup()

    def test_remote_boost_favors_remote_friendly_in_remote_mode(self):
        from candid import jobs as J
        plain = _job("fake", "fake:1", "ML Engineer", "A", "Remote", True,
                     "Python machine learning role.")
        friendly = _job("fake", "fake:2", "ML Engineer", "B", "Remote", True,
                        "Python machine learning role. remote-first, async, "
                        "distributed team, work from anywhere.")
        out = J.filter_jobs([plain, friendly], "ml engineer", "", True, None, 25)
        self.assertEqual(out[0]["source_id"], "fake:2")

    def test_remote_boost_off_by_default(self):
        from candid import jobs as J
        plain = _job("fake", "fake:1", "ML Engineer", "A", "Remote", True,
                     "Python machine learning role.")
        friendly = _job("fake", "fake:2", "ML Engineer", "B", "Remote", True,
                        "Python machine learning role. remote-first, async.")
        out = J.filter_jobs([plain, friendly], "ml engineer", "", False, None, 25)
        # default ranking is stable order by relevance: identical relevance,
        # so original order is preserved
        self.assertEqual([j["source_id"] for j in out], ["fake:1", "fake:2"])


if __name__ == "__main__":
    unittest.main()
