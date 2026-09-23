"""Outreach tracker (CRM-lite) + JD manager-clue extractor.

Tracks cold/warm outreach to hiring managers: log a draft, mark it sent,
move it through replied/no-reply/followed-up/archived, and get nudges for
stale threads. Also extracts hiring-manager clues (name, team, reporting
line) from a job description's text.

Stored as JSON at candid_data/outreach_log.json (git-ignored).

Status flow:
    draft -> sent -> replied | no-reply -> followed-up -> (replied | archived)

Dossiers come from candid.hm (built by another worker); if that module is
missing, dossier refs degrade gracefully to bare ids with no manager info.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from pathlib import Path

from candid import config as C


class OutreachTrackError(Exception):
    """Raised for invalid outreach operations."""


# --- status flow ---------------------------------------------------------------
STATUS_DRAFT = "draft"
STATUS_SENT = "sent"
STATUS_REPLIED = "replied"
STATUS_NO_REPLY = "no-reply"
STATUS_FOLLOWED_UP = "followed-up"
STATUS_ARCHIVED = "archived"

ALL_STATUSES = (
    STATUS_DRAFT,
    STATUS_SENT,
    STATUS_REPLIED,
    STATUS_NO_REPLY,
    STATUS_FOLLOWED_UP,
    STATUS_ARCHIVED,
)

# Current status -> allowed next statuses.
TRANSITIONS = {
    STATUS_DRAFT: {STATUS_SENT},
    STATUS_SENT: {STATUS_REPLIED, STATUS_NO_REPLY},
    STATUS_NO_REPLY: {STATUS_FOLLOWED_UP},
    STATUS_FOLLOWED_UP: {STATUS_REPLIED, STATUS_ARCHIVED},
    STATUS_REPLIED: set(),
    STATUS_ARCHIVED: set(),
}

# Statuses eligible for nudges: a message is out there, no reply yet.
AWAITING_REPLY = {STATUS_SENT, STATUS_FOLLOWED_UP}


# --- storage -------------------------------------------------------------------
def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else C.OUTREACH_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OutreachTrackError(f"Outreach log {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise OutreachTrackError(f"Outreach log {p} should contain a JSON list.")
    return data


def _save(entries: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else C.OUTREACH_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return p


def _get(entries: list[dict], entry_id: str) -> dict:
    for e in entries:
        if e.get("id") == entry_id:
            return e
    raise OutreachTrackError(f"No outreach entry with id '{entry_id}'.")


# --- dossier resolution ----------------------------------------------------------
def _resolve_dossier(dossier_ref) -> dict:
    """Normalize a dossier ref to {id, name, company}.

    Accepts a dossier dict directly or an id string looked up via
    candid.hm (imported lazily). Never raises: on any failure returns a
    bare record with name/company left empty.
    """
    if isinstance(dossier_ref, dict):
        return {
            "id": dossier_ref.get("id"),
            "name": dossier_ref.get("name"),
            "company": dossier_ref.get("company") or "",
        }
    try:
        from candid import hm  # type: ignore  # built by a parallel worker
    except Exception:
        return {"id": str(dossier_ref), "name": None, "company": ""}
    dossier = None
    try:
        for fn_name in ("get_dossier", "get", "find", "lookup"):
            fn = getattr(hm, fn_name, None)
            if callable(fn):
                dossier = fn(dossier_ref)
                if dossier:
                    break
        if dossier is None:
            for fn_name in ("list_dossiers", "load_dossiers", "list", "all"):
                fn = getattr(hm, fn_name, None)
                if callable(fn):
                    for d in fn() or []:
                        if isinstance(d, dict) and str(d.get("id")) == str(dossier_ref):
                            dossier = d
                            break
                    if dossier:
                        break
    except Exception:
        dossier = None
    if isinstance(dossier, dict):
        return {
            "id": dossier.get("id", str(dossier_ref)),
            "name": dossier.get("name"),
            "company": dossier.get("company") or "",
        }
    return {"id": str(dossier_ref), "name": None, "company": ""}


# --- core API --------------------------------------------------------------------
def log_outreach(dossier_ref, channel: str, notes: str = "",
                 path: str | Path | None = None) -> dict:
    """Log a new outreach draft. Returns the entry (status 'draft')."""
    if not channel:
        raise OutreachTrackError("A channel (e.g. 'linkedin', 'email') is required.")
    dossier = _resolve_dossier(dossier_ref)
    entries = _load(path)
    entry = {
        "id": uuid.uuid4().hex[:8],
        "dossier_id": dossier["id"],
        "manager_name": dossier["name"],
        "company": dossier["company"],
        "channel": channel.strip(),
        "status": STATUS_DRAFT,
        "sent_at": None,
        "last_touch": date.today().isoformat(),
        "notes": notes.strip(),
    }
    entries.append(entry)
    _save(entries, path)
    return entry


def _as_iso(value) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    raise OutreachTrackError(f"Not a valid date (expected date or YYYY-MM-DD): {value!r}")


def mark_sent(entry_id: str, sent_date=None,
              path: str | Path | None = None) -> dict:
    """Move a draft to 'sent'. sent_date defaults to today."""
    entries = _load(path)
    entry = _get(entries, entry_id)
    if entry.get("status") != STATUS_DRAFT:
        raise OutreachTrackError(
            f"mark_sent only applies to drafts (entry is '{entry.get('status')}').")
    iso = _as_iso(sent_date) if sent_date is not None else date.today().isoformat()
    return _transition(entries, entry, STATUS_SENT, path,
                       extra={"sent_at": iso, "last_touch": iso})


def update_status(entry_id: str, status: str,
                  path: str | Path | None = None) -> dict:
    """Move an entry to a new status, validating the transition."""
    if status not in ALL_STATUSES:
        raise OutreachTrackError(
            f"Unknown status '{status}'. Choose from: {', '.join(ALL_STATUSES)}")
    entries = _load(path)
    entry = _get(entries, entry_id)
    return _transition(entries, entry, status, path)


def _transition(entries: list[dict], entry: dict, status: str, path,
                extra: dict | None = None) -> dict:
    current = entry.get("status")
    if status != current:
        if status not in TRANSITIONS.get(current, set()):
            raise OutreachTrackError(
                f"Invalid transition '{current}' -> '{status}'. "
                f"Allowed: {sorted(TRANSITIONS.get(current, set())) or ['none']}")
        entry["status"] = status
        entry["last_touch"] = date.today().isoformat()
    if extra:
        entry.update(extra)
    _save(entries, path)
    return entry


def touch(entry_id: str, note: str = "",
          path: str | Path | None = None) -> dict:
    """Bump last_touch to today and append a dated note. Returns the entry."""
    entries = _load(path)
    entry = _get(entries, entry_id)
    today = date.today().isoformat()
    entry["last_touch"] = today
    note = (note or "").strip()
    if note:
        stamped = f"[{today}] {note}"
        entry["notes"] = (entry["notes"] + "\n" + stamped) if entry.get("notes") else stamped
    _save(entries, path)
    return entry


def list_outreach(status: str | None = None, company: str | None = None,
                  path: str | Path | None = None) -> list[dict]:
    """List entries, newest first by last_touch (then sent_at)."""
    entries = _load(path)
    if status is not None:
        entries = [e for e in entries if e.get("status") == status]
    if company is not None:
        entries = [e for e in entries
                   if (e.get("company") or "").lower() == company.lower()]
    return sorted(entries,
                  key=lambda e: (e.get("last_touch") or "", e.get("sent_at") or ""),
                  reverse=True)


def nudge_candidates(days: int = 7, path: str | Path | None = None,
                     today=None) -> list[dict]:
    """Return stale awaiting-reply entries with a suggested next step.

    Each item: {"entry", "days_since_touch", "next_step"} where next_step is
    one of "send follow-up", "try a different channel", "archive".
    """
    now = _as_iso(today) if today is not None else date.today().isoformat()
    stale = []
    for entry in _load(path):
        if entry.get("status") not in AWAITING_REPLY:
            continue
        last = entry.get("last_touch")
        if not last:
            continue
        age = (date.fromisoformat(now) - date.fromisoformat(last)).days
        if age <= days:
            continue
        if age <= days * 2:
            step = "send follow-up"
        elif age <= days * 3:
            step = "try a different channel"
        else:
            step = "archive"
        stale.append({
            "entry": entry,
            "days_since_touch": age,
            "next_step": step,
        })
    stale.sort(key=lambda item: item["days_since_touch"], reverse=True)
    return stale


# --- JD manager-clue extractor -----------------------------------------------------
_NAME = r"[A-Z][a-z]+(?:-[A-Z][a-z]+)? [A-Z][a-z]+(?:-[A-Z][a-z]+)?"
_TEAM_WORDS = r"[A-Z][\w\-&]*(?: [A-Z][\w\-&]*){0,3}"

_MANAGER_PATTERNS = [
    ("hiring manager", re.compile(r"[Hh]iring [Mm]anager[:\s]+(" + _NAME + r")")),
    ("reports to", re.compile(r"[Rr]eports? to (" + _NAME + r")")),
    ("led by", re.compile(r"[Ll]ed by (" + _NAME + r")")),
]

_TEAM_PATTERNS = [
    ("the X team", re.compile(r"[Tt]he (" + _TEAM_WORDS + r") [Tt]eam\b")),
    ("join our X", re.compile(r"[Jj]oin our (" + _TEAM_WORDS + r")\b")),
]


def _containing_sentence(text: str, needle: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if needle in sentence:
            return sentence.strip()
    return None


def extract_manager_clues(jd_text: str) -> dict:
    """Extract hiring-manager clues from a job description.

    Returns {"manager_name", "team", "reporting_line", "raw_hits"}.
    Values are None / [] when nothing is found; never invented.
    """
    text = (jd_text or "").strip()
    clues: dict = {"manager_name": None, "team": None,
                   "reporting_line": None, "raw_hits": []}
    if not text:
        return clues

    manager_hit: tuple[str, str] | None = None  # (full match, name)
    for _label, pattern in _MANAGER_PATTERNS:
        match = pattern.search(text)
        if match:
            manager_hit = (match.group(0).strip(), match.group(1))
            clues["raw_hits"].append(match.group(0).strip())
            break
    if manager_hit:
        clues["manager_name"] = manager_hit[1]
        clues["reporting_line"] = _containing_sentence(text, manager_hit[1])

    for _label, pattern in _TEAM_PATTERNS:
        match = pattern.search(text)
        if match:
            clues["team"] = match.group(1).strip()
            clues["raw_hits"].append(match.group(0).strip())
            break
    return clues
