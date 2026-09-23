"""Weekly application goals: set a target, track progress, count streaks.

Goals live in candid_data/goals.json as {"kind", "target", "created"}.
Only "applications_per_week" goals exist for now.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from candid import config as C
from candid import tracker as T


class GoalsError(Exception):
    """Raised for invalid goal operations."""


SUPPORTED_KINDS = ("applications_per_week",)

log = C.get_logger("goals")


def _goals_path(path: str | Path | None = None) -> Path:
    return Path(path) if path else C.DATA_DIR / "goals.json"


def set_goal(kind: str = "applications_per_week", target: int = 5,
             *, path: str | Path | None = None) -> dict:
    """Set (or replace) the weekly applications goal. Returns the goal dict."""
    if kind not in SUPPORTED_KINDS:
        raise GoalsError(
            f"Unknown goal kind {kind!r}. Only 'applications_per_week' is "
            "supported for now. Next: run `python -m candid goals set --help`")
    if isinstance(target, bool) or not isinstance(target, int) or target < 1:
        raise GoalsError(
            f"Invalid target {target!r}. It must be a whole number of at "
            "least 1. Next: run `python -m candid goals set --help`")
    goal = {"kind": kind, "target": target, "created": date.today().isoformat()}
    p = _goals_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(goal, indent=2), encoding="utf-8")
    return goal


def _load_goal(path: str | Path | None = None) -> dict:
    p = _goals_path(path)
    if not p.exists():
        raise GoalsError(
            "No goal set yet. "
            "Next: run `python -m candid goals set --target 5`")
    try:
        goal = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GoalsError(
            f"Goals file {p} is not valid JSON. Delete it and set a fresh "
            "goal. Next: run `python -m candid goals set --target 5`") from exc
    if not isinstance(goal, dict) or "target" not in goal:
        raise GoalsError(
            f"Goals file {p} is malformed. Delete it and set a fresh goal. "
            "Next: run `python -m candid goals set --target 5`")
    return goal


def _added_in_range(apps: list[dict], start: date, end: date) -> int:
    """Count apps with date_added in [start, end]; skips malformed dates."""
    count = 0
    for a in apps:
        try:
            day = date.fromisoformat(str(a.get("date_added", "")))
        except ValueError:
            continue
        if start <= day <= end:
            count += 1
    return count


def goal_status(*, path: str | Path | None = None,
                today: date | None = None) -> dict:
    """Current goal progress.

    Returns {"kind", "target", "current", "remaining", "met", "streak_weeks"}.
    "current" counts applications added in the current Mon-Sun week;
    "streak_weeks" counts consecutive past weeks (not the current partial
    week) that met the target.
    """
    goal = _load_goal(path)
    target = goal["target"]
    if isinstance(target, bool) or not isinstance(target, int) or target < 1:
        raise GoalsError(
            f"Stored goal target {target!r} is invalid. Set a fresh goal. "
            "Next: run `python -m candid goals set --target 5`")
    apps = T._load()
    now = today or date.today()
    monday = now - timedelta(days=now.weekday())
    current = _added_in_range(apps, monday, now)
    # consecutive past weeks (excluding the current partial week)
    streak = 0
    prev_monday = monday - timedelta(weeks=1)
    while True:
        week_end = prev_monday + timedelta(days=6)
        count = _added_in_range(apps, prev_monday, week_end)
        if count >= target:
            streak += 1
            prev_monday -= timedelta(weeks=1)
        else:
            break
    return {
        "kind": goal.get("kind", "applications_per_week"),
        "target": target,
        "current": current,
        "remaining": max(0, target - current),
        "met": current >= target,
        "streak_weeks": streak,
    }


def render_goals(status: dict) -> str:
    """Render a goal_status dict as a human-readable card."""
    target = status["target"]
    current = status["current"]
    width = 12
    filled = min(width, round(width * current / target)) if target else width
    bar = "#" * filled + "-" * (width - filled)
    lines = [
        f"Goal: {target} applications/week",
        f"This week: {current}/{target} [{bar}]",
    ]
    if status["met"]:
        lines.append("Goal met. Keep the streak going.")
    else:
        lines.append(f"{status['remaining']} more to hit this week's goal.")
    streak = status["streak_weeks"]
    lines.append(f"Streak: {streak} week{'s' if streak != 1 else ''} in a row "
                 "(not counting this week).")
    return "\n".join(lines)
