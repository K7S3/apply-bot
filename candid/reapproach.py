"""Re-approach tracker: companies worth retrying after 6-12 months.

Some companies say no for timing reasons, not fit reasons. This module
keeps a small watchlist: company, last contact date, suggested retry dates
(computed 6 and 12 months out), a note on why it is worth retrying, and a
status (watching / due / re-approached).

Stored at candid_data/reapproach.json (git-ignored). Stdlib only.
"""

from __future__ import annotations

import calendar
import json
from datetime import date
from pathlib import Path

from candid import config as C


class ReapproachError(Exception):
    """Raised for invalid re-approach data or operations."""


#: Retry horizons, in months, computed from last_contact.
RETRY_HORIZONS_MONTHS = (6, 12)

STATUSES = ("watching", "due", "re-approached")

_NEXT = "Run: python -m candid reapproach --help"


def _data_dir(data_dir: str | Path | None = None) -> Path:
    return Path(data_dir) if data_dir else C.DATA_DIR


def reapproach_path(data_dir: str | Path | None = None) -> Path:
    """Path of the watchlist file. Overridable for tests."""
    return _data_dir(data_dir) / "reapproach.json"


def _load(data_dir: str | Path | None = None) -> list[dict]:
    p = reapproach_path(data_dir)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReapproachError(
            f"Re-approach file {p} is not valid JSON: {exc}. {_NEXT}"
        ) from exc
    return data if isinstance(data, list) else []


def _save(records: list[dict],
          data_dir: str | Path | None = None) -> Path:
    p = reapproach_path(data_dir)
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return p


def _parse_date(value: str, what: str = "Date") -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except (ValueError, AttributeError):
        raise ReapproachError(
            f"{what} '{value}' is not a valid YYYY-MM-DD date. {_NEXT}"
        ) from None


def add_months(d: date, months: int) -> date:
    """Add months to a date, clamping to the end of the month if needed."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))


def add(company: str, last_contact: str, reason: str = "",
        status: str = "watching",
        data_dir: str | Path | None = None) -> dict:
    """Add a company to the re-approach watchlist.

    last_contact is YYYY-MM-DD. Retry dates are computed 6 and 12 months
    out. Raises ReapproachError on duplicates (case-insensitive company
    match) or bad input.
    """
    company = (company or "").strip()
    if not company:
        raise ReapproachError(
            f"Company is required. {_NEXT}")
    lc = _parse_date(last_contact, "Last-contact date")
    if status not in STATUSES:
        raise ReapproachError(
            f"Status must be one of {', '.join(STATUSES)}, got '{status}'. "
            f"{_NEXT}")
    records = _load(data_dir)
    if any(r.get("company", "").lower() == company.lower()
           for r in records):
        raise ReapproachError(
            f"'{company}' is already on the watchlist. {_NEXT}")
    rec = {
        "id": max((r.get("id", 0) for r in records), default=0) + 1,
        "company": company,
        "last_contact": lc.isoformat(),
        "retry_6mo": add_months(lc, 6).isoformat(),
        "retry_12mo": add_months(lc, 12).isoformat(),
        "reason": reason or "",
        "status": status,
        "reapproached_on": "",
    }
    records.append(rec)
    _save(records, data_dir)
    return rec


def _find(records: list[dict], company_or_id: str | int) -> dict:
    for r in records:
        if str(r.get("id")) == str(company_or_id):
            return r
        if isinstance(company_or_id, str) and \
                r.get("company", "").lower() == company_or_id.lower():
            return r
    raise ReapproachError(
        f"No watchlist entry for '{company_or_id}'. "
        f"{_NEXT}")


def list_companies(data_dir: str | Path | None = None) -> list[dict]:
    """All watchlist entries, soonest retry date first."""
    return sorted(_load(data_dir),
                  key=lambda r: (r.get("retry_6mo", ""), r.get("company", "")))


def remove(company_or_id: str | int,
           data_dir: str | Path | None = None) -> bool:
    """Remove a watchlist entry. Returns True if one existed."""
    records = _load(data_dir)
    try:
        rec = _find(records, company_or_id)
    except ReapproachError:
        return False
    records.remove(rec)
    _save(records, data_dir)
    return True


def mark(company_or_id: str | int, status: str,
         today: date | None = None,
         data_dir: str | Path | None = None) -> dict:
    """Change an entry's status. Marking 're-approached' stamps the date."""
    if status not in STATUSES:
        raise ReapproachError(
            f"Status must be one of {', '.join(STATUSES)}, got '{status}'. "
            f"{_NEXT}")
    records = _load(data_dir)
    rec = _find(records, company_or_id)
    rec["status"] = status
    if status == "re-approached":
        rec["reapproached_on"] = (today or date.today()).isoformat()
    _save(records, data_dir)
    return rec


def due(today: date | None = None,
        data_dir: str | Path | None = None) -> list[dict]:
    """Entries whose retry date has arrived, most overdue first.

    Each entry gains: due_horizon ('6mo' or '12mo'), due_date, days_overdue.
    Entries already re-approached are excluded.
    """
    today = today or date.today()
    out = []
    for r in list_companies(data_dir=data_dir):
        if r.get("status") == "re-approached":
            continue
        horizon = None
        for h in (6, 12):
            key = f"retry_{h}mo"
            retry = _parse_date(r.get(key, ""), "Retry date")
            if retry <= today:
                horizon, due_date = f"{h}mo", retry
        if horizon is None:
            continue
        entry = dict(r)
        entry["due_horizon"] = horizon
        entry["due_date"] = due_date.isoformat()
        entry["days_overdue"] = (today - due_date).days
        out.append(entry)
    return sorted(out, key=lambda e: (e["days_overdue"], e["company"]),
                  reverse=True)


def render_list(data_dir: str | Path | None = None) -> str:
    """Render the full watchlist."""
    records = list_companies(data_dir=data_dir)
    if not records:
        return ("Re-approach watchlist is empty. Add a company with:\n"
                "  python -m candid reapproach add --company Acme "
                "--last-contact 2026-09-01 --reason \"hiring freeze lifted\"")
    lines = ["Re-approach watchlist:", ""]
    for r in records:
        reason = f" — {r['reason']}" if r.get("reason") else ""
        lines.append(
            f"  #{r['id']} {r['company']} (last contact {r['last_contact']}, "
            f"{r['status']}){reason}")
        lines.append(f"      retry: {r['retry_6mo']} (6mo) / "
                     f"{r['retry_12mo']} (12mo)")
    return "\n".join(lines)


def render_due(today: date | None = None,
               data_dir: str | Path | None = None) -> str:
    """Render entries whose retry date has arrived."""
    entries = due(today=today, data_dir=data_dir)
    if not entries:
        return ("Nothing is due for re-approach. "
                "Watchlist: python -m candid reapproach list")
    lines = ["Due for re-approach:", ""]
    for e in entries:
        over = e["days_overdue"]
        when = f"{over}d overdue" if over else "due now"
        lines.append(
            f"  #{e['id']} {e['company']} — {e['due_horizon']} retry "
            f"date {e['due_date']} ({when})")
        if e.get("reason"):
            lines.append(f"      why retry: {e['reason']}")
    lines.append("")
    lines.append("After reaching out: "
                 "python -m candid reapproach mark <company> "
                 "--status re-approached")
    return "\n".join(lines)
