"""Tests for `candid version` / `candid --version` and the PyPI update notifier.

The update checker is fully offline-safe: HTTP is always mocked here;
real network behavior (errors, timeouts) is simulated with fakes.
"""
import contextlib
import io
import json
import socket
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import __version__  # noqa: E402
from candid import config as C  # noqa: E402
from candid import versioning as V  # noqa: E402


class FakeHTTPResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TtyStdout(io.StringIO):
    def isatty(self):
        return True


def pypi_payload(version):
    return {"info": {"version": version}}


class VersionCommandTests(unittest.TestCase):
    def run_cli(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            CLI.main(argv)
        return buf.getvalue()

    def test_version_flag(self):
        # --version exits via argparse; capture it
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            CLI.build_parser().parse_args(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn(__version__, buf.getvalue())

    def test_version_subcommand(self):
        out = self.run_cli(["version"])
        self.assertIn(f"candid {__version__}", out)
        self.assertIn("Python", out)
        # platform info present (e.g. "Linux x86_64")
        self.assertRegex(out, r"candid \S+ \(Python [0-9.]+, .+\)")

    def test_single_source_of_truth(self):
        out = self.run_cli(["version"])
        self.assertIn(__version__, out)
        self.assertEqual(__version__, "0.3.0")

    def test_version_in_command_inventory(self):
        self.assertIn("version", CLI.COMMANDS)


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / "data"
        self.config_dir = Path(self.tmp.name) / "cfg"
        self.data_dir.mkdir()
        self.config_dir.mkdir()
        # Redirect the module-level paths like the other test files do.
        self._orig = {}
        for name, val in (("DATA_DIR", self.data_dir),
                          ("CONFIG_PATH", self.config_dir / "config.yaml")):
            self._orig[name] = getattr(C, name)
            setattr(C, name, val)

    def tearDown(self):
        for name, val in self._orig.items():
            setattr(C, name, val)

    # -- helpers ---------------------------------------------------------
    def mock_pypi(self, version=None, exc=None, timeout_sentinel=None):
        """Patch urlopen: return a fake PyPI payload, raise, or record args."""
        calls = {}

        def fake(req, timeout=None):
            calls["timeout"] = timeout
            calls["url"] = req.full_url
            if timeout_sentinel is not None:
                raise socket.timeout("timed out")
            if exc is not None:
                raise exc
            return FakeHTTPResponse(pypi_payload(version))

        patcher = mock.patch.object(V.urllib.request, "urlopen", side_effect=fake)
        self.addCleanup(patcher.stop)
        patcher.start()
        return calls

    def write_config(self, text):
        (self.config_dir / "config.yaml").write_text(text, encoding="utf-8")

    # -- check_for_update --------------------------------------------------
    def test_newer_available(self):
        calls = self.mock_pypi(version="0.4.0")
        info = V.check_for_update()
        self.assertIsNotNone(info)
        self.assertTrue(info["update_available"])
        self.assertEqual(info["latest"], "0.4.0")
        self.assertEqual(info["current"], __version__)
        self.assertEqual(calls["url"], V.PYPI_JSON_URL)
        self.assertLessEqual(calls["timeout"], 5.0)

    def test_up_to_date(self):
        self.mock_pypi(version=__version__)
        info = V.check_for_update()
        self.assertIsNotNone(info)
        self.assertFalse(info["update_available"])

    def test_older_on_pypi(self):
        self.mock_pypi(version="0.1.0")
        info = V.check_for_update()
        self.assertFalse(info["update_available"])

    def test_network_error_returns_none(self):
        self.mock_pypi(exc=urllib.error.URLError("no route to host"))
        self.assertIsNone(V.check_for_update())

    def test_timeout_returns_none(self):
        self.mock_pypi(timeout_sentinel=True)
        self.assertIsNone(V.check_for_update())

    def test_malformed_payload_returns_none(self):
        def fake(req, timeout=None):
            return FakeHTTPResponse({"nope": 1})
        with mock.patch.object(V.urllib.request, "urlopen", side_effect=fake):
            self.assertIsNone(V.check_for_update())

    def test_timeout_bound_is_five_seconds(self):
        self.assertLessEqual(V.REQUEST_TIMEOUT, 5.0)

    # -- cache behavior ----------------------------------------------------
    def test_fresh_cache_avoids_network(self):
        V.write_cache({"latest": "0.4.0", "checked_at": time.time(),
                       "notified_version": ""})
        calls = self.mock_pypi(version="9.9.9")  # must NOT be hit
        info = V.check_for_update()
        self.assertTrue(info["update_available"])
        self.assertEqual(info["latest"], "0.4.0")  # cached value, not 9.9.9
        self.assertNotIn("url", calls)

    def test_stale_cache_refetches(self):
        V.write_cache({"latest": __version__,
                       "checked_at": time.time() - 25 * 3600,
                       "notified_version": ""})
        calls = self.mock_pypi(version="0.4.0")
        info = V.check_for_update()
        self.assertIn("url", calls)  # network was hit
        self.assertTrue(info["update_available"])

    def test_cache_survives_corruption(self):
        (self.data_dir / "update_check.json").write_text("not json{{{",
                                                         encoding="utf-8")
        self.mock_pypi(version="0.4.0")
        info = V.check_for_update()
        self.assertTrue(info["update_available"])

    def test_version_comparison(self):
        self.assertTrue(V.is_newer("0.4.0", "0.3.0"))
        self.assertTrue(V.is_newer("0.10.0", "0.9.9"))
        self.assertFalse(V.is_newer("0.3.0", "0.3.0"))
        self.assertFalse(V.is_newer("0.2.9", "0.3.0"))

    # -- notice gating -----------------------------------------------------
    def run_notice(self, is_json=False, tty=True):
        out = TtyStdout() if tty else io.StringIO()
        with mock.patch("sys.stdout", out):
            shown = V.maybe_print_update_notice(is_json=is_json)
        return shown, out.getvalue()

    def test_notice_printed_once_per_version(self):
        self.mock_pypi(version="0.4.0")
        shown, out = self.run_notice()
        self.assertTrue(shown)
        self.assertIn("candid 0.4.0 is available, run pip install -U candid", out)
        # second run: cached as notified -> no repeat
        shown2, out2 = self.run_notice()
        self.assertFalse(shown2)
        self.assertEqual(out2, "")

    def test_notice_repeats_for_newer_version(self):
        self.mock_pypi(version="0.4.0")
        self.run_notice()
        self.mock_pypi(version="0.5.0")
        V.write_cache({"latest": "0.5.0", "checked_at": time.time(),
                       "notified_version": "0.4.0"})
        shown, out = self.run_notice()
        self.assertTrue(shown)
        self.assertIn("candid 0.5.0 is available", out)

    def test_no_notice_when_up_to_date(self):
        self.mock_pypi(version=__version__)
        shown, out = self.run_notice()
        self.assertFalse(shown)
        self.assertEqual(out, "")

    def test_no_notice_when_offline(self):
        self.mock_pypi(exc=urllib.error.URLError("down"))
        shown, out = self.run_notice()
        self.assertFalse(shown)
        self.assertEqual(out, "")

    def test_no_notice_when_piped(self):
        self.mock_pypi(version="0.4.0")
        shown, out = self.run_notice(tty=False)
        self.assertFalse(shown)
        self.assertEqual(out, "")

    def test_no_notice_for_json_output(self):
        self.mock_pypi(version="0.4.0")
        shown, out = self.run_notice(is_json=True)
        self.assertFalse(shown)
        self.assertEqual(out, "")

    def test_opt_out_disables_notice(self):
        self.write_config("check_updates: false\n")
        calls = self.mock_pypi(version="0.4.0")
        shown, out = self.run_notice()
        self.assertFalse(shown)
        self.assertEqual(out, "")
        self.assertNotIn("url", calls)  # no network attempt at all

    def test_opt_out_variants(self):
        for text in ("check_updates: false", "check_updates: False",
                     "check_updates: no", "check_updates: 0"):
            self.write_config(text + "\n")
            self.assertFalse(C.updates_enabled(), text)
        self.write_config("check_updates: true\n")
        self.assertTrue(C.updates_enabled())
        # missing file -> enabled by default
        (self.config_dir / "config.yaml").unlink()
        self.assertTrue(C.updates_enabled())

    def test_malformed_config_file_is_ignored(self):
        self.write_config("this is not: valid: yaml: at all\n:::")
        self.assertTrue(C.updates_enabled())


class StartupHookTests(unittest.TestCase):
    """The hook in main(): TTY-gated, skips --json and `version`, never raises."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_dir = Path(self.tmp.name) / "data"
        self.config_dir = Path(self.tmp.name) / "cfg"
        self.data_dir.mkdir()
        self.config_dir.mkdir()
        self._orig = {}
        for name, val in (("DATA_DIR", self.data_dir),
                          ("CONFIG_PATH", self.config_dir / "config.yaml")):
            self._orig[name] = getattr(C, name)
            setattr(C, name, val)

    def tearDown(self):
        for name, val in self._orig.items():
            setattr(C, name, val)

    def run_main(self, argv, tty=True):
        out = TtyStdout() if tty else io.StringIO()
        with mock.patch("sys.stdout", out):
            CLI.main(argv)
        return out.getvalue()

    def test_hook_skipped_for_version_command(self):
        calls = {}
        def fake(req, timeout=None):
            calls["hit"] = True
            return FakeHTTPResponse(pypi_payload("0.4.0"))
        with mock.patch.object(V.urllib.request, "urlopen", side_effect=fake):
            out = self.run_main(["version"], tty=True)
        self.assertNotIn("hit", calls)  # no check at all
        self.assertIn(f"candid {__version__}", out)

    def test_hook_silent_when_piped(self):
        def fake(req, timeout=None):
            return FakeHTTPResponse(pypi_payload("0.4.0"))
        with mock.patch.object(V.urllib.request, "urlopen", side_effect=fake):
            out = self.run_main(["version"], tty=False)
        self.assertNotIn("is available", out)

    def test_hook_never_breaks_startup(self):
        # Even if the notifier explodes, the command still runs.
        with mock.patch.object(V, "maybe_print_update_notice",
                               side_effect=RuntimeError("boom")):
            out = self.run_main(["version"])
        self.assertIn(f"candid {__version__}", out)

    def test_hook_notice_on_other_command(self):
        # seed a minimal profile so `profile show` runs cleanly
        (self.data_dir / "profile.json").write_text(json.dumps({
            "name": "Test User", "headline": "Data Scientist",
            "skills": ["python"], "seniority": "senior",
            "years_experience": 4, "experience": [], "education": [],
        }), encoding="utf-8")
        orig_profile = C.PROFILE_PATH
        C.PROFILE_PATH = self.data_dir / "profile.json"
        self.addCleanup(setattr, C, "PROFILE_PATH", orig_profile)
        def fake(req, timeout=None):
            return FakeHTTPResponse(pypi_payload("0.4.0"))
        with mock.patch.object(V.urllib.request, "urlopen", side_effect=fake):
            out = self.run_main(["profile", "show"], tty=True)
        self.assertIn("candid 0.4.0 is available, run pip install -U candid", out)


if __name__ == "__main__":
    unittest.main()
