"""Tests for candid.console: Windows console UTF-8 + ANSI color support.

All paths are cross-platform-safe: nothing here requires Windows; POSIX
assertions verify the documented no-op behaviour.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import console  # noqa: E402


class SetupConsoleTest(unittest.TestCase):
    def test_setup_console_never_raises_on_posix(self):
        # Must be safe to call at the very start of main(), repeatedly.
        console.setup_console()
        console.setup_console()

    def test_setup_console_is_idempotent(self):
        console.setup_console()
        # second call must not blow up or change behaviour
        self.assertEqual(console.enable_vt_processing(),
                         console.enable_vt_processing())


class EnsureUtf8Test(unittest.TestCase):
    def test_non_reconfigurable_stream_is_ignored(self):
        # A dummy stdout without reconfigure() must not raise.
        dummy = mock.Mock(spec=[])  # no attributes at all
        with mock.patch.object(sys, "stdout", dummy):
            console.ensure_utf8_console()
        with mock.patch.object(sys, "stderr", dummy):
            console.ensure_utf8_console()

    def test_stream_without_encoding_is_tolerated(self):
        dummy = mock.Mock(spec=[])
        dummy.encoding = None
        with mock.patch.object(sys, "stdout", dummy):
            console.ensure_utf8_console()

    def test_posix_ascii_locale_requests_utf8(self):
        calls = []

        class FakeStream:
            encoding = "ascii"

            def reconfigure(self, **kwargs):
                calls.append(kwargs)

        with mock.patch.object(sys, "platform", "linux"), \
             mock.patch.object(sys, "stdout", FakeStream()), \
             mock.patch.object(sys, "stderr", FakeStream()):
            console.ensure_utf8_console()
        self.assertTrue(calls)
        for kwargs in calls:
            self.assertEqual(kwargs["encoding"], "utf-8")
            self.assertEqual(kwargs["errors"], "replace")

    def test_posix_utf8_locale_is_noop(self):
        calls = []

        class FakeStream:
            encoding = "utf-8"

            def reconfigure(self, **kwargs):
                calls.append(kwargs)

        with mock.patch.object(sys, "platform", "linux"), \
             mock.patch.object(sys, "stdout", FakeStream()), \
             mock.patch.object(sys, "stderr", FakeStream()):
            console.ensure_utf8_console()
        self.assertEqual(calls, [])


class VtProcessingTest(unittest.TestCase):
    def test_enable_vt_processing_returns_bool_without_raising(self):
        result = console.enable_vt_processing()
        self.assertIsInstance(result, bool)

    def test_enable_vt_processing_noop_on_posix(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertFalse(console.enable_vt_processing())


class SupportsColorTest(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)
        console._vt_enabled = None

    def test_no_color_env_disables(self):
        os.environ["NO_COLOR"] = "1"
        os.environ["WT_SESSION"] = "1"
        self.assertFalse(console.supports_color())

    def test_no_color_empty_value_still_disables(self):
        os.environ["NO_COLOR"] = ""
        self.assertFalse(console.supports_color())

    def test_wt_session_enables_on_posix(self):
        os.environ.pop("NO_COLOR", None)
        os.environ["WT_SESSION"] = "abc123"
        with mock.patch.object(sys, "platform", "linux"):
            self.assertTrue(console.supports_color())

    def test_term_program_enables_on_posix(self):
        os.environ.pop("NO_COLOR", None)
        os.environ["TERM_PROGRAM"] = "vscode"
        with mock.patch.object(sys, "platform", "linux"):
            self.assertTrue(console.supports_color())

    def test_non_tty_posix_is_false(self):
        os.environ.pop("NO_COLOR", None)
        os.environ.pop("WT_SESSION", None)
        os.environ.pop("TERM_PROGRAM", None)
        with mock.patch.object(sys, "platform", "linux"), \
             mock.patch.object(sys.stdout, "isatty", return_value=False):
            self.assertFalse(console.supports_color())


class ColorTest(unittest.TestCase):
    def test_no_color_env_returns_plain_text(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertEqual(console.color("boom", "red"), "boom")
            self.assertEqual(console.color("ok", "green"), "ok")
            self.assertEqual(console.color("note", "bold"), "note")

    def test_unknown_style_returns_plain_text(self):
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertEqual(console.color("x", "ultraviolet"), "x")

    def test_wraps_when_supported(self):
        env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
        env["WT_SESSION"] = "1"
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(sys, "platform", "linux"):
            out = console.color("boom", "red")
        self.assertTrue(out.startswith("\033[31m"))
        self.assertTrue(out.endswith("\033[0m"))
        self.assertIn("boom", out)

    def test_all_named_styles_have_distinct_codes(self):
        seen = set()
        with mock.patch.object(console, "supports_color", return_value=True):
            for name in ("red", "green", "yellow", "blue", "bold", "dim"):
                out = console.color("t", name)
                self.assertNotEqual(out, "t")
                seen.add(out[:5])
        self.assertEqual(len(seen), 6)


class CliWiringTest(unittest.TestCase):
    def test_main_calls_setup_console_first(self):
        # Importing __main__ must expose the (possibly guarded) helpers,
        # and main() must start with setup_console().
        from candid import __main__ as CLI

        self.assertTrue(callable(CLI.setup_console))
        self.assertTrue(callable(CLI.color))
        with mock.patch.object(CLI, "setup_console") as sc, \
             mock.patch.object(CLI, "build_parser") as bp:
            args = mock.Mock()
            args.func.side_effect = SystemExit(0)
            bp.return_value.parse_args.return_value = args
            with self.assertRaises(SystemExit):
                CLI.main(["--help"])
            sc.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
