"""Pre-round tech checklist (ritual techcheck).

Local environment checks, all best-effort and offline-safe: python version,
importability of key libraries, free disk space, a quick network
reachability probe with a short timeout (skipped gracefully when offline),
plus a round-type-specific checklist (virtual / coding / phone).

Warnings are advisory, never fatal. No hardware is touched beyond what the
Python standard library allows safely: the camera and mic are checklist
reminders only, never opened.

Public API (the CLI group wires these via lazy imports):
    run_techcheck(round_type, check_network=True) -> list of (name, status, note)
    status is one of "pass", "warn", "info".

Manual use:
    python -m candid.ritual_techcheck --round-type virtual|coding|phone [--no-net]
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import socket
import sys
from pathlib import Path

PASS, WARN, INFO = "pass", "warn", "info"

ROUND_TYPES = ("virtual", "coding", "phone")

_CORE_LIBS = ("json", "sqlite3", "ssl", "urllib.request", "email")
_DISK_WARN_BYTES = 1_000_000_000  # warn below 1 GB free
_NET_TIMEOUT_S = 2


def _data_dir() -> Path:
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    from candid import config as _C
    return _C.DATA_DIR


# ---------------------------------------------------------------------------
# environment checks
# ---------------------------------------------------------------------------

def _check_python() -> tuple[str, str, str]:
    ok = sys.version_info >= (3, 9)
    return (
        "Python version",
        PASS if ok else WARN,
        f"Python {platform.python_version()} on this machine; candid targets 3.9+.",
    )


def _check_core_libs() -> tuple[str, str, str]:
    missing = []
    for mod in _CORE_LIBS:
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    if not missing:
        return ("Core libraries", PASS,
                "json, sqlite3, ssl, urllib, email all import cleanly.")
    return ("Core libraries", WARN,
            f"could not import: {', '.join(missing)}; reinstall or repair Python.")


def _check_pdf_support() -> tuple[str, str, str]:
    try:
        import pypdf  # noqa: F401
        return ("PDF resume parsing", PASS, "pypdf is installed.")
    except Exception:
        return ("PDF resume parsing", WARN,
                "pypdf not installed; use --resume with .md/.txt, or pip install pypdf.")


def _check_disk() -> tuple[str, str, str]:
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(d).free
    note = f"{free / 1e9:.1f} GB free under {d}."
    return ("Disk space", PASS if free >= _DISK_WARN_BYTES else WARN, note)


def _check_network(do_probe: bool) -> tuple[str, str, str]:
    if not do_probe:
        return ("Network reachability", INFO, "probe skipped (--no-net).")
    try:
        sock = socket.create_connection(("8.8.8.8", 53), timeout=_NET_TIMEOUT_S)
        sock.close()
        return ("Network reachability", PASS,
                "outbound connectivity looks fine (probe to 8.8.8.8:53).")
    except Exception:
        return ("Network reachability", WARN,
                "offline or blocked; every local check still works, but have "
                "join links and phone numbers on another device just in case.")


# ---------------------------------------------------------------------------
# round-type checklists (advisory reminders, not tests)
# ---------------------------------------------------------------------------

_ROUND_CHECKLISTS: dict[str, list[tuple[str, str]]] = {
    "virtual": [
        ("Meeting link ready",
         "Join from the calendar invite 5 minutes early; keep a dial-in number as backup."),
        ("Camera and mic",
         "Test both inside the meeting app beforehand; know where mute lives. "
         "Framing: eyes near the top third, light facing you."),
        ("Screen share tidy",
         "Close extra tabs and silence notifications; a clean desktop or a "
         "separate browser profile keeps shares professional."),
        ("Quiet room",
         "Take the call in a room with a door; give housemates a heads-up on timing."),
        ("Bandwidth",
         "Prefer wired or strong wifi; pause cloud backups and streaming during the call."),
    ],
    "coding": [
        ("IDE ready",
         "Open your editor with a fresh scratch file; confirm the language plugin runs."),
        ("Language runtime",
         f"Python {platform.python_version()} on this machine; double-check the version the round expects."),
        ("Coding platform login",
         "Sign in to the platform (CoderPad, HackerRank, CodeSignal, etc.) before the round starts."),
        ("Second monitor",
         "If you have one, put the prompt on one screen and your editor on the other."),
        ("Quiet room",
         "Door closed, notifications silenced; keep water nearby."),
    ],
    "phone": [
        ("Phone charged",
         "Charge to at least 50 percent and keep the charger within reach."),
        ("Quiet room",
         "Take the call somewhere with a door; background noise reads badly on phone audio."),
        ("Notes at hand",
         "Keep your resume and 2-3 questions for them on paper or on screen."),
        ("Do Not Disturb",
         "Silence notifications or enable Do Not Disturb so nothing interrupts."),
        ("Caller number confirmed",
         "Save the interviewer's number as a contact so you recognize the call."),
    ],
}


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def run_techcheck(round_type: str, check_network: bool = True) -> list[tuple[str, str, str]]:
    """Run the pre-round tech checklist.

    Args:
        round_type: one of "virtual", "coding", "phone".
        check_network: if False, skip the reachability probe (used by tests).

    Returns:
        List of (name, status, note); status is "pass", "warn", or "info".
        Warnings are advisory, never fatal.
    """
    rt = (round_type or "").strip().lower()
    if rt not in ROUND_TYPES:
        raise ValueError(
            f"round_type must be one of {', '.join(ROUND_TYPES)}; got {round_type!r}")

    items: list[tuple[str, str, str]] = [
        _check_python(),
        _check_core_libs(),
        _check_pdf_support(),
        _check_disk(),
        _check_network(check_network),
    ]
    for name, note in _ROUND_CHECKLISTS[rt]:
        items.append((name, INFO, note))
    return items


def print_checklist(items: list[tuple[str, str, str]]) -> None:
    tag = {PASS: "PASS", WARN: "WARN", INFO: "INFO"}
    for name, status, note in items:
        print(f"[{tag.get(status, status.upper())}] {name}: {note}")
    warns = sum(1 for _, s, _ in items if s == WARN)
    print()
    if warns:
        print(f"{warns} warning(s), all advisory. Nothing here blocks your round.")
    else:
        print("All checks passed. You are good to go.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="candid ritual techcheck",
        description="Pre-interview tech checklist (advisory only, never fatal).")
    ap.add_argument("--round-type", required=True, choices=ROUND_TYPES,
                    help="Type of interview round")
    ap.add_argument("--no-net", action="store_true",
                    help="Skip the network reachability probe")
    a = ap.parse_args(argv)
    items = run_techcheck(a.round_type, check_network=not a.no_net)
    print(f"Tech check for a {a.round_type} round:\n")
    print_checklist(items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
