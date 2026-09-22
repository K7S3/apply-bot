"""Referral request workflow: track outbound referral asks, draft them,
and nudge you when a sent request has gone quiet.

Stored as JSON at candid_data/referral_requests.json (git-ignored).
Nothing is ever sent automatically — you copy the draft and send it
yourself.

Statuses: drafted -> sent -> reminded -> connected / declined.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from candid import config as C
from candid import followup as F

#: Canonical lifecycle of a referral request.
STATUSES = ("drafted", "sent", "reminded", "connected", "declined")
#: Terminal states — the request needs no further action.
DONE_STATUSES = ("connected", "declined")

FILENAME = "referral_requests.json"

#: Default: remind about a sent request after this many quiet days.
REMIND_AFTER_DAYS = 7


class RefRequestError(Exception):
    """Raised for invalid referral-request operations."""


def _default_path() -> Path:
    """Data path. CANDID_DATA_DIR is re-read at call time so tests can
    point it at a tmp dir even after candid.config was imported."""
    override = os.environ.get("CANDID_DATA_DIR")
    base = Path(override).expanduser() if override else C.DATA_DIR
    return base / FILENAME


def _resolve(path: str | Path | None) -> Path:
    return Path(path) if path else _default_path()


def _load(path: str | Path | None = None) -> list[dict]:
    p = _resolve(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RefRequestError(
            f"Referral file {p} is not valid JSON: {exc}. "
            "Fix or delete the file, then run `python -m candid refreq list`."
        ) from exc
    if not isinstance(data, list):
        raise RefRequestError(
            f"Referral file {p} should contain a JSON list. "
            "Fix or delete the file, then run `python -m candid refreq list`."
        )
    return data


def _save(reqs: list[dict], path: str | Path | None = None) -> Path:
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reqs, indent=2), encoding="utf-8")
    return p


def _next_id(reqs: list[dict]) -> int:
    return max((r.get("id", 0) for r in reqs), default=0) + 1


def _today_iso() -> str:
    return date.today().isoformat()


def add(contact: str, company: str, role: str, *,
        connection: str = "", status: str = "drafted",
        notes: str = "", path: str | Path | None = None) -> dict:
    """Add a referral request. Returns the new record."""
    if not contact or not company or not role:
        raise RefRequestError(
            "Contact, company, and role are all required. "
            "Run `python -m candid refreq add --help`."
        )
    if status not in STATUSES:
        raise RefRequestError(
            f"Unknown status '{status}'. Choose from: {', '.join(STATUSES)}. "
            "Run `python -m candid refreq add --help`."
        )
    reqs = _load(path)
    for r in reqs:
        if (r["contact"].lower() == contact.lower()
                and r["company"].lower() == company.lower()
                and r["role"].lower() == role.lower()):
            return {**r, "duplicate": True}
    rec = {
        "id": _next_id(reqs),
        "contact": contact,
        "company": company,
        "role": role,
        "connection": connection,
        "status": status,
        "notes": notes,
        "date_created": _today_iso(),
        "date_sent": _today_iso() if status == "sent" else "",
        "date_reminded": _today_iso() if status == "reminded" else "",
        "date_closed": _today_iso() if status in DONE_STATUSES else "",
        "date_updated": _today_iso(),
    }
    reqs.append(rec)
    _save(reqs, path)
    return rec


def get(req_id: int, path: str | Path | None = None) -> dict:
    """Return request #req_id or raise."""
    for r in _load(path):
        if r.get("id") == req_id:
            return r
    raise RefRequestError(
        f"No referral request #{req_id}. "
        "Run `python -m candid refreq list` to see ids."
    )


def list_requests(*, status: str | None = None,
                  path: str | Path | None = None) -> list[dict]:
    """All requests, optionally filtered by status."""
    if status is not None and status not in STATUSES:
        raise RefRequestError(
            f"Unknown status '{status}'. Choose from: {', '.join(STATUSES)}. "
            "Run `python -m candid refreq list --help`."
        )
    reqs = _load(path)
    if status is not None:
        reqs = [r for r in reqs if r.get("status") == status]
    return sorted(reqs, key=lambda r: r.get("id", 0))


