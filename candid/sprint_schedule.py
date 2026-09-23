"""Weekly application sprint planner: templates, ICS export, daily suggestions.

Sprints live as a JSON list at ``config.DATA_DIR / "sprints.json"`` (git-ignored)
following the shared batch-29 sprint data contract:

    {"id": int, "week_start": "YYYY-MM-DD (Monday)", "title": str,
     "target_apps": int, "hours_budget": float,
     "targets": [{"company", "role", "jd_link", "priority", "status",
                  "batch", "tracker_id", "done_at"}],
     "time_blocks": [{"day", "start", "end", "kind", "label"}],
     "notes": [...], "status": "active|closed", "created_at": iso,
     "review": dict, "template": str}

This module owns its own small storage helpers; it does not import other
workers' modules. Sprint templates live at
``config.DATA_DIR / "sprint_templates.json"``.
"""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from candid import config as C


class SprintScheduleError(Exception):
    """Raised for invalid sprint-schedule operations."""


# --- constants ---------------------------------------------------------------
SPRINTS_FILE = "sprints.json"
TEMPLATES_FILE = "sprint_templates.json"

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
KINDS = ["research", "tailor", "apply", "followup", "prep"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
FULL_WEEKDAY = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
    "friday": "fri", "saturday": "sat", "sunday": "sun",
}

# Lower rank = worked first when assigning targets to blocks.
PRIORITY_RANK = {"urgent": 0, "high": 0, "medium": 1, "normal": 1, "low": 2}

#: Built-in templates: name -> (target_apps, hours_budget).
BUILT_IN_TEMPLATES: dict[str, tuple[int, float]] = {
    "steady-5": (5, 6.0),
    "aggressive-10": (10, 10.0),
    "light-3": (3, 3.0),
}

_BUILTIN_DEFAULT_BLOCKS: dict[str, list[dict]] = {
    "steady-5": [
        {"day": "mon", "start": "18:00", "end": "19:30", "kind": "research",
         "label": "Evening research"},
        {"day": "tue", "start": "18:00", "end": "19:30", "kind": "tailor",
         "label": "Evening tailoring"},
        {"day": "wed", "start": "18:00", "end": "19:30", "kind": "tailor",
         "label": "Evening tailoring"},
        {"day": "thu", "start": "18:00", "end": "19:30", "kind": "apply",
         "label": "Evening applications"},
    ],
    "aggressive-10": [
        {"day": "mon", "start": "18:00", "end": "20:00", "kind": "research",
         "label": "Evening research"},
        {"day": "tue", "start": "18:00", "end": "20:00", "kind": "tailor",
         "label": "Evening tailoring"},
        {"day": "wed", "start": "18:00", "end": "20:00", "kind": "tailor",
         "label": "Evening tailoring"},
        {"day": "thu", "start": "18:00", "end": "20:00", "kind": "apply",
         "label": "Evening applications"},
        {"day": "fri", "start": "18:00", "end": "20:00", "kind": "apply",
         "label": "Evening applications"},
    ],
    "light-3": [
        {"day": "tue", "start": "18:00", "end": "19:00", "kind": "research",
         "label": "Evening research"},
        {"day": "thu", "start": "18:00", "end": "19:00", "kind": "tailor",
         "label": "Evening tailoring"},
        {"day": "sat", "start": "10:00", "end": "11:00", "kind": "apply",
         "label": "Weekend applications"},
    ],
}


# --- storage helpers ---------------------------------------------------------
def _data_dir() -> Path:
    """Resolve the data dir, honoring CANDID_DATA_DIR at call time.

    Mirrors config._data_dir() but re-reads the env var on every call so
    tests can point at a tmp_path without reimporting.
    """
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _read_json(path: Path, what: str, default):
    if not path.exists():
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SprintScheduleError(f"{what} file {path} is not valid JSON: {exc}") from exc


def _write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _sprints_path() -> Path:
    return _data_dir() / SPRINTS_FILE


def _templates_path() -> Path:
    return _data_dir() / TEMPLATES_FILE


def _load_sprints() -> list[dict]:
    sprints = _read_json(_sprints_path(), "Sprints", [])
    if not isinstance(sprints, list):
        raise SprintScheduleError("sprints.json should contain a JSON list.")
    return sprints


def _save_sprints(sprints: list[dict]) -> Path:
    return _write_json(_sprints_path(), sprints)


def _load_templates() -> dict:
    templates = _read_json(_templates_path(), "Sprint templates", {})
    if not isinstance(templates, dict):
        raise SprintScheduleError("sprint_templates.json should contain a JSON object.")
    return templates


def _save_templates(templates: dict) -> Path:
    return _write_json(_templates_path(), templates)


def _find_sprint(sprints: list[dict], sprint_id: int) -> dict:
    for sp in sprints:
        if sp.get("id") == sprint_id:
            return sp
    raise SprintScheduleError(f"No sprint with id {sprint_id}.")


