"""Tests for the candid ritual command (batch 86).

ritual --help works, all 10 subcommands dispatch (sibling feature functions
are mocked since workers A-D's files are not in this tree), interviewers
add/list round-trips, and cooldown writes the debrief JSON with the exact
schema batch 2's debrief loop is expected to consume.

CANDID_DATA_DIR is set to a temp dir before importing candid modules.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_TMPDATA = tempfile.mkdtemp(prefix="candid-ritual-")
os.environ["CANDID_DATA_DIR"] = _TMPDATA

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import config as C  # noqa: E402
from candid import ritual as R  # noqa: E402

ALL_SUBCOMMANDS = [
    "logistics", "timeline", "materials", "dossier", "warmup",
    "techcheck", "calm", "countdown", "interviewers", "cooldown",
]


class RitualCLIBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="candid-ritual-test-"))
        self._old_candid_data_dir = os.environ.get("CANDID_DATA_DIR")
        os.environ["CANDID_DATA_DIR"] = str(self.tmp)
        self._saved = {}
        for name in ("TRACKER_PATH", "PROFILE_PATH", "PREP_PACKS_DIR",
                     "TAILOR_DIR", "SALARY_DB", "OFFERS_PATH",
                     "GMAIL_PROPOSALS_PATH", "DATA_DIR"):
            self._saved[name] = getattr(C, name)
        C.TRACKER_PATH = self.tmp / "tracker.json"
        C.PROFILE_PATH = self.tmp / "profile.json"
        C.PREP_PACKS_DIR = self.tmp / "prep_packs"
        C.TAILOR_DIR = self.tmp / "tailor"
        C.SALARY_DB = self.tmp / "salary.sqlite"
        C.OFFERS_PATH = self.tmp / "offers.json"
        C.GMAIL_PROPOSALS_PATH = self.tmp / "gmail_proposals.json"
        C.DATA_DIR = self.tmp

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(C, name, val)
        if self._old_candid_data_dir is None:
            os.environ.pop("CANDID_DATA_DIR", None)
        else:
            os.environ["CANDID_DATA_DIR"] = self._old_candid_data_dir

    def run_main(self, argv):
        """Run the CLI main(); returns (exit_code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                CLI.main(argv)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue(), err.getvalue()


class TestRitualHelp(RitualCLIBase):
    def test_ritual_help_lists_all_subcommands(self):
        code, out, _ = self.run_main(["ritual", "--help"])
        self.assertEqual(code, 0)
        for sub in ALL_SUBCOMMANDS:
            self.assertIn(sub, out)

    def test_interviewers_help(self):
        code, out, _ = self.run_main(["ritual", "interviewers", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("--add", out)
        self.assertIn("--list", out)

    def test_cooldown_help(self):
        code, out, _ = self.run_main(["ritual", "cooldown", "--help"])
        self.assertEqual(code, 0)

    def test_ritual_in_commands(self):
        self.assertIn("ritual", CLI.COMMANDS)
        self.assertEqual(CLI.SUBCOMMANDS["ritual"], ALL_SUBCOMMANDS)
        self.assertIn("RitualError", CLI._EXPECTED_ERRORS)
        self.assertEqual(CLI._NEXT_COMMAND["RitualError"],
                         "python -m candid ritual --help")


class TestRitualDispatch(RitualCLIBase):
    #: Extra required flags per subcommand for the dispatch smoke test.
    _EXTRA_ARGS = {
        "logistics": ["--date", "2026-09-25", "--round-type", "virtual"],
        "timeline": ["--start", "2026-09-25 14:00", "--round-type", "virtual"],
        "techcheck": ["--round-type", "virtual", "--no-net"],
        "countdown": ["--start", "2026-09-25 14:00"],
        "interviewers": ["--add", "Jane Doe, Hiring Manager"],
    }

    def test_all_ten_subcommands_dispatch(self):
        """Each subcommand reaches its handler (siblings mocked)."""
        for sub in ALL_SUBCOMMANDS:
            with self.subTest(sub=sub):
                argv = ["ritual", sub, "--company", "Acme",
                        "--role", "Data Scientist"] + self._EXTRA_ARGS.get(sub, [])
                args = CLI.build_parser().parse_args(argv)
                m = mock.MagicMock(return_value=0)
                with mock.patch.dict(R._HANDLERS, {sub: m}):
                    self.assertEqual(CLI.cmd_ritual(args), 0)
                    m.assert_called_once_with(args)

    def test_missing_sibling_raises_ritual_error(self):
        """A subcommand whose module file is absent fails cleanly."""
        args = CLI.build_parser().parse_args(
            ["ritual", "logistics", "--company", "Acme", "--role",
             "Data Scientist", "--date", "2026-09-25",
             "--round-type", "virtual"])
        real_import = R._import_sibling

        def fake_import(name):
            if name == "logistics":
                raise R.RitualError(
                    "ritual subcommand 'logistics' is not available in this "
                    "checkout (candid.ritual_logistics is missing).")
            return real_import(name)

        with mock.patch.object(R, "_import_sibling", side_effect=fake_import):
            with self.assertRaises(R.RitualError) as ctx:
                R.run(args)
        self.assertIn("candid.ritual_logistics", str(ctx.exception))

    def test_unknown_what_raises_ritual_error(self):
        with self.assertRaises(R.RitualError):
            R.run(mock.Mock(what="nonexistent"))


class TestInterviewers(RitualCLIBase):
    def test_add_list_round_trip(self):
        self.run_main(["ritual", "interviewers", "--company", "Acme",
                       "--role", "Data Scientist",
                       "--add", "Jane Doe, Hiring Manager", "--round", "1"])
        self.run_main(["ritual", "interviewers", "--company", "Acme",
                       "--role", "Data Scientist",
                       "--add", "Sam Lee, Senior Engineer"])
        path = self.tmp / "rituals" / "acme-data-scientist" / "interviewers.json"
        self.assertTrue(path.exists())
        panel = json.loads(path.read_text())
        self.assertEqual(len(panel), 2)
        self.assertEqual(panel[0]["name"], "Jane Doe")
        self.assertEqual(panel[0]["title"], "Hiring Manager")
        self.assertEqual(panel[0]["round"], "1")
        self.assertEqual(panel[1]["title"], "Senior Engineer")

        code, out, _ = self.run_main(["ritual", "interviewers",
                                      "--company", "Acme",
                                      "--role", "Data Scientist", "--list"])
        self.assertEqual(code, 0)
        self.assertIn("Jane Doe", out)
        self.assertIn("Sam Lee", out)
        self.assertIn("general guidance", out)
        # Manager gets behavioral/leadership angles; engineer gets coding angles.
        self.assertIn("Likely angle: behavioral / leadership", out)
        self.assertIn("Likely angle: coding / system design", out)

    def test_add_defaults_title(self):
        self.run_main(["ritual", "interviewers", "--company", "Acme",
                       "--role", "Data Scientist", "--add", "Pat"])
        panel = json.loads((self.tmp / "rituals" / "acme-data-scientist"
                            / "interviewers.json").read_text())
        self.assertEqual(panel[0]["title"], "Interviewer")

    def test_company_verified_label(self):
        # "Capital One" has an entry in QUESTIONS_DB (key "capitalone").
        self.run_main(["ritual", "interviewers", "--company", "Capital One",
                       "--role", "Data Scientist",
                       "--add", "Alex Kim, Recruiter"])
        code, out, _ = self.run_main(["ritual", "interviewers",
                                      "--company", "Capital One",
                                      "--role", "Data Scientist", "--list"])
        self.assertEqual(code, 0)
        self.assertIn("company-verified", out)
        self.assertIn("Likely angle: background screen", out)


class TestCooldown(RitualCLIBase):
    def test_cooldown_writes_debrief_json(self):
        answers = iter([
            "Tell me about yourself", "Design a URL shortener", "",
            "SQL window function question", "",
            "Rambled on the motivation answer", "",
            "warm",
            "Email recruiter Friday", "",
        ])
        with mock.patch("builtins.input", side_effect=lambda *a: next(answers)):
            code, out, _ = self.run_main(["ritual", "cooldown",
                                          "--company", "Acme",
                                          "--role", "Data Scientist"])
        self.assertEqual(code, 0)
        path = self.tmp / "debriefs" / "acme-data-scientist.json"
        self.assertTrue(path.exists())
        record = json.loads(path.read_text())
        # Exact schema batch 2's debrief loop is expected to consume.
        self.assertEqual(set(record.keys()),
                         {"company", "role", "date", "questions_asked",
                          "stumped_by", "weak_spots", "vibe", "next_steps"})
        self.assertEqual(record["company"], "Acme")
        self.assertEqual(record["role"], "Data Scientist")
        self.assertEqual(record["questions_asked"],
                         ["Tell me about yourself", "Design a URL shortener"])
        self.assertEqual(record["stumped_by"], ["SQL window function question"])
        self.assertEqual(record["weak_spots"], ["Rambled on the motivation answer"])
        self.assertEqual(record["vibe"], "warm")
        self.assertEqual(record["next_steps"], ["Email recruiter Friday"])
        # Reminder to send thank-you notes via the followup command.
        self.assertIn("python -m candid followup thank-you", out)

    def test_cooldown_tolerates_eof(self):
        with mock.patch("builtins.input", side_effect=EOFError):
            code, out, _ = self.run_main(["ritual", "cooldown",
                                          "--company", "Acme",
                                          "--role", "Data Scientist"])
        self.assertEqual(code, 0)
        record = json.loads((self.tmp / "debriefs" / "acme-data-scientist.json")
                            .read_text())
        self.assertEqual(record["questions_asked"], [])
        self.assertEqual(record["vibe"], "")


if __name__ == "__main__":
    unittest.main()
