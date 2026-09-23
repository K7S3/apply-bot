"""Feature 1 - network contact book.

A lightweight CRM: who you met, where, what they do, and what you talked
about. Stored as JSON under ``candid_data/network/contacts.json``.
"""

from __future__ import annotations

from candid.network import _store as S

_STORE = "contacts.json"
_EMPTY = {"next_id": 1, "contacts": []}


def _db() -> dict:
    return S.load(_STORE, _EMPTY)


def _persist(db: dict) -> None:
    S.save(_STORE, db)


def add_contact(name: str, role: str = "", company: str = "",
                email: str = "", met_at: str | None = None,
                met_at_event: str = "", notes: str = "",
                tags: list[str] | None = None, value: int = 3) -> dict:
    """Add a contact. ``value`` is 1-5: how valuable keeping this warm is."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Contact name is required.")
    if not 1 <= int(value) <= 5:
        raise ValueError("value must be between 1 and 5.")
    db = _db()
    rec = {
        "id": db["next_id"],
        "name": name,
        "role": role.strip(),
        "company": company.strip(),
        "email": email.strip(),
        "met_at": S.parse_date(met_at, "met_at"),
        "met_at_event": met_at_event.strip(),
        "notes": notes.strip(),
        "tags": [t.strip().lower() for t in (tags or []) if t.strip()],
        "value": int(value),
        "created_at": S.today_iso(),
    }
    db["contacts"].append(rec)
    db["next_id"] += 1
    _persist(db)
    return rec


def get_contact(contact_id: int) -> dict:
    for c in _db()["contacts"]:
        if c["id"] == int(contact_id):
            return c
    raise ValueError(f"No contact with id {contact_id}. "
                     f"Run `candid network contacts` to list them.")


def list_contacts() -> list[dict]:
    return sorted(_db()["contacts"], key=lambda c: c["name"].lower())


def search_contacts(query: str) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return list_contacts()
    hits = []
    for c in _db()["contacts"]:
        hay = " ".join([c["name"], c["role"], c["company"],
                        c["met_at_event"], c["notes"], " ".join(c["tags"])])
        if q in hay.lower():
            hits.append(c)
    return hits


def update_contact(contact_id: int, **fields) -> dict:
    allowed = {"name", "role", "company", "email", "met_at", "met_at_event",
               "notes", "tags", "value"}
    db = _db()
    for c in db["contacts"]:
        if c["id"] == int(contact_id):
            for k, v in fields.items():
                if k not in allowed:
                    raise ValueError(f"Cannot update field '{k}'.")
                if k == "met_at":
                    v = S.parse_date(v, "met_at")
                if k == "value" and not 1 <= int(v) <= 5:
                    raise ValueError("value must be between 1 and 5.")
                if k == "tags" and isinstance(v, list):
                    v = [t.strip().lower() for t in v if str(t).strip()]
                c[k] = v
            _persist(db)
            return c
    raise ValueError(f"No contact with id {contact_id}.")


def remove_contact(contact_id: int) -> dict:
    db = _db()
    for i, c in enumerate(db["contacts"]):
        if c["id"] == int(contact_id):
            removed = db["contacts"].pop(i)
            _persist(db)
            return removed
    raise ValueError(f"No contact with id {contact_id}.")


def render_contacts(contacts: list[dict]) -> str:
    if not contacts:
        return "No contacts yet. Add one with `candid network add-contact --name \"...\"`."
    lines = []
    for c in contacts:
        who = c["name"]
        if c["role"] or c["company"]:
            who += f" ({c['role']}{', ' if c['role'] and c['company'] else ''}{c['company']})"
        lines.append(f"#{c['id']}  {who}  [value {c['value']}/5]"
                     + (f"  met {c['met_at']} @ {c['met_at_event']}" if c["met_at_event"] else ""))
    return "\n".join(lines)
