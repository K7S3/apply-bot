"""First-job checklist: a dated milestone timeline for new grads.

`checklist newgrad --graduation 2026-05-15` builds milestones anchored to
your graduation date and stores them in candid_data/checklist.json.
`checklist show` prints progress; `checklist check <item-id>` marks an
item done (use --undo to uncheck).

Dates are computed with plain month arithmetic (no paid APIs, no network).
"""

from __future__ import annotations

import calendar
import json
from datetime import date
from pathlib import Path

from candid import config as C


class ChecklistError(Exception):
    """Expected checklist failure (bad date, unknown item, no checklist)."""


# (item id, title, month offset from graduation, detail)
NEWGRAD_MILESTONES: list[tuple[str, str, int, str]] = [
    ("start-applying",
     "Start applying to new-grad roles", -9,
     "New-grad postings open ~9 months before graduation; apply early, "
     "batch weekly."),
    ("fall-recruiting",
     "Peak fall recruiting window", -7,
     "Career fairs and on-campus interviews peak; line up referrals now."),
    ("spring-recruiting",
     "Peak spring recruiting window", -4,
     "Second big wave of new-grad roles; re-apply to dream companies."),
    ("offer-decisions",
     "Offer decisions and deadlines", -1,
     "Compare offers, negotiate, and accept before exploding deadlines hit."),
    ("background-check",
     "Background check and paperwork", 0,
     "Complete the background check, I-9, and onboarding forms promptly."),
    ("relocation",
     "Relocation planning", 1,
     "Lock housing, plan the move, and sort out any relocation benefits."),
    ("first-day",
     "First day prep", 2,
     "Confirm start date, laptop, and team; rest up before day one."),
]


def shift_months(d: date, months: int) -> date:
    """Add (or subtract) whole months, clamping the day to month length."""
    total = d.year * 12 + (d.month - 1) + months
    y, m = divmod(total, 12)
    last = calendar.monthrange(y, m + 1)[1]
    return date(y, m + 1, min(d.day, last))


def build_timeline(graduation: date) -> list[dict]:
    """Build the milestone list anchored to a graduation date."""
    items = []
    for item_id, title, offset, detail in NEWGRAD_MILESTONES:
        items.append({
            "id": item_id,
            "title": title,
            "due": shift_months(graduation, offset).isoformat(),
            "detail": detail,
            "done": False,
        })
    return items


def _path(path: str | Path | None = None) -> Path:
    return Path(path) if path else C.CHECKLIST_PATH


def generate(graduation_iso: str, path: str | Path | None = None) -> dict:
    """Create (or regenerate) the checklist for a graduation date."""
    try:
        graduation = date.fromisoformat(graduation_iso)
    except ValueError:
        raise ChecklistError(
            f"Bad graduation date {graduation_iso!r}; use YYYY-MM-DD, "
            "e.g. --graduation 2026-05-15") from None
    state = {
        "graduation": graduation.isoformat(),
        "kind": "newgrad",
        "items": build_timeline(graduation),
    }
    save(state, path)
    return state


def load(path: str | Path | None = None) -> dict | None:
    """Load the stored checklist, or None if none exists yet."""
    p = _path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChecklistError(f"Checklist file {p} is not valid JSON: {exc}") from None


def save(state: dict, path: str | Path | None = None) -> Path:
    p = _path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return p


def _require_state(path: str | Path | None = None) -> dict:
    state = load(path)
    if state is None:
        raise ChecklistError(
            "No checklist yet. Create one first:\n"
            "    python -m candid checklist newgrad --graduation YYYY-MM-DD")
    return state


def set_done(item_id: str, done: bool = True,
             path: str | Path | None = None) -> dict:
    """Mark an item done (or not done with done=False); persists the change."""
    state = _require_state(path)
    for item in state["items"]:
        if item["id"] == item_id:
            item["done"] = done
            save(state, path)
            return state
    known = ", ".join(i["id"] for i in state["items"])
    raise ChecklistError(f"Unknown item {item_id!r}. Known ids: {known}")


def progress(state: dict) -> tuple[int, int]:
    """(done count, total count)."""
    items = state.get("items", [])
    return sum(1 for i in items if i.get("done")), len(items)


def render(state: dict, today: date | None = None) -> str:
    """Human-readable checklist with progress."""
    today = today or date.today()
    done, total = progress(state)
    lines = [
        f"First-job checklist (graduation {state.get('graduation', '?')})",
        f"Progress: {done}/{total} done",
        "",
    ]
    for item in state.get("items", []):
        box = "[x]" if item.get("done") else "[ ]"
        due = item.get("due", "?")
        flag = ""
        if not item.get("done"):
            try:
                if date.fromisoformat(due) < today:
                    flag = "  <-- OVERDUE"
            except ValueError:
                pass
        lines.append(f"{box} {item['id']:<18} due {due}{flag}")
        lines.append(f"     {item['title']}")
    return "\n".join(lines)


def checklist_nudges(state: dict | None = None,
                     today: date | None = None) -> list[dict]:
    """Nudges for overdue checklist items. Never raises on bad data."""
    try:
        today = today or date.today()
        state = state if state is not None else load()
        if not state:
            return []
        nudges = []
        for item in state.get("items", []):
            if item.get("done"):
                continue
            try:
                due = date.fromisoformat(item.get("due", ""))
            except ValueError:
                continue
            if due < today:
                nudges.append({
                    "kind": "checklist_overdue",
                    "message": (f"Checklist item overdue: {item['title']} "
                                f"(was due {item['due']})."),
                    "action": "Do it, then mark it done",
                    "command": f"python -m candid checklist check {item['id']}",
                })
        return nudges
    except Exception:
        return []