def _get_sprint(sprint_id: int) -> tuple[list[dict], dict]:
    """Return (sprints, sprint) so callers can mutate and save."""
    sprints = _load_sprints()
    return sprints, _find_sprint(sprints, sprint_id)


# --- validation --------------------------------------------------------------
def validate_blocks(blocks: list[dict]) -> list[dict]:
    """Validate time blocks. Returns the blocks unchanged.

    Raises SprintScheduleError when a block is not a dict, has an invalid
    day, a malformed start/end time, or end <= start.
    """
    if not isinstance(blocks, list):
        raise SprintScheduleError("Time blocks must be a list.")
    for i, b in enumerate(blocks):
        where = f"block #{i}"
        if not isinstance(b, dict):
            raise SprintScheduleError(f"{where}: must be an object.")
        day = str(b.get("day", "")).lower()
        if day not in WEEKDAYS:
            raise SprintScheduleError(
                f"{where}: invalid day {b.get('day')!r}. "
                f"Choose from: {', '.join(WEEKDAYS)}."
            )
        for field in ("start", "end"):
            val = b.get(field)
            if not isinstance(val, str) or not TIME_RE.match(val):
                raise SprintScheduleError(
                    f"{where}: invalid {field} {val!r}. Use HH:MM (24h)."
                )
        if b["end"] <= b["start"]:
            raise SprintScheduleError(
                f"{where}: end ({b['end']}) must be after start ({b['start']})."
            )
        kind = b.get("kind")
        if kind is not None and str(kind).lower() not in KINDS:
            raise SprintScheduleError(
                f"{where}: invalid kind {kind!r}. Choose from: {', '.join(KINDS)}."
            )
    return blocks


# --- templates ----------------------------------------------------------------
def save_template(name: str, target_apps: int, hours_budget: float,
                  default_blocks: list[dict] | None = None) -> dict:
    """Save (or overwrite) a user sprint template. Returns the stored template."""
    name = (name or "").strip()
    if not name:
        raise SprintScheduleError("Template name is required.")
    try:
        target_apps = int(target_apps)
        hours_budget = float(hours_budget)
    except (TypeError, ValueError) as exc:
        raise SprintScheduleError(
            f"target_apps and hours_budget must be numbers: {exc}"
        ) from exc
    if target_apps < 0 or hours_budget < 0:
        raise SprintScheduleError("target_apps and hours_budget must be non-negative.")
    blocks = copy.deepcopy(default_blocks) if default_blocks else []
    if blocks:
        validate_blocks(blocks)
    templates = _load_templates()
    templates[name] = {
        "target_apps": target_apps,
        "hours_budget": hours_budget,
        "default_blocks": blocks,
        "source": "user",
    }
    _save_templates(templates)
    return copy.deepcopy(templates[name])


def list_templates() -> dict:
    """All templates: built-ins merged with user templates.

    User templates override built-ins on name clash. Each entry carries a
    ``source`` key: "builtin" or "user".
    """
    merged: dict[str, dict] = {}
    for name, (apps, hours) in BUILT_IN_TEMPLATES.items():
        merged[name] = {
            "target_apps": apps,
            "hours_budget": hours,
            "default_blocks": copy.deepcopy(_BUILTIN_DEFAULT_BLOCKS[name]),
            "source": "builtin",
        }
    for name, tpl in _load_templates().items():
        merged[name] = {**copy.deepcopy(tpl), "source": "user"}
    return merged


def delete_template(name: str) -> None:
    """Delete a user template. Built-ins cannot be deleted."""
    name = (name or "").strip()
    templates = _load_templates()
    if name in templates:
        del templates[name]
        _save_templates(templates)
        return
    if name in BUILT_IN_TEMPLATES:
        raise SprintScheduleError(
            f"Cannot delete built-in template {name!r}."
        )
    raise SprintScheduleError(f"Unknown template {name!r}.")


def apply_template(sprint_id: int, name: str) -> dict:
    """Apply a template to a sprint.

    Sets target_apps/hours_budget and, when the template has default_blocks,
    replaces the sprint's time_blocks. Records sprint["template"] = name.
    Returns the updated sprint.
    """
    name = (name or "").strip()
    templates = list_templates()
    if name not in templates:
        raise SprintScheduleError(f"Unknown template {name!r}.")
    tpl = templates[name]
    sprints, sp = _get_sprint(sprint_id)
    sp["target_apps"] = tpl["target_apps"]
    sp["hours_budget"] = tpl["hours_budget"]
    if tpl.get("default_blocks"):
        blocks = copy.deepcopy(tpl["default_blocks"])
        validate_blocks(blocks)
        sp["time_blocks"] = blocks
    sp["template"] = name
    _save_sprints(sprints)
    return sp


