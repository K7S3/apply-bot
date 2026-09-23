"""Feature 3 - touchpoint logging.

Every interaction with a contact (email, call, coffee, intro made, ...) is
a touchpoint. Logging them is what keeps warmth scores honest.
"""

from __future__ import annotations

from datetime import date

from candid.network import _store as S
from candid.network import contacts as CT

_STORE = "touchpoints.json"
_EMPTY = {"next_id": 1, "touchpoints": []}

KINDS = ["email", "call", "coffee", "event", "note",
         "value_add", "intro_made", "congrats"]

# How much warmth each kind of touch is worth (see warmth.py).
KIND_WEIGHTS = {
    "email": 1.0,
    "call": 1.5,
    "coffee": 2.0,
    "event": 1.5,
    "note": 0.75,
    "value_add": 1.75,
    "intro_made": 2.5,
    "congrats": 0.5,
}


def _db() -> dict:
    return S.load(_STORE, _EMPTY)


def _persist(db: dict) -> None:
    S.save(_STORE, db)


def log_touch(contact_id: int, kind: str, notes: str = "",
              happened_on: str | None = None) -> dict:
    """Log a touchpoint with a contact."""
    CT.get_contact(contact_id)  # validates the contact exists
    if kind not in KINDS:
        raise ValueError(f"Unknown touch kind '{kind}'. Choose from: "
                         f"{', '.join(KINDS)}.")
    db = _db()
    rec = {
        "id": db["next_id"],
        "contact_id": int(contact_id),
        "kind": kind,
        "notes": (notes or "").strip(),
        "happened_on": S.parse_date(happened_on, "happened_on"),
        "logged_at": S.today_iso(),
    }
    db["touchpoints"].append(rec)
    db["next_id"] += 1
    _persist(db)
    return rec


def touchpoints_for(contact_id: int) -> list[dict]:
    touches = [t for t in _db()["touchpoints"]
               if t["contact_id"] == int(contact_id)]
    return sorted(touches, key=lambda t: t["happened_on"], reverse=True)


def all_touchpoints() -> list[dict]:
    return sorted(_db()["touchpoints"],
                  key=lambda t: t["happened_on"], reverse=True)


def last_touch_date(contact_id: int) -> str | None:
    touches = touchpoints_for(contact_id)
    return touches[0]["happened_on"] if touches else None


def days_since_last_touch(contact_id: int,
                          today: date | None = None) -> int | None:
    last = last_touch_date(contact_id)
    if last is None:
        return None
    today = today or date.today()
    return (today - date.fromisoformat(last)).days


def render_touchpoints(contact_id: int) -> str:
    contact = CT.get_contact(contact_id)
    touches = touchpoints_for(contact_id)
    if not touches:
        return (f"No touchpoints logged for {contact['name']} yet. "
                f"Log one with `candid network log-touch {contact_id} --kind email`.")
    lines = [f"Touchpoints for {contact['name']} ({len(touches)}):"]
    for t in touches:
        extra = f" - {t['notes']}" if t["notes"] else ""
        lines.append(f"  {t['happened_on']}  {t['kind']}{extra}")
    return "\n".join(lines)
