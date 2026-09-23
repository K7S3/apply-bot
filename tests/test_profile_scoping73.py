"""Batch-73 worker C: per-profile scoping tests.

Two profiles (activated via ``profiles.set_request_profile`` when the
candid.profiles module provides it, else the CANDID_PROFILE env var):
- tracker entries are isolated per profile,
- tailor outputs land in the active profile's tailored dir,
- prep packs land in the active profile's prep dir,
- adding a duplicate company+role under another profile warns (stderr)
  but still adds,
- the default profile keeps using the legacy module-level constants
  (backward compat).

Isolation: C.DATA_DIR is patched to a temp dir for the whole test case so
no test data touches the real data directory.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

# Isolate at import time when this module is the first to import candid.
os.environ.setdefault("CANDID_DATA_DIR",
                      tempfile.mkdtemp(prefix="candid73-import-"))

from candid import config as C  # noqa: E402

try:
    from candid import profiles  # noqa: E402
    _HAS_SETTER = hasattr(profiles, "set_request_profile")
except ImportError:
    profiles = None  # type: ignore[assignment]
    _HAS_SETTER = False

from candid import prep, profile as P, tailor, tracker  # noqa: E402

RESUME_TEXT = """\
Test User
Senior Data Scientist | New York, NY | test@example.com

SUMMARY
Data scientist with 5 years of experience.

EXPERIENCE
Senior Data Scientist - Fictional Corp, Jan 2021 - Present
- Built churn models with Python and SQL, lifting retention 12%.
- Led A/B testing program across 3 product teams.

Data Scientist - Other Inc, Jun 2019 - Dec 2020
- Dashboards in Tableau for executive stakeholders.

SKILLS
Python, SQL, machine learning, statistics, Tableau

