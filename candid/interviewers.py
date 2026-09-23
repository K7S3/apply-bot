"""Interviewer roster: track who is interviewing the user for each application.

Stored as JSON at candid_data/interviewers.json (git-ignored).

Each interviewer record looks like::

    {
        "id": 1,
        "app_id": 3,                  # links to a tracker application, may be None
        "name": "Jane Doe",
        "role": "hiring_manager",     # InterviewerRole key; free-form text also allowed
        "round_label": "Round 2",
        "background": {               # optional, entered by the user
            "title": "Engineering Manager, Ads Ranking",
            "team": "Ads Ranking",
            "tenure": "3 years at the company",
            "focus_areas": ["ranking models", "online experiments"],
            "public_links": [{"label": "blog", "url": "https://example.com/post"}],
            "talks": [{"title": "Learning to rank", "topics": ["ranking", "ML"]}],
            "notes": "Met at a meetup in June.",
        },
        "debrief": {                  # filled after each interview round
            "asked": ["System design for ranking", "Tell me about a conflict"],
            "signals": ["loves probing tradeoffs", "pressed on metrics"],
            "follow_up": "Send the experiment write-up she asked for.",
        },
        "created": "2026-09-22",
    }

IMPORTANT: candid never scrapes interviewer data. The ``background`` dict is
entered by the user from public sources they have already looked at (a
LinkedIn profile, a conference talk, a company blog). This module stores what
the user supplies and nothing else.

The role taxonomy below (``InterviewerRole``) is shared with the prep-pack
brief builders in Worker B/C; they import these constants to label briefs.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C


class InterviewerError(Exception):
    """Raised for invalid interviewer operations (bad ids, bad fields)."""


class InterviewerRole:
    """Interview-loop role taxonomy. Free-form roles are also accepted."""

    HIRING_MANAGER = "hiring_manager"
    PEER_ENGINEER = "peer_engineer"
    BAR_RAISER = "bar_raiser"
    RECRUITER = "recruiter"
    SKIP_LEVEL = "skip_level"
    DOMAIN_SPECIALIST = "domain_specialist"


ROLES = [
    InterviewerRole.HIRING_MANAGER,
    InterviewerRole.PEER_ENGINEER,
    InterviewerRole.BAR_RAISER,
    InterviewerRole.RECRUITER,
    InterviewerRole.SKIP_LEVEL,
    InterviewerRole.DOMAIN_SPECIALIST,
]

# User-supplied background fields only; candid never scrapes these.
BACKGROUND_FIELDS = {
    "title",
    "team",
    "tenure",
    "focus_areas",
    "public_links",
    "talks",
    "notes",
}

DEFAULT_PATH = C.DATA_DIR / "interviewers.json"


def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InterviewerError(f"Interviewer file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise InterviewerError(f"Interviewer file {p} should contain a JSON list.")
    return data


def _save(interviewers: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(interviewers, indent=2), encoding="utf-8")
    return p


def _next_id(interviewers: list[dict]) -> int:
    return max((i.get("id", 0) for i in interviewers), default=0) + 1


def _require(interviewers: list[dict], id: int) -> dict:
    rec = next((i for i in interviewers if i.get("id") == id), None)
    if rec is None:
        raise InterviewerError(f"No interviewer with id {id}. Use list_interviewers() to see ids.")
    return rec


def add_interviewer(name: str, *, app_id: int | None = None, role: str = "",
                    round_label: str = "", background: dict | None = None,
                    path: str | Path | None = None) -> dict:
    """Add an interviewer to the roster. Returns the new record.

    ``background`` is a dict of user-supplied background info (see the module
    docstring). It must only contain data the user looked up themselves;
    candid never scrapes it.
    """
    if not name:
        raise InterviewerError("An interviewer name is required.")
    interviewers = _load(path)
    rec = {
        "id": _next_id(interviewers),
        "app_id": app_id,
        "name": name.strip(),
        "role": (role or "").strip(),
        "round_label": (round_label or "").strip(),
        "background": _normalize_background(background or {}),
        "debrief": {"asked": [], "signals": [], "follow_up": ""},
        "created": date.today().isoformat(),
    }
    interviewers.append(rec)
    _save(interviewers, path)
    return dict(rec)


def list_interviewers(app_id: int | None = None,
                      path: str | Path | None = None) -> list[dict]:
    """List interviewers, optionally filtered to one application."""
    interviewers = _load(path)
    if app_id is None:
        return [dict(i) for i in interviewers]
    return [dict(i) for i in interviewers if i.get("app_id") == app_id]


def get_interviewer(id: int, path: str | Path | None = None) -> dict | None:
    """Return the interviewer record with this id, or None if missing."""
    interviewers = _load(path)
    rec = next((i for i in interviewers if i.get("id") == id), None)
    return dict(rec) if rec else None


def remove_interviewer(id: int, path: str | Path | None = None) -> None:
    """Remove an interviewer. Raises InterviewerError if the id is unknown."""
    interviewers = _load(path)
    rec = _require(interviewers, id)
    interviewers.remove(rec)
    _save(interviewers, path)


def find_by_app(app_id: int, path: str | Path | None = None) -> list[dict]:
    """Return all interviewers linked to one application id."""
    return list_interviewers(app_id=app_id, path=path)


def _normalize_background(background: dict) -> dict:
    """Normalize a user-supplied background dict into the canonical shape."""
    unknown = set(background) - BACKGROUND_FIELDS
    if unknown:
        raise InterviewerError(
            f"Unknown background field(s): {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(BACKGROUND_FIELDS))}."
        )
    norm = {}
    for field in BACKGROUND_FIELDS:
        if field in background:
            norm[field] = background[field]
        elif field in ("focus_areas", "public_links", "talks"):
            norm[field] = []
        else:
            norm[field] = None
    return norm


def update_background(id: int, path: str | Path | None = None, **fields) -> dict:
    """Update an interviewer's user-supplied background fields.

    Accepts title, team, tenure, focus_areas, public_links, talks, notes.
    Unknown fields raise InterviewerError.
    """
    unknown = set(fields) - BACKGROUND_FIELDS
    if unknown:
        raise InterviewerError(
            f"Unknown background field(s): {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(BACKGROUND_FIELDS))}."
        )
    interviewers = _load(path)
    rec = _require(interviewers, id)
    for key, value in fields.items():
        rec["background"][key] = value
    _save(interviewers, path)
    return dict(rec)


def add_debrief(id: int, asked: list[str] | None = None,
                signals: list[str] | None = None, follow_up: str = "",
                path: str | Path | None = None) -> dict:
    """Attach or update a debrief for an interviewer.

    ``asked`` and ``signals`` are appended to the existing lists (skipping
    items already present); ``follow_up`` replaces the previous note when a
    non-empty value is passed. Returns the updated record.
    """
    interviewers = _load(path)
    rec = _require(interviewers, id)
    debrief = rec.setdefault("debrief", {"asked": [], "signals": [], "follow_up": ""})
    for question in asked or []:
        if question not in debrief.setdefault("asked", []):
            debrief["asked"].append(question)
    for signal in signals or []:
        if signal not in debrief.setdefault("signals", []):
            debrief["signals"].append(signal)
    if follow_up:
        debrief["follow_up"] = follow_up
    _save(interviewers, path)
    return dict(rec)
