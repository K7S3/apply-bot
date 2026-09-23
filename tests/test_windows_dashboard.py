"""Windows-compatibility tests for the candid dashboard.

Covers the hardening in batch 98: localhost-only binding, a browser-launch
that can never crash the server, and a source-level ban on POSIX-only APIs
in candid/dashboard.py.
"""
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import dashboard as D  # noqa: E402


class BindAddressTest(unittest.TestCase):
    def test_bind_host_constant_is_localhost(self):
        self.assertEqual(D.BIND_HOST, "127.0.0.1")

    def test_serve_binds_bind_host_not_all_interfaces(self):
        src = inspect.getsource(D.serve)
        self.assertIn("BIND_HOST", src)
        self.assertNotIn("0.0.0.0", src)

    def test_bind_host_used_in_url_and_server(self):
        src = inspect.getsource(D.serve)
        self.assertIn("ThreadingHTTPServer((BIND_HOST", src)
        self.assertIn("http://{BIND_HOST}", src)


class BrowserLaunchTest(unittest.TestCase):
    def test_webbrowser_failure_is_swallowed(self):
        with patch.object(D.webbrowser, "open",
                          side_effect=OSError("no default browser")):
            D._open_browser("http://127.0.0.1:8765/")  # must not raise

    def test_webbrowser_other_exception_is_swallowed(self):
        with patch.object(D.webbrowser, "open",
                          side_effect=RuntimeError("edge case")):
            D._open_browser("http://127.0.0.1:8765/")  # must not raise

    def test_serve_registers_browser_launch_not_direct_open(self):
        # The browser launch runs on a Timer and goes through the guarded
        # helper — a bare ``webbrowser.open`` in serve() would be a crash
        # risk on Windows default-browser edge cases.
        src = inspect.getsource(D.serve)
        self.assertIn("_open_browser", src)
        self.assertNotIn("webbrowser.open", src)


class PosixApiTest(unittest.TestCase):
    def test_no_posix_only_references(self):
        src = (ROOT / "candid" / "dashboard.py").read_text(encoding="utf-8")
        for banned in ("os.fork", "signal.", "import pwd", "import grp",
                       "import termios", "import fcntl"):
            self.assertNotIn(banned, src,
                             f"dashboard.py must not use POSIX-only {banned!r}")

    def test_no_hardcoded_tmp_paths(self):
        src = (ROOT / "candid" / "dashboard.py").read_text(encoding="utf-8")
        self.assertNotIn('"/tmp', src)
        self.assertNotIn("'/tmp", src)

    def test_temp_upload_uses_cross_platform_tempdir(self):
        src = inspect.getsource(D.DashboardHandler.do_POST)
        self.assertIn("tempfile.gettempdir()", src)


if __name__ == "__main__":
    unittest.main()