EDUCATION
State University - B.S. Computer Science, 2015 - 2019
"""


def _activate(name):
    """Activate a profile: setter first, CANDID_PROFILE env as fallback.

    Creates the profile on first use (the real profiles module validates
    names on set_request_profile).
    """
    if _HAS_SETTER:
        if name is not None:
            try:
                profiles.create_profile(name)
            except Exception:
                pass  # already exists
        profiles.set_request_profile(name)
    elif name is None:
        os.environ.pop("CANDID_PROFILE", None)
    else:
        os.environ["CANDID_PROFILE"] = name


def _deactivate(prev_env):
    """Restore the profile state that was active before the test."""
    try:
        if _HAS_SETTER:
            profiles.set_request_profile(prev_env)
    except Exception:
        pass
    if prev_env is None:
        os.environ.pop("CANDID_PROFILE", None)
    else:
        os.environ["CANDID_PROFILE"] = prev_env


class ProfileScopingTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(prefix="candid73-")
        self.orig_data_dir = C.DATA_DIR
        self.orig_config_dir = C.CONFIG_DIR
        C.DATA_DIR = Path(self.td.name) / "data"
        C.CONFIG_DIR = Path(self.td.name) / "config"
        self.prev_env = os.environ.get("CANDID_PROFILE")
        _deactivate(None)  # start from a clean "default" state

    def tearDown(self):
        _deactivate(self.prev_env)
        C.DATA_DIR = self.orig_data_dir
        C.CONFIG_DIR = self.orig_config_dir
        self.td.cleanup()

    # -- tracker isolation ------------------------------------------------
    def test_track_add_isolated_per_profile(self):
        _activate("data-scientist")
        rec = tracker.add("Acme", "SWE")
        self.assertEqual(rec["id"], 1)

        _activate("backend-dev")
        self.assertEqual(tracker.list_apps(), [])

        _activate("data-scientist")
        apps = tracker.list_apps()
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["company"], "Acme")

    def test_cross_profile_duplicate_warns_but_still_adds(self):
        _activate("data-scientist")
        tracker.add("Acme", "SWE")

        _activate("backend-dev")
        err = io.StringIO()
        with redirect_stderr(err):
            rec = tracker.add("Acme", "SWE")
        self.assertFalse(rec.get("duplicate"),
                         "cross-profile match must not block the add")
        self.assertIn("warning: 'Acme / SWE' is already tracked under "
                      "profile 'data-scientist'; adding here too.",
                      err.getvalue())
        apps = tracker.list_apps()
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["company"], "Acme")

    def test_cross_profile_duplicate_case_insensitive(self):
        _activate("data-scientist")
        tracker.add("  ACME ", "swe")

        _activate("backend-dev")
        err = io.StringIO()
        with redirect_stderr(err):
            tracker.add("acme", "SWE")
        self.assertIn("warning:", err.getvalue())

    def test_warning_degrades_gracefully_without_profiles(self):
        # The cross-profile warning must never break `track add`, even if
        # per-profile support raises.
        _activate("backend-dev")
        err = io.StringIO()
        with mock.patch("candid.profiles.list_profiles",
                        side_effect=RuntimeError("nope")):
            with redirect_stderr(err):
                rec = tracker.add("Solo", "Engineer")
        self.assertEqual(err.getvalue(), "")
        self.assertFalse(rec.get("duplicate"))

    # -- tailor -----------------------------------------------------------
    def test_tailor_output_lands_in_profile_tailored_dir(self):
        _activate("data-scientist")
        prof = P.build_profile([RESUME_TEXT])
        text = tailor.build_resume(prof, "Python SQL machine learning",
                                   company="Acme", role="SWE")
        out = tailor.save_tailored(text, company="Acme", role="SWE",
                                   kind="resume")
        self.assertEqual(out.parent, C.tailored_dir())
        self.assertTrue(out.exists())
        self.assertNotEqual(C.tailored_dir(), C.TAILOR_DIR)

        _activate("backend-dev")
        other_dir = C.tailored_dir()
        self.assertNotEqual(other_dir, out.parent)
        self.assertFalse((other_dir / out.name).exists())

    # -- prep -------------------------------------------------------------
    def test_prep_pack_lands_in_profile_prep_dir(self):
        _activate("data-scientist")
        prof = P.build_profile([RESUME_TEXT])
        md, path = prep.build_pack(prof, "Fictional Corp", "Data Scientist")
        self.assertEqual(path.parent, C.prep_packs_dir())
        self.assertTrue(path.exists())
        self.assertNotEqual(C.prep_packs_dir(), C.PREP_PACKS_DIR)

    # -- profile load/save + onboard --------------------------------------
    def test_profile_load_save_scoped_per_profile(self):
        resume_file = Path(self.td.name) / "resume.txt"
        resume_file.write_text(RESUME_TEXT, encoding="utf-8")

        _activate("data-scientist")
        prof = P.onboard(resume_path=resume_file)
        self.assertEqual(P.load_profile()["name"], prof["name"])
        self.assertEqual(C.profile_json_path().parent.name, "data-scientist")

        _activate("backend-dev")
        with self.assertRaises(P.OnboardError):
            P.load_profile()

    # -- backward compat --------------------------------------------------
    def test_default_profile_uses_legacy_constants(self):
        _activate(None)
        self.assertEqual(C.tracker_path(), C.TRACKER_PATH)
        self.assertEqual(C.profile_json_path(), C.PROFILE_PATH)
        self.assertEqual(C.prep_packs_dir(), C.PREP_PACKS_DIR)
        self.assertEqual(C.tailored_dir(), C.TAILOR_DIR)
        self.assertEqual(C.offers_path(), C.OFFERS_PATH)
        self.assertEqual(C.salary_db_path(), C.SALARY_DB)

    def test_default_track_add_writes_legacy_path(self):
        orig_tracker = C.TRACKER_PATH
        legacy = Path(self.td.name) / "legacy-tracker.json"
        C.TRACKER_PATH = legacy
        try:
            _activate(None)
            tracker.add("Hooli", "SWE")
            self.assertTrue(legacy.exists())
            rows = json.loads(legacy.read_text(encoding="utf-8"))
            self.assertEqual(rows[0]["company"], "Hooli")
        finally:
            C.TRACKER_PATH = orig_tracker


if __name__ == "__main__":
    unittest.main()
