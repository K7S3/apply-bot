"""Context packet assembly for context-aware email drafting.

Builds a single dict with everything a drafter needs about one tracked
application: the tracker record (stage, status, applied date, role,
interviewers, notes), days since last contact, and company notes when
available.

DRAFTS ONLY: nothing here sends email, opens sockets, or makes network
calls. Missing data yields empty fields, never exceptions.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C
from candid import tracker as T


def _parse_iso(value: object) -> date | None:
    """Parse an ISO date (or datetime) string. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _resolve_apps(tracker: str | Path | list | None) -> list[dict]:
    """Resolve the ``tracker`` argument to a list of application records.

    Accepts a path to a tracker JSON file, a ready-made list of records,
    or None (reads the default tracker via the tracker module).
    Never raises: an unreadable or malformed store yields [].
    """
    try:
        if tracker is None:
            return T.list_apps()
        if isinstance(tracker, (str, Path)):
            return T.list_apps(path=tracker)
        if isinstance(tracker, list):
            return [a for a in tracker if isinstance(a, dict)]
    except (T.TrackerError, OSError, ValueError):
        return []
    return []


def _company_notes_path(tracker: str | Path | list | None) -> Path:
    """Where to look for company notes.

    Convention: ``company_notes.json`` (a JSON object mapping company name
    to free-text notes) lives next to the tracker file when a tracker path
    was given, else under the default data dir.
    """
    if isinstance(tracker, (str, Path)):
        return Path(tracker).parent / "company_notes.json"
    return C.DATA_DIR / "company_notes.json"


def _load_company_notes(tracker: str | Path | list | None) -> dict:
    """Load company notes keyed by lowercased company name. Never raises."""
    path = _company_notes_path(tracker)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k).lower(): v for k, v in data.items()}


def _find_application(
    apps: list[dict], company: str | None, app_id: int | None
) -> dict | None:
    """Pick the record to use. app_id wins; else exact company match, then
    substring match (tracker.list_apps semantics)."""
    if app_id is not None:
        return next((a for a in apps if a.get("id") == app_id), None)
    query = (company or "").strip().lower()
    if not query:
        return None
    exact = [a for a in apps if str(a.get("company", "")).lower() == query]
    if exact:
        return exact[0]
    partial = [a for a in apps if query in str(a.get("company", "")).lower()]
    return partial[0] if partial else None


def _latest_contact(rec: dict) -> date | None:
    """Latest known contact date from date_updated/date_added/status_history."""
    candidates = [_parse_iso(rec.get("date_updated")), _parse_iso(rec.get("date_added"))]
    history = rec.get("status_history")
    if isinstance(history, list):
        for entry in history:
            if isinstance(entry, dict):
                candidates.append(_parse_iso(entry.get("date")))
    parsed = [d for d in candidates if d is not None]
    return max(parsed) if parsed else None


def build_context(
    company: str | None, tracker: str | Path | list | None = None,
    app_id: int | None = None,
) -> dict:
    """Assemble the context packet for drafting an email about ``company``.

    ``tracker`` may be a tracker.json path, a list of application records,
    or None (uses the default tracker file). ``app_id`` selects a specific
    application when several match.

    Returns a dict with empty-but-valid fields when the application is not
    found or data is missing. Never raises on bad data.
    """
    apps = _resolve_apps(tracker)
    rec = _find_application(apps, company, app_id) or {}
    notes_map = _load_company_notes(tracker)

    name = str(rec.get("company", "") or (company or "")).strip()
    applied = _parse_iso(rec.get("date_added"))
    last_contact = _latest_contact(rec)
    today = date.today()

    def _days(d: date | None) -> int | None:
        return (today - d).days if d is not None else None

    interviewers = rec.get("interviewers") or []
    if isinstance(interviewers, str):
        interviewers = [interviewers]
    open_questions = rec.get("open_questions") or []
    if isinstance(open_questions, str):
        open_questions = [open_questions]

    return {
        "company": name,
        "found": bool(rec),
        "application_id": rec.get("id"),
        "role": str(rec.get("role", "") or ""),
        "status": str(rec.get("status", "") or ""),
        "stage": str(rec.get("status", "") or ""),
        "applied_date": applied.isoformat() if applied else "",
        "days_since_applied": _days(applied),
        "last_contact": last_contact.isoformat() if last_contact else "",
        "days_since_last_contact": _days(last_contact),
        "interviewers": [str(i) for i in interviewers],
        "notes": str(rec.get("notes", "") or ""),
        "company_notes": str(notes_map.get(name.lower(), "") or ""),
        "jd_link": str(rec.get("jd_link", "") or ""),
        "open_questions": [str(q) for q in open_questions],
    }
