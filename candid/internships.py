"""Internship application tracker (bulk mode).

A lighter-weight sibling of tracker.py for the internship season: the
stage model is the classic recruiting pipeline

    applied -> oa (online assessment) -> phone -> onsite -> offer
        -> accepted / rejected

plus bulk CSV import and deadline watchlists. Stored as JSON at
candid_data/internships.json (git-ignored, per config.py patterns).

Usage:
    python -m candid internships add --company X --role "SWE Intern" --deadline 2026-10-15
    python -m candid internships list
    python -m candid internships update 1 --stage oa
    python -m candid internships import-csv internships.csv
    python -m candid internships deadlines --days 30
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path

from candid import config as C


class InternshipsError(Exception):
    """Raised for invalid internship operations."""


def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else C.INTERNSHIPS_PATH
    if not p.exists():
        return []
    try:
        raw = p.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InternshipsError(f"Internships file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise InternshipsError(f"Internships file {p} should contain a JSON list.")
    return data


def _save(items: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else C.INTERNSHIPS_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return p


def _next_id(items: list[dict]) -> int:
    return max((a.get("id", 0) for a in items), default=0) + 1


def _check_stage(stage: str) -> str:
    if stage not in C.INTERN_STATUSES:
        raise InternshipsError(
            f"Unknown internship stage '{stage}'. "
            f"Choose from: {', '.join(C.INTERN_STATUSES)}")
    return stage


def _check_deadline(deadline: str) -> str:
    deadline = (deadline or "").strip()
    if not deadline:
        return ""
    try:
        datetime.strptime(deadline, "%Y-%m-%d")
    except ValueError:
        raise InternshipsError(
            f"Bad deadline {deadline!r}: use YYYY-MM-DD, e.g. "
            f"{date.today().isoformat()}.") from None
    return deadline


def _is_duplicate(items: list[dict], company: str, role: str) -> bool:
    return any(a["company"].lower() == company.lower()
               and a["role"].lower() == role.lower() for a in items)


def add(company: str, role: str, *, location: str = "", deadline: str = "",
        url: str = "", stage: str = "applied", notes: str = "",
        path: str | Path | None = None) -> dict:
    """Add an internship application. Returns the new record.

    A company+role already tracked returns the EXISTING record (a copy)
    with ``"duplicate": True`` and no write happens.
    """
    if not company or not role:
        raise InternshipsError("Both --company and --role are required to add an internship.")
    _check_stage(stage)
    deadline = _check_deadline(deadline)
    items = _load(path)
    if _is_duplicate(items, company, role):
        rec = next(a for a in items
                   if a["company"].lower() == company.lower()
                   and a["role"].lower() == role.lower())
        return {**rec, "duplicate": True}
    rec = {
        "id": _next_id(items),
        "company": company.strip(),
        "role": role.strip(),
        "location": location.strip(),
        "deadline": deadline,
        "url": url.strip(),
        "stage": stage,
        "notes": notes.strip(),
        "date_added": date.today().isoformat(),
        "date_updated": date.today().isoformat(),
    }
    items.append(rec)
    _save(items, path)
    return rec


def list_internships(*, stage: str | None = None, company: str | None = None,
                     path: str | Path | None = None) -> list[dict]:
    """List internship applications, optionally filtered by stage/company."""
    items = _load(path)
    if stage:
        _check_stage(stage)
        items = [a for a in items if a.get("stage") == stage]
    if company:
        items = [a for a in items if company.lower() in a.get("company", "").lower()]
    return sorted(items, key=lambda a: a["id"])


def update(intern_id: int, *, stage: str | None = None, deadline: str | None = None,
           notes: str | None = None, url: str | None = None, role: str | None = None,
           path: str | Path | None = None) -> dict:
    """Update an internship's stage/deadline/notes/url/role. Returns the record."""
    items = _load(path)
    rec = next((a for a in items if a.get("id") == intern_id), None)
    if rec is None:
        raise InternshipsError(
            f"No internship with id {intern_id}. Use `internships list` to see ids.")
    if stage is not None:
        rec["stage"] = _check_stage(stage)
    if deadline is not None:
        rec["deadline"] = _check_deadline(deadline)
    if notes is not None:
        rec["notes"] = notes
    if url is not None:
        rec["url"] = url
    if role is not None:
        if not role.strip():
            raise InternshipsError("Role cannot be empty.")
        rec["role"] = role.strip()
    rec["date_updated"] = date.today().isoformat()
    _save(items, path)
    return rec


def remove(intern_id: int, path: str | Path | None = None) -> None:
    """Delete an internship record."""
    items = _load(path)
    kept = [a for a in items if a.get("id") != intern_id]
    if len(kept) == len(items):
        raise InternshipsError(f"No internship with id {intern_id}.")
    _save(kept, path)


#: CSV columns for import-csv. Only company and role are required;
#: location, deadline, url are optional.
CSV_COLUMNS = ["company", "role", "location", "deadline", "url"]


