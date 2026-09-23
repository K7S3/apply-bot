"""Tests for the crashlog / bug-report / diagnostics CLI wiring (worker C).

Exercises the real ``candid.crashlog`` / ``candid.bugreport`` modules with
the data dir redirected into a temp dir. Because ``candid.crashlog`` binds
its path constants at import time, the tests monkeypatch the path
attributes on *both* ``candid.config`` and ``candid.crashlog`` (the
``candid.bugreport`` helpers read config attributes lazily, so patching
config is enough for them).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import bugreport as B  # noqa: E402
from candid import config as C  # noqa: E402
from candid import crashlog as CL  # noqa: E402


class CrashCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-crashcli-"))
        self._saved = {}
        for name in ("DATA_DIR", "CRASH_LOG_PATH", "CRASH_LAST_PATH",
                     "CONSENT_PATH"):
            self._saved[("config", name)] = getattr(C, name)
            setattr(C, name, self.tmp / name.lower().replace("_path", "")
                    if name != "DATA_DIR" else self.tmp)
        # crashlog.py binds these at import time -> patch the module too
        for name in ("CRASH_LOG_PATH", "CRASH_LAST_PATH"):
            self._saved[("crashlog", name)] = getattr(CL, name)
            setattr(CL, name, getattr(C, name))
        self._prev_hook = sys.excepthook

    def tearDown(self):
        sys.excepthook = self._prev_hook
        for (mod, name), val in self._saved.items():
            setattr(C if mod == "config" else CL, name, val)

    # -- helpers ---------------------------------------------------------
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def seed(self, exc_type="ValueError", message="boom", command="match",
             count=1, site="a"):
        recs = []
        for _ in range(count):
            try:
                _SITES[site](exc_type, message)
            except _EXC[exc_type] as e:  # noqa: BLE001
                recs.append(CL.log_crash(e, command=command,
                                         argv=["candid", command]))
        return recs[0] if count == 1 else recs


_EXC = {"ValueError": ValueError, "KeyError": KeyError,
        "RuntimeError": RuntimeError}


def _raise_site_a(exc_type, message):
    raise _EXC[exc_type](message)  # distinct source line -> distinct hash


def _raise_site_b(exc_type, message):
    raise _EXC[exc_type](message)  # distinct source line -> distinct hash


_SITES = {"a": _raise_site_a, "b": _raise_site_b}


class TestCrashlogCLI(CrashCLIBase):
    def test_list_renders_table_on_seeded_records(self):
        r1 = self.seed(exc_type="ValueError", command="match")
        r2 = self.seed(exc_type="KeyError", command="prep")
        code, out, err = self.run_cli(["crashlog", "list"])
        self.assertEqual(code, 0)
        self.assertIn("ValueError", out)
        self.assertIn("KeyError", out)
        self.assertIn("match", out)
        self.assertIn(r1["traceback_hash"][:8], out)
        self.assertIn(r2["traceback_hash"][:8], out)
        self.assertIn(r1["ts"][:10], out)

    def test_list_empty(self):
        code, out, err = self.run_cli(["crashlog", "list"])
        self.assertEqual(code, 0)
        self.assertIn("No crashes recorded", out)

    def test_list_json_and_limit(self):
        self.seed(exc_type="ValueError", command="match", count=3)
        code, out, err = self.run_cli(["crashlog", "list", "--json",
                                       "--limit", "2"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["exc_type"], "ValueError")

    def test_show_by_id_and_prefixes(self):
        rec = self.seed(exc_type="RuntimeError", command="prep",
                        message="kaput")
        code, out, err = self.run_cli(["crashlog", "show", rec["id"]])
        self.assertEqual(code, 0)
        self.assertIn("RuntimeError", out)
        self.assertIn("kaput", out)
        # id prefix and hash prefix both resolve
        for ref in (rec["id"][:6], rec["traceback_hash"][:8]):
            code, out, err = self.run_cli(["crashlog", "show", ref])
            self.assertEqual(code, 0)
            self.assertIn("RuntimeError", out)

    def test_show_unknown_ref_friendly(self):
        self.seed()
        code, out, err = self.run_cli(["crashlog", "show", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("crashlog list", err)
        self.assertNotIn("Traceback", err)

    def test_stats(self):
        self.seed(exc_type="ValueError", command="match", count=2)
        self.seed(exc_type="KeyError", command="prep", site="b")
        code, out, err = self.run_cli(["crashlog", "stats"])
        self.assertEqual(code, 0)
        self.assertIn("Total crashes recorded: 3", out)
        self.assertIn("ValueError", out)
        self.assertIn("KeyError", out)
        self.assertIn("match", out)  # command resolved via sample_id

    def test_clear_yes_clears_log_and_marker(self):
        self.seed()
        self.assertIsNotNone(CL.check_last_crash())
        code, out, err = self.run_cli(["crashlog", "clear", "--yes"])
        self.assertEqual(code, 0)
        self.assertIn("Cleared 1 crash record", out)
        self.assertFalse(C.CRASH_LOG_PATH.exists())
        self.assertIsNone(CL.check_last_crash())

    def test_clear_requires_confirmation(self):
        self.seed()
        with mock.patch("builtins.input", return_value="n"):
            code, out, err = self.run_cli(["crashlog", "clear"])
        self.assertEqual(code, 0)
        self.assertIn("Aborted", out)
        self.assertTrue(C.CRASH_LOG_PATH.exists())

        with mock.patch("builtins.input", return_value="y"):
            code, out, err = self.run_cli(["crashlog", "clear"])
        self.assertEqual(code, 0)
        self.assertIn("Cleared 1 crash record", out)
        self.assertFalse(C.CRASH_LOG_PATH.exists())


class TestBugReportCLI(CrashCLIBase):
    def test_consent_round_trip(self):
        code, out, err = self.run_cli(["bug-report", "--status"])
        self.assertEqual(code, 0)
        self.assertIn("UNDECIDED", out)

        code, out, err = self.run_cli(["bug-report", "--opt-in"])
        self.assertEqual(code, 0)
        self.assertIn("Opted in", out)

        code, out, err = self.run_cli(["bug-report", "--status"])
        self.assertIn("OPTED IN", out)

        code, out, err = self.run_cli(["bug-report", "--opt-out"])
        self.assertEqual(code, 0)
        self.assertIn("Opted out", out)

        code, out, err = self.run_cli(["bug-report", "--status"])
        self.assertIn("OPTED OUT", out)

    def test_build_and_save_for_seeded_crash(self):
        home = str(Path.home())
        rec = self.seed(exc_type="ValueError", command="match",
                        message=f"contact alex@example.com in {home}/secret")
        code, out, err = self.run_cli(["bug-report"])
        self.assertEqual(code, 0)
        self.assertIn("# candid bug report", out)   # preview printed
        m = [l for l in out.splitlines()
             if l.startswith("Saved bug report to")]
        self.assertEqual(len(m), 1)
        saved = Path(m[0].split("Saved bug report to", 1)[1].strip())
        self.assertTrue(saved.exists())
        body = saved.read_text(encoding="utf-8")
        self.assertIn("ValueError", body)
        self.assertIn(rec["traceback_hash"], body)
        # PII redacted: no raw email or home dir in the report
        self.assertIn("[EMAIL]", body)
        self.assertNotIn("alex@example.com", body)
        self.assertNotIn(f"{home}/secret", body)

    def test_build_with_id_and_out(self):
        rec = self.seed(exc_type="KeyError", command="prep")
        out_path = str(self.tmp / "custom" / "r.md")
        code, out, err = self.run_cli(
            ["bug-report", "--id", rec["id"], "--out", out_path])
        self.assertEqual(code, 0)
        self.assertTrue(Path(out_path).exists())

    def test_show_redactions(self):
        self.seed()
        code, out, err = self.run_cli(["bug-report", "--show-redactions"])
        self.assertEqual(code, 0)
        self.assertIn("redaction audit", out)

    def test_empty_log_friendly_no_traceback(self):
        code, out, err = self.run_cli(["bug-report"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertIn("No crashes recorded", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("Traceback", out)

    def test_opt_in_unlocks_shareable_file(self):
        rec = self.seed()
        # undecided: no shareable file mentioned
        code, out, err = self.run_cli(["bug-report", "--id", rec["id"]])
        self.assertEqual(code, 0)
        self.assertNotIn("Shareable file", out)
        # opt in: shareable file generated with instructions
        self.run_cli(["bug-report", "--opt-in"])
        code, out, err = self.run_cli(["bug-report", "--id", rec["id"]])
        self.assertEqual(code, 0)
        self.assertIn("Shareable file", out)
        self.assertIn("Nothing was sent anywhere", out)

    def test_bugreport_error_is_friendly(self):
        self.seed()
        code, out, err = self.run_cli(["bug-report", "--id", "deadbeef"])
        self.assertEqual(code, 1)
        self.assertIn("Error:", err)
        self.assertNotIn("Traceback", err)


class TestDiagnosticsCLI(CrashCLIBase):
    def test_diagnostics_redacted(self):
        self.seed()
        code, out, err = self.run_cli(["diagnostics"])
        self.assertEqual(code, 0)
        self.assertIn("python", out)
        self.assertNotIn(str(Path.home()), out)

    def test_diagnostics_json(self):
        code, out, err = self.run_cli(["diagnostics", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("python", data)
        self.assertNotIn(str(Path.home()), json.dumps(data))


class TestLastCrashHint(CrashCLIBase):
    def test_hint_appears_once_then_clears(self):
        rec = self.seed(exc_type="RuntimeError", command="mock",
                        message="ai failed")
        # marker present -> next main() prints the hint to stderr
        code, out, err = self.run_cli(["crashlog", "list"])
        self.assertEqual(code, 0)
        self.assertIn("Note: candid crashed during the previous run", err)
        self.assertIn("RuntimeError", err)
        self.assertIn("'mock'", err)
        self.assertIn(f"candid crashlog show {rec['id']}", err)
        self.assertIn("candid bug-report", err)
        # marker cleared: a second run shows no hint
        self.assertIsNone(CL.check_last_crash())
        code, out, err = self.run_cli(["crashlog", "list"])
        self.assertNotIn("Note: candid crashed", err)

    def test_no_hint_without_marker(self):
        code, out, err = self.run_cli(["crashlog", "list"])
        self.assertNotIn("Note: candid crashed", err)

    def test_broken_hook_never_breaks_cli(self):
        # install_crash_hook raising must not stop the CLI
        with mock.patch.object(CL, "install_crash_hook",
                               side_effect=RuntimeError("nope")):
            code, out, err = self.run_cli(["crashlog", "stats"])
        self.assertEqual(code, 0)
        self.assertIn("Total crashes recorded: 0", out)


if __name__ == "__main__":
    unittest.main()
