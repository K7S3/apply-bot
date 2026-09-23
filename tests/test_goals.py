"""Tests for candid.goals: set/validate, weekly counts, streaks."""

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import config as C  # noqa: E402
from candid import goals as G  # noqa: E402

# A fixed Tuesday, so week boundaries are deterministic.
TODAY = date(2026, 9, 22)
MONDAY = date(2026, 9, 21)


def _app(i, added):
    return {"id": i, "company": "Acme", "role": "DS", "jd_link": "",
            "status": "applied", "notes": "", "date_added": added,
            "date_updated": added, "prep_pack": ""}


class GoalsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-goals-"))
        self._saved = {name: getattr(C, name)
                       for name in ("TRACKER_PATH", "DATA_DIR")}
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.DATA_DIR = self.tmp

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)

    def write_apps(self, apps):
        C.TRACKER_PATH.write_text(json.dumps(apps), encoding="utf-8")


class SetGoalTest(GoalsBase):
    def test_set_goal_writes_file(self):
        goal = G.set_goal(target=5)
        self.assertEqual(goal["kind"], "applications_per_week")
        self.assertEqual(goal["target"], 5)
        self.assertIn("created", goal)
        stored = json.loads((self.tmp / "goals.json").read_text())
        self.assertEqual(stored["target"], 5)

    def test_set_goal_replaces_existing(self):
        G.set_goal(target=5)
        G.set_goal(target=3)
        stored = json.loads((self.tmp / "goals.json").read_text())
        self.assertEqual(stored["target"], 3)

    def test_invalid_kind(self):
        with self.assertRaises(G.GoalsError) as cm:
            G.set_goal(kind="offers_per_week", target=2)
        self.assertIn("applications_per_week", str(cm.exception))

    def test_invalid_targets(self):
        for bad in (0, -3, "5", 2.5, True, None):
            with self.subTest(target=bad):
                with self.assertRaises(G.GoalsError):
                    G.set_goal(target=bad)


class GoalStatusTest(GoalsBase):
    def test_no_goal_raises_with_next_command(self):
        self.write_apps([])
        with self.assertRaises(G.GoalsError) as cm:
            G.goal_status(today=TODAY)
        self.assertTrue(str(cm.exception).rstrip().endswith(
            "Next: run `python -m candid goals set --target 5`"))

    def test_weekly_count(self):
        self.write_apps([
            _app(1, "2026-09-21"),  # Monday: current week
            _app(2, "2026-09-21"),
            _app(3, "2026-09-21"),
            _app(4, "2026-09-22"),  # today: current week
            _app(5, "2026-09-20"),  # Sunday: last week, not counted
        ])
        G.set_goal(target=5)
        st = G.goal_status(today=TODAY)
        self.assertEqual(st["kind"], "applications_per_week")
        self.assertEqual(st["target"], 5)
        self.assertEqual(st["current"], 4)
        self.assertEqual(st["remaining"], 1)
        self.assertFalse(st["met"])
        self.assertEqual(st["streak_weeks"], 0)

    def test_goal_met(self):
        self.write_apps([_app(i, "2026-09-21") for i in range(1, 7)])
        G.set_goal(target=5)
        st = G.goal_status(today=TODAY)
        self.assertTrue(st["met"])
        self.assertEqual(st["remaining"], 0)
        self.assertEqual(st["current"], 6)

    def test_streak_counts_consecutive_past_weeks(self):
        # target 3: prev week 3 (met), week before 3 (met), week before that 1 (missed)
        prev = MONDAY - timedelta(weeks=1)
        apps = []
        for wk in range(3):
            start = prev - timedelta(weeks=wk)
            n = 3 if wk < 2 else 1
            for j in range(n):
                apps.append(_app(len(apps) + 1,
                                 (start + timedelta(days=j)).isoformat()))
        self.write_apps(apps)
        G.set_goal(target=3)
        st = G.goal_status(today=TODAY)
        self.assertEqual(st["streak_weeks"], 2)

    def test_streak_excludes_current_week(self):
        # current week apps must not inflate the streak
        self.write_apps([_app(1, "2026-09-21"), _app(2, "2026-09-22")])
        G.set_goal(target=2)
        st = G.goal_status(today=TODAY)
        self.assertTrue(st["met"])
        self.assertEqual(st["streak_weeks"], 0)

    def test_long_streak(self):
        apps = []
        for wk in range(4):
            start = MONDAY - timedelta(weeks=wk + 1)
            for j in range(2):
                apps.append(_app(len(apps) + 1,
                                 (start + timedelta(days=j)).isoformat()))
        self.write_apps(apps)
        G.set_goal(target=2)
        st = G.goal_status(today=TODAY)
        self.assertEqual(st["streak_weeks"], 4)

    def test_streak_respects_real_today(self):
        # no today= passed: must not crash, keys present
        self.write_apps([])
        G.set_goal(target=5)
        st = G.goal_status()
        self.assertEqual(set(st), {"kind", "target", "current",
                                  "remaining", "met", "streak_weeks"})


class RenderGoalsTest(GoalsBase):
    def test_render_not_met(self):
        out = G.render_goals({"kind": "applications_per_week", "target": 5,
                              "current": 4, "remaining": 1, "met": False,
                              "streak_weeks": 2})
        self.assertIn("Goal: 5 applications/week", out)
        self.assertIn("This week: 4/5", out)
        self.assertIn("1 more", out)
        self.assertIn("Streak: 2 weeks", out)

    def test_render_met(self):
        out = G.render_goals({"kind": "applications_per_week", "target": 5,
                              "current": 5, "remaining": 0, "met": True,
                              "streak_weeks": 3})
        self.assertIn("Goal met", out)
        self.assertIn("Streak: 3 weeks", out)


if __name__ == "__main__":
    unittest.main()
