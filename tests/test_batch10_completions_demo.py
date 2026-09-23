"""Tests for batch 10 workstream A: shell completions + demo tour.

Run: python -m unittest tests.test_batch10_completions_demo -v
"""
import argparse
import contextlib
import io
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from candid import __main__ as CLI  # noqa: E402
from candid import completions  # noqa: E402
from candid import config as C  # noqa: E402
from candid import demo  # noqa: E402

DATA_ATTRS = (
    "DATA_DIR", "PROFILE_PATH", "TRACKER_PATH", "OFFERS_PATH",
    "SALARY_DB", "PREP_PACKS_DIR", "TAILOR_DIR", "GMAIL_PROPOSALS_PATH",
)


def fresh_parser():
    return CLI.build_parser()


def bare_parser():
    """A minimal parser with one subparsers action, for register() unit tests.

    (The full build_parser() already wires every command, so registering
    onto it again would raise a conflicting-subparser error.)
    """
    parser = argparse.ArgumentParser(prog="candid")
    parser.add_subparsers(dest="cmd", required=True)
    return parser


def subparsers_of(parser):
    return next(
        a for a in parser._actions
        if isinstance(a, argparse._SubParsersAction))


class CompletionsRegisterTest(unittest.TestCase):
    def test_register_adds_completions_command(self):
        parser = bare_parser()
        completions.register(subparsers_of(parser))
        sub = subparsers_of(parser)
        self.assertIn("completions", sub.choices)
        args = parser.parse_args(["completions", "bash"])
        self.assertEqual(args.shell, "bash")
        self.assertTrue(callable(args.func))
        self.assertIs(args.func, completions.cmd_completions)

    def test_shell_argument_is_restricted(self):
        parser = bare_parser()
        completions.register(subparsers_of(parser))
        for shell in ("bash", "zsh", "fish"):
            self.assertEqual(
                parser.parse_args(["completions", shell]).shell, shell)
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(["completions", "powershell"])

    def test_demo_register_adds_keep_option(self):
        parser = bare_parser()
        demo.register(subparsers_of(parser))
        args = parser.parse_args(["demo"])
        self.assertIsNone(args.keep)
        self.assertTrue(callable(args.func))
        self.assertIs(args.func, demo.cmd_demo)
        args = parser.parse_args(["demo", "--keep", "/tmp/x"])
        self.assertEqual(args.keep, "/tmp/x")


class CompletionsGenerateTest(unittest.TestCase):
    def setUp(self):
        # fresh_parser() (the real build_parser) already wires completions/demo
        self.parser = fresh_parser()

    def test_all_shells_contain_known_commands(self):
        gens = {"bash": completions.generate_bash,
                "zsh": completions.generate_zsh,
                "fish": completions.generate_fish}
        for shell, gen in gens.items():
            script = gen(self.parser)
            for token in ("match", "tailor", "track", "prep", "completions",
                          "demo"):
                self.assertIn(token, script, f"{shell} missing {token}")

    def test_all_shells_contain_known_subcommands(self):
        gens = {"bash": completions.generate_bash,
                "zsh": completions.generate_zsh,
                "fish": completions.generate_fish}
        for shell, gen in gens.items():
            script = gen(self.parser)
            for token in ("cover-letter", "export-csv", "thank-you",
                          "check-in", "import-lca"):
                self.assertIn(token, script, f"{shell} missing {token}")

    def test_scripts_generated_from_live_parser(self):
        # Single source of truth: a command added to the live parser must
        # show up in regenerated scripts.
        sub = subparsers_of(self.parser)
        added = sub.add_parser("zzsynthetic", help="synthetic test command")
        try:
            for gen in (completions.generate_bash, completions.generate_zsh,
                        completions.generate_fish):
                self.assertIn("zzsynthetic", gen(self.parser))
        finally:
            del sub.choices["zzsynthetic"]
            sub._choices_actions = [
                a for a in sub._choices_actions if a.dest != "zzsynthetic"]

    def test_bash_script_syntax(self):
        if shutil.which("bash") is None:
            self.skipTest("bash not installed")
        self._assert_syntax_ok("bash", "-n",
                               completions.generate_bash(self.parser))

    def test_zsh_script_syntax(self):
        if shutil.which("zsh") is None:
            self.skipTest("zsh not installed")
        self._assert_syntax_ok("zsh", "-n",
                               completions.generate_zsh(self.parser))

    def _assert_syntax_ok(self, prog, flag, script):
        with tempfile.NamedTemporaryFile("w", suffix=".compl",
                                         delete=False) as f:
            f.write(script)
            path = f.name
        try:
            r = subprocess.run([prog, flag, path], capture_output=True,
                               text=True, timeout=60)
            self.assertEqual(r.returncode, 0,
                             f"{prog} syntax check failed: {r.stderr}")
        finally:
            os.unlink(path)

    def test_zsh_dispatch_with_stubs(self):
        # Functionally exercise the generated zsh: stub out the completion
        # builtins, fake the command line, and check the dispatch.
        if shutil.which("zsh") is None:
            self.skipTest("zsh not installed")
        script = completions.generate_zsh(self.parser)
        with tempfile.NamedTemporaryFile("w", suffix=".zsh",
                                         delete=False) as f:
            f.write(script)
            path = f.name
        harness = r"""
_arguments() {
  case "$*" in
    *"1:command"*) state=args; line=($LINEWORDS); return 1 ;;
    *) print -r -- "ARGUMENTS $*"; return 0 ;;
  esac
}
_describe() { print -r -- "DESCRIBE $*"; }
words=($WORDS); CURRENT=$CUR; LINEWORDS=($LINEW); state=""; line=()
source %s
""" % path.replace("'", "'\\''")
        try:
            def run(words, cur, linew):
                env = (f"WORDS='{' '.join(words)}' CUR={cur} "
                       f"LINEW='{' '.join(linew)}'")
                prog = f"{env} zsh -f -c {shlex.quote(harness)}"
                r = subprocess.run(prog, shell=True, capture_output=True,
                                   text=True, timeout=60)
                return r.stdout
            # completing `candid track <TAB>` offers subcommands
            out = run(["candid", "track"], 3, ["track"])
            self.assertIn("DESCRIBE", out)
            self.assertIn("subcommand", out)
            # completing `candid match --<TAB>` offers match's options
            out = run(["candid", "match"], 3, ["match"])
            self.assertIn("ARGUMENTS", out)
            self.assertIn("--jd", out)
        finally:
            os.unlink(path)


