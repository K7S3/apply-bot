"""Networking CRM: coffee chats, referrals given/received, thank-yous owed.

Stored as JSON at candid_data/network.json (git-ignored), mirroring the
tracker's storage conventions: a flat list of records with an integer id,
``add`` dedupes nothing (each conversation is its own record).

``network thanks`` lists the contacts that conventionally owe a thank-you
(coffee chats and received referrals that aren't marked thanked) and prints
the exact ``followup thank-you`` command to draft one — or ``--draft ID``
to print the draft inline using the existing followup generator.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C

NETWORK_TYPES = ["coffee-chat", "referral-received", "referral-given"]

#: Types that conventionally owe a thank-you note.
THANK_YOU_TYPES = {"coffee-chat", "referral-received"}


class NetworkError(Exception):
    """Raised for invalid network operations."""


def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else C.NETWORK_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NetworkError(f"Network file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise NetworkError(f"Network file {p} should contain a JSON list.")
    return data


def _save(contacts: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else C.NETWORK_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(contacts, indent=2), encoding="utf-8")
    return p


def _next_id(contacts: list[dict]) -> int:
    return max((c.get("id", 0) for c in contacts), default=0) + 1


def add(type_: str, contact: str, *, company: str = "", role: str = "",
        notes: str = "", path: str | Path | None = None) -> dict:
    """Log a networking contact. Returns the new record."""
    if type_ not in NETWORK_TYPES:
        raise NetworkError(
            f"Unknown type '{type_}'. Choose from: {', '.join(NETWORK_TYPES)}")
    if not contact:
        raise NetworkError("--contact is required to add a network entry.")
    contacts = _load(path)
    rec = {
        "id": _next_id(contacts),
        "type": type_,
        "contact": contact.strip(),
        "company": company.strip(),
        "role": role.strip(),
        "notes": notes.strip(),
        "date_added": date.today().isoformat(),
        "thanked": False,
        "date_thanked": "",
    }
    contacts.append(rec)
    _save(contacts, path)
    return rec


def list_contacts(*, type_: str | None = None,
                  path: str | Path | None = None) -> list[dict]:
    """List contacts, optionally filtered by type."""
    contacts = _load(path)
    if type_:
        if type_ not in NETWORK_TYPES:
            raise NetworkError(
                f"Unknown type '{type_}'. Choose from: {', '.join(NETWORK_TYPES)}")
        contacts = [c for c in contacts if c["type"] == type_]
    return sorted(contacts, key=lambda c: c["id"])


def mark_thanked(contact_id: int, path: str | Path | None = None) -> dict:
    """Mark a contact's thank-you as sent. Returns the record."""
    contacts = _load(path)
    rec = next((c for c in contacts if c.get("id") == contact_id), None)
    if rec is None:
        raise NetworkError(
            f"No network entry with id {contact_id}. Use `network list` to see ids.")
    rec["thanked"] = True
    rec["date_thanked"] = date.today().isoformat()
    _save(contacts, path)
    return rec


def thanks_owed(path: str | Path | None = None) -> list[dict]:
    """Contacts that conventionally owe a thank-you, oldest first."""
    owed = [c for c in _load(path)
            if c["type"] in THANK_YOU_TYPES and not c.get("thanked")]
    return sorted(owed, key=lambda c: c.get("date_added", ""))


def draft_command(rec: dict) -> str:
    """The exact ``followup thank-you`` command to draft for this contact."""
    cmd = (f"python -m candid followup thank-you --person \"{rec['contact']}\" "
           f"--role \"{rec['role'] or 'the role'}\" "
           f"--company \"{rec['company'] or 'their company'}\"")
    if rec.get("notes"):
        cmd += f" --topics \"{rec['notes'][:120]}\""
    return cmd


def thank_you_draft(contact_id: int, name: str,
                    path: str | Path | None = None) -> str:
    """Generate a thank-you draft for a contact via the existing followup module."""
    from candid import followup as F
    rec = next((c for c in _load(path) if c.get("id") == contact_id), None)
    if rec is None:
        raise NetworkError(
            f"No network entry with id {contact_id}. Use `network list` to see ids.")
    return F.thank_you(name or "Your Name", rec["contact"],
                       rec["role"] or "the role", rec["company"] or "their company",
                       topics=rec.get("notes", ""))


def render_list(contacts: list[dict]) -> str:
    if not contacts:
        return ("No network entries yet. Add one with: "
                "python -m candid network add --type coffee-chat --contact NAME --company X")
    lines = [f"{'ID':<4}{'Type':<18}{'Contact':<24}{'Company':<22}Added"]
    for c in contacts:
        mark = " ✓ thanked" if c.get("thanked") else ""
        lines.append(
            f"{c['id']:<4}{c['type']:<18}{c['contact'][:23]:<24}"
            f"{c['company'][:21]:<22}{c.get('date_added', '')}{mark}"
        )
    return "\n".join(lines)


def render_thanks(owed: list[dict]) -> str:
    if not owed:
        return ("No thank-yous owed — you're all caught up.\n"
                "Log new contacts with: python -m candid network add --type coffee-chat --contact NAME")
    lines = [f"{len(owed)} thank-you(s) owed (oldest first):", ""]
    for c in owed:
        lines.append(
            f"#{c['id']}  {c['contact']} ({c['type']}, {c.get('date_added', 'unknown date')})"
            + (f" — {c['company']}" if c.get("company") else "")
        )
        lines.append(f"      → draft it: {draft_command(c)}")
        lines.append(f"      → then mark sent: python -m candid network mark-thanked {c['id']}")
        lines.append("")
    return "\n".join(lines).rstrip()
