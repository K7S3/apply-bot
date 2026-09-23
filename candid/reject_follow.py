"""Rejection reframe: re-approach scheduling, feedback capture, and response drafts.

A rejection is a future lead, not a dead end. This module:

- schedules a re-approach reminder N months after a rejected application
  (e.g. re-apply when the team is hiring again),
- tracks "ask for feedback" outreach and the feedback that comes back,
- drafts gracious rejection response emails (thank-you / feedback ask),
- converts interview contacts into network entries.

Nothing is ever sent automatically — drafts are for you to copy, edit,
and send yourself.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C
from candid import tracker as T

REAPPROACH_PATH = "reapproaches.json"
FEEDBACK_PATH = "reject_feedback.json"
CONTACTS_PATH = "network_contacts.json"

# Re-approach window: from one month out to two years.
MIN_MONTHS = 1
MAX_MONTHS = 24


class RejectFollowError(Exception):
    """Raised for invalid rejection-follow-up operations."""


# --- JSON list helpers ---------------------------------------------------------

def _load(path: str | Path | None, default: str) -> list[dict]:
    p = Path(path) if path else C.DATA_DIR / default
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RejectFollowError(f"File {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RejectFollowError(f"File {p} should contain a JSON list.")
    return data


def _save(items: list[dict], path: str | Path | None, default: str) -> Path:
    p = Path(path) if path else C.DATA_DIR / default
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return p


def _find_app(app_id: int, tracker_path: str | Path | None) -> dict:
    apps = T.list_apps(path=tracker_path)
    rec = next((a for a in apps if a.get("id") == app_id), None)
    if rec is None:
        raise RejectFollowError(f"No application with id {app_id}. Use `track list` to see ids.")
    return rec


def _add_months(start: date, months: int) -> date:
    """Shift a date forward by N calendar months (clamped to month end)."""
    year = start.year + (start.month - 1 + months) // 12
    month = (start.month - 1 + months) % 12 + 1
    day = start.day
    last_day = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return date(year, month, min(day, last_day))


# --- re-approach scheduling ----------------------------------------------------

def schedule_reapproach(app_id: int, months: int = 9, note: str = "",
                        *, reapproach_path: str | Path | None = None,
                        tracker_path: str | Path | None = None) -> dict:
    """Schedule a reminder to re-approach a rejected application.

    Only rejected applications can be re-approached; an existing reminder
    for the app is replaced (upsert) and returned.
    """
    if not MIN_MONTHS <= months <= MAX_MONTHS:
        raise RejectFollowError(f"months must be between {MIN_MONTHS} and {MAX_MONTHS}, got {months}.")
    app = _find_app(app_id, tracker_path)
    if app.get("status") != "rejected":
        raise RejectFollowError(
            f"Application {app_id} is '{app.get('status')}', not rejected. "
            "Re-approaches only apply to rejected applications."
        )
    items = _load(reapproach_path, REAPPROACH_PATH)
    rec = {
        "app_id": app_id,
        "company": app["company"],
        "role": app["role"],
        "due_date": _add_months(date.today(), months).isoformat(),
        "note": note.strip(),
        "created": date.today().isoformat(),
    }
    existing = next((i for i in items if i.get("app_id") == app_id), None)
    if existing is not None:
        existing.update(rec)
        rec = existing
    else:
        items.append(rec)
    _save(items, reapproach_path, REAPPROACH_PATH)
    return rec


def due_reapproaches(today: str | None = None,
                     path: str | Path | None = None) -> list[dict]:
    """Return re-approaches whose due_date is on or before today, sorted."""
    today_iso = today or date.today().isoformat()
    return sorted(
        (i for i in _load(path, REAPPROACH_PATH) if i.get("due_date", "") <= today_iso),
        key=lambda i: i["due_date"],
    )


def cancel_reapproach(app_id: int,
                      path: str | Path | None = None) -> bool:
    """Cancel a re-approach reminder. Returns True if one existed."""
    items = _load(path, REAPPROACH_PATH)
    kept = [i for i in items if i.get("app_id") != app_id]
    if len(kept) == len(items):
        return False
    _save(kept, path, REAPPROACH_PATH)
    return True


# --- feedback tracking ---------------------------------------------------------

def ask_feedback(app_id: int, who: str, *, path: str | Path | None = None,
                 tracker_path: str | Path | None = None) -> dict:
    """Record that you asked someone for interview feedback (upsert)."""
    app = _find_app(app_id, tracker_path)
    items = _load(path, FEEDBACK_PATH)
    rec = {
        "app_id": app_id,
        "company": app["company"],
        "role": app["role"],
        "who": who.strip(),
        "asked_date": date.today().isoformat(),
        "feedback": None,
        "received_date": None,
    }
    existing = next((i for i in items if i.get("app_id") == app_id), None)
    if existing is not None:
        existing.update(rec)
        rec = existing
    else:
        items.append(rec)
    _save(items, path, FEEDBACK_PATH)
    return rec


def log_feedback(app_id: int, text: str,
                 path: str | Path | None = None) -> dict:
    """Log feedback text against an existing ask record."""
    items = _load(path, FEEDBACK_PATH)
    rec = next((i for i in items if i.get("app_id") == app_id), None)
    if rec is None:
        raise RejectFollowError(
            f"No feedback request recorded for application {app_id}. "
            "Use ask_feedback() first."
        )
    rec["feedback"] = text.strip()
    rec["received_date"] = date.today().isoformat()
    _save(items, path, FEEDBACK_PATH)
    return rec


def pending_feedback(path: str | Path | None = None) -> list[dict]:
    """Return ask records that have no feedback yet, sorted by asked_date."""
    return sorted(
        (i for i in _load(path, FEEDBACK_PATH) if not i.get("feedback")),
        key=lambda i: i.get("asked_date", ""),
    )


# --- response drafts -----------------------------------------------------------

def draft_response(rejection: dict, kind: str) -> dict:
    """Draft a reply to a rejection email.

    ``rejection`` is a rejection dict (from reject_log) with at least
    ``company`` and ``role`` keys. ``kind`` is "thankyou" or "feedback".
    Returns {"subject", "body"}. Never invents facts about the company.
    """
    company = (rejection.get("company") or "").strip()
    role = (rejection.get("role") or "").strip()
    if kind == "thankyou":
        subject = f"Thank you — {role} at {company}"
        body = (
            f"Thank you for letting me know about the {role} role at {company}.\n\n"
            "I really enjoyed meeting the team and learning about the work. "
            "If the right opportunity opens up in the future, I'd love to be "
            "considered — please keep me in mind.\n\n"
            "Wishing you and the team all the best.\n\n"
            "Best,\n"
            "[Your Name]"
        )
    elif kind == "feedback":
        subject = f"Feedback request — {role} at {company}"
        body = (
            f"Thank you for considering me for the {role} role at {company}.\n\n"
            "I'm always looking to grow, and I'd be grateful for any feedback "
            "you're able to share. In particular:\n\n"
            "- What was the one area where I fell short of what you were looking for?\n"
            "- Is there a skill or experience that would make me a stronger fit next time?\n\n"
            "I completely understand if there's nothing specific to share. "
            "Thanks again for your time and consideration.\n\n"
            "Best,\n"
            "[Your Name]"
        )
    else:
        raise RejectFollowError(f"Unknown draft kind '{kind}'. Choose from: thankyou, feedback.")
    return {"subject": subject, "body": body}


# --- network conversion --------------------------------------------------------

def to_network(app_id: int, names: list[str], *,
                path: str | Path | None = None,
                tracker_path: str | Path | None = None) -> list[dict]:
    """Add interview contacts to the network list.

    Each name becomes {"name", "company", "role", "source": "rejected interview",
    "date_added"}. Existing (name, company) pairs are not duplicated.
    Returns the full contacts list.
    """
    app = _find_app(app_id, tracker_path)
    contacts = _load(path, CONTACTS_PATH)
    seen = {(c.get("name", "").lower(), c.get("company", "").lower()) for c in contacts}
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        key = (name.lower(), app["company"].lower())
        if key in seen:
            continue
        contacts.append({
            "name": name,
            "company": app["company"],
            "role": app["role"],
            "source": "rejected interview",
            "date_added": date.today().isoformat(),
        })
        seen.add(key)
    _save(contacts, path, CONTACTS_PATH)
    return contacts


# --- render helpers ------------------------------------------------------------

def render_reapproaches(items: list[dict]) -> str:
    """Render re-approach reminders as one line each."""
    if not items:
        return "No re-approaches scheduled. Rejected applications can be revisited later — use schedule_reapproach()."
    return "\n".join(
        f"- {i['company']} — {i['role']} (app #{i['app_id']}), due {i['due_date']}"
        + (f" — {i['note']}" if i.get("note") else "")
        for i in items
    )


def render_feedback(items: list[dict]) -> str:
    """Render feedback records as one line each."""
    if not items:
        return "No feedback requests pending. Ask an interviewer for feedback with ask_feedback()."
    return "\n".join(
        f"- {i['company']} — {i['role']} (app #{i['app_id']}), asked {i.get('who', '?')} on "
        f"{i.get('asked_date', '?')}" + (" — feedback received" if i.get("feedback") else " — awaiting reply")
        for i in items
    )


def render_contacts(contacts: list[dict]) -> str:
    """Render network contacts as one line each."""
    if not contacts:
        return "No network contacts yet. Convert interview contacts with to_network()."
    return "\n".join(
        f"- {c.get('name')} ({c.get('company')}, {c.get('role')}) — via {c.get('source')}"
        for c in contacts
    )
