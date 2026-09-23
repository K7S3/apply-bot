"""Tests for batch 10 workstream B: candid.profiles and candid.doctor.

- profiles: CRUD round-trip in a temp CANDID_CONFIG_DIR.
- doctor: fails gracefully with fix hints on an empty dir, exits 0 on a
  healthy dir, and --json output parses.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from candid import doctor as D
from candid import profiles as P


def _env(tmp: Path) -> dict:
    return {
        "CANDID_CONFIG_DIR": str(tmp / "config"),
        "CANDID_DATA_DIR": str(tmp / "data"),
    }


def _run_profiles(**kwargs) -> tuple[int, str, str]:
    """Run cmd_profiles with a synthetic namespace; capture output."""
    ns = {"what": None}
    ns.update(kwargs)
    a = argparse.Namespace(**ns)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = P.cmd_profiles(a)
    return code, out.getvalue(), err.getvalue()


def _run_doctor(as_json: bool = False) -> tuple[int, str]:
    a = argparse.Namespace(json=as_json)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = D.cmd_doctor(a)
    return code, out.getvalue()


class TestProfiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = mock.patch.dict(os.environ, _env(Path(self.tmp.name)))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    # -- CRUD round trip ------------------------------------------------
    def test_crud_round_trip(self):
        code, out, _ = _run_profiles(
            what="create", name="ml-nyc", role="Machine Learning Engineer",
            seniority="senior", domains="ads ranking,recommendations",
            locations="New York NY,Remote", min_salary=180000.0,
            notes="product teams")
        self.assertEqual(code, 0)
        self.assertIn("Created profile 'ml-nyc'", out)

        code, out, _ = _run_profiles(what="list")
        self.assertEqual(code, 0)
        self.assertIn("ml-nyc", out)
        self.assertNotIn("*", out)  # nothing active yet

        code, out, _ = _run_profiles(what="use", name="ml-nyc")
        self.assertEqual(code, 0)
        self.assertIn("Active profile: ml-nyc", out)

        active = P.get_active_profile()
        self.assertEqual(active["target_role"], "Machine Learning Engineer")
        self.assertEqual(active["seniority"], "senior")
        self.assertEqual(active["domains"], ["ads ranking", "recommendations"])
        self.assertEqual(active["locations"], ["New York NY", "Remote"])
        self.assertEqual(active["min_salary"], 180000.0)

        code, out, _ = _run_profiles(what="list")
        self.assertIn("ml-nyc *", out)

        code, out, _ = _run_profiles(
            what="update", name="ml-nyc", role=None, seniority=None,
            domains="llm", locations=None, min_salary=200000.0, notes=None)
        self.assertEqual(code, 0)
        shown = P.show_profile("ml-nyc")
        self.assertEqual(shown["domains"], ["llm"])
        self.assertEqual(shown["min_salary"], 200000.0)
        self.assertEqual(shown["target_role"], "Machine Learning Engineer")

        code, out, _ = _run_profiles(what="show", name="ml-nyc")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["name"], "ml-nyc")

        code, out, _ = _run_profiles(what="delete", name="ml-nyc")
        self.assertEqual(code, 0)
        self.assertEqual(P.list_profiles(), [])
        # deleting the active profile clears the pointer
        self.assertIsNone(P.get_active_profile_name())
        with self.assertRaises(P.ProfilesError):
            P.get_active_profile()

    # -- error paths ----------------------------------------------------
    def test_create_duplicate_fails_cleanly(self):
        _run_profiles(what="create", name="a", role="R", seniority=None,
                      domains=None, locations=None, min_salary=None, notes=None)
        code, out, err = _run_profiles(
            what="create", name="a", role="R", seniority=None,
            domains=None, locations=None, min_salary=None, notes=None)
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertIn("profiles update", err)

    def test_invalid_name_rejected(self):
        code, out, err = _run_profiles(
            what="create", name="bad name!", role="R", seniority=None,
            domains=None, locations=None, min_salary=None, notes=None)
        self.assertEqual(code, 1)
        self.assertIn("Invalid profile name", err)
        self.assertIn("Fix:", err)

    def test_missing_role_rejected(self):
        code, out, err = _run_profiles(
            what="create", name="norole", role="", seniority=None,
            domains=None, locations=None, min_salary=None, notes=None)
        self.assertEqual(code, 1)
        self.assertIn("target_role", err)

    def test_use_missing_profile_fails(self):
        code, out, err = _run_profiles(what="use", name="ghost")
        self.assertEqual(code, 1)
        self.assertIn("No profile named 'ghost'", err)

    def test_bad_seniority_rejected(self):
        code, out, err = _run_profiles(
            what="create", name="x", role="R", seniority="wizard",
            domains=None, locations=None, min_salary=None, notes=None)
        self.assertEqual(code, 1)
        self.assertIn("seniority", err)

    def test_corrupt_json_reports_fix(self):
        d = P.profiles_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "broken.json").write_text("{not json", encoding="utf-8")
        code, out, err = _run_profiles(what="show", name="broken")
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", err)
        self.assertIn("Fix:", err)

    def test_show_defaults_to_active(self):
        _run_profiles(what="create", name="one", role="R", seniority=None,
                      domains=None, locations=None, min_salary=None, notes=None)
        _run_profiles(what="use", name="one")
        self.assertEqual(P.show_profile()["name"], "one")
        self.assertEqual(P.show_profile(None)["name"], "one")


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = mock.patch.dict(os.environ, _env(Path(self.tmp.name)))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_empty_dir_fails_with_fix_hints(self):
        code, out = _run_doctor()
        self.assertEqual(code, 1)  # at least one FAIL
        self.assertIn("[FAIL]", out)
        self.assertIn("Fix:", out)
        self.assertIn("onboard --resume", out)
        self.assertIn("doctor:", out)

    def test_healthy_dir_exits_zero(self):
        data = Path(self.tmp.name) / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "profile.json").write_text(
            json.dumps({"name": "K", "skills": ["python"]}), encoding="utf-8")
        (data / "tracker.json").write_text("[]", encoding="utf-8")
        code, out = _run_doctor()
        # ollama/disk can only WARN; nothing should FAIL
        self.assertEqual(code, 0)
        self.assertNotIn("[FAIL]", out)
        self.assertIn("[PASS] profile-json", out)
        self.assertIn("[PASS] tracker-json", out)

    def test_json_output_parseable(self):
        code, out = _run_doctor(as_json=True)
        payload = json.loads(out)
        self.assertIn("ok", payload)
        self.assertIn("summary", payload)
        self.assertIn("checks", payload)
        self.assertEqual(payload["ok"], code == 0)
        names = {c["name"] for c in payload["checks"]}
        for expected in ("python-version", "data-dir", "profile-json",
                         "tracker-json", "ollama", "disk-space",
                         "samples-dir", "config-dir-writable"):
            self.assertIn(expected, names)
        for c in payload["checks"]:
            self.assertIn(c["status"], ("PASS", "WARN", "FAIL"))

    def test_invalid_tracker_json_fails(self):
        data = Path(self.tmp.name) / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "profile.json").write_text(
            json.dumps({"name": "K", "skills": ["python"]}), encoding="utf-8")
        (data / "tracker.json").write_text("{broken", encoding="utf-8")
        code, out = _run_doctor()
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] tracker-json", out)
        self.assertIn("Fix:", out)

    def test_ollama_never_fails(self):
        # Even with no Ollama running, the check must be WARN at worst.
        checks = {c.name: c for c in D.run_checks()}
        self.assertIn(checks["ollama"].status, ("PASS", "WARN"))


if __name__ == "__main__":
    unittest.main()
