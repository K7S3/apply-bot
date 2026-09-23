"""Tests for the candid notification engine (candid.notify) and the
`candid notify` CLI wiring.

Isolation: CONFIG_DIR is monkeypatched to a temp dir per test (the engine
resolves candid.config.CONFIG_DIR at call time). OS backends are mocked;
no real notifications are ever sent.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import notify as N  # noqa: E402

try:
    import candid.notify_reminders  # noqa: F401
    HAS_REMINDERS = True
except ImportError:
    HAS_REMINDERS = False


class NotifyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-notify-"))
        self._saved_config_dir = C.CONFIG_DIR
        C.CONFIG_DIR = self.tmp

    def tearDown(self):
        C.CONFIG_DIR = self._saved_config_dir
        # Importing candid.notify (here and via the `candid notify` CLI)
        # leaves a `notify` attribute on the `candid` package. Remove it so
        # that other test modules which monkeypatch sys.modules["candid.notify"]
        # keep working: `from candid import notify` must fall back to the
        # sys.modules entry instead of the real module.
        import candid
        try:
            delattr(candid, "notify")
        except AttributeError:
            pass


class PrefsTest(NotifyBase):
    def test_defaults(self):
        prefs = N.get_prefs()
        self.assertTrue(prefs["enabled"])
        self.assertEqual(prefs["quiet_start"], "22:00")
        self.assertEqual(prefs["quiet_end"], "08:00")
        for cat in ("interviews", "deadlines", "followups", "watchlist", "system"):
            self.assertTrue(prefs["categories"][cat])
        self.assertIsNone(prefs["snoozed_until"])

    def test_prefs_persist_to_notify_json(self):
        N.set_pref("enabled", False)
        path = self.tmp / "notify.json"
        self.assertTrue(path.exists())
        stored = json.loads(path.read_text())
        self.assertFalse(stored["enabled"])

    def test_set_pref_enabled_coerces_strings(self):
        self.assertFalse(N.set_pref("enabled", "false")["enabled"])
        self.assertTrue(N.set_pref("enabled", "yes")["enabled"])
        self.assertTrue(N.set_pref("enabled", True)["enabled"])
        self.assertFalse(N.set_pref("enabled", "0")["enabled"])

    def test_set_pref_quiet_times(self):
        prefs = N.set_pref("quiet_start", "9:30")
        self.assertEqual(prefs["quiet_start"], "09:30")
        prefs = N.set_pref("quiet_end", "7:5")
        self.assertEqual(prefs["quiet_end"], "07:05")

    def test_set_pref_category(self):
        prefs = N.set_pref("categories.interviews", "false")
        self.assertFalse(prefs["categories"]["interviews"])
        self.assertTrue(prefs["categories"]["deadlines"])

    def test_set_pref_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            N.set_pref("bogus", "x")

    def test_set_pref_unknown_category_raises(self):
        with self.assertRaises(ValueError):
            N.set_pref("categories.nope", "true")

    def test_set_pref_bad_time_raises(self):
        with self.assertRaises(ValueError):
            N.set_pref("quiet_start", "25:00")
        with self.assertRaises(ValueError):
            N.set_pref("quiet_end", "not-a-time")


class QuietTest(NotifyBase):
    def _dt(self, hh, mm):
        return datetime(2026, 9, 22, hh, mm)

    def test_overnight_window(self):
        N.set_pref("quiet_start", "22:00")
        N.set_pref("quiet_end", "08:00")
        self.assertTrue(N.is_quiet(self._dt(22, 0)))
        self.assertTrue(N.is_quiet(self._dt(23, 30)))
        self.assertTrue(N.is_quiet(self._dt(0, 15)))
        self.assertTrue(N.is_quiet(self._dt(7, 59)))
        self.assertFalse(N.is_quiet(self._dt(8, 0)))
        self.assertFalse(N.is_quiet(self._dt(12, 0)))
        self.assertFalse(N.is_quiet(self._dt(21, 59)))

    def test_daytime_window(self):
        N.set_pref("quiet_start", "09:00")
        N.set_pref("quiet_end", "17:00")
        self.assertTrue(N.is_quiet(self._dt(9, 0)))
        self.assertTrue(N.is_quiet(self._dt(12, 30)))
        self.assertFalse(N.is_quiet(self._dt(8, 59)))
        self.assertFalse(N.is_quiet(self._dt(17, 0)))
        self.assertFalse(N.is_quiet(self._dt(22, 0)))

    def test_equal_start_end_means_no_quiet(self):
        N.set_pref("quiet_start", "00:00")
        N.set_pref("quiet_end", "00:00")
        self.assertFalse(N.is_quiet(self._dt(3, 0)))
        self.assertFalse(N.is_quiet(self._dt(15, 0)))

    def test_default_dt_is_now(self):
        self.assertIsInstance(N.is_quiet(), bool)

    def test_bad_stored_time_is_not_quiet(self):
        prefs = N.get_prefs()
        prefs["quiet_start"] = "junk"
        N.save_prefs(prefs)
        self.assertFalse(N.is_quiet(self._dt(23, 0)))


class SnoozeTest(NotifyBase):
    def test_snooze_sets_until_and_clear_removes(self):
        until = N.snooze(timedelta(hours=2))
        got = N.snoozed_until()
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got.timestamp(), until.timestamp(), delta=5)
        N.clear_snooze()
        self.assertIsNone(N.snoozed_until())

    def test_expired_snooze_reads_as_none(self):
        prefs = N.get_prefs()
        prefs["snoozed_until"] = (datetime.now() - timedelta(hours=1)).isoformat()
        N.save_prefs(prefs)
        self.assertIsNone(N.snoozed_until())

    def test_snooze_returns_future_datetime(self):
        until = N.snooze(timedelta(minutes=30))
        self.assertGreater(until, datetime.now())


class QueueFlushTest(NotifyBase):
    def test_queue_record_shape(self):
        rec = N.queue_notification("T", "B", category="interviews",
                                   urgency="critical")
        self.assertEqual(rec["title"], "T")
        self.assertEqual(rec["body"], "B")
        self.assertEqual(rec["category"], "interviews")
        self.assertEqual(rec["urgency"], "critical")
        self.assertTrue(rec["id"])
        self.assertIn("queued_at", rec)

    def test_queue_unknown_urgency_normalizes(self):
        rec = N.queue_notification("T", "B", urgency="bogus")
        self.assertEqual(rec["urgency"], "normal")

    def test_flush_delivers_when_clear(self):
        N.queue_notification("One", "b1")
        N.queue_notification("Two", "b2")
        with mock.patch("candid.notify.is_quiet", return_value=False), \
             mock.patch("candid.notify._deliver", return_value=True):
            delivered = N.flush_queue()
        self.assertEqual(len(delivered), 2)
        self.assertEqual([r["title"] for r in delivered], ["One", "Two"])
        self.assertEqual(json.loads((self.tmp / "notify_queue.json").read_text()), [])
        for r in delivered:
            self.assertTrue(N.was_sent(r["id"]))

    def test_flush_noop_when_quiet(self):
        N.queue_notification("One", "b1")
        with mock.patch("candid.notify.is_quiet", return_value=True), \
             mock.patch("candid.notify._deliver", return_value=True) as d:
            delivered = N.flush_queue()
        self.assertEqual(delivered, [])
        d.assert_not_called()
        queue = json.loads((self.tmp / "notify_queue.json").read_text())
        self.assertEqual(len(queue), 1)

    def test_flush_keeps_failed_items(self):
        N.queue_notification("One", "b1")
        with mock.patch("candid.notify.is_quiet", return_value=False), \
             mock.patch("candid.notify._deliver", return_value=False):
            delivered = N.flush_queue()
        self.assertEqual(delivered, [])
        queue = json.loads((self.tmp / "notify_queue.json").read_text())
        self.assertEqual(len(queue), 1)
        self.assertFalse(N.was_sent(queue[0]["id"]))


class DedupTest(NotifyBase):
    def test_mark_and_was_sent(self):
        self.assertFalse(N.was_sent("abc"))
        N.mark_sent("abc")
        self.assertTrue(N.was_sent("abc"))

    def test_old_entries_pruned(self):
        old = (datetime.now() - timedelta(days=40)).isoformat()
        (self.tmp / "notify_sent.json").write_text(json.dumps({"old-id": old}))
        self.assertFalse(N.was_sent("old-id"))
        N.mark_sent("new-id")
        stored = json.loads((self.tmp / "notify_sent.json").read_text())
        self.assertNotIn("old-id", stored)
        self.assertIn("new-id", stored)

    def test_recent_entries_survive_prune(self):
        recent = (datetime.now() - timedelta(days=2)).isoformat()
        (self.tmp / "notify_sent.json").write_text(json.dumps({"rid": recent}))
        N.mark_sent("another")
        stored = json.loads((self.tmp / "notify_sent.json").read_text())
        self.assertIn("rid", stored)


class NotifyFlowTest(NotifyBase):
    def test_disabled_returns_false_without_queueing(self):
        N.set_pref("enabled", False)
        with mock.patch("candid.notify._deliver") as d:
            self.assertFalse(N.notify("T", "B"))
        d.assert_not_called()
        self.assertFalse((self.tmp / "notify_queue.json").exists())

    def test_disabled_category_returns_false(self):
        N.set_pref("categories.deadlines", False)
        with mock.patch("candid.notify._deliver") as d:
            self.assertFalse(N.notify("T", "B", category="deadlines"))
        d.assert_not_called()

    def test_unknown_category_is_allowed(self):
        with mock.patch("candid.notify.is_quiet", return_value=False), \
             mock.patch("candid.notify._snoozed", return_value=False), \
             mock.patch("candid.notify._deliver", return_value=True) as d:
            self.assertTrue(N.notify("T", "B", category="general"))
        d.assert_called_once()

    def test_quiet_queues_and_returns_false(self):
        with mock.patch("candid.notify.is_quiet", return_value=True), \
             mock.patch("candid.notify._deliver") as d:
            self.assertFalse(N.notify("T", "B"))
        d.assert_not_called()
        queue = json.loads((self.tmp / "notify_queue.json").read_text())
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["title"], "T")

    def test_snoozed_queues_and_returns_false(self):
        N.snooze(timedelta(hours=1))
        with mock.patch("candid.notify.is_quiet", return_value=False), \
             mock.patch("candid.notify._deliver") as d:
            self.assertFalse(N.notify("T", "B"))
        d.assert_not_called()
        queue = json.loads((self.tmp / "notify_queue.json").read_text())
        self.assertEqual(len(queue), 1)

    def test_backend_failure_queues_and_returns_false(self):
        with mock.patch("candid.notify.is_quiet", return_value=False), \
             mock.patch("candid.notify._snoozed", return_value=False), \
             mock.patch("candid.notify._deliver", return_value=False):
            self.assertFalse(N.notify("T", "B"))
        queue = json.loads((self.tmp / "notify_queue.json").read_text())
        self.assertEqual(len(queue), 1)

    def test_success_returns_true_without_queueing(self):
        with mock.patch("candid.notify.is_quiet", return_value=False), \
             mock.patch("candid.notify._snoozed", return_value=False), \
             mock.patch("candid.notify._deliver", return_value=True):
            self.assertTrue(N.notify("T", "B"))
        self.assertFalse((self.tmp / "notify_queue.json").exists())

    def test_deliver_exception_never_raises(self):
        with mock.patch("candid.notify.is_quiet", return_value=False), \
             mock.patch("candid.notify._snoozed", return_value=False), \
             mock.patch("candid.notify._deliver",
                        side_effect=RuntimeError("boom")):
            self.assertFalse(N.notify("T", "B"))


class BackendTest(NotifyBase):
    def _patch_platform(self, name):
        return mock.patch("candid.notify.platform.system", return_value=name)

    def test_macos_prefers_terminal_notifier(self):
        def which(cmd):
            return "/usr/local/bin/terminal-notifier" if cmd == "terminal-notifier" else None
        with self._patch_platform("Darwin"), \
             mock.patch("candid.notify.shutil.which", side_effect=which), \
             mock.patch("candid.notify.subprocess.run") as run:
            self.assertTrue(N._notify_macos("Hi", "Body", "normal"))
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "terminal-notifier")
        self.assertIn("Hi", cmd)
        self.assertIn("Body", cmd)
        self.assertEqual(run.call_args[1]["timeout"], 10)
        self.assertNotIn("shell", run.call_args[1])

    def test_macos_osascript_escapes_quotes(self):
        def which(cmd):
            return "/usr/bin/osascript" if cmd == "osascript" else None
        with self._patch_platform("Darwin"), \
             mock.patch("candid.notify.shutil.which", side_effect=which), \
             mock.patch("candid.notify.subprocess.run") as run:
            self.assertTrue(N._notify_macos('Say "hi"', "C:\\path", "normal"))
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "osascript")
        script = cmd[cmd.index("-e") + 1]
        self.assertIn('\\"hi\\"', script)
        self.assertIn("C:\\\\path", script)

    def test_macos_no_backend_false(self):
        with self._patch_platform("Darwin"), \
             mock.patch("candid.notify.shutil.which", return_value=None):
            self.assertFalse(N._notify_macos("T", "B", "normal"))

    def test_linux_notify_send(self):
        def which(cmd):
            return "/usr/bin/notify-send" if cmd == "notify-send" else None
        with self._patch_platform("Linux"), \
             mock.patch("candid.notify.shutil.which", side_effect=which), \
             mock.patch("candid.notify.subprocess.run") as run:
            self.assertTrue(N._notify_linux("T", "B", "critical"))
        cmd = run.call_args[0][0]
        self.assertEqual(cmd, ["notify-send", "--urgency=critical", "T", "B"])
        self.assertEqual(run.call_args[1]["timeout"], 10)

    def test_linux_gdbus_fallback(self):
        def which(cmd):
            return "/usr/bin/gdbus" if cmd == "gdbus" else None
        with self._patch_platform("Linux"), \
             mock.patch("candid.notify.shutil.which", side_effect=which), \
             mock.patch("candid.notify.subprocess.run") as run:
            self.assertTrue(N._notify_linux("T", "B", "normal"))
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "gdbus")
        self.assertIn("T", cmd)
        self.assertIn("B", cmd)

    def test_linux_no_backend_false(self):
        with self._patch_platform("Linux"), \
             mock.patch("candid.notify.shutil.which", return_value=None):
            self.assertFalse(N._notify_linux("T", "B", "normal"))

    def test_subprocess_timeout_is_failure(self):
        import subprocess as sp
        with mock.patch("candid.notify.subprocess.run",
                        side_effect=sp.TimeoutExpired("x", 10)):
            self.assertFalse(N._run(["whatever"]))

    def test_unsupported_platform_returns_false(self):
        with self._patch_platform("Plan9"):
            self.assertFalse(N._deliver("T", "B"))

    def test_windows_without_winsdk_returns_false(self):
        with self._patch_platform("Windows"):
            with mock.patch.dict("sys.modules", {"winsdk": None,
                                                 "winsdk.windows": None}):
                self.assertFalse(N._notify_windows("T", "B", "normal"))


class CLINotifyTest(NotifyBase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code
                return (code if isinstance(code, int) else 1,
                        out.getvalue(), err.getvalue())
            return 0, out.getvalue(), err.getvalue()

    def _no_quiet(self):
        p1 = mock.patch("candid.notify.is_quiet", return_value=False)
        p2 = mock.patch("candid.notify._snoozed", return_value=False)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_send_delivered(self):
        self._no_quiet()
        with mock.patch("candid.notify._deliver", return_value=True):
            code, out, _ = self.run_cli(
                ["notify", "send", "--title", "T", "--body", "B"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "delivered")

    def test_send_skipped_when_disabled(self):
        N.set_pref("enabled", False)
        code, out, _ = self.run_cli(
            ["notify", "send", "--title", "T", "--body", "B"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "skipped")

    def test_send_queued_when_quiet(self):
        with mock.patch("candid.notify.is_quiet", return_value=True), \
             mock.patch("candid.notify._snoozed", return_value=False):
            code, out, _ = self.run_cli(
                ["notify", "send", "--title", "T", "--body", "B"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "queued")

    def test_prefs_show_and_set(self):
        code, out, _ = self.run_cli(["notify", "prefs"])
        self.assertEqual(code, 0)
        self.assertIn('"enabled": true', out)
        code, out, _ = self.run_cli(
            ["notify", "prefs", "--set", "enabled=false",
             "--set", "categories.watchlist=false"])
        self.assertEqual(code, 0)
        self.assertIn('"enabled": false', out)
        self.assertFalse(N.get_prefs()["categories"]["watchlist"])

    def test_prefs_bad_key_friendly_error(self):
        code, out, err = self.run_cli(
            ["notify", "prefs", "--set", "bogus=1"])
        self.assertEqual(code, 1)
        self.assertIn("Error", err)

    def test_snooze_and_unsnooze(self):
        code, out, _ = self.run_cli(["notify", "snooze", "--minutes", "30"])
        self.assertEqual(code, 0)
        self.assertIn("Snoozed until", out)
        self.assertIsNotNone(N.snoozed_until())
        code, out, _ = self.run_cli(["notify", "unsnooze"])
        self.assertEqual(code, 0)
        self.assertIn("Snooze cleared", out)
        self.assertIsNone(N.snoozed_until())

    def test_snooze_for_duration(self):
        code, out, _ = self.run_cli(["notify", "snooze", "--for", "2h"])
        self.assertEqual(code, 0)
        until = N.snoozed_until()
        self.assertIsNotNone(until)
        self.assertGreater(until, datetime.now() + timedelta(hours=1, minutes=50))

    def test_flush(self):
        N.queue_notification("Q1", "b")
        self._no_quiet()
        with mock.patch("candid.notify._deliver", return_value=True):
            code, out, _ = self.run_cli(["notify", "flush"])
        self.assertEqual(code, 0)
        self.assertIn("Delivered 1 queued notification(s).", out)

    @unittest.skipIf(HAS_REMINDERS, "notify_reminders exists in this worktree")
    def test_due_missing_module_hint(self):
        code, out, err = self.run_cli(["notify", "due"])
        self.assertEqual(code, 1)
        self.assertIn("notify_reminders", out)


if __name__ == "__main__":
    unittest.main()