# --- ICS export ---------------------------------------------------------------
def _fold_ics_line(line: str) -> str:
    """Fold one content line per RFC 5545 (75-octet limit, CRLF + space)."""
    parts = []
    rest = line
    while len(rest.encode("utf-8")) > 75:
        cut = 75
        while len(rest[:cut].encode("utf-8")) > 75:
            cut -= 1
        parts.append(rest[:cut])
        rest = " " + rest[cut:]
    parts.append(rest)
    return "\r\n".join(parts)


def _weekday_date(week_start: str, day: str) -> "datetime.date":
    try:
        monday = datetime.strptime(week_start, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SprintScheduleError(
            f"Sprint week_start {week_start!r} is not YYYY-MM-DD."
        ) from exc
    offset = WEEKDAYS.index(day)
    return monday + timedelta(days=offset)


def export_ics(sprint_id: int) -> str:
    """Export a sprint's time blocks as an iCalendar string (RFC 5545).

    Uses floating local times (no TZDB dependency). Each block becomes one
    VEVENT dated from the sprint's week_start (a Monday) plus the block's day.
    """
    _, sp = _get_sprint(sprint_id)
    blocks = sp.get("time_blocks") or []
    validate_blocks(blocks)
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//candid//sprint-schedule//EN",
    ]
    for b in blocks:
        day = str(b["day"]).lower()
        date = _weekday_date(sp.get("week_start", ""), day)
        stamp = date.strftime("%Y%m%d")
        kind = str(b.get("kind", "")).strip()
        label = str(b.get("label", "")).strip()
        summary = f"{kind.title()}: {label}" if label else kind.title() or "Sprint block"
        # Deterministic UID: re-exporting the same sprint updates events
        # instead of duplicating them on calendar import.
        uid = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"candid-sprint-{sprint_id}-{day}-{b['start']}-{b['end']}",
        )
        start = b["start"].replace(":", "")
        end = b["end"].replace(":", "")
        for content in (
            "BEGIN:VEVENT",
            f"UID:{uid}@candid",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{stamp}T{start}00",
            f"DTEND:{stamp}T{end}00",
            f"SUMMARY:{summary}",
            "END:VEVENT",
        ):
            lines.append(_fold_ics_line(content))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_ics(sprint_id: int, path: str | Path) -> Path:
    """Write export_ics(sprint_id) to path. Returns the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(export_ics(sprint_id), encoding="utf-8")
    return p


# --- daily suggestions ---------------------------------------------------------
def _resolve_day(day: str) -> str:
    d = (day or "").strip().lower()
    if d == "today":
        return WEEKDAYS[datetime.now().weekday()]
    if d in WEEKDAYS:
        return d
    if d in FULL_WEEKDAY:
        return FULL_WEEKDAY[d]
    raise SprintScheduleError(
        f"Unknown day {day!r}. Use 'today' or one of: {', '.join(WEEKDAYS)}."
    )


def _ranked_targets(targets: list[dict]) -> list[dict]:
    todo = [t for t in targets if t.get("status") == "todo"]
    # Stable sort: equal priorities keep their original order.
    return sorted(todo, key=lambda t: PRIORITY_RANK.get(str(t.get("priority", "")).lower(), 3))


def _task_for(block: dict, target: dict | None) -> str:
    kind = str(block.get("kind", "")).lower()
    label = str(block.get("label", "")).strip()
    company = (target or {}).get("company") or ""
    role = (target or {}).get("role") or ""
    who = f"{company} {role}".strip()
    if kind == "research":
        return f"Research: {who}" if who else "Research: pick a target company"
    if kind == "tailor":
        return f"Tailor resume for {company}" if company else "Tailor resume for next target"
    if kind == "apply":
        return f"Apply to {who}" if who else "Apply to next target"
    if kind == "followup":
        return f"Follow up with {company}" if company else "Follow up on recent applications"
    if kind == "prep":
        return f"Interview prep: {label}" if label else "Interview prep"
    return label or "Sprint block"


def suggest_day(sprint_id: int, day: str = "today") -> list[dict]:
    """Suggest ordered tasks for one weekday of the sprint.

    Remaining ``todo`` targets are sorted by priority (high first) and
    assigned to that day's time blocks round-robin. Returns a list of
    {"block": <block dict>, "task": <suggestion string>}.
    """
    _, sp = _get_sprint(sprint_id)
    key = _resolve_day(day)
    blocks = [b for b in (sp.get("time_blocks") or []) if str(b.get("day", "")).lower() == key]
    if not blocks:
        return []
    ranked = _ranked_targets(sp.get("targets") or [])
    suggestions = []
    for i, block in enumerate(blocks):
        target = ranked[i % len(ranked)] if ranked else None
        suggestions.append({"block": block, "task": _task_for(block, target)})
    return suggestions
