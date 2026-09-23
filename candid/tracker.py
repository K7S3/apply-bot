"""Application tracker: add/list/update applications, filterable views, funnel stats.

Stored as JSON at candid_data/tracker.json (git-ignored).
Statuses: saved, applied, selected_for_interview, rejected, offer, withdrawn.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C


class TrackerError(Exception):
    """Raised for invalid tracker operations."""


# Application kinds. "postdoc" is the academic track (worker-2 feature);
# records added before kinds existed have no kind and default to "industry".
# Do NOT change C.STATUSES.
KINDS = ("industry", "postdoc")
DEFAULT_KIND = "industry"
# Deadline this close triggers the "draft research statement" hint.
POSTDOC_DEADLINE_HINT_DAYS = 30


def _validate_kind(kind: str | None) -> str:
    k = (kind or DEFAULT_KIND).strip().lower()
    if k not in KINDS:
        raise TrackerError(f"Unknown kind '{kind}'. Choose from: {', '.join(KINDS)}")
    return k


def kind_of(app: dict) -> str:
    """Kind of a tracker record; legacy records (no kind) are 'industry'."""
    return (app.get("kind") or DEFAULT_KIND).strip().lower() or DEFAULT_KIND


def parse_deadline(value: str | None) -> date | None:
    """Parse a YYYY-MM-DD deadline string. Never raises: bad dates → None."""
    try:
        return date.fromisoformat((value or "").strip())
    except (ValueError, AttributeError, TypeError):
        return None


def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else C.TRACKER_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrackerError(f"Tracker file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise TrackerError(f"Tracker file {p} should contain a JSON list.")
    return data


def _save(apps: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else C.TRACKER_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(apps, indent=2), encoding="utf-8")
    return p


def _next_id(apps: list[dict]) -> int:
    return max((a.get("id", 0) for a in apps), default=0) + 1


def add(company: str, role: str, *, jd_link: str = "", status: str = "saved",
        notes: str = "", kind: str = "industry", pi: str = "", lab: str = "",
        funding_source: str = "", deadline: str = "", start_date: str = "",
        path: str | Path | None = None) -> dict:
    """Add an application. Returns the new record.

    If the same company+role is already tracked, returns the EXISTING
    record (a copy) with ``"duplicate": True`` instead of duplicating —
    no write happens. Check ``rec.get("duplicate")`` to tell the user.

    Postdoc track (``kind="postdoc"``): ``pi`` (principal investigator),
    ``lab`` (research group), ``funding_source`` (e.g. NIH F32),
    ``deadline`` and ``start_date`` are free-form YYYY-MM-DD strings.
    ``deadline``/``start_date`` are never validated as dates at add time;
    use :func:`parse_deadline` when reading them (bad dates → None).
    """
    if not company or not role:
        raise TrackerError("Both --company and --role are required to add an application.")
    if status not in C.STATUSES:
        raise TrackerError(f"Unknown status '{status}'. Choose from: {', '.join(C.STATUSES)}")
    apps = _load(path)
    for a in apps:
        if a["company"].lower() == company.lower() and a["role"].lower() == role.lower():
            return {**a, "duplicate": True}
    rec = {
        "id": _next_id(apps),
        "company": company.strip(),
        "role": role.strip(),
        "jd_link": jd_link.strip(),
        "status": status,
        "notes": notes.strip(),
        "date_added": date.today().isoformat(),
        "date_updated": date.today().isoformat(),
        "prep_pack": "",
        "kind": _validate_kind(kind),
        "pi": (pi or "").strip(),
        "lab": (lab or "").strip(),
        "funding_source": (funding_source or "").strip(),
        "deadline": (deadline or "").strip(),
        "start_date": (start_date or "").strip(),
    }
    apps.append(rec)
    _save(apps, path)
    return rec


def update(app_id: int, *, status: str | None = None, notes: str | None = None,
           prep_pack: str | None = None, kind: str | None = None,
           pi: str | None = None, lab: str | None = None,
           funding_source: str | None = None, deadline: str | None = None,
           start_date: str | None = None, path: str | Path | None = None) -> dict:
    """Update an application's status/notes/prep_pack/postdoc fields.

    Returns the record. Only fields passed as non-None are changed;
    ``kind`` is validated when given. Postdoc fields (``pi``, ``lab``,
    ``funding_source``, ``deadline``, ``start_date``) are accepted for
    any record and silently ignored by industry rendering.
    """
    apps = _load(path)
    rec = next((a for a in apps if a.get("id") == app_id), None)
    if rec is None:
        raise TrackerError(f"No application with id {app_id}. Use `track list` to see ids.")
    if status is not None:
        if status not in C.STATUSES:
            raise TrackerError(f"Unknown status '{status}'. Choose from: {', '.join(C.STATUSES)}")
        rec["status"] = status
    if notes is not None:
        rec["notes"] = notes
    if prep_pack is not None:
        rec["prep_pack"] = prep_pack
    if kind is not None:
        rec["kind"] = _validate_kind(kind)
    if pi is not None:
        rec["pi"] = pi.strip()
    if lab is not None:
        rec["lab"] = lab.strip()
    if funding_source is not None:
        rec["funding_source"] = funding_source.strip()
    if deadline is not None:
        rec["deadline"] = deadline.strip()
    if start_date is not None:
        rec["start_date"] = start_date.strip()
    rec["date_updated"] = date.today().isoformat()
    _save(apps, path)
    return rec


def remove(app_id: int, path: str | Path | None = None) -> None:
    apps = _load(path)
    kept = [a for a in apps if a.get("id") != app_id]
    if len(kept) == len(apps):
        raise TrackerError(f"No application with id {app_id}.")
    _save(kept, path)


def list_apps(*, status: str | None = None, company: str | None = None,
              kind: str | None = None, path: str | Path | None = None) -> list[dict]:
    """List applications, optionally filtered by status, company and/or kind.

    ``kind`` accepts "industry" or "postdoc"; legacy records without a
    kind count as "industry".
    """
    apps = _load(path)
    if status:
        if status not in C.STATUSES:
            raise TrackerError(f"Unknown status '{status}'. Choose from: {', '.join(C.STATUSES)}")
        apps = [a for a in apps if a["status"] == status]
    if company:
        apps = [a for a in apps if company.lower() in a["company"].lower()]
    if kind is not None:
        k = _validate_kind(kind)
        apps = [a for a in apps if kind_of(a) == k]
    return sorted(apps, key=lambda a: a["id"])


def search(query: str, path: str | Path | None = None) -> list[dict]:
    """Case-insensitive search over company, role, notes, jd_link, and the
    postdoc fields (pi, lab, funding_source)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    out = []
    for a in _load(path):
        hay = " ".join(str(a.get(f, "")) for f in
                       ("company", "role", "notes", "jd_link",
                        "pi", "lab", "funding_source")).lower()
        if q in hay:
            out.append(a)
    return sorted(out, key=lambda a: a["id"])


