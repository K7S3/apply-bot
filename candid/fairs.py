"""Career fair logger: record fairs, the companies/people you talked to,
and who still needs a follow-up.

Stored as JSON at candid_data/fairs.json (git-ignored).

A fair is a dict:
    {"id", "name", "date" (YYYY-MM-DD or ""), "school", "date_added",
     "companies": [
        {"person", "company", "contact", "notes", "added",
         "followup_done", "followup_date"}]}

Company entries are logged with a single comma-separated string:
    "Jane Smith, Stripe, jane@stripe.com, talked about new grad roles"
parsed as person / company / contact / notes.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from candid import config as C


class FairError(Exception):
    """Raised for invalid fair operations."""


def _load(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else C.FAIRS_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FairError(f"Fair file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise FairError(f"Fair file {p} should contain a JSON list.")
    return data


def _save(fairs: list[dict], path: str | Path | None = None) -> Path:
    p = Path(path) if path else C.FAIRS_PATH
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(fairs, indent=2), encoding="utf-8")
    return p


def _next_id(fairs: list[dict]) -> int:
    return max((f.get("id", 0) for f in fairs), default=0) + 1


def _check_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parts = value.split("-")
    if len(parts) != 3 or not all(x.isdigit() for x in parts):
        raise FairError(f"Date '{value}' should be YYYY-MM-DD (or empty).")
    y, m, d = (int(x) for x in parts)
    if not (1 <= m <= 12 and 1 <= d <= 31 and y >= 1900):
        raise FairError(f"Date '{value}' is not a valid calendar date.")
    return f"{y:04d}-{m:02d}-{d:02d}"


def add_fair(name: str, *, date_: str = "", school: str = "",
             path: str | Path | None = None) -> dict:
    """Create a fair record. Returns the new record."""
    if not (name or "").strip():
        raise FairError("--name is required to add a fair.")
    fairs = _load(path)
    rec = {
        "id": _next_id(fairs),
        "name": name.strip(),
        "date": _check_date(date_),
        "school": school.strip(),
        "date_added": date.today().isoformat(),
        "companies": [],
    }
    fairs.append(rec)
    _save(fairs, path)
    return rec


def list_fairs(path: str | Path | None = None) -> list[dict]:
    """All fairs, sorted by id."""
    return sorted(_load(path), key=lambda f: f.get("id", 0))


def get_fair(fair_id: int, path: str | Path | None = None) -> dict:
    fairs = _load(path)
    rec = next((f for f in fairs if f.get("id") == fair_id), None)
    if rec is None:
        raise FairError(f"No fair with id {fair_id}. Use `fair list` to see ids.")
    return rec


def _save_one(rec: dict, path: str | Path | None = None) -> dict:
    fairs = _load(path)
    for i, f in enumerate(fairs):
        if f.get("id") == rec.get("id"):
            fairs[i] = rec
            break
    else:
        fairs.append(rec)
    _save(fairs, path)
    return rec


def parse_company_entry(text: str) -> dict:
    """Parse "Person, Company, contact, notes about the chat".

    One token  -> treated as the company name.
    Two tokens -> person, company.
    Three+     -> person, company, contact, notes (rest joined).
    Empty person or company raises FairError.
    """
    parts = [(p or "").strip() for p in (text or "").split(",")]
    parts = [p for p in parts if p != ""]
    if not parts:
        raise FairError("Empty company entry. Format: \"Name, Company, contact, notes\"")
    person, company, contact, notes = "", "", "", ""
    if len(parts) == 1:
        company = parts[0]
    else:
        person, company = parts[0], parts[1]
        if len(parts) > 2:
            contact = parts[2]
        if len(parts) > 3:
            notes = ", ".join(parts[3:])
    if not company:
        raise FairError("Could not find a company name in the entry.")
    return {"person": person, "company": company,
            "contact": contact, "notes": notes}


def add_company(fair_id: int, entry: str,
                path: str | Path | None = None) -> dict:
    """Log a company/person you talked to at a fair. Returns the entry."""
    rec = get_fair(fair_id, path)
    parsed = parse_company_entry(entry)
    parsed.update({
        "added": date.today().isoformat(),
        "followup_done": False,
        "followup_date": "",
    })
    rec.setdefault("companies", []).append(parsed)
    _save_one(rec, path)
    return parsed


def list_companies(fair_id: int, path: str | Path | None = None) -> list[dict]:
    return get_fair(fair_id, path).get("companies", [])


def mark_followup_done(fair_id: int, who: str,
                       path: str | Path | None = None) -> dict:
    """Mark a company's follow-up as done, matched by person or company name."""
    rec = get_fair(fair_id, path)
    needle = (who or "").strip().lower()
    if not needle:
        raise FairError("Give a person or company name to mark done.")
    for entry in rec.get("companies", []):
        if needle in entry.get("person", "").lower() \
                or needle in entry.get("company", "").lower():
            entry["followup_done"] = True
            entry["followup_date"] = date.today().isoformat()
            _save_one(rec, path)
            return entry
    raise FairError(f"No company entry matching '{who}' at fair #{fair_id}.")


