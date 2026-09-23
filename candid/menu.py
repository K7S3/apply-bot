"""Plain-language intent menu mapped onto real candid commands.

The menu is data-driven: every entry is checked against
``candid.__main__.COMMANDS`` / ``SUBCOMMANDS`` at import time, so it can
never list a command that does not exist in this tree.
"""

from __future__ import annotations

from candid import __main__ as cli

# (plain-language intent, argv to run). Checked against COMMANDS/SUBCOMMANDS
# below; entries pointing at missing commands are dropped silently.
_INTENTS: list[tuple[str, list[str]]] = [
    ("Set up my profile", ["onboard"]),
    ("Score a job description", ["match"]),
    ("Tailor my resume", ["tailor", "resume"]),
    ("Track a new application", ["track", "add"]),
    ("See my applications", ["track", "list"]),
    ("Prepare for an interview", ["prep"]),
    ("Practice interviews", ["mock"]),
    ("Check salary data", ["salary", "lookup"]),
    ("Find jobs", ["jobs", "curate"]),
    ("Compare offers", ["offer", "compare"]),
    ("Draft a follow-up email", ["followup", "thank-you"]),
    ("Open the dashboard", ["dashboard"]),
]


def _command_exists(argv: list[str]) -> bool:
    cmd = argv[0]
    if cmd not in cli.COMMANDS:
        return False
    if len(argv) > 1:
        subs = cli.SUBCOMMANDS.get(cmd) or []
        return argv[1] in subs
    return True


#: Numbered menu entries that actually exist in this tree.
MENU: list[tuple[str, list[str]]] = [
    (label, argv) for label, argv in _INTENTS if _command_exists(argv)
]


def pick_intent(choice: str) -> list[str] | None:
    """Map a menu choice to the argv list that runs it.

    Accepts a 1-based menu number ("3"), the intent label
    ("Tailor my resume"), or the command words ("tailor resume").
    Returns None for anything invalid.
    """
    norm = (choice or "").strip().lower()
    if not norm:
        return None
    # menu number, tolerating a trailing dot ("3.")
    num = norm[:-1] if norm.endswith(".") else norm
    if num.isdigit():
        i = int(num) - 1
        if 0 <= i < len(MENU):
            return list(MENU[i][1])
        return None
    for label, argv in MENU:
        if norm == label.lower() or norm == " ".join(argv):
            return list(argv)
    return None


def show_menu() -> str | None:
    """Print the intent menu, read one choice, return the intent label.

    Returns None when the user cancels (empty / q) or picks something
    invalid.
    """
    print("What would you like to do?")
    for i, (label, argv) in enumerate(MENU, 1):
        print(f"  {i:>2}. {label:<28} (candid {' '.join(argv)})")
    choice = input("Choose [1-%d] (q to cancel): " % len(MENU)).strip()
    if not choice or choice.lower() in ("q", "quit", "cancel", "exit"):
        return None
    argv = pick_intent(choice)
    if argv is None:
        print("Not a valid choice.")
        return None
    label = next(l for l, a in MENU if a == argv)
    return label
