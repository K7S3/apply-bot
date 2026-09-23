"""Tests for candid.prefill (smart default pre-fill) and candid.confirm
(confirm-before-destroy).

CONFIG_DIR is redirected with the CANDID_CONFIG_DIR env var so no real
user config is touched.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import confirm as CF  # noqa: E402
from candid import prefill as PF  # noqa: E402


class EnvBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-prefill-"))
        self._old = os.environ.get("CANDID_CONFIG_DIR")
        os.environ["CANDID_CONFIG_DIR"] = str(self.tmp)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CANDID_CONFIG_DIR", None)
        else:
            os.environ["CANDID_CONFIG_DIR"] = self._old

    def _write(self, name, payload):
        p = self.tmp / name
        if isinstance(payload, str):
            p.write_text(payload, encoding="utf-8")
        else:
            p.write_text(json.dumps(payload), encoding="utf-8")
        return p


class ResolutionOrderTest(EnvBase):
    def test_defaults_beats_history_beats_builtin(self):
        self._write("defaults.json", {"tailor": {"tone": "formal"}})
        self._write("history.json", {"last": {"tailor": {"tone": "chatty"}}})
        self.assertEqual(PF.get_default("tailor", "tone"), "formal")

    def test_history_beats_builtin(self):
        self._write("history.json", {"last": {"tailor": {"tone": "chatty"}}})
        self.assertEqual(PF.get_default("tailor", "tone"), "chatty")

    def test_builtin_fallback(self):
        self.assertEqual(PF.get_default("tailor", "tone"), "confident")
        self.assertEqual(PF.get_default("tailor", "length"), "one-page")

    def test_nothing_anywhere_returns_none(self):
        self.assertIsNone(PF.get_default("match", "min_score"))
        self.assertIsNone(PF.get_default("nope", "nope"))

    def test_builtin_empty_string_falls_through(self):
        # jobs/location builtin is "" -- get_default returns it as-is;
        # format_default renders no suffix for it.
        self.assertEqual(PF.get_default("jobs", "location"), "")
        self.assertEqual(PF.format_default(PF.get_default("jobs", "location")), "")


class CorruptFilesTest(EnvBase):
    def test_corrupt_defaults_falls_through_to_history(self):
        self._write("defaults.json", "{not valid json!!")
        self._write("history.json", {"last": {"tailor": {"tone": "chatty"}}})
        self.assertEqual(PF.get_default("tailor", "tone"), "chatty")

    def test_corrupt_defaults_and_history_falls_to_builtin(self):
        self._write("defaults.json", "{nope")
        self._write("history.json", "[1,2,3")
        self.assertEqual(PF.get_default("tailor", "tone"), "confident")

    def test_non_dict_json_treated_as_empty(self):
        self._write("defaults.json", ["a", "list"])
        self.assertEqual(PF.get_default("tailor", "tone"), "confident")

    def test_malformed_sections_ignored(self):
        self._write("defaults.json", {"tailor": "not-a-dict"})
        self._write("history.json", {"last": {"tailor": {"tone": 42}}})
        self.assertEqual(PF.get_default("tailor", "tone"), "confident")


class ConfigDirOverrideTest(EnvBase):
    def test_override_honored_at_call_time(self):
        other = Path(tempfile.mkdtemp(prefix="candid-prefill-b-"))
        (other / "defaults.json").write_text(
            json.dumps({"tailor": {"tone": "bold"}}), encoding="utf-8")
        # First call uses self.tmp (no defaults.json) -> builtin.
        self.assertEqual(PF.get_default("tailor", "tone"), "confident")
        # Change the env var AFTER import / after first call: picked up live.
        os.environ["CANDID_CONFIG_DIR"] = str(other)
        self.assertEqual(PF.get_default("tailor", "tone"), "bold")
        # And back again.
        os.environ["CANDID_CONFIG_DIR"] = str(self.tmp)
        self.assertEqual(PF.get_default("tailor", "tone"), "confident")


class RecordHistoryTest(EnvBase):
    def test_round_trip(self):
        PF.record_history("jobs", "location", "Boston")
        self.assertEqual(PF.get_default("jobs", "location"), "Boston")
        data = json.loads((self.tmp / "history.json").read_text(encoding="utf-8"))
        self.assertEqual(data["last"]["jobs"]["location"], "Boston")

    def test_defaults_still_win_over_recorded_history(self):
        self._write("defaults.json", {"jobs": {"location": "NYC"}})
        PF.record_history("jobs", "location", "Boston")
        self.assertEqual(PF.get_default("jobs", "location"), "NYC")

    def test_corrupt_history_rewritten_clean(self):
        self._write("history.json", "{garbage")
        PF.record_history("tailor", "tone", "formal")
        data = json.loads((self.tmp / "history.json").read_text(encoding="utf-8"))
        self.assertEqual(data["last"]["tailor"]["tone"], "formal")

    def test_preserves_other_commands(self):
        PF.record_history("tailor", "tone", "formal")
        PF.record_history("jobs", "location", "Boston")
        self.assertEqual(PF.get_default("tailor", "tone"), "formal")
        self.assertEqual(PF.get_default("jobs", "location"), "Boston")

    def test_non_str_stored_value_ignored_by_get_default(self):
        self._write("history.json", {"last": {"tailor": {"tone": 42}}})
        self.assertEqual(PF.get_default("tailor", "tone"), "confident")


class FormatDefaultTest(unittest.TestCase):
    def test_none(self):
        self.assertEqual(PF.format_default(None), "")

    def test_empty_string(self):
        self.assertEqual(PF.format_default(""), "")

    def test_value(self):
        self.assertEqual(PF.format_default("confident"), " [default: confident]")


class ConfirmDestructiveTest(unittest.TestCase):
    def _tty(self, answer):
        """Patch stdin to a TTY and input() to return `answer`."""
        stdin = mock.Mock()
        stdin.isatty.return_value = True
        return mock.patch.object(CF.sys, "stdin", stdin), mock.patch(
            "builtins.input", return_value=answer
        )

    def test_explicit_yes(self):
        p1, p2 = self._tty("yes")
        with p1, p2, mock.patch("builtins.print"):
            self.assertTrue(CF.confirm_destructive("do X"))

    def test_y(self):
        p1, p2 = self._tty("y")
        with p1, p2, mock.patch("builtins.print"):
            self.assertTrue(CF.confirm_destructive("do X"))

    def test_no(self):
        p1, p2 = self._tty("no")
        with p1, p2, mock.patch("builtins.print"):
            self.assertFalse(CF.confirm_destructive("do X"))

    def test_empty_defaults_to_no(self):
        p1, p2 = self._tty("")
        with p1, p2, mock.patch("builtins.print"):
            self.assertFalse(CF.confirm_destructive("do X"))

    def test_prints_consequence(self):
        p1, p2 = self._tty("n")
        with p1, p2, mock.patch("builtins.print") as pr:
            CF.confirm_destructive("erase all saved smart defaults")
        pr.assert_any_call("This will erase all saved smart defaults.")

    def test_assume_yes_returns_true_without_prompting(self):
        with mock.patch("builtins.input", side_effect=AssertionError("prompted!")), \
             mock.patch("builtins.print") as pr:
            self.assertTrue(CF.confirm_destructive("do X", assume_yes=True))
        pr.assert_not_called()

    def test_assume_no_returns_false_without_prompting(self):
        with mock.patch("builtins.input", side_effect=AssertionError("prompted!")), \
             mock.patch("builtins.print") as pr:
            self.assertFalse(CF.confirm_destructive("do X", assume_no=True))
        pr.assert_not_called()

    def test_non_tty_returns_false_without_prompting(self):
        stdin = mock.Mock()
        stdin.isatty.return_value = False
        with mock.patch.object(CF.sys, "stdin", stdin), \
             mock.patch("builtins.input", side_effect=AssertionError("prompted!")), \
             mock.patch("builtins.print") as pr:
            self.assertFalse(CF.confirm_destructive("do X"))
        pr.assert_not_called()


class DestructiveActionsTest(unittest.TestCase):
    def test_required_keys_present(self):
        for key in ("track remove", "track purge", "retention purge",
                    "defaults clear", "insights clear"):
            self.assertIn(key, CF.DESTRUCTIVE_ACTIONS)
            self.assertTrue(CF.DESTRUCTIVE_ACTIONS[key])

    def test_lookup_helper(self):
        self.assertEqual(
            CF.destructive_description("track remove"),
            "permanently delete this application from the tracker",
        )
        self.assertIsNone(CF.destructive_description("no such action"))


if __name__ == "__main__":
    unittest.main()
