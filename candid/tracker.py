"""Application tracker: add/list/update applications, filterable views, funnel stats.

Stored as JSON at candid_data/tracker.json (git-ignored).
Statuses: saved, applied, selected_for_interview, rejected, offer, withdrawn.

New-grad track (additive fields, old records keep working):
- ``internship`` (bool): marked via ``track add --internship``.
- ``return_offer`` ("", "yes", "pending", "no"): set via
  ``track update <id> --return-offer yes``.
- ``converted_from`` (int | None): the internship app id a full-time
  application converts from, created with ``candid convert --from <id> ...``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C


class TrackerError(Exception):
    """Raised for invalid tracker operations."""


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


# Valid return-offer values recorded on an internship application.
RETURN_OFFER_VALUES = ("yes", "pending", "no")


def _next_id(apps: list[dict]) -> int:
    return max((a.get("id", 0) for a in apps), default=0) + 1


def add(company: str, role: str, *, jd_link: str = "", status: str = "saved",
        notes: str = "", internship: bool = False,
        path: str | Path | None = None) -> dict:
    """Add an application. Returns the new record.

    If the same company+role is already tracked, returns the EXISTING
    record (a copy) with ``"duplicate": True`` instead of duplicating —
    no write happens. Check ``rec.get("duplicate")`` to tell the user.

    Pass ``internship=True`` for a summer/new-grad internship application.
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
        "internship": bool(internship),
        "return_offer": "",
        "converted_from": None,
    }
    apps.append(rec)
    _save(apps, path)
    return rec


def update(app_id: int, *, status: str | None = None, notes: str | None = None,
           prep_pack: str | None = None, return_offer: str | None = None,
           path: str | Path | None = None) -> dict:
    """Update an application's status/notes/prep_pack/return_offer.

    Returns the record. ``return_offer`` is one of "yes", "pending", "no"
    (clears with ""). Meant for internship applications, but any record
    can carry it; old records without the key read as "".
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
    if return_offer is not None:
        ro = return_offer.strip().lower()
        if ro not in RETURN_OFFER_VALUES and ro != "":
            raise TrackerError(
                f"Unknown return-offer '{return_offer}'. "
                f"Choose from: {', '.join(RETURN_OFFER_VALUES)}")
        rec["return_offer"] = ro
    rec["date_updated"] = date.today().isoformat()
    _save(apps, path)
    return rec


def convert(from_id: int, *, company: str, role: str, notes: str = "",
            status: str = "saved", jd_link: str = "",
            path: str | Path | None = None) -> dict:
    """Create a full-time application linked to an internship app.

    Records ``converted_from = from_id`` on the new record so the
    internship-to-fulltime funnel stays linked. Returns the new record.
    """
    apps = _load(path)
    src = next((a for a in apps if a.get("id") == from_id), None)
    if src is None:
        raise TrackerError(f"No application with id {from_id}. Use `track list` to see ids.")
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
        "internship": False,
        "return_offer": "",
        "converted_from": from_id,
    }
    apps.append(rec)
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
              "date_added", "date_updated", "prep_pack",
              "internship", "return_offer", "converted_from"]
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


def conversion_stats(path: str | Path | None = None) -> dict:
    """Internship-to-fulltime funnel.

    internships -> applied -> interviews -> offers -> return offers
    -> converted (linked full-time app) -> accepted (converted with status offer).
    Rates are percentages (rounded to 1 decimal), 0.0 when the denominator is 0.
    Old records without the ``internship``/``return_offer``/``converted_from``
    keys are treated as full-time apps with no return offer.
    """
    apps = _load(path)
    interns = [a for a in apps if a.get("internship")]
    submitted = {"applied", "selected_for_interview", "rejected", "offer"}
    applied = [a for a in interns if a.get("status") in submitted]
    interviews = [a for a in interns
                  if a.get("status") in ("selected_for_interview", "offer")]
    offers = [a for a in interns if a.get("status") == "offer"]
    ro_yes = [a for a in interns if a.get("return_offer") == "yes"]
    ro_pending = [a for a in interns if a.get("return_offer") == "pending"]
    converted = [a for a in apps if a.get("converted_from") is not None]
    accepted = [a for a in converted if a.get("status") == "offer"]

    def pct(num: int, den: int) -> float:
        return round(100 * num / den, 1) if den else 0.0

    return {
        "internships": len(interns),
        "applied": len(applied),
        "interviews": len(interviews),
        "offers": len(offers),
        "return_offers_yes": len(ro_yes),
        "return_offers_pending": len(ro_pending),
        "converted": len(converted),
        "accepted": len(accepted),
        "interview_rate": pct(len(interviews), len(applied)),
        "offer_rate": pct(len(offers), len(applied)),
        "return_offer_rate": pct(len(ro_yes), len(offers)),
        "convert_rate": pct(len(converted), len(ro_yes)),
        "accept_rate": pct(len(accepted), len(ro_yes)),
    }


def render_conversion_stats(s: dict) -> str:
    lines = [
        f"Internships tracked: {s['internships']}",
        "",
        "Internship -> full-time funnel:",
        f"  internships         {s['internships']:>3}",
        f"  applied             {s['applied']:>3}",
        f"  interviews          {s['interviews']:>3}   ({s['interview_rate']}% of applied)",
        f"  offers              {s['offers']:>3}   ({s['offer_rate']}% of applied)",
        f"  return offers       {s['return_offers_yes']:>3}   ({s['return_offer_rate']}% of offers)",
        f"    pending           {s['return_offers_pending']:>3}",
        f"  converted (FT app)  {s['converted']:>3}   ({s['convert_rate']}% of return offers)",
        f"  accepted (FT offer) {s['accepted']:>3}   ({s['accept_rate']}% of return offers)",
        "",
        "Mark internships with `track add --internship`, record outcomes with",
        "`track update <id> --return-offer yes|pending|no`, and link full-time",
        "apps with `candid convert --from <id> --company X --role Y`.",
    ]
    return "\n".join(lines)


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
        status = a.get("status", "")
        tag = " [intern]" if a.get("internship") else ""
        lines.append(
            f"{a['id']:<4}{a['company'][:21]:<22}{a['role'][:33]:<34}"
            f"{status + tag:<22}{a.get('date_updated', '')}"
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