class CompletionsCommandTest(unittest.TestCase):
    def test_cmd_completions_prints_script(self):
        parser = fresh_parser()  # build_parser already wires `completions`
        for shell in ("bash", "zsh", "fish"):
            args = parser.parse_args(["completions", shell])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                args.func(args)
            out = buf.getvalue()
            self.assertIn("match", out)
            self.assertIn("candid", out.lower())


class DemoRunTest(unittest.TestCase):
    def _snapshot(self):
        return ({name: getattr(C, name) for name in DATA_ATTRS},
                os.environ.get("CANDID_DATA_DIR"))

    def _assert_restored(self, saved_attrs, saved_env):
        for name, value in saved_attrs.items():
            self.assertEqual(getattr(C, name), value,
                             f"config.{name} was not restored")
        self.assertEqual(os.environ.get("CANDID_DATA_DIR"), saved_env,
                         "CANDID_DATA_DIR was not restored")

    def test_demo_end_to_end(self):
        saved_attrs, saved_env = self._snapshot()
        real_dir = Path(saved_attrs["DATA_DIR"])
        before = (sorted(p.name for p in real_dir.iterdir())
                  if real_dir.exists() else None)
        started = time.perf_counter()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            demo.cmd_demo(types.SimpleNamespace(keep=None))
        elapsed = time.perf_counter() - started
        out = buf.getvalue()

        # key sections of the narrated tour are printed
        lowered = out.lower()
        for section in ("onboard", "match", "tailor", "track", "prep"):
            self.assertIn(section, lowered, f"missing section: {section}")
        self.assertIn("Alex Rivera", out)
        self.assertIn("Match score:", out)
        self.assertIn("Prep pack saved to", out)
        self.assertIn("Your real candid data is untouched", out)

        # fast and non-interactive
        self.assertLess(elapsed, 30, f"demo took {elapsed:.1f}s")

        # temp data dir was cleaned up
        m = re.search(r"throwaway data dir:\s*\n\s*(\S+)", out)
        self.assertIsNotNone(m, "demo did not print its temp data dir")
        self.assertFalse(Path(m.group(1)).exists(),
                         "demo temp dir was not cleaned up")

        # config + env restored, real data dir untouched
        self._assert_restored(saved_attrs, saved_env)
        after = (sorted(p.name for p in real_dir.iterdir())
                 if real_dir.exists() else None)
        self.assertEqual(before, after, "real DATA_DIR was modified by demo")

    def test_demo_keep_persists_data(self):
        saved_attrs, saved_env = self._snapshot()
        with tempfile.TemporaryDirectory() as td:
            keep = Path(td) / "keepme"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                demo.cmd_demo(types.SimpleNamespace(keep=str(keep)))
            out = buf.getvalue()
            self.assertTrue((keep / "profile.json").exists())
            self.assertTrue((keep / "tracker.json").exists())
            self.assertTrue((keep / "prep_packs").is_dir())
            self.assertTrue((keep / "tailored").is_dir())
            self.assertIn(str(keep), out)
        self._assert_restored(saved_attrs, saved_env)


if __name__ == "__main__":
    unittest.main()
