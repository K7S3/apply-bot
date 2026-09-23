"""Tests for the pre-interview ritual modules: ritual_calm and ritual_countdown.

Run: cd <repo> && python -m unittest discover -s tests
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix="candid-ritual-test-")
os.environ["CANDID_DATA_DIR"] = _TMPDIR

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import ritual_calm as RC          # noqa: E402
from candid import ritual_countdown as RCD    # noqa: E402


class _HermeticDataDir(unittest.TestCase):
    """Point CANDID_DATA_DIR at this module's temp dir for every test.

    Sibling test modules assign the same env var at import time; without a
    per-test reset, whichever module is imported last wins and the modules
    under test (which resolve the data dir at call time) read the wrong
    profile.json.
    """

    def setUp(self):
        self._old_candid_data_dir = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = _TMPDIR

    def tearDown(self):
        old = getattr(self, "_old_candid_data_dir", None)
        if old is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = old


def _run_quiet(func, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = func(*args, **kwargs)
    return result, buf.getvalue()


def _profile_path():
    return Path(_TMPDIR) / "profile.json"


def _write_profile(profile):
    _profile_path().write_text(json.dumps(profile), encoding="utf-8")


def _remove_profile():
    try:
        _profile_path().unlink()
    except FileNotFoundError:
        pass


class CalmRoutineTest(_HermeticDataDir):
    def setUp(self):
        super().setUp()
        _remove_profile()

    def tearDown(self):
        _remove_profile()
        super().tearDown()

    def test_no_wait_is_instant(self):
        started = time.perf_counter()
        _run_quiet(RC.run_calm, cycles=4, no_wait=True)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0, "no_wait run should be instant")

    def test_result_structure(self):
        result, _ = _run_quiet(RC.run_calm, cycles=4, no_wait=True)
        self.assertEqual(result["routine"], "calm")
        self.assertEqual(result["cycles"], 4)
        self.assertEqual(len(result["breathing"]["phases_done"]), 16)
        phases = [p["phase"] for p in result["breathing"]["phases_done"]]
        self.assertEqual(phases[:4], ["inhale", "hold", "exhale", "hold"])
        self.assertEqual(len(result["grounding"]), 5)
        self.assertEqual(len(result["affirmations"]), 3)
        self.assertEqual(len(result["reframes"]), 2)

    def test_cycles_param_controls_phases(self):
        result, _ = _run_quiet(RC.run_calm, cycles=2, no_wait=True)
        self.assertEqual(result["cycles"], 2)
        self.assertEqual(len(result["breathing"]["phases_done"]), 8)

    def test_cycles_floor_at_one(self):
        result, _ = _run_quiet(RC.run_calm, cycles=0, no_wait=True)
        self.assertEqual(result["cycles"], 1)
        self.assertEqual(len(result["breathing"]["phases_done"]), 4)

    def test_affirmations_from_real_profile(self):
        _write_profile({
            "name": "Test User",
            "headline": "Backend Engineer",
            "skills": ["python", "sql", "kafka"],
            "years_experience": 5,
            "seniority": "mid",
        })
        result, _ = _run_quiet(RC.run_calm, cycles=1, no_wait=True)
        self.assertTrue(result["profile_used"])
        joined = " ".join(result["affirmations"])
        self.assertIn("python", joined)
        self.assertIn("sql", joined)
        self.assertIn("5 years", joined)
        self.assertIn("Backend Engineer", joined)

    def test_affirmations_generic_without_profile(self):
        result, _ = _run_quiet(RC.run_calm, cycles=1, no_wait=True)
        self.assertFalse(result["profile_used"])
        self.assertEqual(list(result["affirmations"]), RC.GENERIC_AFFIRMATIONS)
        joined = " ".join(result["affirmations"]).lower()
        for invented in ("python", "sql", "engineer", "years"):
            self.assertNotIn(invented, joined,
                             "generic affirmations must not fabricate specifics")

    def test_explicit_profile_arg_wins(self):
        result, _ = _run_quiet(
            RC.run_calm, cycles=1, no_wait=True,
            profile={"name": "Ava", "headline": "Designer", "skills": ["figma"]},
        )
        self.assertTrue(result["profile_used"])
        self.assertIn("figma", " ".join(result["affirmations"]))

    def test_calm_output_has_no_em_dashes(self):
        _, out = _run_quiet(RC.run_calm, cycles=2, no_wait=True)
        self.assertNotIn("\u2014", out)
        self.assertNotIn("\u2013", out)


class CountdownPlanTest(_HermeticDataDir):
    START = datetime(2026, 9, 25, 14, 0)

    def test_build_countdown_returns_time_label_pairs(self):
        items = RCD.build_countdown(self.START)
        self.assertTrue(items)
        for when, label in items:
            self.assertIsInstance(when, datetime)
            self.assertIsInstance(label, str)
            self.assertTrue(label)

    def test_checklist_is_chronological(self):
        items = RCD.build_countdown(self.START)
        times = [when for when, _ in items]
        self.assertEqual(times, sorted(times))

    def test_anchors_back_calculated(self):
        items = {label: when for when, label in RCD.build_countdown(self.START)}
        wake = self.START - timedelta(hours=RCD.WAKE_LEAD_HOURS)
        bedtime = wake - timedelta(hours=RCD.SLEEP_HOURS)
        self.assertIn("Wake up", items)
        self.assertEqual(items["Wake up"], wake)
        bedtime_label = (
            f"Bedtime: 8 hours of sleep before your "
            f"{wake.strftime('%H:%M')} wake-up"
        )
        self.assertIn(bedtime_label, items)
        self.assertEqual(items[bedtime_label], bedtime)
        self.assertEqual(
            items["Interview time. Breathe. You prepared for this"], self.START
        )

    def test_evening_items_land_day_before(self):
        items = RCD.build_countdown(self.START)
        first = items[0][0]
        self.assertEqual(first.date(), self.START.date() - timedelta(days=1))
        self.assertEqual((first.hour, first.minute), (19, 0))

    def test_key_items_present(self):
        labels = " | ".join(l for _, l in RCD.build_countdown(self.START))
        for needle in (
            "Nothing new after 9pm",
            "Real breakfast, no skipping",
            "Join the call early",
            "light walk",
        ):
            self.assertIn(needle, labels)

    def test_reminder_texts(self):
        reminders = RCD.reminder_texts(self.START)
        self.assertEqual(len(reminders), 5)
        for rem in reminders:
            self.assertIn("at", rem)
            self.assertIn("text", rem)
            datetime.strptime(rem["at"], "%Y-%m-%d %H:%M")

    def test_result_is_json_serializable(self):
        result = RCD.countdown_result(self.START)
        dumped = json.dumps(result)
        back = json.loads(dumped)
        self.assertEqual(len(back["checklist"]), len(RCD.build_countdown(self.START)))
        self.assertEqual(back["sleep_target_hours"], RCD.SLEEP_HOURS)

    def test_parse_start(self):
        self.assertEqual(
            RCD.parse_start("2026-09-25 14:00"), self.START
        )
        with self.assertRaises(ValueError):
            RCD.parse_start("not a date")

    def test_main_text_output(self):
        _, out = _run_quiet(
            RCD.main, ["--start", "2026-09-25 14:00"]
        )
        self.assertIn("Interview countdown", out)
        self.assertIn("Nothing new after 9pm", out)
        self.assertNotIn("\u2014", out)

    def test_main_json_output(self):
        result, out = _run_quiet(
            RCD.main, ["--start", "2026-09-25 14:00", "--json"]
        )
        self.assertEqual(result, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["start"], "2026-09-25 14:00")


if __name__ == "__main__":
    unittest.main()
