"""Action calendar + job timing scores for best-time-to-apply analysis.

``cmd_calendar(a)`` renders a deadline-driven action calendar over the
tracked applications. ``timing_score`` / ``annotate_timing`` score curated
job dicts by posting freshness (used by the opt-in ``jobs curate --timing``
flag).

Only stdlib is used; timing primitives come from ``candid.timing``.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from candid import timing as TM

#: Tracked applications in a terminal state  -  never produce calendar actions.
_CLOSED_STATUSES = {"rejected", "offer", "withdrawn"}

#: Guidance copy per posting-age bucket (keys match timing.BUCKETS).
_BUCKET_GUIDANCE = {
    "0-3 days": "apply now  -  fresh postings get the most attention",
    "4-7 days": "apply this week  -  still early",
    "8-14 days": "apply soon  -  going stale",
    "15-30 days": "likely stale  -  verify the posting is still open first",
    "31+ days": "likely stale  -  verify the posting is still open first",
}

_RELATIVE_AGE = re.compile(
    r"(?P<n>\d+)\s*(?P<unit>minutes?|mins?|hours?|hrs?|days?|weeks?)\s+ago",
    re.IGNORECASE,
)


def _parse_date(value) -> date | None:
    """Best-effort parse of ISO date/datetime strings."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", value.strip())
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except ValueError:
                return None
    return None


def _relative_to_date(text: str) -> date | None:
    """Parse relative ages like '3d ago', '2 weeks ago', 'yesterday'."""
    t = text.strip().lower()
    if t in ("today", "just now", "now"):
        return date.today()
    if t == "yesterday":
        return date.today() - timedelta(days=1)
    m = _RELATIVE_AGE.search(t)
    if not m:
        # compact forms: "3d ago", "2w ago", "5h ago"
        m = re.search(r"(?P<n>\d+)\s*(?P<unit>[mhdw])\s+ago", t)
    if m:
        n = int(m.group("n"))
        unit = m.group("unit").lower()[0]
        if unit == "m":  # minutes
            days = 0
        elif unit == "h":
            days = 0 if n < 24 else n // 24
        elif unit == "d":
            days = n
        else:  # weeks
            days = n * 7
        return date.today() - timedelta(days=days)
    return None


def _job_posted_date(job: dict) -> date | None:
    """Posted date for a curated job dict; ISO or relative like '3d ago'."""
    for key in ("posted_date", "date_posted", "published", "posted"):
        value = job.get(key)
        if not value:
            continue
        parsed = _parse_date(value)
        if parsed is not None:
            return parsed
        if isinstance(value, str):
            rel = _relative_to_date(value)
            if rel is not None:
                return rel
    return None


# ---------------------------------------------------------------------------
# freshness scoring (pure, no I/O)
# ---------------------------------------------------------------------------

def timing_score(job: dict) -> tuple[float, str]:
    """Freshness score 0-100 for a curated job dict plus a short note.

    100 at 0-3 days old, decaying to ~20 at 30+ days. Missing posted date
    scores 50 with an "age unknown" note. A deadline within 7 days adds an
    urgency note (it never changes the score). Reads defensively: never
    raises on odd input.
    """
    try:
        posted = _job_posted_date(job)
    except Exception:
        posted = None
    try:
        deadline = _parse_date(job.get("deadline"))
    except Exception:
        deadline = None

    if posted is None:
        score = 50.0
        note = "age unknown  -  apply on merit"
    else:
        age = max(0, (date.today() - posted).days)
        if age <= 3:
            score = 100.0
        elif age <= 30:
            score = 100.0 - (age - 3) * (80.0 / 27.0)
        else:
            score = 20.0
        score = max(20.0, min(100.0, score))
        note = f"posted {age}d ago"
        if age <= 3:
            note += "  -  fresh"
        elif age > 14:
            note += "  -  going stale"

    if deadline is not None:
        days_left = (deadline - date.today()).days
        if days_left < 0:
            note += "; deadline passed"
        elif days_left <= 7:
            note += f"; deadline in {days_left}d  -  apply soon"

    return round(score, 1), note


def annotate_timing(jobs: list[dict]) -> list[dict]:
    """Return copies of jobs with timing_score/timing_note, best first.

    Inputs are never mutated.
    """
    annotated = []
    for job in jobs:
        copy = dict(job)
        score, note = timing_score(job)
        copy["timing_score"] = score
        copy["timing_note"] = note
        annotated.append(copy)
    annotated.sort(key=lambda j: j["timing_score"], reverse=True)
    return annotated


# ---------------------------------------------------------------------------
# best apply weekday from the user's own history
# ---------------------------------------------------------------------------

def _best_apply_weekday(apps: list[dict]) -> tuple[str | None, str]:
    """Derive the user's best apply weekday from positive outcomes.

    Returns (weekday_name, note). Falls back to (None, heuristic note) when
    there is not enough positive-outcome data.
    """
    positives = [a for a in apps
                 if TM.is_positive(a) and TM.get_applied_date(a) is not None]
    if len(positives) < 3:
        return None, ("heuristic: apply within 3 days of posting  -  "
                      "not enough of your own outcomes to personalize yet")
    counts: dict[str, int] = {}
    for app in positives:
        wd = TM.get_applied_date(app).strftime("%A")  # type: ignore[union-attr]
        counts[wd] = counts.get(wd, 0) + 1
    best = max(counts, key=lambda w: counts[w])
    note = (f"your best apply day is {best} "
            f"({counts[best]}/{len(positives)} of your positive outcomes; "
            f"{TM.honesty_note(positives)})")
    return best, note


