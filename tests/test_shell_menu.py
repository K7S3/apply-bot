"""Tests for candid/shell.py (interactive REPL) and candid/menu.py (intent menu).

No real TTY is ever required: the shell loop is fed iterables of lines,
and input()/readline are monkeypatched.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import menu  # noqa: E402
from candid import shell  # noqa: E402


class ShellBase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-shell-"))
        # keep history writes out of the real user config dir
        self._saved_config_dir = C.CONFIG_DIR
        C.CONFIG_DIR = self.tmp / "config"
        # never touch the real readline state in tests
        self._saved_readline = shell.readline

    def tearDown(self):
        C.CONFIG_DIR = self._saved_config_dir
        shell.readline = self._saved_readline


class TestDispatch(ShellBase):
    def test_dispatch_calls_main_with_argv(self):
        seen = []

        def fake_main(argv):
            seen.append(argv)

        with mock.patch.object(CLI, "main", fake_main):
            rc = shell.run_shell(lines=["match --jd jd.txt --company Acme"])
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [["match", "--jd", "jd.txt", "--company", "Acme"]])

    def test_dispatch_quoting(self):
        seen = []

        def fake_main(argv):
            seen.append(argv)

        with mock.patch.object(CLI, "main", fake_main):
            shell.run_shell(lines=['track add --company "Acme Inc" --role DS'])
        self.assertEqual(seen, [["track", "add", "--company", "Acme Inc", "--role", "DS"]])

    def test_systemexit_does_not_kill_loop(self):
        calls = []

        def fake_main(argv):
            calls.append(argv)
            raise SystemExit(2)  # e.g. argparse usage error / --help

        with mock.patch.object(CLI, "main", fake_main):
            rc = shell.run_shell(lines=["bad command here", "track list"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [["bad", "command", "here"], ["track", "list"]])

    def test_empty_line_is_noop(self):
        seen = []

        def fake_main(argv):
            seen.append(argv)

        with mock.patch.object(CLI, "main", fake_main):
            shell.run_shell(lines=["", "   ", "\t"])
        self.assertEqual(seen, [])


class TestBuiltins(ShellBase):
    def test_help_lists_commands(self):
        import io
        buf = io.StringIO()
        with mock.patch.object(CLI, "main") as m, \
                mock.patch("sys.stdout", buf):
            shell.run_shell(lines=["help"])
        m.assert_not_called()
        out = buf.getvalue()
        for cmd in ("onboard", "match", "track", "dashboard"):
            self.assertIn(cmd, out)

    def test_exit_and_quit_return_zero(self):
        with mock.patch.object(CLI, "main") as m:
            self.assertEqual(shell.run_shell(lines=["exit"]), 0)
            self.assertEqual(shell.run_shell(lines=["quit"]), 0)
        m.assert_not_called()

    def test_exit_stops_processing_later_lines(self):
        seen = []

        def fake_main(argv):
            seen.append(argv)

        with mock.patch.object(CLI, "main", fake_main):
            shell.run_shell(lines=["match --jd x", "exit", "track list"])
        self.assertEqual(seen, [["match", "--jd", "x"]])

    def test_clear_does_not_dispatch_or_crash(self):
        with mock.patch.object(CLI, "main") as m:
            rc = shell.run_shell(lines=["clear"])
        self.assertEqual(rc, 0)
        m.assert_not_called()


class TestInputHandling(ShellBase):
    def test_eof_exits_zero(self):
        with mock.patch.object(CLI, "main") as m, \
                mock.patch("builtins.input", side_effect=EOFError), \
                mock.patch.object(sys.stdin, "isatty", return_value=True):
            rc = shell.run_shell()
        self.assertEqual(rc, 0)
        m.assert_not_called()

    def test_ctrl_c_continues_loop(self):
        seen = []

        def fake_main(argv):
            seen.append(argv)

        inputs = iter([KeyboardInterrupt(), "track list", EOFError()])

        def fake_input(prompt=""):
            v = next(inputs)
            if isinstance(v, BaseException):
                raise v
            return v

        with mock.patch.object(CLI, "main", fake_main), \
                mock.patch("builtins.input", fake_input), \
                mock.patch.object(sys.stdin, "isatty", return_value=True):
            rc = shell.run_shell()
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [["track", "list"]])

    def test_non_tty_without_lines_errors(self):
        import io
        buf = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=False), \
                mock.patch("sys.stderr", buf):
            rc = shell.run_shell()
        self.assertNotEqual(rc, 0)
        self.assertIn("not a TTY", buf.getvalue())


class TestHistory(ShellBase):
    def test_history_file_written(self):
        with mock.patch.object(CLI, "main"):
            shell.run_shell(lines=["match --jd jd.txt", "track list", ""])
        hist = (C.CONFIG_DIR / "shell_history").read_text(encoding="utf-8")
        self.assertIn("match --jd jd.txt", hist)
        self.assertIn("track list", hist)
        # empty line is a no-op: not recorded
        self.assertEqual([l for l in hist.splitlines() if l.strip()],
                         ["match --jd jd.txt", "track list"])

    def test_history_appends_across_runs(self):
        with mock.patch.object(CLI, "main"):
            shell.run_shell(lines=["onboard"])
            shell.run_shell(lines=["dashboard"])
        hist = (C.CONFIG_DIR / "shell_history").read_text(encoding="utf-8").splitlines()
        self.assertEqual(hist, ["onboard", "dashboard"])

    def test_history_works_without_readline(self):
        shell.readline = None  # simulate readline-less environment
        with mock.patch.object(CLI, "main"):
            rc = shell.run_shell(lines=["track stats"])
        self.assertEqual(rc, 0)
        hist = (C.CONFIG_DIR / "shell_history").read_text(encoding="utf-8")
        self.assertIn("track stats", hist)


class TestMenu(unittest.TestCase):
    def test_menu_lists_only_existing_commands(self):
        self.assertTrue(menu.MENU, "menu must not be empty")
        for label, argv in menu.MENU:
            self.assertIn(argv[0], CLI.COMMANDS, label)
            if len(argv) > 1:
                self.assertIn(argv[1], CLI.SUBCOMMANDS.get(argv[0], []), label)

    def test_menu_has_about_twelve_intents(self):
        self.assertGreaterEqual(len(menu.MENU), 10)
        self.assertLessEqual(len(menu.MENU), 14)

    def test_no_today_intent(self):
        # 'today' does not exist in this tree, so it must not be listed
        for label, argv in menu.MENU:
            self.assertNotEqual(argv[0], "today")

    def test_pick_intent_by_number(self):
        self.assertEqual(menu.pick_intent("1"), ["onboard"])
        self.assertEqual(menu.pick_intent("3"), ["tailor", "resume"])
        self.assertEqual(menu.pick_intent("3."), ["tailor", "resume"])
        self.assertEqual(menu.pick_intent(str(len(menu.MENU))), list(menu.MENU[-1][1]))

    def test_pick_intent_by_label_and_command(self):
        self.assertEqual(menu.pick_intent("Tailor my resume"), ["tailor", "resume"])
        self.assertEqual(menu.pick_intent("tailor my resume"), ["tailor", "resume"])
        self.assertEqual(menu.pick_intent("salary lookup"), ["salary", "lookup"])
        self.assertEqual(menu.pick_intent("dashboard"), ["dashboard"])

    def test_pick_intent_invalid(self):
        self.assertIsNone(menu.pick_intent("0"))
        self.assertIsNone(menu.pick_intent("99"))
        self.assertIsNone(menu.pick_intent("bogus choice"))
        self.assertIsNone(menu.pick_intent(""))
        self.assertIsNone(menu.pick_intent("   "))

    def test_pick_intent_returns_copy(self):
        argv = menu.pick_intent("1")
        argv.append("mutated")
        self.assertEqual(menu.pick_intent("1"), ["onboard"])

    def test_show_menu_valid_choice(self):
        import io
        buf = io.StringIO()
        with mock.patch("builtins.input", return_value="2"), \
                mock.patch("sys.stdout", buf):
            label = menu.show_menu()
        self.assertEqual(label, menu.MENU[1][0])
        self.assertIn("1.", buf.getvalue())  # numbered list was printed

    def test_show_menu_invalid_and_cancel(self):
        with mock.patch("builtins.input", return_value="nope"):
            self.assertIsNone(menu.show_menu())
        with mock.patch("builtins.input", return_value="q"):
            self.assertIsNone(menu.show_menu())
        with mock.patch("builtins.input", return_value=""):
            self.assertIsNone(menu.show_menu())


if __name__ == "__main__":
    unittest.main()
