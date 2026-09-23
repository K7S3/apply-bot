"""T-24h interview countdown plan.

Given an interview start time, generate an ordered evening-before and
morning-of checklist with times relative to the start, plus suggested
reminder texts the user can paste into nudges or a calendar.

Standalone use:
    python -m candid.ritual_countdown --start "2026-09-25 14:00"
    python -m candid.ritual_countdown --start "2026-09-25 14:00" --json

The ``ritual countdown`` CLI wiring is done by a sibling module; this
module exposes the clean function interface:

    build_countdown(start_dt) -> list of (datetime, label) tuples
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta

# How far back we anchor the routine. Wake is 3h before the start so there
# is room for a walk, a real breakfast, and getting ready without rushing.
WAKE_LEAD_HOURS = 3
SLEEP_HOURS = 8


# ---------------------------------------------------------------------------
# plan generation
# ---------------------------------------------------------------------------

def build_countdown(start_dt):
    """Build the ordered checklist as (datetime, label) tuples.

    Everything is anchored to ``start_dt``: the evening-before items land
    on the previous day, the bedtime is back-calculated from the wake time
    to hit an 8-hour sleep target.
    """
    start_dt = _coerce(start_dt)
    wake = start_dt - timedelta(hours=WAKE_LEAD_HOURS)
    bedtime = wake - timedelta(hours=SLEEP_HOURS)
    day_before = (start_dt - timedelta(days=1)).date()

    def evening(hour, minute):
        return datetime.combine(day_before, datetime.min.time()).replace(
            hour=hour, minute=minute
        )

    items = [
        (
            evening(19, 0),
            "Lay out clothes, ID, and anything you need to bring",
        ),
        (
            evening(19, 30),
            "Charge phone, laptop, headphones; confirm the join link and meeting details",
        ),
        (
            evening(20, 0),
            "Light review only: skim your one-pager and the role notes",
        ),
        (
            evening(21, 0),
            "Nothing new after 9pm. Screens down, wind down",
        ),
        (
            bedtime,
            f"Bedtime: 8 hours of sleep before your {wake.strftime('%H:%M')} wake-up",
        ),
        (wake, "Wake up"),
        (
            wake + timedelta(minutes=30),
            "Exercise or a light walk, 20 to 30 minutes",
        ),
        (
            wake + timedelta(hours=1),
            "Real breakfast, no skipping",
        ),
        (
            wake + timedelta(hours=1, minutes=30),
            "Shower, dress, final check of docs and devices",
        ),
        (
            start_dt - timedelta(minutes=30),
            "Join the call early / arrive 15 to 30 minutes ahead",
        ),
        (
            start_dt,
            "Interview time. Breathe. You prepared for this",
        ),
    ]
    items.sort(key=lambda pair: pair[0])
    return items


def reminder_texts(start_dt):
    """Suggested reminder texts, ready to paste into nudges or a calendar."""
    start_dt = _coerce(start_dt)
    wake = start_dt - timedelta(hours=WAKE_LEAD_HOURS)
    bedtime = wake - timedelta(hours=SLEEP_HOURS)
    day_before = (start_dt - timedelta(days=1)).date()

    def evening(hour, minute):
        return datetime.combine(day_before, datetime.min.time()).replace(
            hour=hour, minute=minute
        )

    return [
        {
            "at": evening(19, 0).strftime("%Y-%m-%d %H:%M"),
            "text": "Evening prep: clothes out, devices charging, join details confirmed.",
        },
        {
            "at": evening(21, 0).strftime("%Y-%m-%d %H:%M"),
            "text": "Nothing new after 9pm. Wind down now.",
        },
        {
            "at": bedtime.strftime("%Y-%m-%d %H:%M"),
            "text": "Bedtime. 8 hours ahead. Phone on charge, alarm set.",
        },
        {
            "at": wake.strftime("%Y-%m-%d %H:%M"),
            "text": (
                f"Up and moving. Walk, breakfast, final check. "
                f"Interview at {start_dt.strftime('%H:%M')}."
            ),
        },
        {
            "at": (start_dt - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M"),
            "text": "Join early. Camera on, notes open, breathe.",
        },
    ]


def countdown_result(start_dt):
    """Full result dict: ordered checklist, reminders, and key anchors."""
    start_dt = _coerce(start_dt)
    wake = start_dt - timedelta(hours=WAKE_LEAD_HOURS)
    bedtime = wake - timedelta(hours=SLEEP_HOURS)
    return {
        "start": start_dt.strftime("%Y-%m-%d %H:%M"),
        "wake": wake.strftime("%Y-%m-%d %H:%M"),
        "bedtime": bedtime.strftime("%Y-%m-%d %H:%M"),
        "sleep_target_hours": SLEEP_HOURS,
        "checklist": [
            {"at": dt.strftime("%Y-%m-%d %H:%M"), "label": label}
            for dt, label in build_countdown(start_dt)
        ],
        "reminders": reminder_texts(start_dt),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _coerce(value):
    if isinstance(value, datetime):
        return value
    raise TypeError(f"start must be a datetime, got {type(value).__name__}")


def parse_start(text):
    """Parse ``YYYY-MM-DD HH:MM`` (24h clock)."""
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError(
            f'Could not parse start time {text!r}. '
            'Use the form "2026-09-25 14:00".'
        ) from exc


def format_checklist_text(result):
    lines = [
        f"Interview countdown (interview at {result['start']})",
        f"Wake: {result['wake']}  |  Bedtime: {result['bedtime']} "
        f"({result['sleep_target_hours']}h sleep target)",
        "",
    ]
    for item in result["checklist"]:
        when = datetime.strptime(item["at"], "%Y-%m-%d %H:%M")
        lines.append(f"  {when.strftime('%a %b %d %H:%M')}  {item['label']}")
    lines += ["", "Suggested reminders (paste into nudges or calendar):", ""]
    for rem in result["reminders"]:
        when = datetime.strptime(rem["at"], "%Y-%m-%d %H:%M")
        lines.append(f"  {when.strftime('%a %b %d %H:%M')}  {rem['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# standalone entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="T-24h interview countdown plan generator."
    )
    ap.add_argument("--start", required=True,
                    help='Interview start, e.g. "2026-09-25 14:00".')
    ap.add_argument("--json", action="store_true",
                    help="Print the plan as JSON instead of text.")
    args = ap.parse_args(argv)
    result = countdown_result(parse_start(args.start))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_checklist_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