def import_csv(csv_path: str | Path, *, path: str | Path | None = None,
               default_deadline: str = "") -> dict:
    """Bulk-add internships from a CSV. Returns {added, skipped_duplicates,
    skipped_bad, errors}.

    Required columns: company, role. Optional: location, deadline, url.
    Rows with a missing company or role, or a bad deadline, are skipped
    (counted in skipped_bad with a note in errors); duplicates are skipped.
    """
    p = Path(csv_path)
    if not p.exists():
        raise InternshipsError(f"CSV file not found: {p}")
    added = skipped_dup = skipped_bad = 0
    errors: list[str] = []
    with p.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
        missing = [c for c in ("company", "role") if c not in headers]
        if missing:
            raise InternshipsError(
                f"CSV is missing required column(s): {', '.join(missing)}. "
                f"Expected at least: company, role (optional: location, deadline, url).")
        for n, row in enumerate(reader, 2):  # header is line 1
            company = (row.get("company") or "").strip()
            role = (row.get("role") or "").strip()
            if not company or not role:
                skipped_bad += 1
                errors.append(f"row {n}: missing company or role - skipped")
                continue
            kw = {
                "location": (row.get("location") or "").strip(),
                "deadline": (row.get("deadline") or "").strip() or default_deadline,
                "url": (row.get("url") or "").strip(),
            }
            try:
                rec = add(company, role, path=path, **kw)
            except InternshipsError as exc:
                skipped_bad += 1
                errors.append(f"row {n} ({company} / {role}): {exc} - skipped")
                continue
            if rec.get("duplicate"):
                skipped_dup += 1
            else:
                added += 1
    return {"added": added, "skipped_duplicates": skipped_dup,
            "skipped_bad": skipped_bad, "errors": errors}


def deadlines(days: int = 30, path: str | Path | None = None,
              today: str | None = None) -> list[dict]:
    """Upcoming application deadlines within the next `days` days.

    Sorted soonest-first. Excludes records with no deadline, past
    deadlines, and applications already accepted or rejected. Each record
    is a copy with ``"days_left"`` attached.
    """
    if days < 0:
        raise InternshipsError("--days must be >= 0.")
    now = date.fromisoformat(today) if today else date.today()
    items = _load(path)
    upcoming = []
    for a in items:
        if not a.get("deadline"):
            continue
        if a.get("stage") in ("accepted", "rejected"):
            continue
        try:
            dl = date.fromisoformat(a["deadline"])
        except ValueError:
            continue
        left = (dl - now).days
        if 0 <= left <= days:
            upcoming.append({**a, "days_left": left})
    return sorted(upcoming, key=lambda a: (a["deadline"], a["id"]))


def stats(path: str | Path | None = None) -> dict:
    """Pipeline stats: counts per stage."""
    items = _load(path)
    counts = {s: 0 for s in C.INTERN_STATUSES}
    for a in items:
        counts[a.get("stage", "applied")] = counts.get(a.get("stage"), 0) + 1
    return {"total": len(items), "counts": counts}


# --- rendering ----------------------------------------------------------------

NEXT_ACTIONS = {
    "applied": "watch for OA invite; prep LeetCode easy/medium",
    "oa": "complete within 72h of invite; prep data structures",
    "phone": "prep 30-min behavioral + 1 coding question",
    "onsite": "full prep pack: coding, system design basics, behavioral",
    "offer": "compare comp + deadline; negotiate before signing",
    "accepted": "-",
    "rejected": "note lessons, keep moving",
}


def render_list(items: list[dict]) -> str:
    if not items:
        return ("No internships tracked yet. Add one with:\n"
                "  python -m candid internships add --company X --role \"SWE Intern\"")
    lines = [f"{'ID':<4}{'Company':<22}{'Role':<30}{'Stage':<10}Deadline"]
    for a in items:
        lines.append(
            f"{a['id']:<4}{a['company'][:21]:<22}{a['role'][:29]:<30}"
            f"{a.get('stage', ''):<10}{a.get('deadline') or '-'}"
        )
        hint = NEXT_ACTIONS.get(a.get("stage", ""), "")
        if hint and hint != "-":
            lines.append(f"      -> next: {hint}")
    return "\n".join(lines)


def render_deadlines(items: list[dict]) -> str:
    if not items:
        return "No upcoming internship deadlines in this window."
    lines = ["Upcoming internship deadlines (soonest first):"]
    for a in items:
        left = a.get("days_left", 0)
        when = "TODAY" if left == 0 else f"in {left}d"
        lines.append(
            f"  {a['deadline']} ({when}): {a['company']} - {a['role']} "
            f"[{a.get('stage', '')}]#{a['id']}"
        )
        if a.get("url"):
            lines.append(f"      apply: {a['url']}")
    return "\n".join(lines)


def render_stats(s: dict) -> str:
    lines = [f"Internships: {s['total']}", "", "Pipeline:"]
    for st in C.INTERN_STATUSES:
        n = s["counts"][st]
        bar = "#" * min(n, 40)
        lines.append(f"  {st:<10} {n:>3}  {bar}")
    return "\n".join(lines)
