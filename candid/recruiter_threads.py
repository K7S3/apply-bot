"""Recruiter relationship manager: interaction/thread log per recruiter.

Tracks every touch (email, LinkedIn, phone call, other) with a recruiter so the
user can see the full history of a relationship at a glance. Also guards
against double-submission: ``same_role_pitches`` flags when two or more
*different* recruiters pitched the same company+role.

Thread data is stored as JSON at ``C.DATA_DIR / "recruiter_threads.json"``
(git-ignored). Recruiter *profiles* live in ``C.DATA_DIR / "recruiters.json"``
(written by the profiles module); this module only READS that file to validate
that a recruiter exists. It never writes it.

Valid touch channels: email, linkedin, phone, other.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from candid import config as C


class RecruiterError(Exception):
    """Raised for invalid recruiter thread operations."""


CHANNELS = ("email", "linkedin", "phone", "other")

GENERIC_DOMAINS = {
    "gmail", "yahoo", "hotmail", "outlook", "aol", "icloud", "protonmail",
    "proton", "zoho", "yandex", "mail", "gmx", "live", "msn",
}


def _threads_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else C.DATA_DIR / "recruiter_threads.json"


def _recruiters_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else C.DATA_DIR / "recruiters.json"


def _load(path: str | Path | None = None) -> list[dict]:
    """Load thread touches. Uses path override for tests."""
    p = _threads_path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecruiterError(f"Thread file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RecruiterError(f"Thread file {p} should contain a JSON list.")
    return data


def _save(touches: list[dict], path: str | Path | None = None) -> Path:
    """Save thread touches. Uses path override for tests."""
    p = _threads_path(path)
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(touches, indent=2), encoding="utf-8")
    return p


def _known_recruiters(path: str | Path | None = None) -> set[str]:
    """Read-only view of recruiter names from recruiters.json. Never writes."""
    p = _recruiters_path(path)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecruiterError(f"Recruiter file {p} is not valid JSON: {exc}") from exc
    names: set[str] = set()
    if isinstance(data, dict):  # name -> profile mapping
        names.update(str(k) for k in data)
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and entry.get("name"):
                names.add(str(entry["name"]))
            elif isinstance(entry, str):
                names.add(entry)
    return names


def _validate_recruiter(recruiter: str, recruiters_path: str | Path | None = None) -> str:
    name = (recruiter or "").strip()
    if not name:
        raise RecruiterError("Recruiter name is required.")
    known = _known_recruiters(recruiters_path)
    if known and name.lower() not in {k.lower() for k in known}:
        raise RecruiterError(
            f"Unknown recruiter '{name}'. Add a profile for them first."
        )
    return name


def _validate_channel(channel: str) -> str:
    ch = (channel or "").strip().lower()
    if ch not in CHANNELS:
        raise RecruiterError(
            f"Invalid channel '{channel}'. Choose from: {', '.join(CHANNELS)}"
        )
    return ch


def _next_id(touches: list[dict]) -> int:
    return max((t.get("id", 0) for t in touches), default=0) + 1


def log_touch(recruiter: str, channel: str, summary: str, date: str | None = None,
              *, role: str = "", company: str = "", replied: bool = False,
              path: str | Path | None = None,
              recruiters_path: str | Path | None = None) -> dict:
    """Record one interaction with a recruiter. Returns the new touch record.

    ``role`` and ``company`` describe what the touch was about and power the
    duplicate-outreach guard in ``same_role_pitches``. ``replied`` marks
    whether the recruiter replied, feeding the response-rate analytics.
    """
    name = _validate_recruiter(recruiter, recruiters_path)
    ch = _validate_channel(channel)
    if not (summary or "").strip():
        raise RecruiterError("A short summary of the touch is required.")
    touches = _load(path)
    touch = {
        "id": _next_id(touches),
        "recruiter": name,
        "channel": ch,
        "summary": summary.strip(),
        "date": date or _today().isoformat(),
        "role": (role or "").strip(),
        "company": (company or "").strip(),
        "replied": bool(replied),
    }
    touches.append(touch)
    _save(touches, path)
    return touch


def mark_replied(touch_id: int, path: str | Path | None = None) -> dict:
    """Mark an existing touch as replied. Returns the updated touch."""
    touches = _load(path)
    for t in touches:
        if t.get("id") == touch_id:
            t["replied"] = True
            _save(touches, path)
            return t
    raise RecruiterError(f"No touch with id {touch_id}.")


def _today() -> date:
    return date.today()


def thread(recruiter: str, *, path: str | Path | None = None,
           recruiters_path: str | Path | None = None) -> list[dict]:
    """Chronological list of touches with a recruiter (oldest first)."""
    name = _validate_recruiter(recruiter, recruiters_path)
    hits = [t for t in _load(path) if t.get("recruiter", "").lower() == name.lower()]
    return sorted(hits, key=lambda t: (t.get("date", ""), t.get("id", 0)))


def last_touch(recruiter: str, *, path: str | Path | None = None,
               recruiters_path: str | Path | None = None) -> dict | None:
    """Most recent touch with a recruiter, or None if there are none."""
    history = thread(recruiter, path=path, recruiters_path=recruiters_path)
    return history[-1] if history else None


def _normalize(text: str) -> str:
    """Normalize a company/role string for duplicate-outreach matching."""
    s = (text or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _touch_matches(touch: dict, norm_role: str, norm_company: str) -> bool:
    """True when a touch is about the given normalized role+company."""
    if not norm_role or not norm_company:
        return False
    t_role = _normalize(touch.get("role", ""))
    t_company = _normalize(touch.get("company", ""))
    if t_role == norm_role and t_company == norm_company:
        return True
    # Fall back to the free-text summary when role/company were not set.
    if not touch.get("role") and not touch.get("company"):
        blob = _normalize(touch.get("summary", ""))
        return norm_role in blob and norm_company in blob
    return False


def same_role_pitches(role: str, company: str, *,
                      path: str | Path | None = None,
                      recruiters_path: str | Path | None = None) -> list[dict]:
    """Flag duplicate outreach: 2+ DIFFERENT recruiters pitching one company+role.

    Matching is done on normalized company+role strings (case, punctuation,
    and extra whitespace are ignored). Returns one dict per flagged group:
    ``{"role": ..., "company": ..., "recruiters": [...],
    "pitches": [(recruiter, touch), ...]}``. Empty list when there is no
    overlap, so the user only sees a warning when double-submission is a real
    risk.
    """
    norm_role = _normalize(role)
    norm_company = _normalize(company)
    matching = [t for t in _load(path)
                if _touch_matches(t, norm_role, norm_company)]
    recruiters = sorted({t["recruiter"] for t in matching})
    if len(recruiters) < 2:
        return []
    pitches = [(t["recruiter"], t) for t in
               sorted(matching, key=lambda t: (t.get("date", ""), t.get("id", 0)))]
    return [{
        "role": (role or "").strip(),
        "company": (company or "").strip(),
        "recruiters": recruiters,
        "pitches": pitches,
    }]


def _guess_company_from_subject(subject: str) -> str:
    """Heuristic: subjects like 'Senior SWE at Acme' or 'Acme | Staff Engineer'."""
    s = (subject or "").strip()
    for pat in (r"\bat\s+([A-Z][\w&'.-]+(?:\s+[A-Z][\w&'.-]+){0,3})",
                r"\bwith\s+([A-Z][\w&'.-]+(?:\s+[A-Z][\w&'.-]+){0,3})",
                r"\bfrom\s+([A-Z][\w&'.-]+(?:\s+[A-Z][\w&'.-]+){0,3})"):
        m = re.search(pat, s)
        if m:
            return m.group(1).strip()
    m = re.match(r"^([A-Z][\w&'.-]+(?:\s+[A-Z][\w&'.-]+){0,3})\s*[|:\-–]", s)
    return m.group(1).strip() if m else ""


def _guess_company_from_snippet(snippet: str) -> str:
    """Heuristic: snippets like 'I am hiring for X at Acme'."""
    s = (snippet or "").strip()
    m = re.search(r"\bat\s+([A-Z][\w&'.-]+(?:\s+[A-Z][\w&'.-]+){0,3})", s)
    return m.group(1).strip() if m else ""


def _guess_company_from_email(email: str) -> str:
    """Heuristic: use the sender's email domain (acme.com -> Acme)."""
    m = re.search(r"@([\w.-]+)$", (email or "").strip().lower())
    if not m:
        return ""
    host = m.group(1)
    labels = host.split(".")
    core = labels[0] if len(labels) >= 2 else host
    if core in GENERIC_DOMAINS:
        return ""
    return core.replace("-", " ").title()


def propose_from_gmail(messages: list[dict]) -> list[dict]:
    """Propose recruiter profiles from Gmail takeout messages. Read-only: writes nothing.

    Each message dict may carry: from_name, from_email, subject, snippet, date.
    The company is a *guess* from simple heuristics, always labeled
    ``"company_guess": True`` so the coordinator/CLI shows it as unconfirmed.
    The caller must confirm before saving any profile.
    """
    proposals = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        email = (msg.get("from_email") or "").strip()
        name = (msg.get("from_name") or email or "").strip()
        subject = msg.get("subject") or ""
        snippet = msg.get("snippet") or ""
        company, source = "", ""
        for heuristic, fn in (
            ("subject", lambda: _guess_company_from_subject(subject)),
            ("snippet", lambda: _guess_company_from_snippet(snippet)),
            ("email_domain", lambda: _guess_company_from_email(email)),
        ):
            guess = fn()
            if guess:
                company, source = guess, heuristic
                break
        proposals.append({
            "name": name,
            "email": email,
            "company": company,
            "company_guess": bool(company),
            "company_source": source,
            "channel": "email",
            "subject": subject,
            "snippet": snippet,
            "date": msg.get("date") or "",
        })
    return proposals