# ---------------------------------------------------------------------------
# calendar building blocks
# ---------------------------------------------------------------------------

def _urgency_tag(days_left: int) -> str:
    if days_left < 0:
        return "overdue"
    if days_left <= 3:
        return "<=3 days"
    if days_left <= 7:
        return "<=7 days"
    return "later"


def build_deadlines(apps: list[dict], days: int) -> list[dict]:
    """Upcoming deadlines (open statuses only), sorted by urgency."""
    today = date.today()
    out = []
    for app in apps:
        if app.get("status") in _CLOSED_STATUSES:
            continue
        try:
            deadline = TM.get_deadline(app)
        except Exception:
            deadline = None
        if deadline is None:
            continue
        days_left = (deadline - today).days
        if days_left < 0 or days_left <= days:
            out.append({
                "app_id": app.get("id"),
                "company": app.get("company", ""),
                "role": app.get("role", ""),
                "status": app.get("status", ""),
                "deadline": deadline.isoformat(),
                "days_left": days_left,
                "urgency": _urgency_tag(days_left),
            })
    out.sort(key=lambda d: d["days_left"])
    return out


def build_windows(apps: list[dict], best_weekday: str | None,
                  weekday_note: str) -> list[dict]:
    """Best apply windows for saved postings with a posted date.

    The bucket reflects how old the posting is *today* (not the age at
    some past apply date): a posting that has sat 15+ days is going
    stale whether or not you have applied yet.
    """
    today = date.today()
    out = []
    for app in apps:
        if app.get("status") != "saved":
            continue
        try:
            posted = TM.get_posted_date(app)
        except Exception:
            posted = None
        if posted is None:
            continue
        age = max(0, (today - posted).days)
        bucket = TM.bucket_posting_age(age)
        out.append({
            "app_id": app.get("id"),
            "company": app.get("company", ""),
            "role": app.get("role", ""),
            "posted_date": posted.isoformat(),
            "age_days": age,
            "bucket": bucket,
            "guidance": _BUCKET_GUIDANCE[bucket],
            "best_weekday": best_weekday,
            "timing_basis": ("personal history" if best_weekday
                             else "heuristic"),
            "timing_note": weekday_note,
        })
    out.sort(key=lambda w: w["age_days"])
    return out


def build_actions(deadlines: list[dict], windows: list[dict]) -> list[str]:
    """Prioritized one-line actions: deadlines first, then fresh postings."""
    actions = []
    for d in deadlines:
        if d["days_left"] < 0:
            step = (f"deadline passed {-d['days_left']}d ago  -  "
                    f"confirm the posting is still open before applying")
        else:
            step = f"submit application within {d['days_left']}d"
        actions.append(
            f"[deadline {d['urgency']}] {step}: "
            f"{d['role']} @ {d['company']} (due {d['deadline']})")
    for w in windows:
        if w["bucket"] in ("0-3 days", "4-7 days"):
            actions.append(
                f"[apply soon] {w['guidance']}: {w['role']} @ {w['company']} "
                f"(posted {w['age_days']}d ago)  -  next: tailor resume and apply")
    return actions


def render_calendar(deadlines: list[dict], windows: list[dict],
                   actions: list[str], days: int,
                   weekday_note: str) -> str:
    """Human-readable calendar text."""
    lines = [f"Action calendar  -  next {days} days", ""]
    if deadlines:
        lines.append("Deadlines:")
        for d in deadlines:
            when = (f"{-d['days_left']}d overdue" if d["days_left"] < 0
                    else f"in {d['days_left']}d")
            lines.append(f"  [{d['urgency']}] {d['role']} @ {d['company']}  -  "
                         f"due {d['deadline']} ({when})")
    else:
        lines.append("Deadlines: none tracked in this window.")
    lines.append("")
    if windows:
        lines.append("Best apply windows:")
        for w in windows:
            lines.append(f"  [{w['bucket']}] {w['role']} @ {w['company']}  -  "
                         f"posted {w['age_days']}d ago: {w['guidance']}")
        lines.append(f"  ({weekday_note})")
    else:
        lines.append("Best apply windows: no saved postings with a posted date.")
    lines.append("")
    if actions:
        lines.append("Actions (in order):")
        for i, a in enumerate(actions, 1):
            lines.append(f"  {i}. {a}")
    else:
        lines.append("Actions: nothing urgent  -  keep an eye on fresh postings.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def cmd_calendar(a) -> None:
    """``python -m candid timing calendar [--days N] [--json]``.

    ``a`` is an argparse Namespace with ``days`` (int, default 14) and
    ``json`` (bool).
    """
    days = getattr(a, "days", 14) or 14
    as_json = getattr(a, "json", False)

    try:
        apps = TM.load_applications()
    except Exception:
        apps = []

    best_weekday, weekday_note = _best_apply_weekday(apps)
    deadlines = build_deadlines(apps, days)
    windows = build_windows(apps, best_weekday, weekday_note)
    actions = build_actions(deadlines, windows)

    if as_json:
        print(json.dumps({
            "deadlines": deadlines,
            "windows": windows,
            "actions": actions,
        }, indent=2))
    else:
        print(render_calendar(deadlines, windows, actions, days, weekday_note))
