"""Pre-interview logistics checklists.

Builds a round-type-specific logistics checklist (virtual, onsite, or
phone), stores per-interview state as JSON under
``candid_data/rituals/<ritual_id>/logistics.json``, and lets the user
check items off.

Programmatic use (this is what the CLI layer calls via lazy imports)::

    from candid import ritual_logistics as RL
    data = RL.build_logistics("virtual", "Acme", "Data Scientist", "2026-09-25")
    RL.save_logistics(data)
    print(RL.render_logistics(data))
    RL.check_item(data["ritual_id"], 3)

Checklist content is generic advice only; nothing here is invented about
the user's own experience.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

from candid import config as _config


class RitualError(Exception):
    """Raised for bad input or missing ritual state."""


ROUND_TYPES = ("virtual", "onsite", "phone")

# --- per-round-type checklist templates --------------------------------------
# Each entry is (label, detail). Content is generic interview advice.

_VIRTUAL_ITEMS = [
    ("Join link saved and easy to find",
     "Save the video-call link somewhere you can open it in one click; "
     "test that it loads."),
    ("Backup device ready",
     "Phone or tablet charged, logged in, and able to join the call if "
     "your laptop fails."),
    ("Charger plugged in or nearby",
     "Keep the laptop charger within reach for the whole session."),
    ("Quiet, private room secured",
     "A room with a door you can close; tell housemates you must not be "
     "disturbed."),
    ("Camera and microphone tested",
     "Run a quick test call; check lighting, framing, and audio levels."),
    ("Time zone confirmed",
     "Confirm the interview time in your local time zone against the invite."),
    ("Join 10 minutes early",
     "Join the call 10 minutes before start to settle in and absorb any "
     "tech hiccups."),
]

_ONSITE_ITEMS = [
    ("Office address confirmed",
     "Confirm the building address, floor, and suite from the invite."),
    ("Arrival buffer planned (30 min early)",
     "Plan to arrive about 30 minutes early; pad for traffic or transit "
     "delays."),
    ("ID and documents packed",
     "Photo ID plus anything the recruiter asked for (forms, references)."),
    ("Printed resume copies packed",
     "Bring 3-5 clean printed copies of your resume."),
    ("Dress code decided",
     "Pick your outfit the night before; match the company's dress code."),
    ("Parking or transit plan set",
     "Know where to park or which stop to use, and the walking route in."),
    ("Contact person details saved",
     "Name and phone number of your contact; know who to ask for at "
     "reception."),
]

_PHONE_ITEMS = [
    ("Quiet room secured",
     "Somewhere private with good cell reception or a landline."),
    ("Phone fully charged",
     "Charge to 100%; keep a charger nearby for long rounds."),
    ("Notes and resume nearby",
     "Resume, role notes, and questions for them on paper or screen."),
    ("Interviewer number confirmed",
     "Confirm who calls whom, the number, and the exact time."),
    ("Call plan clear",
     "Know the plan if the call drops: who redials, and any backup number."),
]


def _checklist_for(round_type: str) -> list[tuple[str, str]]:
    if round_type == "virtual":
        return list(_VIRTUAL_ITEMS)
    if round_type == "onsite":
        return list(_ONSITE_ITEMS)
    if round_type == "phone":
        return list(_PHONE_ITEMS)
    raise RitualError(
        f"Unknown round type {round_type!r}; expected one of: "
        + ", ".join(ROUND_TYPES)
    )


# --- helpers -----------------------------------------------------------------

def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise RitualError(f"Cannot build a ritual id from {text!r}")
    return slug


def ritual_id_for(company: str, role: str, date_str: str) -> str:
    """Default ritual id: slug of ``company-role-date``."""
    return "-".join((_slug(company), _slug(role), _slug(date_str)))


def _validate_inputs(round_type: str, company: str, role: str,
                     date_value: str | date | datetime) -> tuple[str, str, str, str]:
    rt = (round_type or "").strip().lower()
    if rt not in ROUND_TYPES:
        raise RitualError(
            f"Unknown round type {round_type!r}; expected one of: "
            + ", ".join(ROUND_TYPES)
        )
    company = (company or "").strip()
    role = (role or "").strip()
    if not company:
        raise RitualError("company is required")
    if not role:
        raise RitualError("role is required")
    if isinstance(date_value, datetime):
        date_str = date_value.date().isoformat()
    elif isinstance(date_value, date):
        date_str = date_value.isoformat()
    else:
        date_str = (date_value or "").strip()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise RitualError(
                f"Bad date {date_value!r}; expected YYYY-MM-DD"
            ) from None
    return rt, company, role, date_str


def _data_dir() -> Path:
    """Ritual storage root, resolved at call time.

    Honors CANDID_DATA_DIR (used by tests); falls back to the project's
    candid_data directory.
    """
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return _config.PROJECT_ROOT / "candid_data"


def _ritual_path(ritual_id: str) -> Path:
    return _data_dir() / "rituals" / ritual_id / "logistics.json"


# --- core API -----------------------------------------------------------------

def build_logistics(round_type: str, company: str, role: str,
                    date: str | date | datetime,
                    ritual_id: str | None = None) -> dict:
    """Build a logistics checklist dict for one interview.

    ``ritual_id`` defaults to a slug of ``company-role-date``; pass an
    explicit id to override (matches the ``--ritual-id`` CLI flag).
    """
    rt, company, role, date_str = _validate_inputs(round_type, company, role, date)
    if ritual_id is not None:
        ritual_id = _slug(str(ritual_id))
    else:
        ritual_id = ritual_id_for(company, role, date_str)
    items = [
        {"n": i + 1, "label": label, "detail": detail, "done": False}
        for i, (label, detail) in enumerate(_checklist_for(rt))
    ]
    return {
        "ritual_id": ritual_id,
        "company": company,
        "role": role,
        "date": date_str,
        "round_type": rt,
        "items": items,
    }


def save_logistics(data: dict) -> Path:
    """Write checklist state to candid_data/rituals/<id>/logistics.json."""
    ritual_id = data.get("ritual_id")
    if not ritual_id:
        raise RitualError("Checklist data has no ritual_id; cannot save")
    path = _ritual_path(ritual_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def load_logistics(ritual_id: str) -> dict:
    """Load checklist state; raises RitualError if it does not exist."""
    ritual_id = _slug(str(ritual_id))
    path = _ritual_path(ritual_id)
    if not path.exists():
        raise RitualError(
            f"No logistics checklist found for ritual id {ritual_id!r}; "
            "build one first with: ritual logistics --company X --role Y "
            "--date YYYY-MM-DD --round-type virtual|onsite|phone"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def check_item(ritual_id: str, n: int, done: bool = True) -> dict:
    """Mark checklist item ``n`` (1-based) done (or not) and persist.

    Returns the updated checklist dict.
    """
    data = load_logistics(ritual_id)
    items = data.get("items", [])
    try:
        idx = int(n) - 1
    except (TypeError, ValueError):
        raise RitualError(f"Item number must be an integer, got {n!r}") from None
    if not 0 <= idx < len(items):
        raise RitualError(
            f"Item {n} out of range; checklist has {len(items)} items"
        )
    items[idx]["done"] = bool(done)
    save_logistics(data)
    return data


def render_logistics(data: dict) -> str:
    """Printable plain-ASCII summary of the checklist."""
    items = data.get("items", [])
    done = sum(1 for it in items if it.get("done"))
    lines = [
        "INTERVIEW LOGISTICS CHECKLIST",
        f"Company   : {data.get('company', '?')}",
        f"Role      : {data.get('role', '?')}",
        f"Date      : {data.get('date', '?')}",
        f"Round     : {data.get('round_type', '?')}",
        f"Ritual id : {data.get('ritual_id', '?')}",
        f"Progress  : {done}/{len(items)} checked",
        "-" * 60,
    ]
    for it in items:
        box = "[x]" if it.get("done") else "[ ]"
        lines.append(f"{box} {it['n']:>2}. {it['label']}")
        if it.get("detail"):
            lines.append(f"         {it['detail']}")
    lines.append("-" * 60)
    lines.append("Check an item off with: ritual logistics check <n> "
                 "--ritual-id " + str(data.get("ritual_id", "")))
    return "\n".join(lines)


# --- standalone CLI (the wired CLI lives elsewhere; this is a fallback) ------

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "check":
        p = argparse.ArgumentParser(prog="ritual logistics check")
        p.add_argument("n", type=int, help="1-based item number to check off")
        p.add_argument("--ritual-id", required=True)
        p.add_argument("--uncheck", action="store_true",
                       help="Mark the item not done instead")
        a = p.parse_args(argv[1:])
        data = check_item(a.ritual_id, a.n, done=not a.uncheck)
        print(render_logistics(data))
        return 0
    p = argparse.ArgumentParser(prog="ritual logistics")
    p.add_argument("--company", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--round-type", required=True,
                   choices=list(ROUND_TYPES))
    p.add_argument("--ritual-id", default=None,
                   help="Override the default company-role-date id")
    a = p.parse_args(argv)
    try:
        data = build_logistics(a.round_type, a.company, a.role, a.date,
                               ritual_id=a.ritual_id)
    except RitualError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    path = save_logistics(data)
    print(render_logistics(data))
    print(f"\nSaved to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
