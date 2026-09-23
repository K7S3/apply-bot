"""Confirm-before-destroy for candid destructive CLI actions.

``confirm_destructive`` prints "This will <action>." and requires an
explicit yes; the prompt defaults to No.

Non-TTY safety: when stdin is not a terminal and neither ``assume_yes``
nor ``assume_no`` is set, this returns False *without prompting* -- a CLI
piped into a script or run from a cron job must never hang waiting for
input it cannot see, and must never destroy data on an unattended run.

Integration note: if ``candid.interactive`` ever provides ``ask_confirm``
(worker 1's interactive-mode feature), the prompt half of this module can
delegate to it; the TTY guard and flag semantics here stay as-is. Until
then the prompt is a local ``input()`` guarded by the TTY check.
"""

from __future__ import annotations

import sys

# --- data-driven action descriptions -------------------------------------------
# Key: the CLI action identifier. Value: the plain-language consequence used
# in "This will <description>.". CLI wiring looks up the description here
# instead of hard-coding prompt text per command.
DESTRUCTIVE_ACTIONS: dict[str, str] = {
    "track remove": "permanently delete this application from the tracker",
    "track purge": "permanently delete ALL applications from the tracker",
    "retention purge": "permanently delete data older than the retention window",
    "defaults clear": "erase all saved smart defaults",
    "insights clear": "erase all saved insights",
}


def destructive_description(key: str) -> str | None:
    """Look up the description for a destructive action key, else None."""
    return DESTRUCTIVE_ACTIONS.get(key)


def _prompt_yes_no(prompt: str) -> bool:
    """Return True only on an explicit yes to a y/N prompt."""
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes"}


def confirm_destructive(
    action: str,
    *,
    assume_yes: bool = False,
    assume_no: bool = False,
) -> bool:
    """Ask before a destructive action; True only on explicit yes.

    Prints "This will <action>." then a y/N prompt (default No).

    - ``assume_yes=True``: return True immediately, no prompt.
    - ``assume_no=True``: return False immediately, no prompt.
    - stdin not a TTY and neither flag set: return False without
      prompting (safe default; no hang).
    """
    if assume_yes:
        return True
    if assume_no:
        return False
    if not sys.stdin.isatty():
        return False
    print(f"This will {action}.")
    return _prompt_yes_no("Proceed? [y/N]: ")
