"""Day-of interview timeline generator.

Works backwards from the interview start time to produce a timed
schedule: wake up, breakfast, shower/dress, materials review, warm-up,
tech check, calm slot, join early (virtual/phone) or depart with buffer
(onsite), the interview block itself, and a post-interview debrief.

Programmatic use (this is what the CLI layer calls via lazy imports)::

    from datetime import datetime
    from candid import ritual_timeline as RT
    events = RT.build_timeline(datetime(2026, 9, 25, 14, 0), "virtual",
                               wake="07:30")
    print(RT.render_timeline(events))

All slots are generic routine advice; no external dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from candid.ritual_logistics import RitualError, ROUND_TYPES  # noqa: F401  (re-exported)


# Offsets are minutes relative to interview start; each entry is
# (offset_minutes, label). Negative offsets run before the start.
_VIRTUAL_OFFSETS: list[tuple[int, str]] = [
    (-200, "Breakfast (40 min)"),
    (-160, "Shower and dress (40 min)"),
    (-120, "Materials review: resume, job description, questions for them (40 min)"),
    (-80, "Warm-up slot: read your notes aloud, one practice answer (30 min)"),
    (-50, "Tech check: camera, mic, speakers, lighting, backup device (20 min)"),
    (-30, "Calm slot: breathe, drink water, settle in (15 min)"),
    (-10, "Join the call 10 minutes early"),
]

_ONSITE_OFFSETS: list[tuple[int, str]] = [
    (-225, "Breakfast (40 min)"),
    (-185, "Shower and dress (40 min)"),
    (-145, "Materials review: resume, job description, questions for them (40 min)"),
    (-105, "Warm-up slot: read your notes aloud, one practice answer (30 min)"),
    (-75, "Final bag check: ID, resume copies, charger (15 min)"),
    (-60, "Depart for the office (aim to arrive about 30 min early)"),
    (-30, "Arrived: check in, calm slot, breathe, review notes"),
]

# Phone rounds follow the virtual (remote) pattern.
_OFFSETS: dict[str, list[tuple[int, str]]] = {
    "virtual": _VIRTUAL_OFFSETS,
    "phone": _VIRTUAL_OFFSETS,
    "onsite": _ONSITE_OFFSETS,
}

_DEFAULT_WAKE_OFFSET_MIN = 390  # 6.5 hours before start


def _offsets_for(round_type: str) -> list[tuple[int, str]]:
    rt = (round_type or "").strip().lower()
    if rt not in _OFFSETS:
        raise RitualError(
            f"Unknown round type {round_type!r}; expected one of: "
            + ", ".join(ROUND_TYPES)
        )
    return _OFFSETS[rt]


def _parse_wake(wake: str | None, start: datetime) -> datetime:
    """Resolve the wake time: default is 6.5h before start."""
    if wake is None:
        return start - timedelta(minutes=_DEFAULT_WAKE_OFFSET_MIN)
    text = str(wake).strip()
    try:
        hh, mm = text.split(":")
        wake_t = time(int(hh), int(mm))
    except (ValueError, AttributeError):
        raise RitualError(
            f"Bad wake time {wake!r}; expected HH:MM like '07:30'"
        ) from None
    if not (0 <= wake_t.hour <= 23 and 0 <= wake_t.minute <= 59):
        raise RitualError(f"Bad wake time {wake!r}; expected HH:MM like '07:30'")
    combined = datetime.combine(start.date(), wake_t)
    if start.tzinfo is not None:
        combined = combined.replace(tzinfo=start.tzinfo)
    return combined


def build_timeline(start_dt: datetime, round_type: str,
                   wake: str | None = None,
                   interview_minutes: int = 60) -> list[tuple[datetime, str]]:
    """Build the day-of schedule as a chronological list of (time, label).

    ``start_dt`` is the interview start (naive or timezone-aware; the
    timeline inherits whatever it carries). ``wake`` is an optional
    "HH:MM" override for the wake-up time; the default is 6.5 hours
    before start. Raises RitualError for a bad round type, a bad wake
    time, or a wake time that leaves no room for the morning routine.
    """
    if not isinstance(start_dt, datetime):
        raise RitualError(
            f"start_dt must be a datetime, got {type(start_dt).__name__}"
        )
    if not isinstance(interview_minutes, int) or interview_minutes <= 0:
        raise RitualError("interview_minutes must be a positive integer")
    offsets = _offsets_for(round_type)
    wake_dt = _parse_wake(wake, start_dt)

    earliest_slot = start_dt + timedelta(minutes=min(o for o, _ in offsets))
    if wake_dt > earliest_slot:
        raise RitualError(
            f"Wake time {wake_dt.strftime('%H:%M')} leaves no room for the "
            f"morning routine before a {start_dt.strftime('%H:%M')} start; "
            "pick an earlier wake time."
        )

    events: list[tuple[datetime, str]] = [(wake_dt, "Wake up")]
    for offset, label in offsets:
        events.append((start_dt + timedelta(minutes=offset), label))
    events.append((start_dt, f"Interview block ({interview_minutes} min)"))
    events.append((
        start_dt + timedelta(minutes=interview_minutes),
        "Post-interview debrief: write down questions asked, your answers, "
        "and notes for the thank-you email (15 min)",
    ))
    events.sort(key=lambda e: e[0])
    return events


def render_timeline(events: list[tuple[datetime, str]],
                    title: str = "INTERVIEW DAY TIMELINE") -> str:
    """Printable plain-ASCII rendering of the schedule."""
    lines = [title, "-" * 60]
    for when, label in events:
        lines.append(f"{when.strftime('%H:%M')} - {label}")
    lines.append("-" * 60)
    return "\n".join(lines)


def timeline_json(events: list[tuple[datetime, str]]) -> str:
    """JSON rendering: [{"time": isoformat, "label": ...}, ...]."""
    payload = [{"time": when.isoformat(), "label": label}
               for when, label in events]
    return json.dumps(payload, indent=2)


def parse_start(text: str, timezone: str | None = None) -> datetime:
    """Parse ``"2026-09-25 14:00"`` (or ISO) into a datetime.

    Attaches ``timezone`` (an IANA name like "America/New_York") when the
    parsed value is naive and a timezone is given.
    """
    text = (text or "").strip()
    start: datetime | None = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            start = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if start is None:
        try:
            start = datetime.fromisoformat(text)
        except ValueError:
            raise RitualError(
                f"Bad start {text!r}; expected 'YYYY-MM-DD HH:MM'"
            ) from None
    if start.tzinfo is None and timezone:
        try:
            start = start.replace(tzinfo=ZoneInfo(timezone))
        except ZoneInfoNotFoundError:
            raise RitualError(
                f"Unknown timezone {timezone!r}; use an IANA name like "
                "'America/New_York'"
            ) from None
    return start


# --- standalone CLI (the wired CLI lives elsewhere; this is a fallback) ------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ritual timeline")
    p.add_argument("--start", required=True,
                   help="'2026-09-25 14:00' (interview start)")
    p.add_argument("--round-type", required=True,
                   choices=list(ROUND_TYPES))
    p.add_argument("--timezone", default=None,
                   help="IANA name, e.g. America/New_York")
    p.add_argument("--wake", default=None, help="'07:30' override")
    p.add_argument("--duration", type=int, default=60,
                   help="Interview length in minutes (default 60)")
    p.add_argument("--json", action="store_true",
                   help="Emit JSON instead of text")
    a = p.parse_args(argv)
    try:
        start = parse_start(a.start, a.timezone)
        events = build_timeline(start, a.round_type, wake=a.wake,
                                interview_minutes=a.duration)
    except RitualError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(timeline_json(events))
    else:
        header = (f"INTERVIEW DAY TIMELINE - {start.strftime('%Y-%m-%d %H:%M')}"
                  + (f" {start.tzinfo}" if start.tzinfo else ""))
        print(render_timeline(events, title=header))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
