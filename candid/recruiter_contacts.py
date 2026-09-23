"""Recruiter relationship manager: recruiter profiles CRUD + do-not-engage list.

Tracks recruiters the user has heard from so they can follow up with the
good ones and avoid the bad ones. Each recruiter has a name, company, kind
("inhouse" for an employer's own recruiter, "agency" for a third-party
recruiter), contact channel, and free-form notes/tags.

The do-not-engage list: flag a recruiter as blocked with a reason
(e.g. "spammy", "ghosted twice"). Blocked recruiters are excluded from
list_recruiters() by default (pass include_blocked=True to see them),
and is_blocked(name) answers "should I engage?" quickly.

Stored as JSON at DATA_DIR / "recruiters.json" (git-ignored), the same
convention as tracker.py.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C

KINDS = ("inhouse", "agency")
CHANNELS = ("email", "linkedin", "phone")


class RecruiterError(Exception):
    """Raised for invalid recruiter contact operations."""


def _default_path() -> Path:
    return C.DATA_DIR / "recruiters.json"


def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else _default_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecruiterError(f"Recruiter file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RecruiterError(f"Recruiter file {p} should contain a JSON list.")
    return data


def _save(records: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else _default_path()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return p


def _next_id(records: list[dict]) -> int:
    return max((r.get("id", 0) for r in records), default=0) + 1


def _norm(s: str | None) -> str:
    """Normalize for dedupe/compare: collapse whitespace, lowercase."""
    return " ".join((s or "").split()).casefold()


def _norm_tags(tags: list[str] | None) -> list[str]:
    out = []
    for t in tags or []:
        t = _norm(t)
        if t and t not in out:
            out.append(t)
    return out


def _check_first_contact(value: str) -> str:
    """Validate first_contact as an ISO date (YYYY-MM-DD) or empty."""
    value = (value or "").strip()
    if not value:
        return ""
    try:
        date.fromisoformat(value)
    except ValueError:
        raise RecruiterError(
            f"first_contact '{value}' is not a valid date. Use YYYY-MM-DD."
        )
    return value


def _validate_common(*, kind: str, channel: str, agency: str, first_contact: str) -> tuple[str, str, str]:
    if kind not in KINDS:
        raise RecruiterError(f"Unknown kind '{kind}'. Choose from: {', '.join(KINDS)}")
    if channel not in CHANNELS:
        raise RecruiterError(
            f"Unknown contact channel '{channel}'. Choose from: {', '.join(CHANNELS)}"
        )
    if kind == "agency" and not agency.strip():
        raise RecruiterError("kind 'agency' requires an agency name.")
    return kind, channel.strip(), _check_first_contact(first_contact)


def _find_by_id(records: list[dict], recruiter_id: int) -> dict | None:
    return next((r for r in records if r.get("id") == recruiter_id), None)


def add(name: str, company: str, *, kind: str = "inhouse", agency: str = "",
        channel: str = "email", handle: str = "", first_contact: str = "",
        notes: str = "", tags: list[str] | None = None,
        path: str | Path | None = None) -> dict:
    """Add a recruiter profile. Returns the new record.

    If a recruiter with the same normalized name+company already exists,
    returns the EXISTING record (a copy) with ``"duplicate": True``
    instead of duplicating, no write happens. Check
    ``rec.get("duplicate")`` to tell the user.
    """
    if not _norm(name):
        raise RecruiterError("Recruiter --name is required.")
    if not _norm(company):
        raise RecruiterError("Recruiter --company is required.")
    kind, channel, first_contact = _validate_common(
        kind=kind, channel=channel, agency=agency, first_contact=first_contact
    )
    records = _load(path)
    for r in records:
        if _norm(r["name"]) == _norm(name) and _norm(r["company"]) == _norm(company):
            return {**r, "duplicate": True}
    today = date.today().isoformat()
    rec = {
        "id": _next_id(records),
        "name": " ".join(name.split()),
        "company": " ".join(company.split()),
        "kind": kind,
        "agency": " ".join(agency.split()),
        "channel": channel,
        "handle": handle.strip(),
        "first_contact": first_contact,
        "notes": notes.strip(),
        "tags": _norm_tags(tags),
        "blocked": False,
        "blocked_reason": "",
        "date_added": today,
        "date_updated": today,
    }
    records.append(rec)
    _save(records, path)
    return rec


def get(recruiter_id: int, path: str | Path | None = None) -> dict:
    """Return one recruiter record by id."""
    rec = _find_by_id(_load(path), recruiter_id)
    if rec is None:
        raise RecruiterError(f"No recruiter with id {recruiter_id}.")
    return rec


def list_recruiters(*, kind: str | None = None, company: str | None = None,
                    tag: str | None = None, include_blocked: bool = False,
                    path: str | Path | None = None) -> list[dict]:
    """List recruiters, excluding blocked ones unless include_blocked=True.

    Optional filters: kind ("inhouse"/"agency"), company (case-insensitive
    substring), tag (exact, case-insensitive).
    """
    if kind is not None and kind not in KINDS:
        raise RecruiterError(f"Unknown kind '{kind}'. Choose from: {', '.join(KINDS)}")
    records = _load(path)
    out = []
    for r in records:
        if r.get("blocked") and not include_blocked:
            continue
        if kind and r.get("kind") != kind:
            continue
        if company and company.lower() not in r.get("company", "").lower():
            continue
        if tag and _norm(tag) not in (r.get("tags") or []):
            continue
        out.append(r)
    return sorted(out, key=lambda r: r["id"])


def update(recruiter_id: int, *, name: str | None = None, company: str | None = None,
           kind: str | None = None, agency: str | None = None,
           channel: str | None = None, handle: str | None = None,
           first_contact: str | None = None, notes: str | None = None,
           tags: list[str] | None = None,
           path: str | Path | None = None) -> dict:
    """Update a recruiter's fields. Returns the updated record."""
    records = _load(path)
    rec = _find_by_id(records, recruiter_id)
    if rec is None:
        raise RecruiterError(f"No recruiter with id {recruiter_id}.")
    if name is not None:
        if not _norm(name):
            raise RecruiterError("Recruiter name cannot be blank.")
        rec["name"] = " ".join(name.split())
    if company is not None:
        if not _norm(company):
            raise RecruiterError("Recruiter company cannot be blank.")
        rec["company"] = " ".join(company.split())
    if kind is not None:
        if kind not in KINDS:
            raise RecruiterError(f"Unknown kind '{kind}'. Choose from: {', '.join(KINDS)}")
        rec["kind"] = kind
    if agency is not None:
        rec["agency"] = " ".join(agency.split())
    if channel is not None:
        if channel not in CHANNELS:
            raise RecruiterError(
                f"Unknown contact channel '{channel}'. Choose from: {', '.join(CHANNELS)}"
            )
        rec["channel"] = channel
    if handle is not None:
        rec["handle"] = handle.strip()
    if first_contact is not None:
        rec["first_contact"] = _check_first_contact(first_contact)
    if notes is not None:
        rec["notes"] = notes.strip()
    if tags is not None:
        rec["tags"] = _norm_tags(tags)
    if rec["kind"] == "agency" and not rec["agency"].strip():
        raise RecruiterError("kind 'agency' requires an agency name.")
    # Renaming onto an existing record's name+company is a dupe, reject it.
    for other in records:
        if (other["id"] != rec["id"]
                and _norm(other["name"]) == _norm(rec["name"])
                and _norm(other["company"]) == _norm(rec["company"])):
            raise RecruiterError(
                f"A recruiter named '{rec['name']}' at '{rec['company']}' already exists "
                f"(id {other['id']})."
            )
    rec["date_updated"] = date.today().isoformat()
    _save(records, path)
    return rec


