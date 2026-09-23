"""Interactive prompt toolkit shared by candid's CLI interactive features.

Stdlib only: no new dependencies. All user-facing prompts funnel through
this module so colors, TTY gating, and clean failures stay consistent.

Conventions:
  - ``is_tty()`` is true only when stdin AND stdout are TTYs.
  - Colors are emitted only when ``is_tty()`` is true and the ``NO_COLOR``
    environment variable is unset (empty or absent means color is OK).
  - ``InteractiveError`` is raised for clean failures (EOF, non-TTY with
    no fallback). The CLI catches these and prints a one-line message
    with no traceback.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

__all__ = [
    "InteractiveError",
    "is_tty",
    "bold",
    "green",
    "yellow",
    "red",
    "dim",
    "banner",
    "hint",
    "ask",
    "ask_choice",
    "ask_confirm",
    "ask_path",
    "ask_int",
]


class InteractiveError(Exception):
    """A clean, user-facing failure in an interactive prompt.

    Raised on EOF and when input is needed but the session is not
    interactive and no fallback (default) was provided. The CLI catches
    these and prints a one-line message with no traceback.
    """


def is_tty() -> bool:
    """True only when both stdin AND stdout are TTYs."""
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _color_allowed() -> bool:
    """Colors are emitted only on a TTY with NO_COLOR unset."""
    return is_tty() and not os.environ.get("NO_COLOR")


def _style(text: str, code: str) -> str:
    if _color_allowed():
        return f"\033[{code}m{text}\033[0m"
    return text


def bold(text: str) -> str:
    """Bold styling, TTY-gated."""
    return _style(text, "1")


def green(text: str) -> str:
    """Green styling, TTY-gated."""
    return _style(text, "32")


def yellow(text: str) -> str:
    """Yellow styling, TTY-gated."""
    return _style(text, "33")


def red(text: str) -> str:
    """Red styling, TTY-gated."""
    return _style(text, "31")


def dim(text: str) -> str:
    """Dim styling, TTY-gated."""
    return _style(text, "2")


def banner(text: str) -> None:
    """Print a section banner line (dim, TTY-gated colors)."""
    print(dim(f"=== {text} ==="), flush=True)


def hint(text: str) -> None:
    """Print a small hint line (dim, TTY-gated colors)."""
    print(dim(f"hint: {text}"), flush=True)


def _read_line(prompt: str, password: bool) -> str:
    """Read one line from the user; InteractiveError on EOF."""
    try:
        if password:
            return getpass.getpass(prompt)
        return input(prompt)
    except EOFError:
        raise InteractiveError("input ended unexpectedly (EOF)")


def _check_interactive(default, has_default: bool, what: str):
    """Non-TTY guard: never call input() when not interactive.

    Returns the default when one exists, otherwise raises
    InteractiveError.
    """
    if sys.stdin.isatty():
        return None, False
    if has_default:
        return default, True
    raise InteractiveError(
        f"cannot ask for {what}: stdin is not interactive "
        "(run in a terminal or pass a default)"
    )


def ask(
    prompt: str,
    default: str | None = None,
    validator=None,
    required: bool = False,
    password: bool = False,
) -> str:
    """Ask for free-form text.

    - ``default``: shown as ``[default]``; empty input returns it.
    - ``validator``: callable returning True or an error string;
      re-prompts on failure, printing the error string when given.
    - ``required=True`` with no default: re-prompts on empty input.
    - Raises ``InteractiveError`` on EOF.
    - Never calls ``input()`` when stdin is not a TTY: returns the
      default if one exists, else raises ``InteractiveError``.
    """
    fallback, used = _check_interactive(default, default is not None, "input")
    if used:
        return fallback

    shown = f"{prompt} [{default}]: " if default is not None else f"{prompt}: "
    while True:
        raw = _read_line(shown, password)
        if raw == "" and default is not None:
            return default
        if raw.strip() == "" and required and default is None:
            print(yellow("This field is required."), flush=True)
            continue
        if validator is not None:
            ok = validator(raw)
            if ok is not True:
                msg = ok if isinstance(ok, str) else "Invalid input."
                print(yellow(str(msg)), flush=True)
                continue
        return raw


def _normalize_options(options) -> list[tuple[str, str]]:
    """Accept list[str] or list[(value, label)]; return (value, label) pairs."""
    pairs = []
    for opt in options:
        if isinstance(opt, (tuple, list)) and len(opt) == 2:
            pairs.append((str(opt[0]), str(opt[1])))
        else:
            pairs.append((str(opt), str(opt)))
    return pairs


def ask_choice(prompt: str, options, default: str | int | None = None) -> str:
    """Ask the user to pick from a numbered menu.

    ``options`` may be a list of strings or a list of ``(value, label)``
    tuples. Returns the VALUE of the chosen option. Accepts a 1-based
    number or the exact value text. ``default`` may be a value or a
    1-based index into the options. Re-prompts on invalid input.
    """
    pairs = _normalize_options(options)
    if not pairs:
        raise InteractiveError("ask_choice needs at least one option")

    default_idx: int | None = None
    if default is not None:
        if isinstance(default, int) and 1 <= default <= len(pairs):
            default_idx = default - 1
        else:
            for i, (value, _label) in enumerate(pairs):
                if value == str(default):
                    default_idx = i
                    break

    fallback, used = _check_interactive(
        pairs[default_idx][0] if default_idx is not None else None,
        default_idx is not None,
        "a choice",
    )
    if used:
        return fallback

    print(prompt, flush=True)
    for i, (value, label) in enumerate(pairs, start=1):
        marker = " (default)" if default_idx == i - 1 else ""
        print(f"  {i}) {label}{marker}", flush=True)

    while True:
        suffix = f" [{default_idx + 1}]" if default_idx is not None else ""
        raw = _read_line(f"Choice{suffix}: ", False).strip()
        if raw == "" and default_idx is not None:
            return pairs[default_idx][0]
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(pairs):
                return pairs[idx][0]
        else:
            for value, _label in pairs:
                if raw == value:
                    return value
        print(yellow(f"Please enter a number 1-{len(pairs)} or an exact value."), flush=True)


def ask_confirm(prompt: str, default: bool = False) -> bool:
    """Ask a yes/no question.

    Shows ``[Y/n]`` when default is True, ``[y/N]`` otherwise. Accepts
    y/yes/n/no (case-insensitive); empty input returns the default.
    Re-prompts on anything else.
    """
    fallback, used = _check_interactive(default, True, "confirmation")
    if used:
        return fallback

    shown = f"{prompt} [{'Y/n' if default else 'y/N'}]: "
    while True:
        raw = _read_line(shown, False).strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print(yellow("Please answer y or n."), flush=True)


def ask_path(prompt: str, must_exist: bool = False, default=None) -> Path:
    """Ask for a filesystem path. Expands ``~``.

    When ``must_exist`` is true, re-prompts until the path exists.
    """
    default_str = str(default) if default is not None else None
    fallback, used = _check_interactive(
        Path(default_str).expanduser() if default_str is not None else None,
        default_str is not None,
        "a path",
    )
    if used:
        return fallback

    while True:
        raw = ask(prompt, default=default_str)
        path = Path(raw).expanduser()
        if must_exist and not path.exists():
            print(yellow(f"Path does not exist: {path}"), flush=True)
            continue
        return path


def ask_int(
    prompt: str,
    default: int | None = None,
    min: int | None = None,  # noqa: A002 - matches builtin-style param name
    max: int | None = None,  # noqa: A002 - matches builtin-style param name
) -> int:
    """Ask for an integer, optionally bounded by min/max."""
    default_str = str(default) if default is not None else None
    fallback, used = _check_interactive(default, default is not None, "a number")
    if used:
        return fallback

    while True:
        raw = ask(prompt, default=default_str)
        try:
            value = int(raw.strip())
        except ValueError:
            print(yellow(f"'{raw}' is not a whole number."), flush=True)
            continue
        if min is not None and value < min:
            print(yellow(f"Must be at least {min}."), flush=True)
            continue
        if max is not None and value > max:
            print(yellow(f"Must be at most {max}."), flush=True)
            continue
        return value
