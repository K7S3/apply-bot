"""Sprint review and continuity: close out a week, carry over todos, streaks.

Weekly sprints live as a JSON list at candid_data/sprints.json (git-ignored).
This module is self-contained: it owns its own sprints.json storage
helpers and does not import the other sprint modules (worker A/B own
candid/sprint.py and candid/sprint_exec.py).

Shared sprint data contract (sprint dict):
  {"id": int, "week_start": "YYYY-MM-DD (Monday)", "title": str,
   "target_apps": int, "hours_budget": float,
   "targets": [{"company": str, "role": str, "jd_link": str,
                "priority": str, "status": "todo|done", "batch": str,
                "tracker_id": int|None, "done_at": str|None}],
   "time_blocks": [...], "notes": [...], "status": "active|closed",
   "created_at": iso, "review": dict, "template": str}

Note: the contract draft lists "target_apps" twice (str and int); this
module treats it as the integer number of applications targeted for the
week, coercing defensively.

Review dict (stored in sprint["review"] by review_sprint):
  {"targets_done": int, "targets_total": int, "target_apps": int,
   "hit_target": bool, "completion_pct": float,
   "by_priority": {prio: {"done": int, "total": int}, ...},
   "by_batch": {batch: {"done": int, "total": int}, ...},
   "notes_count": int, "generated_at": iso,
   "tracker_outcomes": {status: count, ...}  # from linked tracker entries
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from candid import config as C


class SprintReviewError(Exception):
    """Raised for invalid sprint-review operations."""


# --- storage -----------------------------------------------------------------

def _sprints_path() -> Path:
    """sprints.json location; reads the env override per call (test-friendly)."""
    return C._data_dir() / "sprints.json"


def load_sprints() -> list[dict]:
    """Load the sprint list; missing file means no sprints yet."""
    p = _sprints_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SprintReviewError(f"Sprints file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise SprintReviewError(f"Sprints file {p} should contain a JSON list.")
    return data


def save_sprints(sprints: list[dict]) -> Path:
    """Persist the sprint list. Returns the path written."""
    p = _sprints_path()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sprints, indent=2), encoding="utf-8")
    return p


def get_sprint(sprint_id: int, sprints: list[dict] | None = None) -> dict:
    """Return the sprint with the given id, or raise SprintReviewError."""
    for s in sprints if sprints is not None else load_sprints():
        if s.get("id") == sprint_id:
            return s
    raise SprintReviewError(f"No sprint with id {sprint_id}.")


def _next_id(sprints: list[dict]) -> int:
    return max((s.get("id", 0) for s in sprints), default=0) + 1


# --- helpers -----------------------------------------------------------------

def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise SprintReviewError(f"Bad date '{value}': expected YYYY-MM-DD.") from exc


def _snap_to_monday(d: date) -> date:
    """Snap any date back to the Monday of its week."""
    return d - timedelta(days=d.weekday())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _target_apps_int(sprint: dict) -> int:
    try:
        return int(sprint.get("target_apps") or 0)
    except (TypeError, ValueError):
        return 0


def _tracker_outcomes(targets: list[dict]) -> dict:
    """Count current tracker statuses for targets that link a tracker_id.

    Lazy-imports candid.tracker and skips anything it cannot resolve -
    a missing tracker file, unknown ids, or a broken entry are all fine.
    """
    counts: dict[str, int] = {}
    try:
        from candid import tracker as T
        apps = T.list_apps()
    except Exception:
        return counts
    by_id = {a.get("id"): a for a in apps}
    for t in targets:
        rec = by_id.get(t.get("tracker_id"))
        if isinstance(rec, dict):
            st = str(rec.get("status", "unknown"))
            counts[st] = counts.get(st, 0) + 1
    return counts


def _review_dict(sprint: dict) -> dict:
    """Compute a review dict for a sprint without persisting anything."""
    targets = sprint.get("targets") or []
    done = sum(1 for t in targets if t.get("status") == "done")
    total = len(targets)
    goal = _target_apps_int(sprint)
    completion_pct = round(100.0 * done / total, 1) if total else 0.0
    if goal > 0:
        hit = done >= goal
    else:
        hit = bool(total) and done == total

    def _breakdown(key: str, default: str) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for t in targets:
            bucket = str(t.get(key) or default)
            entry = out.setdefault(bucket, {"done": 0, "total": 0})
            entry["total"] += 1
            if t.get("status") == "done":
                entry["done"] += 1
        return dict(sorted(out.items()))

    return {
        "targets_done": done,
        "targets_total": total,
        "target_apps": goal,
        "hit_target": hit,
        "completion_pct": completion_pct,
        "by_priority": _breakdown("priority", "none"),
        "by_batch": _breakdown("batch", "none"),
        "notes_count": len(sprint.get("notes") or []),
        "generated_at": _now_iso(),
        "tracker_outcomes": _tracker_outcomes(targets),
    }


def _review_for(sprint: dict) -> dict:
    """Use the stored review if present, else compute one in memory (no save)."""
    stored = sprint.get("review")
    if isinstance(stored, dict) and stored:
        return stored
    return _review_dict(sprint)


# --- public API ---------------------------------------------------------------

def review_sprint(sprint_id: int) -> dict:
    """Build a review for the sprint, store it in sprint["review"], and return it.

    Never changes the sprint's status.
    """
    sprints = load_sprints()
    sprint = get_sprint(sprint_id, sprints)
    review = _review_dict(sprint)
    sprint["review"] = review
    save_sprints(sprints)
    return review


def carryover(sprint_id: int, new_week_start: str | None = None) -> dict:
    """Start the next week's sprint from the current one.

    Copies unfinished (todo) targets, keeps target_apps and hours_budget,
    closes the old sprint, and returns the NEW sprint dict. The new week is
    the old week's Monday + 7 days, or a given date snapped back to Monday.
    If the old sprint has no stored review yet, one is generated before
    closing so the history stays reviewable.
    """
    sprints = load_sprints()
    old = get_sprint(sprint_id, sprints)

    if new_week_start:
        new_monday = _snap_to_monday(_parse_date(new_week_start))
    else:
        new_monday = _parse_date(old.get("week_start", "")) + timedelta(weeks=1)
    new_week_iso = new_monday.isoformat()

    if any(s.get("week_start") == new_week_iso for s in sprints):
        raise SprintReviewError(
            f"A sprint already exists for the week of {new_week_iso}.")

    todos = [t for t in (old.get("targets") or []) if t.get("status") != "done"]
    new_targets = []
    for t in todos:
        nt = dict(t)
        nt["status"] = "todo"
        nt["done_at"] = None
        new_targets.append(nt)

    new = {
        "id": _next_id(sprints),
        "week_start": new_week_iso,
        "title": f"Week of {new_week_iso} (carryover)",
        "target_apps": old.get("target_apps", 0),
        "hours_budget": old.get("hours_budget", 0.0),
        "targets": new_targets,
        "time_blocks": [],
        "notes": [],
        "status": "active",
        "created_at": _now_iso(),
        "review": {},
        "template": old.get("template", ""),
    }
    if not old.get("review"):
        old["review"] = _review_dict(old)
    old["status"] = "closed"
    sprints.append(new)
    save_sprints(sprints)
    return new


def compare_sprints(id_a: int, id_b: int) -> dict:
    """Compare two sprints (b minus a) using stored reviews.

    Reviews missing from the file are computed in memory so a comparison
    always works; nothing is written.
    """
    sprints = load_sprints()
    ra = _review_for(get_sprint(id_a, sprints))
    rb = _review_for(get_sprint(id_b, sprints))
    return {
        "target_apps": (rb.get("target_apps") or 0) - (ra.get("target_apps") or 0),
        "done": (rb.get("targets_done") or 0) - (ra.get("targets_done") or 0),
        "completion_pct": round(
            (rb.get("completion_pct") or 0.0) - (ra.get("completion_pct") or 0.0), 1),
        "hit_target": (bool(ra.get("hit_target")), bool(rb.get("hit_target"))),
    }


def streaks() -> dict:
    """Hit-target streaks over closed sprints, sorted by week_start.

    A streak is consecutive hit weeks with no week gaps. current_streak
    ends at the most recent closed sprint; best_streak is the longest
    such run anywhere in history. Returns {"current_streak", "best_streak"}.
    """
    closed = [s for s in load_sprints() if s.get("status") == "closed"]
    weeks: list[tuple[date, bool]] = []
    for s in closed:
        try:
            week = _parse_date(s.get("week_start", ""))
        except SprintReviewError:
            continue
        weeks.append((week, bool(_review_for(s).get("hit_target"))))
    weeks.sort(key=lambda w: w[0])

    current = 0
    prev: date | None = None
    for week, hit in reversed(weeks):
        if prev is None:
            if not hit:
                break
            current = 1
        elif hit and (prev - week).days == 7:
            current += 1
        else:
            break
        prev = week

    best = 0
    run = 0
    prev = None
    for week, hit in weeks:
        if hit and (prev is None or (week - prev).days == 7):
            run += 1
        elif hit:
            run = 1
        else:
            run = 0
        prev = week
        best = max(best, run)

    return {"current_streak": current, "best_streak": best}


def render_review(sprint_id: int) -> str:
    """Human-readable Markdown-ish summary of a sprint's review."""
    sprint = get_sprint(sprint_id)
    rev = _review_for(sprint)
    done, total = rev["targets_done"], rev["targets_total"]
    goal = rev["target_apps"]
    verdict = "HIT" if rev["hit_target"] else "MISSED"
    lines = [
        f"# Sprint review: {sprint.get('title', '(untitled)')}",
        f"Week of {sprint.get('week_start', '?')} - status: {sprint.get('status', '?')}",
        "",
        f"Targets: {done}/{total} done ({rev['completion_pct']}%)",
        f"Goal: {goal} applications - {verdict}",
        "",
    ]
    if rev["by_priority"]:
        lines.append("By priority:")
        for prio, b in rev["by_priority"].items():
            lines.append(f"  {prio}: {b['done']}/{b['total']} done")
        lines.append("")
    if rev["by_batch"]:
        lines.append("By batch:")
        for batch, b in rev["by_batch"].items():
            lines.append(f"  {batch}: {b['done']}/{b['total']} done")
        lines.append("")
    outcomes = rev.get("tracker_outcomes") or {}
    if outcomes:
        lines.append("Tracker outcomes (linked targets):")
        for st, n in sorted(outcomes.items()):
            lines.append(f"  {st}: {n}")
        lines.append("")
    lines.append(f"Notes: {rev['notes_count']}")
    lines.append(f"Reviewed: {rev['generated_at']}")
    return "\n".join(lines).rstrip()