def export_csv(dest: str | Path, path: str | Path | None = None) -> Path:
    """Export the tracker to a CSV file. Returns the destination path."""
    import csv
    apps = _load(path)
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "company", "role", "status", "jd_link", "notes",
              "date_added", "date_updated", "prep_pack"]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for a in sorted(apps, key=lambda x: x.get("id", 0)):
            w.writerow({k: a.get(k, "") for k in fields})
    return p


def stats(path: str | Path | None = None) -> dict:
    """Funnel stats: counts per status, response rate, interview rate, offer rate."""
    apps = _load(path)
    counts = {s: 0 for s in C.STATUSES}
    for a in apps:
        counts[a.get("status", "saved")] = counts.get(a.get("status"), 0) + 1
    applied_base = counts["applied"] + counts["selected_for_interview"] + counts["rejected"] + counts["offer"]
    responses = sum(counts[s] for s in C.RESPONSE_STATUSES)
    interviews = counts["selected_for_interview"] + counts["offer"]
    return {
        "total": len(apps),
        "counts": counts,
        "response_rate": round(100 * responses / applied_base, 1) if applied_base else 0.0,
        "interview_rate": round(100 * interviews / applied_base, 1) if applied_base else 0.0,
        "offer_rate": round(100 * counts["offer"] / applied_base, 1) if applied_base else 0.0,
        "response_base": applied_base,
    }


# per-status next-action hints shown under each row of render_list
NEXT_ACTIONS = {
    "saved": "tailor resume + apply",
    "applied": "follow up if quiet > 14d",
    "selected_for_interview": "build a prep pack",
    "offer": "compare + negotiate",
    "rejected": "note lessons, keep moving",
    "withdrawn": "—",
}


def postdoc_next_action(app: dict, today: date | None = None) -> str:
    """Postdoc-aware next-action hint for one tracker record.

    Rules: deadline within POSTDOC_DEADLINE_HINT_DAYS → "draft research
    statement"; a named PI → "email PI"; a named lab → "contact the lab".
    The status-based industry hint is kept as a fallback. Never raises
    (bad deadline strings parse to None via :func:`parse_deadline`).
    """
    today = today or date.today()
    hints: list[str] = []
    deadline = parse_deadline(app.get("deadline", ""))
    if deadline is not None:
        days_left = (deadline - today).days
        if days_left < 0:
            hints.append("deadline passed - check for an extension")
        elif days_left <= POSTDOC_DEADLINE_HINT_DAYS:
            hints.append("draft research statement")
    pi = (app.get("pi") or "").strip()
    if pi:
        hints.append(f"email PI ({pi})")
    elif (app.get("lab") or "").strip():
        hints.append("contact the lab")
    base = NEXT_ACTIONS.get(app.get("status", ""), "")
    if base and base != "—":
        hints.append(base)
    return " + ".join(hints)


