"""Interactive REPL for the candid CLI (`candid shell`).

Reads lines at a ``candid> `` prompt, parses them with shlex, and dispatches
into the existing CLI by calling ``candid.__main__.main()``.  Argparse's
SystemExit (from ``--help`` or usage errors) is swallowed so the loop keeps
running.

Stdlib only.  The loop is factored so tests can feed an iterable of lines
instead of real stdin: ``run_shell(lines=[...])``.
"""

from __future__ import annotations

import os
import shlex
import sys

from candid import __main__ as cli
from candid import config

try:
    import readline  # noqa: F401  (optional; history also works without it)
except ImportError:  # pragma: no cover
    readline = None  # type: ignore[assignment]

PROMPT = "candid> "

BUILTINS = ("help", "exit", "quit", "clear")

#: One-line blurbs for the `help` builtin.
_COMMAND_BLURBS = {
    "onboard": "Ingest resume/LinkedIn into your profile.",
    "profile": "Show your stored profile.",
    "match": "Score a job description against your profile.",
    "tailor": "Tailored resume / cover letter.",
    "track": "Application tracker (add, list, update, ...).",
    "prep": "Build an interview prep pack.",
    "followup": "Draft thank-you / check-in / referral emails.",
    "offer": "Record and compare offers.",
    "negotiate": "Negotiation playbook, scripts, counter drafts.",
    "salary": "Salary intelligence (lookup, LCA import, parse ranges).",
    "mock": "Mock interviews: coding judge, AI interviewer, behavioral.",
    "jobs": "Curate open jobs and feed the tracker.",
    "dashboard": "Launch the local web dashboard.",
    "import": "Import your own data exports (mbox, LinkedIn ZIP, ...).",
    "gmail": "Gmail Takeout mbox import: parse, propose, confirm.",
    "linkedin": "Import LinkedIn's official data export.",
}


def _history_path():
    # Looked up dynamically so tests can monkeypatch config.CONFIG_DIR.
    return config.CONFIG_DIR / "shell_history"


class _History:
    """Append-only command history. Works with or without readline."""

    def __init__(self, path=None):
        self.path = path if path is not None else _history_path()
        self._loaded = False

    def load(self):
        """Seed this readline session from the on-disk history file."""
        if self._loaded:
            return
        self._loaded = True
        if readline is None:
            return
        try:
            if self.path.exists():
                for line in self.path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        readline.add_history(line)
        except OSError:
            pass

    def add(self, line: str):
        line = line.rstrip("\n")
        if not line.strip():
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass  # history is best-effort; never break the REPL
        if readline is not None:
            try:
                readline.add_history(line)
            except Exception:
                pass


def _print_help():
    print("Shell builtins: help, exit (quit), clear")
    print("Commands:")
    for cmd in cli.COMMANDS:
        blurb = _COMMAND_BLURBS.get(cmd, "")
        print(f"  {cmd:<10} {blurb}")
    print("\nType any candid command, e.g. `match --help` or `track list`.")


def _clear_screen():
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    else:
        print()


def _stdin_lines():
    """Yield lines from the real stdin, handling Ctrl-C / Ctrl-D."""
    while True:
        try:
            yield input(PROMPT)
        except EOFError:
            # Ctrl-D: clean exit
            print()
            return
        except KeyboardInterrupt:
            # Ctrl-C: newline and keep looping
            print()
            continue


def _dispatch(argv: list[str]) -> None:
    """Run one parsed command through the real CLI, staying in the loop."""
    try:
        cli.main(argv)
    except SystemExit:
        # argparse exits on --help (0) or usage errors (2); main() already
        # printed the friendly message. Either way, keep looping.
        pass
    except Exception as e:  # unexpected: report, don't kill the REPL
        print(f"Error: {e}", file=sys.stderr)


def _handle_line(raw: str, hist: _History) -> str:
    """Process one input line. Returns 'exit' when the loop should stop."""
    line = raw.strip()
    if not line:
        return "continue"  # empty line = no-op
    hist.add(line)
    try:
        argv = shlex.split(line, posix=True)
    except ValueError as e:
        print(f"Could not parse that line: {e}", file=sys.stderr)
        return "continue"
    if not argv:
        return "continue"
    head = argv[0]
    if head in ("exit", "quit"):
        return "exit"
    if head == "clear":
        _clear_screen()
        return "continue"
    if head == "help":
        _print_help()
        return "continue"
    _dispatch(argv)
    return "continue"


def run_shell(argv=None, lines=None) -> int:
    """Run the interactive shell. Returns the process exit code.

    ``lines``: optional iterable of input lines (used by tests so the
    ``candid> `` prompt never blocks on real stdin).
    """
    hist = _History()
    hist.load()
    if lines is None:
        if not sys.stdin.isatty():
            print("candid shell: stdin is not a TTY and no commands were "
                  "given; refusing to hang. Run interactively or pipe "
                  "commands in.", file=sys.stderr)
            return 2
        source = _stdin_lines()
    else:
        source = iter(lines)
    for raw in source:
        if _handle_line(raw, hist) == "exit":
            break
    return 0


def cmd_shell(a):
    """argparse entry point (wired in by the coordinator)."""
    sys.exit(run_shell(argv=getattr(a, "args", None)))