def delete(recruiter_id: int, path: str | Path | None = None) -> None:
    """Delete a recruiter record."""
    records = _load(path)
    kept = [r for r in records if r.get("id") != recruiter_id]
    if len(kept) == len(records):
        raise RecruiterError(f"No recruiter with id {recruiter_id}.")
    _save(kept, path)


def search_by_name(query: str, *, include_blocked: bool = False,
                   path: str | Path | None = None) -> list[dict]:
    """Case-insensitive substring search over recruiter names."""
    q = _norm(query)
    if not q:
        return []
    out = [r for r in list_recruiters(include_blocked=include_blocked, path=path)
           if q in _norm(r.get("name", ""))]
    return sorted(out, key=lambda r: r["id"])


def block(recruiter_id: int, reason: str = "",
          path: str | Path | None = None) -> dict:
    """Flag a recruiter as do-not-engage, with a reason. Returns the record."""
    records = _load(path)
    rec = _find_by_id(records, recruiter_id)
    if rec is None:
        raise RecruiterError(f"No recruiter with id {recruiter_id}.")
    rec["blocked"] = True
    rec["blocked_reason"] = (reason or "").strip()
    rec["date_updated"] = date.today().isoformat()
    _save(records, path)
    return rec


def unblock(recruiter_id: int, path: str | Path | None = None) -> dict:
    """Remove a recruiter from the do-not-engage list. Returns the record."""
    records = _load(path)
    rec = _find_by_id(records, recruiter_id)
    if rec is None:
        raise RecruiterError(f"No recruiter with id {recruiter_id}.")
    rec["blocked"] = False
    rec["blocked_reason"] = ""
    rec["date_updated"] = date.today().isoformat()
    _save(records, path)
    return rec


def is_blocked(name: str, *, company: str | None = None,
               path: str | Path | None = None) -> bool:
    """True if a recruiter with this (normalized) name is on the do-not-engage list.

    Pass company to disambiguate when two recruiters share a name.
    """
    q = _norm(name)
    if not q:
        raise RecruiterError("A name is required for the blocked check.")
    for r in _load(path):
        if _norm(r.get("name", "")) != q:
            continue
        if company is not None and _norm(r.get("company", "")) != _norm(company):
            continue
        return bool(r.get("blocked"))
    return False


def render_list(recruiters: list[dict]) -> str:
    if not recruiters:
        return "No recruiters tracked yet."
    lines = [f"{'ID':<4}{'Name':<24}{'Company':<22}{'Kind':<10}{'Channel':<10}Blocked"]
    for r in recruiters:
        blocked = "yes" if r.get("blocked") else ""
        lines.append(
            f"{r['id']:<4}{r['name'][:23]:<24}{r['company'][:21]:<22}"
            f"{r.get('kind', ''):<10}{r.get('channel', ''):<10}{blocked}"
        )
        reason = r.get("blocked_reason", "")
        if reason:
            lines.append(f"      blocked reason: {reason}")
    return "\n".join(lines)
