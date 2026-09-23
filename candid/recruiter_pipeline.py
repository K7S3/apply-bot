"""Recruiter relationship manager: links between recruiters and applications.

Tracks which recruiters sent you which applications, per-recruiter funnel
stats, stale-thread nudges, and reply draft templates (never sent).

Link data lives at C.DATA_DIR / "recruiter_links.json" (git-ignored).
Application ids always refer to candid/tracker.py records and are validated
read-only against the tracker file: this module never writes tracker.json.

All drafts are copy-paste text. Nothing here sends email or messages.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from candid import config as C


class RecruiterError(Exception):
    """Raised for invalid recruiter-pipeline operations."""


# Statuses where the pipeline is still in motion with a recruiter.
ACTIVE_STATUSES = {"saved", "applied", "selected_for_interview", "offer"}


def _load(path: str | Path | None = None) -> dict[str, dict]:
    p = Path(path) if path else C.DATA_DIR / "recruiter_links.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecruiterError(f"Recruiter links file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RecruiterError(f"Recruiter links file {p} should contain a JSON object.")
    return data


def _save(recruiters: dict[str, dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else C.DATA_DIR / "recruiter_links.json"
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(recruiters, indent=2), encoding="utf-8")
    return p


def _key(recruiter: str) -> str:
    k = (recruiter or "").strip().lower()
    if not k:
        raise RecruiterError("Recruiter name is required.")
    return k


def _tracker_ids(tracker_path: str | Path | None = None) -> set[int]:
    """Read-only set of application ids in the tracker file."""
    p = Path(tracker_path) if tracker_path else C.DATA_DIR / "tracker.json"
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    if not isinstance(data, list):
        return set()
    return {a.get("id") for a in data if isinstance(a.get("id"), int)}


def upsert_recruiter(recruiter: str, *, agency: str = "", email: str = "",
                     last_touch: str | None = None, notes: str = "",
                     path: str | Path | None = None) -> dict:
    """Create or update a recruiter record. Returns the record."""
    k = _key(recruiter)
    if last_touch is not None:
        try:
            date.fromisoformat(last_touch)
        except ValueError:
            raise RecruiterError(
                f"last_touch '{last_touch}' is not a valid ISO date (YYYY-MM-DD).") from None
    data = _load(path)
    rec = data.get(k, {
        "recruiter": recruiter.strip(),
        "agency": "",
        "email": "",
        "last_touch": "",
        "notes": "",
        "apps": [],
    })
    rec["recruiter"] = recruiter.strip()
    if agency:
        rec["agency"] = agency.strip()
    if email:
        rec["email"] = email.strip()
    if last_touch is not None:
        rec["last_touch"] = last_touch
    if notes:
        rec["notes"] = notes.strip()
    data[k] = rec
    _save(data, path)
    return rec


def touch(recruiter: str, when: str | None = None,
          path: str | Path | None = None) -> dict:
    """Record a touch (default: today) with a recruiter."""
    return upsert_recruiter(recruiter, last_touch=when or date.today().isoformat(), path=path)


def link(recruiter: str, app_id: int, *, path: str | Path | None = None,
         tracker_path: str | Path | None = None) -> dict:
    """Link a recruiter to a tracker application. Returns the recruiter record.

    The app id is validated read-only against the tracker file.
    """
    k = _key(recruiter)
    if app_id not in _tracker_ids(tracker_path):
        raise RecruiterError(
            f"No application with id {app_id} in the tracker. Nothing was linked.")
    data = _load(path)
    rec = data.get(k)
    if rec is None:
        rec = {
            "recruiter": recruiter.strip(),
            "agency": "",
            "email": "",
            "last_touch": "",
            "notes": "",
            "apps": [],
        }
        data[k] = rec
    apps = rec.setdefault("apps", [])
    if app_id not in apps:
        apps.append(app_id)
        apps.sort()
    _save(data, path)
    return rec


def unlink(recruiter: str, app_id: int, path: str | Path | None = None) -> dict:
    """Remove a recruiter/application link. Returns the recruiter record."""
    k = _key(recruiter)
    data = _load(path)
    rec = data.get(k)
    if rec is None:
        raise RecruiterError(f"No recruiter '{recruiter.strip()}' on record.")
    apps = rec.get("apps", [])
    if app_id not in apps:
        raise RecruiterError(
            f"Recruiter '{recruiter.strip()}' is not linked to application {app_id}.")
    rec["apps"] = [a for a in apps if a != app_id]
    _save(data, path)
    return rec


def for_application(app_id: int, path: str | Path | None = None) -> list[str]:
    """Recruiter names linked to a tracker application."""
    return sorted(r["recruiter"] for r in _load(path).values() if app_id in r.get("apps", []))


def for_recruiter(recruiter: str, path: str | Path | None = None) -> list[int]:
    """Application ids linked to a recruiter."""
    rec = _load(path).get(_key(recruiter))
    return sorted(rec.get("apps", [])) if rec else []


def _apps_by_id(tracker_path: str | Path | None = None) -> dict[int, dict]:
    p = Path(tracker_path) if tracker_path else C.DATA_DIR / "tracker.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {a.get("id"): a for a in data if isinstance(data, list)
            and isinstance(a.get("id"), int)}


def recruiter_funnel(recruiter: str, *, path: str | Path | None = None,
                     tracker_path: str | Path | None = None) -> dict:
    """Per-recruiter funnel stats over their linked applications.

    Counts by tracker status plus response, interview, and offer rates
    computed like candid.tracker.stats. Rates are 0.0 on zero denominators.
    """
    k = _key(recruiter)
    data = _load(path)
    rec = data.get(k)
    if rec is None:
        raise RecruiterError(f"No recruiter '{recruiter.strip()}' on record.")
    apps_by_id = _apps_by_id(tracker_path)
    linked = [apps_by_id[a] for a in rec.get("apps", []) if a in apps_by_id]
    counts = {s: 0 for s in C.STATUSES}
    for a in linked:
        st = a.get("status", "saved")
        counts[st] = counts.get(st, 0) + 1
    applied_base = (counts["applied"] + counts["selected_for_interview"]
                    + counts["rejected"] + counts["offer"])
    responses = sum(counts[s] for s in C.RESPONSE_STATUSES)
    interviews = counts["selected_for_interview"] + counts["offer"]
    return {
        "recruiter": rec["recruiter"],
        "total": len(linked),
        "counts": counts,
        "response_rate": round(100 * responses / applied_base, 1) if applied_base else 0.0,
        "interview_rate": round(100 * interviews / applied_base, 1) if applied_base else 0.0,
        "offer_rate": round(100 * counts["offer"] / applied_base, 1) if applied_base else 0.0,
        "response_base": applied_base,
    }


def _suggest_action(rec: dict, linked_apps: list[dict]) -> str:
    """Plain-text next-action suggestion for a stale recruiter thread."""
    name = rec["recruiter"]
    statuses = {a.get("status") for a in linked_apps}
    if not linked_apps:
        return (f"{name} has no applications linked yet. Consider sending a brief "
                "intro message: your target roles, location, and availability, and "
                "ask what openings they are working on right now.")
    if statuses & {"selected_for_interview"}:
        return (f"{name} has an interview-stage role that went quiet. Consider asking "
                "for the interview timeline and whether the client has given any feedback.")
    if statuses & {"applied"}:
        return (f"{name} has applied role(s) with no update. Consider asking whether "
                "the client reviewed your profile and what the next step is.")
    if statuses & {"offer"}:
        return (f"{name} has an offer-stage role. Consider checking in on the "
                "offer details and decision timeline.")
    if statuses == {"saved"}:
        return (f"{name} has saved role(s) not yet submitted. Consider asking which "
                "role they want to submit you for first, or move on if there is no reply.")
    if statuses and statuses <= {"rejected", "withdrawn"}:
        return (f"{name} has no active applications; the linked roles were rejected. "
                "Consider asking what client feedback came back so you can adjust, "
                "then share your updated target roles.")
    return (f"{name} has no active applications. Consider a short check-in with your "
            "current target roles and start date to reopen the thread.")


def _contacts_names() -> dict[str, str]:
    """All known recruiter display names from the contacts file.

    Returns {lowercased name: display name}. Recruiters with no touches
    anywhere still show up as stale ("never touched") so neglect is visible.
    """
    try:
        raw = json.loads((_data_path("recruiters.json")).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    items = raw if isinstance(raw, list) else (list(raw.values()) if isinstance(raw, dict) else [])
    for rec in items:
        if isinstance(rec, dict) and rec.get("name"):
            name = str(rec["name"]).strip()
            out.setdefault(name.casefold(), name)
    return out


def _data_path(name: str) -> Path:
    override = os.environ.get("CANDID_DATA_DIR")
    base = Path(override).expanduser() if override else C.DATA_DIR
    return base / name


def _thread_last_touches(threads_path: str | Path | None = None) -> dict[str, tuple[str, str]]:
    """Latest touch date per recruiter from the threads file.

    Returns {lowercased name: (display name, YYYY-MM-DD date)}. The threads
    module is the richer interaction log (worker B), so its dates take part
    in stale detection alongside the pipeline store's last_touch.
    """
    from candid import recruiter_threads as RT

    out: dict[str, tuple[str, str]] = {}
    try:
        touches = RT._load(threads_path)
    except Exception:
        return out
    if isinstance(touches, dict):
        items = [t for v in touches.values() if isinstance(v, list) for t in v]
    else:
        items = touches if isinstance(touches, list) else []
    for t in items:
        if not isinstance(t, dict):
            continue
        name = (t.get("recruiter") or "").strip()
        d = (t.get("date") or "").strip()
        if not name or not d:
            continue
        key = name.casefold()
        if key not in out or d > out[key][1]:
            out[key] = (name, d)
    return out


def stale_threads(days: int = 14, *, path: str | Path | None = None,
                  tracker_path: str | Path | None = None,
                  threads_path: str | Path | None = None) -> list[dict]:
    """Recruiters whose last touch is older than `days` with no active linked app.

    Last-touch information is merged from the pipeline store, the threads
    file (the richer touch log), and the contacts file; the most recent
    date wins. Recruiters known only via threads or contacts are included
    too, so neglect is visible.

    Returns a list of {"recruiter", "days_since_touch", "suggestion"} dicts.
    Suggestions are plain text; nothing is sent.
    """
    if days < 0:
        raise RecruiterError("days must be 0 or greater.")
    today = date.today()
    apps_by_id = _apps_by_id(tracker_path)
    store = _load(path)
    thread_last = _thread_last_touches(threads_path)
    contacts = _contacts_names()
    out = []
    for key in set(store.keys()) | set(thread_last.keys()) | set(contacts.keys()):
        if key in store:
            rec = store[key]
        elif key in thread_last:
            rec = {"recruiter": thread_last[key][0], "apps": []}
        else:
            rec = {"recruiter": contacts[key], "apps": []}
        linked = [apps_by_id[a] for a in rec.get("apps", []) if a in apps_by_id]
        if any(a.get("status") in ACTIVE_STATUSES for a in linked):
            continue
        candidates = [c for c in (rec.get("last_touch") or "",
                                  thread_last.get(key, ("", ""))[1]) if c]
        last = max(candidates) if candidates else ""
        try:
            last_date = date.fromisoformat(last)
        except ValueError:
            last_date = None
        age = (today - last_date).days if last_date else None
        if age is None or age > days:
            out.append({
                "recruiter": rec["recruiter"],
                "days_since_touch": age,
                "last_touch": last or "never",
                "suggestion": _suggest_action(rec, linked),
            })
    out.sort(key=lambda d: (d["days_since_touch"] is None, -(d["days_since_touch"] or 0)))
    return out


DRAFT_KINDS = ("interested", "not_interested", "need_details", "schedule_call")

_TEMPLATES = {
    "interested": {
        "subject": "Interested in the {role} role",
        "body": ("Hi {recruiter},\n\nThanks for reaching out about the {role} role at "
                 "{company}. I am interested and would like to learn more.\n\n"
                 "A quick summary: {summary}\n\nHappy to share my resume and set up "
                 "a time to talk.\n\nBest,\n{name}"),
        "timing": "Send within one business day while the role is fresh.",
    },
    "not_interested": {
        "subject": "Re: {role} role - passing for now",
        "body": ("Hi {recruiter},\n\nThanks for thinking of me for the {role} role at "
                 "{company}. It is not the right fit for me right now, so I will pass.\n\n"
                 "I appreciate you keeping me in mind for future roles that match "
                 "{interest}.\n\nBest,\n{name}"),
        "timing": "Send within two business days so the recruiter can move on.",
    },
    "need_details": {
        "subject": "Quick questions on the {role} role",
        "body": ("Hi {recruiter},\n\nThanks for sharing the {role} role at {company}. "
                 "Before I decide, could you share a few details?\n\n"
                 "- Compensation range\n- Location and remote policy\n"
                 "- Employment type (full-time or contract)\n"
                 "- Interview process and timeline\n\nThanks,\n{name}"),
        "timing": "Send within one business day to keep the conversation warm.",
    },
    "schedule_call": {
        "subject": "Call to discuss the {role} role",
        "body": ("Hi {recruiter},\n\nI would like to schedule a short call to discuss "
                 "the {role} role at {company}.\n\nI am generally available {availability}. "
                 "Let me know what works for you, or send a calendar invite.\n\n"
                 "Best,\n{name}"),
        "timing": "Offer times within the next 2 to 3 business days.",
    },
}


def reply_draft(recruiter: str, kind: str, name: str, *, role: str = "the role",
                company: str = "the company", summary: str = "available on request",
                interest: str = "my background", availability: str = "weekday afternoons") -> dict:
    """Build a short copy-paste reply draft for a recruiter.

    kind is one of "interested", "not_interested", "need_details",
    "schedule_call". Returns {"subject", "body", "timing"}. Nothing is sent.
    """
    if not (name or "").strip():
        raise RecruiterError("Your name is required for the draft signature.")
    _key(recruiter)
    if kind not in _TEMPLATES:
        raise RecruiterError(
            f"Unknown draft kind '{kind}'. Choose from: {', '.join(DRAFT_KINDS)}")
    t = _TEMPLATES[kind]
    kw = {
        "recruiter": recruiter.strip(),
        "role": role.strip() or "the role",
        "company": company.strip() or "the company",
        "summary": summary,
        "interest": interest,
        "availability": availability,
        "name": name.strip(),
    }
    return {
        "subject": t["subject"].format(**kw),
        "body": t["body"].format(**kw),
        "timing": t["timing"],
    }


def render_links(path: str | Path | None = None) -> str:
    """Human-readable summary of recruiter links."""
    data = _load(path)
    if not data:
        return "No recruiter links yet. Add a recruiter first, then link applications."
    lines = [f"{len(data)} recruiter(s) tracked", ""]
    for rec in sorted(data.values(), key=lambda r: r["recruiter"].lower()):
        n = len(rec.get("apps", []))
        lines.append(f"- {rec['recruiter']} ({n} linked application{'s' if n != 1 else ''})")
    return "\n".join(lines)
