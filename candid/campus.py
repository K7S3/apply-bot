"""Campus recruiting timeline for new-grad job seekers.

IMPORTANT: every date below is SEEDED DATA - hand-written typical
recruiting windows, not scraped facts and not company-specific deadlines.
Treat them as planning guides ("when to start watching"), then confirm
real deadlines on each company's own university/careers page.

All concrete dates are computed relative to today, so the calendar never
goes stale.
"""

from __future__ import annotations

from datetime import date


class CampusError(Exception):
    """Raised for campus command failures."""


# ---------------------------------------------------------------------------
# seeded dataset - typical patterns, NOT scraped facts
# ---------------------------------------------------------------------------
#
# Each window: (month, day) start and end within a calendar year.
# "occurrences span a single calendar year" for all three windows, so
# relative-to-today math only needs the current and next year.

RECRUITING_WINDOWS = [
    {
        "id": "fall-fulltime",
        "name": "Fall full-time new-grad recruiting",
        "start": (8, 1),
        "end": (11, 30),
        "blurb": "The main new-grad hiring wave: most full-time roles for "
                 "next-year graduates post and interview in this window.",
    },
    {
        "id": "spring",
        "name": "Spring recruiting",
        "start": (1, 5),
        "end": (3, 31),
        "blurb": "Second wave: leftover headcount, smaller teams, and "
                 "companies that hire closer to graduation.",
    },
    {
        "id": "internship",
        "name": "Internship recruiting (for next summer)",
        "start": (9, 1),
        "end": (11, 30),
        "blurb": "Apply in the fall BEFORE the summer you want to intern. "
                 "Many return offers convert to full-time new-grad offers.",
    },
]

# Per-company-type notes: how each type typically deviates from the windows.
COMPANY_TYPE_NOTES = {
    "big tech": "Post new-grad roles Aug-Oct; interviews Sep-Dec; most "
                "decisions by January.",
    "quant": "Earliest wave of all; applications open late summer and "
             "interviews run through the fall. Miss the start and the "
             "seats are gone.",
    "startups": "Irregular and year-round, with peaks in Sep-Nov and Jan-Mar. "
                "Apply directly on the careers page and through referrals; "
                "many never post publicly at all.",
    "defense": "Slowest cycle; background checks and headcount approvals "
               "can stretch well past the fall window. Apply early.",
}

SCHOOL_TYPES = {
    "target": "On-campus recruiting (OCR) is active at your school: prioritize "
              "career fairs, info sessions, and OCR postings alongside online "
              "applications.",
    "non-target": "No OCR pipeline: apply online as early as the window opens, "
                  "and lean on referrals, cold outreach, and open-source "
                  "visibility.",
    "bootcamp": "Career services vary widely: your portfolio, projects, and "
                "referrals carry the most weight. Timelines follow the "
                "startup peak windows.",
}


# ---------------------------------------------------------------------------
# date math (pure - easy to test)
# ---------------------------------------------------------------------------

def window_dates(window: dict, year: int) -> tuple[date, date]:
    """Concrete (start, end) dates of one seeded window for a calendar year."""
    (sm, sd), (em, ed) = window["start"], window["end"]
    return date(year, sm, sd), date(year, em, ed)


def next_occurrence(window: dict, today: date) -> tuple[date, date]:
    """The current or next occurrence of a window relative to today."""
    start, end = window_dates(window, today.year)
    if end < today:
        start, end = window_dates(window, today.year + 1)
    return start, end


def window_status(window: dict, today: date) -> dict:
    """Where a window stands relative to today.

    Returns {"state": "active"|"upcoming", "days": int, "start": date,
    "end": date}. "days" is 0 when active, else days until the start.
    """
    start, end = next_occurrence(window, today)
    if start <= today <= end:
        return {"state": "active", "days": 0, "start": start, "end": end}
    return {"state": "upcoming", "days": (start - today).days,
            "start": start, "end": end}


def upcoming_events(days: int, today: date | None = None) -> list[dict]:
    """Window start/end events happening within the next ``days`` days.

    Each event: {"date": date, "kind": "opens"|"closes", "window": name}.
    Sorted by date. ``days`` must be >= 0.
    """
    if days is None:
        days = 30
    if days < 0:
        raise CampusError("--days must be 0 or more.")
    today = today or date.today()
    cutoff = _add_days(today, days)
    events: list[dict] = []
    for window in RECRUITING_WINDOWS:
        for yr in (today.year, today.year + 1):
            start, end = window_dates(window, yr)
            if today <= start <= cutoff:
                events.append({"date": start, "kind": "opens",
                               "window": window["name"]})
            if today <= end <= cutoff:
                events.append({"date": end, "kind": "closes",
                               "window": window["name"]})
    events.sort(key=lambda e: (e["date"], e["kind"]))
    return events


def _add_days(d: date, n: int) -> date:
    from datetime import timedelta
    return d + timedelta(days=n)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

SEEDED_LABEL = ("Seeded typical patterns - NOT scraped facts. Confirm real "
                "deadlines on each company's own careers page.")


def render_timeline(school_type: str | None = None,
                    today: date | None = None) -> str:
    """Full campus recruiting calendar with per-company-type notes."""
    if school_type is not None and school_type not in SCHOOL_TYPES:
        raise CampusError(
            f"Unknown school type: {school_type!r}. "
            f"Choose one of: {', '.join(sorted(SCHOOL_TYPES))}.")
    today = today or date.today()
    lines = [
        "Campus recruiting timeline (new-grad track)",
        SEEDED_LABEL,
        "",
    ]
    if school_type:
        lines.append(f"School profile: {school_type}")
        lines.append(SCHOOL_TYPES[school_type])
        lines.append("")
    for window in RECRUITING_WINDOWS:
        st = window_status(window, today)
        if st["state"] == "active":
            state = "ACTIVE NOW"
        else:
            state = f"starts in {st['days']} days"
        lines.append(f"* {window['name']}")
        lines.append(f"    {st['start'].isoformat()} to {st['end'].isoformat()} "
                     f"- {state}")
        lines.append(f"    {window['blurb']}")
    lines += ["", "Per company type:"]
    for ctype, note in COMPANY_TYPE_NOTES.items():
        lines.append(f"* {ctype}: {note}")
    lines += ["",
              "Next: watch upcoming window edges with "
              "`python -m candid campus deadlines --days 60`."]
    return "\n".join(lines)


def render_deadlines(days: int = 30, today: date | None = None) -> str:
    """Upcoming window opens/closes within the next ``days`` days."""
    if days is None:
        days = 30
    events = upcoming_events(days, today=today)
    today = today or date.today()
    lines = [
        f"Campus recruiting window events in the next {days} days",
        SEEDED_LABEL,
        "",
    ]
    if not events:
        lines.append("No window starts or ends in this period.")
        lines.append("Run `python -m candid campus timeline` for the full calendar.")
        return "\n".join(lines)
    for e in events:
        n = (e["date"] - today).days
        when = "today" if n == 0 else f"in {n} days"
        lines.append(f"* {e['date'].isoformat()} - {e['window']} {e['kind']} "
                     f"({when})")
    return "\n".join(lines)
