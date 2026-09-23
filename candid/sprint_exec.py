"""Sprint execution: log applications, daily check-ins, and pace progress.

Works on the shared sprints.json list at DATA_DIR / "sprints.json" (see the
shared sprint data contract). Storage helpers are self-contained here so this
module does not depend on candid.sprint (owned by another worker).
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from candid import config as C


class SprintExecError(Exception):
    """Raised for invalid sprint execution operations."""


PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _data_dir() -> Path:
    """Resolve the data dir at call time so CANDID_DATA_DIR overrides work."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _sprints_path() -> Path:
    return _data_dir() / "sprints.json"


def _load_sprints() -> list[dict]:
    p = _sprints_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SprintExecError(f"Sprints file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise SprintExecError(f"Sprints file {p} should contain a JSON list.")
    return data


def _save_sprints(sprints: list[dict]) -> Path:
    p = _sprints_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sprints, indent=2), encoding="utf-8")
    return p


def _get_sprint(sprints: list[dict], sprint_id: int) -> dict:
    sprint = next((s for s in sprints if s.get("id") == sprint_id), None)
    if sprint is None:
        raise SprintExecError(f"No sprint with id {sprint_id}.")
    return sprint


def _find_target(sprint: dict, company: str, role: str) -> dict | None:
    """Find a target by case-insensitive company+role match."""
    co, ro = company.strip().lower(), role.strip().lower()
    return next(
        (
            t
            for t in sprint.get("targets", [])
            if t.get("company", "").strip().lower() == co
            and t.get("role", "").strip().lower() == ro
        ),
        None,
    )


def _require_target(sprint: dict, sprint_id: int, company: str, role: str) -> dict:
    target = _find_target(sprint, company, role)
    if target is None:
        raise SprintExecError(
            f"No target for {company!r} / {role!r} in sprint {sprint_id}. "
            "Add the target to the sprint first, then log the application."
        )
    return target


def _verify_tracker_id(tracker_id: int) -> None:
    """Check a tracker id exists, importing candid.tracker lazily."""
    from candid import tracker  # noqa: PLC0415 -- lazy import by design

    tracker_path = _data_dir() / "tracker.json"
    known = {a.get("id") for a in tracker.list_apps(path=tracker_path)}
    if tracker_id not in known:
        raise SprintExecError(
            f"No tracker entry with id {tracker_id}. "
            "Use `track list` to see valid ids."
        )


def log_application(
    sprint_id: int,
    company: str,
    role: str,
    tracker_id: int | None = None,
    applied_at: str | None = None,
) -> dict:
    """Mark a sprint target as done (application submitted).

    Case-insensitive match on company+role. Sets ``done_at`` (defaults to
    today). If ``tracker_id`` is given, it must exist in the application
    tracker and is stored on the target. Raises SprintExecError when there
    is no matching target or the tracker id is unknown.
    """
    sprints = _load_sprints()
    sprint = _get_sprint(sprints, sprint_id)
    target = _require_target(sprint, sprint_id, company, role)
    if tracker_id is not None:
        _verify_tracker_id(tracker_id)
        target["tracker_id"] = tracker_id
    target["status"] = "done"
    target["done_at"] = applied_at or date.today().isoformat()
    _save_sprints(sprints)
    return target


def unlog_application(sprint_id: int, company: str, role: str) -> dict:
    """Revert a logged application: target back to todo, clears done_at/tracker_id."""
    sprints = _load_sprints()
    sprint = _get_sprint(sprints, sprint_id)
    target = _require_target(sprint, sprint_id, company, role)
    target["status"] = "todo"
    target["done_at"] = None
    target["tracker_id"] = None
    _save_sprints(sprints)
    return target


def daily_checkin(sprint_id: int, text: str, day: str | None = None) -> list[dict]:
    """Append a note for the day. One note entry per day max: if an entry
    for ``day`` (default today) already exists, the text is appended to it."""
    sprints = _load_sprints()
    sprint = _get_sprint(sprints, sprint_id)
    day_iso = day or date.today().isoformat()
    notes = sprint.setdefault("notes", [])
    existing = next((n for n in notes if n.get("date") == day_iso), None)
    if existing is None:
        notes.append({"date": day_iso, "text": text})
    elif existing.get("text"):
        existing["text"] = existing["text"] + "\n" + text
    else:
        existing["text"] = text
    _save_sprints(sprints)
    return notes


def remaining_targets(sprint_id: int, priority: str | None = None) -> list[dict]:
    """Todo targets, optionally filtered by priority, sorted high->medium->low."""
    if priority is not None and priority not in PRIORITY_ORDER:
        raise SprintExecError(
            f"Unknown priority {priority!r}. Choose from: high, medium, low."
        )
    sprints = _load_sprints()
    sprint = _get_sprint(sprints, sprint_id)
    todos = [t for t in sprint.get("targets", []) if t.get("status") == "todo"]
    if priority is not None:
        todos = [t for t in todos if t.get("priority") == priority]
    return sorted(todos, key=lambda t: PRIORITY_ORDER.get(t.get("priority"), 99))


def progress(sprint_id: int, today: str | date | None = None) -> dict:
    """Sprint pace report.

    ``expected_by_now`` = target_apps * (elapsed days in sprint week / 7),
    with elapsed clamped to 0..7. ``on_pace`` is True when logged
    applications meet or exceed the expected count.
    """
    sprints = _load_sprints()
    sprint = _get_sprint(sprints, sprint_id)
    targets = sprint.get("targets", [])
    done = sum(1 for t in targets if t.get("status") == "done")
    total = len(targets)
    target_apps = sprint.get("target_apps", 0)
    today_d = today if isinstance(today, date) else (
        date.fromisoformat(today) if today else date.today()
    )
    try:
        week_start = date.fromisoformat(sprint["week_start"])
    except (KeyError, ValueError):
        week_start = today_d
    elapsed = max(0, min(7, (today_d - week_start).days))
    expected = target_apps * (elapsed / 7)
    return {
        "done": done,
        "total_targets": total,
        "target_apps": target_apps,
        "pct_of_targets": round(done / total * 100, 1) if total else 0.0,
        "expected_by_now": expected,
        "on_pace": done >= expected,
        "remaining": sorted(
            [t for t in targets if t.get("status") == "todo"],
            key=lambda t: PRIORITY_ORDER.get(t.get("priority"), 99),
        ),
    }


def link_tracker(sprint_id: int, company: str, role: str, tracker_id: int) -> dict:
    """Attach an existing tracker id to a target without marking it done."""
    _verify_tracker_id(tracker_id)
    sprints = _load_sprints()
    sprint = _get_sprint(sprints, sprint_id)
    target = _require_target(sprint, sprint_id, company, role)
    target["tracker_id"] = tracker_id
    _save_sprints(sprints)
    return target