def update(req_id: int, *, status: str | None = None, note: str = "",
           path: str | Path | None = None) -> dict:
    """Update a request's status and/or append a note. Returns the record."""
    if status is not None and status not in STATUSES:
        raise RefRequestError(
            f"Unknown status '{status}'. Choose from: {', '.join(STATUSES)}. "
            "Run `python -m candid refreq update --help`."
        )
    if status is None and not note:
        raise RefRequestError(
            "Nothing to update: pass --status and/or --note. "
            "Run `python -m candid refreq update --help`."
        )
    reqs = _load(path)
    for r in reqs:
        if r.get("id") == req_id:
            if status is not None:
                r["status"] = status
                if status == "sent" and not r.get("date_sent"):
                    r["date_sent"] = _today_iso()
                if status == "reminded":
                    r["date_reminded"] = _today_iso()
                if status in DONE_STATUSES:
                    r["date_closed"] = _today_iso()
            if note:
                prev = r.get("notes", "")
                r["notes"] = (prev + "\n" + note).strip() if prev else note
            r["date_updated"] = _today_iso()
            _save(reqs, path)
            return r
    raise RefRequestError(
        f"No referral request #{req_id}. "
        "Run `python -m candid refreq list` to see ids."
    )


def draft(req_id: int, *, name: str = "Your Name",
          path: str | Path | None = None) -> str:
    """Draft the referral ask for request #req_id via followup.referral_ask()."""
    r = get(req_id, path)
    return F.referral_ask(
        name, r["contact"], r["role"], r["company"],
        connection=r.get("connection") or "",
    )


def _days_since(iso: str, today: date) -> int | None:
    try:
        d = date.fromisoformat((iso or "")[:10])
    except ValueError:
        return None
    return (today - d).days


def remind(days: int = REMIND_AFTER_DAYS, *, today: date | None = None,
           name: str = "Your Name",
           path: str | Path | None = None) -> list[dict]:
    """Requests in `sent` with no reply after ``days`` quiet days.

    Each entry: {request, days_quiet, message, draft, command}. The draft is a
    gentle nudge built with followup.check_in()'s concise tone. Nothing is
    sent — you copy, edit, and send it yourself.
    """
    if days < 1:
        raise RefRequestError(
            f"--days must be at least 1 (got {days}). "
            "Run `python -m candid refreq remind --help`."
        )
    today = today or date.today()
    out: list[dict] = []
    for r in list_requests(status="sent", path=path):
        quiet = _days_since(r.get("date_sent") or r.get("date_created") or "",
                            today)
        if quiet is None or quiet < days:
            continue
        last = r.get("date_sent") or r.get("date_created") or ""
        draft_text = F.check_in(
            name, r["contact"], r["role"], r["company"],
            last_contact=f"my referral request on {last}" if last else "my request",
            tone="concise",
        )
        out.append({
            "request": r,
            "days_quiet": quiet,
            "message": (
                f"Referral request to {r['contact']} ({r['role']} @ "
                f"{r['company']}) sent {quiet}d ago with no reply."
            ),
            "draft": draft_text,
            "command": (
                f"python -m candid refreq update {r['id']} --status reminded"
            ),
        })
    return out


def render_list(reqs: list[dict]) -> str:
    """One-line-per-request summary for the CLI."""
    if not reqs:
        return ("No referral requests yet. "
                "Add one with `python -m candid refreq add`.")
    lines = []
    for r in reqs:
        dup = " (duplicate)" if r.get("duplicate") else ""
        lines.append(
            f"#{r['id']} [{r.get('status', '?')}] {r['contact']} — "
            f"{r['role']} @ {r['company']}"
            + (f" (sent {r['date_sent']})" if r.get("date_sent") else "")
            + dup
        )
    return "\n".join(lines)


def render_reminders(reminders: list[dict]) -> str:
    """Nudge-style rendering of remind() output (mirrors nudges.render)."""
    if not reminders:
        return "No referral requests need a nudge. 🎉"
    lines = [f"📌 {len(reminders)} referral request(s) need a nudge:", ""]
    for rem in reminders:
        lines.append(f"• {rem['message']}")
        lines.append(f"  → After nudging, mark it: {rem['command']}")
        lines.append("")
        lines.append(rem["draft"])
        lines.append("")
    return "\n".join(lines).rstrip()
