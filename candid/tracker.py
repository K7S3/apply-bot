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


def validate_deadline(raw: str) -> str:
    """Normalize a deadline string to YYYY-MM-DD ("" clears it)."""
    s = (raw or "").strip()
    if not s:
        return ""
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise TrackerError(
            f"Bad deadline {raw!r}: use YYYY-MM-DD, e.g. --deadline 2026-10-15."
        ) from None


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
        notes: str = "", deadline: str = "",
        path: str | Path | None = None) -> dict:
    """Add an application. Returns the new record.

    If the same company+role is already tracked, returns the EXISTING
    record (a copy) with ``"duplicate": True`` instead of duplicating —
    no write happens. Check ``rec.get("duplicate")`` to tell the user.
    """
    if not company or not role:
        raise TrackerError("Both --company and --role are required to add an application.")
    if status not in C.STATUSES:
        raise TrackerError(f"Unknown status '{status}'. Choose from: {', '.join(C.STATUSES)}")
    deadline = validate_deadline(deadline)
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
        "deadline": deadline,
        "date_added": date.today().isoformat(),
        "date_updated": date.today().isoformat(),
        "prep_pack": "",
        "resume_variant": {},
        "cover_letter": {},
        "match_score": None,
        "gate": {},
    }
    apps.append(rec)
    _save(apps, path)
    return rec


def update(app_id: int, *, status: str | None = None, notes: str | None = None,
           prep_pack: str | None = None, deadline: str | None = None,
           variant_chosen: bool | None = None,
           match_score: float | None = None,
           path: str | Path | None = None) -> dict:
    """Update an application. Returns the record.

    ``deadline`` sets/clears the YYYY-MM-DD deadline ("" clears).
    ``variant_chosen=True`` marks the recorded resume variant as the
    chosen one for submission; ``False`` un-marks it.
    ``match_score`` stores the last match score for the gate's floor check.
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
    if deadline is not None:
        rec["deadline"] = validate_deadline(deadline)
    if variant_chosen is not None:
        variant = rec.get("resume_variant") or {}
        if not variant.get("tone"):
            raise TrackerError(
                f"No tailored resume variant recorded for application #{app_id} yet. "
                f"Tailor one first: `python -m candid tailor resume --app-id {app_id} --jd jd.txt`."
            )
        variant["chosen"] = bool(variant_chosen)
        rec["resume_variant"] = variant
    if match_score is not None:
        try:
            score = float(match_score)
        except (TypeError, ValueError):
            raise TrackerError(f"Bad match score {match_score!r}: use a number 0-100.") from None
        if not 0 <= score <= 100:
            raise TrackerError(f"Bad match score {match_score!r}: use a number 0-100.")
        rec["match_score"] = round(score, 1)
    # tolerate records created before the gate fields existed
    rec.setdefault("resume_variant", {})
    rec.setdefault("cover_letter", {})
    rec.setdefault("match_score", None)
    rec.setdefault("gate", {})
    rec["date_updated"] = date.today().isoformat()
    _save(apps, path)
    return rec


def record_variant(app_id: int, *, tone: str, length: str, jd_text: str,
                   resume_text: str, chosen: bool = False,
                   path: str | Path | None = None) -> dict:
    """Record a tailored resume variant on the application (for the gate)."""
    from candid import gate as G
    apps = _load(path)
    rec = next((a for a in apps if a.get("id") == app_id), None)
    if rec is None:
        raise TrackerError(f"No application with id {app_id}. Use `track list` to see ids.")
    rec["resume_variant"] = {
        "tone": tone,
        "length": length,
        "jd_sha": G.jd_sha(jd_text),
        "created_at": date.today().isoformat(),
        "chosen": bool(chosen),
        "resume_text": resume_text,
    }
    rec["date_updated"] = date.today().isoformat()
    _save(apps, path)
    return rec


def record_cover_letter(app_id: int, *, text: str, hook: str = "",
                        path: str | Path | None = None) -> dict:
    """Record a tailored cover letter on the application (for the gate)."""
    apps = _load(path)
    rec = next((a for a in apps if a.get("id") == app_id), None)
    if rec is None:
        raise TrackerError(f"No application with id {app_id}. Use `track list` to see ids.")
    rec["cover_letter"] = {
        "created_at": date.today().isoformat(),
        "hook": hook or "",
        "text": text,
    }
    rec["date_updated"] = date.today().isoformat()
    _save(apps, path)
    return rec


def record_gate_result(app_id: int, result: dict,
                       path: str | Path | None = None) -> dict:
    """Stamp the last gate run onto the application. Returns the record."""
    apps = _load(path)
    rec = next((a for a in apps if a.get("id") == app_id), None)
    if rec is None:
        raise TrackerError(f"No application with id {app_id}. Use `track list` to see ids.")
    rec["gate"] = {
        "ran_at": date.today().isoformat(),
        "gate_version": result.get("gate_version", 1),
        "verdict": result.get("verdict", ""),
        "strict": bool(result.get("strict", False)),
        "blocks": list(result.get("blocks", [])),
        "warnings": list(result.get("warnings", [])),
        "passed": result.get("passed", 0),
        "total": result.get("total", 0),
    }
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
              path: str | Path | None = None) -> list[dict]:
    """List applications, optionally filtered by status and/or company."""
    apps = _load(path)
    if status:
        if status not in C.STATUSES:
            raise TrackerError(f"Unknown status '{status}'. Choose from: {', '.join(C.STATUSES)}")
        apps = [a for a in apps if a["status"] == status]
    if company:
        apps = [a for a in apps if company.lower() in a["company"].lower()]
    return sorted(apps, key=lambda a: a["id"])


def search(query: str, path: str | Path | None = None) -> list[dict]:
    """Case-insensitive search over company, role, notes, and jd_link."""
    q = (query or "").strip().lower()
    if not q:
        return []
    out = []
    for a in _load(path):
        hay = " ".join(str(a.get(f, "")) for f in
                       ("company", "role", "notes", "jd_link")).lower()
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


def render_list(apps: list[dict]) -> str:
    if not apps:
        return "No applications tracked yet. Add one with: python -m candid track add --company X --role Y"
    lines = [f"{'ID':<4}{'Company':<22}{'Role':<34}{'Status':<22}Updated"]
    for a in apps:
        lines.append(
            f"{a['id']:<4}{a['company'][:21]:<22}{a['role'][:33]:<34}"
            f"{a['status']:<22}{a.get('date_updated', '')}"
        )
        hint = NEXT_ACTIONS.get(a.get("status", ""), "")
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
