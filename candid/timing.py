"""Timing core: shared helpers for best-time-to-apply analysis.

This module is the contract other timing_* feature modules build on:
timing_curve, timing_advise, timing_patterns, timing_calendar, timing_trends.
Do NOT rename the public names here  -  sibling batch workers depend on them.

Design rules:
  - Everything is descriptive of the user's own tracker history. Nothing is
    a prediction, and nothing is invented to fill a gap.
  - MIN_SAMPLE (5) is the minimum sample before rates are shown or claims
    are made. Below that, callers show counts plus the honesty note.
  - Missing timing fields (posted_date etc.) are normal for old records;
    helpers return None and callers handle it.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

from candid import config as C

#: A "response" = the company moved you forward, not just replied.
POSITIVE_STATUSES = {"selected_for_interview", "offer"}

#: Minimum sample size before rates are shown / guidance is derived.
MIN_SAMPLE = 5

#: Posting-age buckets, in display order.
BUCKETS = ["0-3 days", "4-7 days", "8-14 days", "15-30 days", "31+ days"]


def load_applications(path: str | Path | None = None) -> list[dict]:
    """Read the tracker JSON defensively. Never raises on bad/missing data."""
    p = Path(path) if path else C.TRACKER_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [a for a in data if isinstance(a, dict)]


def _parse_date(value) -> date | None:
    """Parse an ISO date/datetime string (or date object). None if unusable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def get_posted_date(app: dict) -> date | None:
    """Posting date from app["posted_date"]. None if missing/invalid."""
    return _parse_date(app.get("posted_date"))


def get_applied_date(app: dict) -> date | None:
    """Applied date: app["applied_date"], falling back to app["date_added"]."""
    return _parse_date(app.get("applied_date") or app.get("date_added"))


def get_first_response_date(app: dict) -> date | None:
    """First substantive company response date. None if missing/invalid."""
    return _parse_date(app.get("first_response_date"))


def get_deadline(app: dict) -> date | None:
    """Application deadline. None if missing/invalid."""
    return _parse_date(app.get("deadline"))


def is_positive(app: dict) -> bool:
    """True when the company moved the application forward."""
    return app.get("status") in POSITIVE_STATUSES


def posting_age_days(app: dict) -> int | None:
    """Days between posting and applying. None if either date is missing."""
    posted = get_posted_date(app)
    applied = get_applied_date(app)
    if posted is None or applied is None:
        return None
    return (applied - posted).days


def bucket_posting_age(days: int) -> str:
    """Bucket a posting age (days) into one of BUCKETS. Negatives clamp to 0."""
    d = max(int(days), 0)
    if d <= 3:
        return "0-3 days"
    if d <= 7:
        return "4-7 days"
    if d <= 14:
        return "8-14 days"
    if d <= 30:
        return "15-30 days"
    return "31+ days"


def response_rate(apps) -> float | None:
    """Share of apps with a positive outcome. None when empty."""
    apps = list(apps)
    if not apps:
        return None
    return sum(1 for a in apps if is_positive(a)) / len(apps)


def enough_data(apps, n: int = MIN_SAMPLE) -> bool:
    """True when there are at least n applications to reason about."""
    return len(list(apps)) >= n


def honesty_note(apps) -> str:
    """One-line honest framing of how much the data can say."""
    apps = list(apps)
    n = len(apps)
    if enough_data(apps):
        return (f"Based on {n} applications with timing data. "
                "This describes your own history  -  not a prediction about "
                "any single posting.")
    return (f"Not enough data yet (need {MIN_SAMPLE}+ applications with "
            f"timing info; currently {n}). "
            "Record --posted-date when tracking and this gets smarter.")


#: timing subcommand -> (feature module, handler function).
_TIMING_COMMANDS = {
    "curve": ("timing_curve", "cmd_curve"),
    "analyze": ("timing_curve", "cmd_analyze"),
    "advise": ("timing_advise", "cmd_advise"),
    "reposts": ("timing_advise", "cmd_reposts"),
    "weekday": ("timing_patterns", "cmd_weekday"),
    "deadline": ("timing_patterns", "cmd_deadline"),
    "calendar": ("timing_calendar", "cmd_calendar"),
    "seasons": ("timing_trends", "cmd_seasons"),
    "followups": ("timing_trends", "cmd_followups"),
}


def dispatch(a) -> int | None:
    """Route a parsed `timing` args namespace to its feature-module handler.

    Feature modules are imported lazily (deferred import) so `import
    candid.timing` never pulls in the whole timing feature set.
    Returns the handler's return value; unknown commands print the valid
    list and return 2.
    """
    cmd = getattr(a, "timing_cmd", None)
    target = _TIMING_COMMANDS.get(cmd)
    if target is None:
        valid = ", ".join(_TIMING_COMMANDS)
        print(f"Unknown timing command: {cmd!r}.", file=sys.stderr)
        print(f"Valid timing subcommands: {valid}", file=sys.stderr)
        return 2
    module_name, func_name = target
    module = importlib.import_module(f"candid.{module_name}")
    handler = getattr(module, func_name)
    return handler(a)
