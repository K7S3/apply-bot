"""Outreach timing: when did you last email a connection?

``get_last_contact(full_name, mbox_path)`` scans a Gmail Takeout mbox for
messages whose From/To/Cc headers mention the connection's full name and
returns the most recent message date (or None).

Name matching is deliberately defensive: a case-insensitive full-name
substring match against the display name and address parts of the headers.
When the match is ambiguous (more than one distinct contact identity), or
when there is no match at all, this returns None. It never guesses.

This is the hook behind the outreach queue's "last contact" column: the
queue can show, next to each contact, when you last emailed them, so you
space out intro requests sensibly. candid's gmail module parses message
bodies into dicts (candid/gmail.py ``parse_mbox``), but that drops To/Cc
headers, so this module reads headers with stdlib ``mailbox`` directly and
uses ``gmail.iter_mbox_files`` for Takeout path discovery (a single .mbox
file or a directory of them).

Everything is offline: the mbox file is only read, never modified.
"""

from __future__ import annotations

import mailbox
from datetime import date
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

#: Headers scanned for the connection's name.
_SCANNED_HEADERS = ("From", "To", "Cc")


class TimingError(Exception):
    """Raised for outreach-timing problems (missing mbox file, ...)."""


def _msg_date(msg) -> date | None:
    """Parse a message's Date header into a date; None if unparseable."""
    raw = msg.get("Date", "") or ""
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return dt.date() if dt is not None else None


def _header_identities(msg, needle: str) -> list[tuple[str, str]]:
    """(display name, address) pairs from From/To/Cc containing the name.

    ``needle`` is the lowercased full name; matching is a case-insensitive
    substring over both the display name and the address, so
    "Ann Lee <ann.lee@example.com>" matches the name "Ann Lee" whether it
    appears in the display part or the address.
    """
    hits: list[tuple[str, str]] = []
    for header in _SCANNED_HEADERS:
        for display, addr in getaddresses(msg.get_all(header, [])):
            hay = f"{display} {addr}".lower()
            if needle and needle in hay:
                hits.append((display.strip().lower(), addr.strip().lower()))
    return hits


def get_last_contact(name: str, mbox_path: str | Path) -> date | None:
    """Most recent date you emailed with ``name``, or None.

    Scans every .mbox under ``mbox_path`` (a single Takeout .mbox file or a
    directory of them) for messages where the connection's full name appears
    in a From/To/Cc header.

    Returns None when:
    - the name is blank,
    - no message mentions the name in From/To/Cc,
    - the match is ambiguous (more than one distinct contact identity
      matches, e.g. two different people sharing the name),
    - matched messages have no parseable Date header.

    Raises TimingError when the mbox path does not exist.
    """
    from candid import gmail as G
    full = (name or "").strip()
    if not full:
        return None
    p = Path(mbox_path)
    if not p.exists():
        raise TimingError(f"mbox not found: {p}")
    needle = full.lower()
    dates: list[date] = []
    identities: set[tuple[str, str]] = set()
    for f in G.iter_mbox_files(p):
        box = mailbox.mbox(str(f))
        try:
            for msg in box:
                try:
                    hits = _header_identities(msg, needle)
                except Exception:
                    continue  # malformed headers: skip the message
                if not hits:
                    continue
                identities.update(hits)
                d = _msg_date(msg)
                if d is not None:
                    dates.append(d)
        finally:
            box.close()
    if not dates:
        return None
    if len(identities) > 1:
        return None  # ambiguous: never guess
    return max(dates)