def followups(fair_id: int | None = None,
              path: str | Path | None = None) -> list[dict]:
    """Everyone who still needs a follow-up.

    Returns entries shaped {"fair_id", "fair_name", "fair_date", "person",
    "company", "contact", "notes"} with followup_done == False.
    """
    out = []
    fairs = _load(path)
    if fair_id is not None:
        fairs = [f for f in fairs if f.get("id") == fair_id]
    for f in fairs:
        for e in f.get("companies", []):
            if e.get("followup_done"):
                continue
            out.append({
                "fair_id": f.get("id"),
                "fair_name": f.get("name", ""),
                "fair_date": f.get("date", ""),
                "person": e.get("person", ""),
                "company": e.get("company", ""),
                "contact": e.get("contact", ""),
                "notes": e.get("notes", ""),
            })
    return out


def suggested_action(entry: dict) -> str:
    """One-line suggested next action for a follow-up entry."""
    name = entry.get("person") or "the recruiter"
    where = f" at {entry['company']}" if entry.get("company") else ""
    met = f" at {entry['fair_name']}" if entry.get("fair_name") else ""
    contact = entry.get("contact") or "their career page"
    return (f"Email {name}{where} ({contact}) thanking them for the chat{met}; "
            f"mention {entry['notes'] or 'what you discussed'} and ask about next steps.")


def draft_followup(name: str, entry: dict, role: str = "") -> str:
    """Ready-to-use follow-up email draft.

    Uses the existing followup.check_in conventions; falls back to a plain
    template if the followup module is unavailable.
    """
    person = entry.get("person") or "there"
    company = entry.get("company") or "your team"
    role = role or entry.get("notes") or "roles we discussed"
    last_contact = entry.get("fair_date") or ""
    try:
        from candid import followup as F
        return F.check_in(name or "Your Name", person, role, company,
                          last_contact=last_contact or "", tone="warm")
    except Exception:
        return (
            f"Subject: Great meeting you at {entry.get('fair_name') or 'the career fair'}\n\n"
            f"Hi {person},\n\n"
            f"It was great chatting with you about {role} at {company}. "
            f"I'd love to stay in touch and learn more about next steps.\n\n"
            f"Best,\n{name or 'Your Name'}"
        )


def render_fairs(fairs: list[dict]) -> str:
    if not fairs:
        return ("No fairs logged yet. Add one with:\n"
                "  python -m candid fair add --name \"Fall Career Fair\" "
                "--date 2026-09-15 --school \"Rutgers\"")
    lines = [f"{'ID':<4}{'Fair':<30}{'Date':<12}School / companies"]
    for f in fairs:
        n = len(f.get("companies", []))
        lines.append(f"{f['id']:<4}{f['name'][:29]:<30}"
                     f"{f.get('date', ''):<12}{f.get('school', '')} ({n} companies)")
    return "\n".join(lines)


def render_companies(fair: dict) -> str:
    entries = fair.get("companies", [])
    if not entries:
        return (f"Fair #{fair['id']} \"{fair['name']}\" has no companies yet. "
                "Add one with:\n"
                f"  python -m candid fair companies --fair {fair['id']} "
                "--add \"Jane Smith, Stripe, jane@.., talked about new grad roles\"")
    lines = [f"Fair #{fair['id']} \"{fair['name']}\" — {len(entries)} conversation(s):"]
    for e in entries:
        who = e.get("person") or "(no name)"
        done = " [follow-up done]" if e.get("followup_done") else ""
        lines.append(f"  - {who} @ {e.get('company')}{done}")
        if e.get("contact"):
            lines.append(f"      contact: {e['contact']}")
        if e.get("notes"):
            lines.append(f"      notes: {e['notes']}")
    return "\n".join(lines)


def render_followups(entries: list[dict]) -> str:
    if not entries:
        return ("No pending follow-ups. Nice. "
                "Mark one done with:\n"
                "  python -m candid fair companies --fair <id> --done \"Jane Smith\"")
    lines = [f"{len(entries)} follow-up(s) pending:"]
    for i, e in enumerate(entries, 1):
        who = e.get("person") or e.get("company") or "(unknown)"
        lines.append(f"\n{i}. {who} — {e.get('fair_name', '')} ({e.get('fair_date', '')})")
        lines.append(f"   {suggested_action(e)}")
    lines.append("\nPrint a ready-to-use draft with: "
                 "python -m candid fair followup --draft <n>")
    return "\n".join(lines)
