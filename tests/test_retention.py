"""Tests for candid.retention (data retention: archive old terminal apps).

Data paths are redirected into a temp dir by monkeypatching candid.config
attributes (same approach as tests/test_cli_ux.py).
"""
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import retention as R  # noqa: E402


def _iso(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


class RetentionBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-retention-"))
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp
        C.ensure_data_dirs()

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def seed_tracker(self, apps):
        (self.tmp / "tracker.json").write_text(json.dumps(apps))

    def load_tracker(self):
        return json.loads((self.tmp / "tracker.json").read_text())

    def load_archive(self):
        p = self.tmp / "archive.json"
        return json.loads(p.read_text()) if p.exists() else None


class ArchiveOldTests(RetentionBase):
    def seed_mixed(self):
        apps = [
            {"id": 1, "company": "OldCo", "role": "Dev",
             "status": "rejected", "date_added": _iso(400),
             "date_updated": _iso(200)},
            {"id": 2, "company": "RecentCo", "role": "Dev",
             "status": "rejected", "date_added": _iso(60),
             "date_updated": _iso(30)},
            {"id": 3, "company": "ActiveCo", "role": "Dev",
             "status": "applied", "date_added": _iso(400),
             "date_updated": _iso(200)},
            {"id": 4, "company": "InterviewCo", "role": "Dev",
             "status": "selected_for_interview", "date_added": _iso(400),
             "date_updated": _iso(200)},
            {"id": 5, "company": "OfferCo", "role": "Dev",
             "status": "offer", "date_added": _iso(400),
             "date_updated": _iso(250)},
            {"id": 6, "company": "WithdrawnCo", "role": "Dev",
             "status": "withdrawn", "date_added": _iso(400),
             "date_updated": _iso(190)},
            {"id": 7, "company": "BadDateCo", "role": "Dev",
             "status": "rejected", "date_added": "nonsense",
             "date_updated": "not-a-date"},
            {"id": 8, "company": "NoDateCo", "role": "Dev",
             "status": "withdrawn", "date_added": _iso(400)},
        ]
        self.seed_tracker(apps)

    def test_old_terminal_apps_archived_recent_and_active_kept(self):
        self.seed_mixed()
        res = R.archive_old(days=180, data_dir=self.tmp)
        self.assertEqual(res["archived"], [1, 5, 6])
        self.assertFalse(res["dry_run"])

        tracker = self.load_tracker()
        self.assertEqual({a["id"] for a in tracker}, {2, 3, 4, 7, 8})

        archive = self.load_archive()
        self.assertEqual({a["id"] for a in archive}, {1, 5, 6})
        for rec in archive:
            self.assertEqual(rec["archived_on"], date.today().isoformat())
            self.assertIn("company", rec)  # full record preserved

    def test_malformed_dates_never_crash(self):
        self.seed_tracker([
            {"id": 1, "status": "rejected", "date_updated": "not-a-date"},
            {"id": 2, "status": "offer"},                       # missing date
            {"id": 3, "status": "rejected", "date_updated": None},
            {"id": 4, "status": "rejected", "date_updated": ""},
            {"id": 5, "status": "rejected", "date_updated": "2026-13-99"},
            {"id": 6, "status": "rejected", "date_updated": "  "},
        ])
        res = R.archive_old(days=180, data_dir=self.tmp)
        self.assertEqual(res["archived"], [])
        self.assertEqual(res["skipped"], 6)
        self.assertEqual(len(self.load_tracker()), 6)

    def test_dry_run_changes_nothing(self):
        self.seed_mixed()
        before = (self.tmp / "tracker.json").read_bytes()
        res = R.archive_old(days=180, data_dir=self.tmp, dry_run=True)
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["archived"], [1, 5, 6])
        self.assertEqual((self.tmp / "tracker.json").read_bytes(), before)
        self.assertFalse((self.tmp / "archive.json").exists())

    def test_archive_appends_across_runs(self):
        self.seed_tracker([
            {"id": 1, "status": "rejected", "date_updated": _iso(200)},
            {"id": 2, "status": "applied", "date_updated": _iso(200)},
        ])
        R.archive_old(days=180, data_dir=self.tmp)
        # Add another old terminal app and run again: appends, keeps prior.
        self.seed_tracker(self.load_tracker() + [
            {"id": 3, "status": "offer", "date_updated": _iso(300)},
        ])
        res = R.archive_old(days=180, data_dir=self.tmp)
        self.assertEqual(res["archived"], [3])
        archive = self.load_archive()
        self.assertEqual([a["id"] for a in archive], [1, 3])
        self.assertEqual([a["id"] for a in self.load_tracker()], [2])

    def test_custom_days_cutoff(self):
        self.seed_tracker([
            {"id": 1, "status": "rejected", "date_updated": _iso(40)},
            {"id": 2, "status": "rejected", "date_updated": _iso(20)},
        ])
        res = R.archive_old(days=30, data_dir=self.tmp)
        self.assertEqual(res["archived"], [1])
        self.assertEqual([a["id"] for a in self.load_tracker()], [2])

    def test_missing_tracker_is_empty(self):
        res = R.archive_old(days=180, data_dir=self.tmp)
        self.assertEqual(res["archived"], [])
        self.assertEqual(res["skipped"], 0)

    def test_negative_days_rejected(self):
        with self.assertRaises(R.RetentionError):
            R.archive_old(days=-1, data_dir=self.tmp)


class ArchiveStatsTests(RetentionBase):
    def test_empty_archive(self):
        stats = R.archive_stats(data_dir=self.tmp)
        self.assertEqual(stats, {"archived_count": 0, "oldest": None,
                                 "newest": None})

    def test_stats_after_archiving(self):
        self.seed_tracker([
            {"id": 1, "status": "rejected", "date_updated": _iso(200)},
            {"id": 2, "status": "withdrawn", "date_updated": _iso(250)},
        ])
        R.archive_old(days=180, data_dir=self.tmp)
        stats = R.archive_stats(data_dir=self.tmp)
        self.assertEqual(stats["archived_count"], 2)
        self.assertEqual(stats["oldest"], date.today().isoformat())
        self.assertEqual(stats["newest"], date.today().isoformat())

    def test_stats_reflect_manual_archive_dates(self):
        (self.tmp / "archive.json").write_text(json.dumps([
            {"id": 1, "archived_on": "2026-01-01"},
            {"id": 2, "archived_on": "2026-09-01"},
            {"id": 3, "archived_on": "2026-05-15"},
        ]))
        stats = R.archive_stats(data_dir=self.tmp)
        self.assertEqual(stats["archived_count"], 3)
        self.assertEqual(stats["oldest"], "2026-01-01")
        self.assertEqual(stats["newest"], "2026-09-01")


if __name__ == "__main__":
    unittest.main()