def next_action(app: dict) -> str:
    """Next-action hint for one record; postdoc records get the
    postdoc-aware hint, everything else the industry status hint."""
    if kind_of(app) == "postdoc":
        return postdoc_next_action(app)
    return NEXT_ACTIONS.get(app.get("status", ""), "")


def render_list(apps: list[dict]) -> str:
    if not apps:
        return "No applications tracked yet. Add one with: python -m candid track add --company X --role Y"
    lines = [f"{'ID':<4}{'Company':<22}{'Role':<34}{'Status':<22}Updated"]
    for a in apps:
        lines.append(
            f"{a['id']:<4}{a['company'][:21]:<22}{a['role'][:33]:<34}"
            f"{a['status']:<22}{a.get('date_updated', '')}"
        )
        hint = next_action(a)
        if hint and hint != "—":
            lines.append(f"      → next: {hint}")
    return "\n".join(lines)


def render_stats(s: dict) -> str:
    lines = [
        f"Tracked: {s['total']} applications",
        "",
        "Funnel:",
    ]
    for st in C.STATUSES:
        n = s["counts"][st]
        bar = "█" * min(n, 40)
        lines.append(f"  {st:<22} {n:>3}  {bar}")
    lines += [
        "",
        f"Response rate:  {s['response_rate']}%  (of {s['response_base']} submitted)",
        f"Interview rate: {s['interview_rate']}%",
        f"Offer rate:     {s['offer_rate']}%",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI wiring hook (worker-2). The orchestrator wires this into candid.__main__
# with one line per track subparsers object:
#
#     from candid import tracker as T
#     T.add_parsers(track_subparsers)   # track's own subparsers
#
# and threads the parsed args through cmd_track:
#
#     T.add(..., kind=a.kind, pi=a.pi or "", lab=a.lab or "",
#           funding_source=a.funding_source or "", deadline=a.deadline or "",
#           start_date=a.start_date or "")
#     T.list_apps(status=a.status, company=a.company, kind=a.kind)
#     T.update(a.id, status=a.status, notes=a.notes,
#              kind=getattr(a, "kind", None), pi=getattr(a, "pi", None), ...)
#
# This module cannot import argparse subparsers from __main__ (it must not
# be edited by worker-2), so the hook is provided for the parent to call.
# ---------------------------------------------------------------------------

def add_parsers(subparsers) -> None:
    """Attach postdoc CLI flags to the track add/list subparsers.

    ``subparsers`` is the argparse ``_SubParsersAction`` for the ``track``
    command (built in candid.__main__; children "add" and "list"). Only
    ADDS arguments; existing args are untouched.

    * ``track add``: --kind {industry,postdoc} --pi --lab --funding-source
      --deadline YYYY-MM-DD --start-date YYYY-MM-DD
    * ``track list``: --kind {industry,postdoc}
    """
    choices = getattr(subparsers, "choices", {}) or {}
    add_p = choices.get("add")
    if add_p is not None:
        add_p.add_argument("--kind", choices=KINDS, default="industry",
                           help="Application kind: postdoc for academic positions "
                                "(default: industry)")
        add_p.add_argument("--pi", default="",
                           help="Principal investigator (postdoc)")
        add_p.add_argument("--lab", default="",
                           help="Lab / research group (postdoc)")
        add_p.add_argument("--funding-source", dest="funding_source", default="",
                           help="Funding source, e.g. NIH F32 (postdoc)")
        add_p.add_argument("--deadline", default="",
                           help="Application deadline YYYY-MM-DD (postdoc)")
        add_p.add_argument("--start-date", dest="start_date", default="",
                           help="Earliest start date YYYY-MM-DD (postdoc)")
    list_p = choices.get("list")
    if list_p is not None:
        list_p.add_argument("--kind", choices=KINDS,
                            help="Filter by application kind (industry/postdoc)")
    # update: postdoc fields are also handy on update
    update_p = choices.get("update")
    if update_p is not None:
        update_p.add_argument("--kind", choices=KINDS,
                              help="Change the application kind")
        update_p.add_argument("--pi", help="Principal investigator (postdoc)")
        update_p.add_argument("--lab", help="Lab / research group (postdoc)")
        update_p.add_argument("--funding-source", dest="funding_source",
                              help="Funding source, e.g. NIH F32 (postdoc)")
        update_p.add_argument("--deadline",
                              help="Application deadline YYYY-MM-DD (postdoc)")
        update_p.add_argument("--start-date", dest="start_date",
                              help="Earliest start date YYYY-MM-DD (postdoc)")
