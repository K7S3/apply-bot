"""Interview scheduling helper: parse a pasted interview invite, then draft
a reply proposing your available time slots.

Stdlib only. Parsing is deliberately honest about uncertainty: the
result shows exactly what was extracted, and anything ambiguous comes
back as an explicit "please confirm" flag rather than a guess.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"])}

_DATE_RES = [
    # 2026-09-24 / 2026/09/24
    re.compile(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b"),
    # Sep 24 / September 24 / Sep 24th / Sep 24, 2026
    re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
               r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?"
               r"(?:\s*,?\s*(\d{4}))?", re.I),
    # weekday names on their own (for confirm flags, not dates)
    re.compile(r"\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
               r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b", re.I),
]

#: 2:30 PM / 2pm / 14:30 / 2.30pm
_TIME_RE = re.compile(
    r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b", re.I)
_TIME24_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")

_TZ_ABBR_RE = re.compile(
    r"\b(PT|PST|PDT|ET|EST|EDT|CT|CST|CDT|MT|MST|MDT|GMT|UTC|CET)\b")
_TZ_NAME_RE = re.compile(
    r"\b(Eastern|Central|Mountain|Pacific|Atlantic|Alaska|Hawaii-Aleutian)"
    r"(?:\s+Time)?\b", re.I)
_TZ_IANA_RE = re.compile(r"\bAmerica/(New_York|Chicago|Denver|Los_Angeles|"
                         r"Anchorage|Honolulu)\b")

_DURATION_RE = re.compile(
    r"\b(\d{1,3})\s*(?:-|–)?\s*(min(?:ute)?s?|hr|hour)s?\b", re.I)

_VIDEO_HOSTS = ("zoom.us", "meet.google.com", "teams.microsoft.com",
                "webex.com", "gotomeeting.com", "bluejeans.com",
                "chime.aws", "whereby.com")
_URL_RE = re.compile(r"https?://[^\s)>\"']+")

#: "interviewer: Jane Doe" / "with Jane Doe" / "you'll meet Jane Doe"
_NAME_RE = re.compile(
    r"(?:interviewer(?:s)?|panelist(?:s)?|with|meet(?:ing)?(?:\s+with)?|"
    r"speak(?:ing)?\s+with|hosted\s+by)\s*:?\s*"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z'.-]+)+)", re.I)


class SchedulingError(Exception):
    """Raised for invalid scheduling operations."""


def _extract_dates(text: str, today: date) -> tuple[list[str], list[str]]:
    """Return (iso dates, confirm flags). Year-less dates resolve to the
    next occurrence on or after ``today`` and get flagged to confirm."""
    dates: list[str] = []
    flags: list[str] = []
    for rx in _DATE_RES[:2]:
        for m in rx.finditer(text or ""):
            g = m.groups()
            try:
                if len(g[0]) == 4 and g[0][0].isdigit():
                    y, mo, d = int(g[0]), int(g[1]), int(g[2])
                    assumed_year = False
                else:
                    mo = _MONTHS.get(g[0][:3].lower(), 0)
                    d = int(g[1])
                    y = int(g[2]) if len(g) > 2 and g[2] else None
                    if y is None:
                        if mo and 1 <= d <= 31:
                            y = today.year
                            cand = date(y, mo, d)
                            if cand < today:
                                y += 1
                            assumed_year = True
                        else:
                            continue
                    elif y < 2000 or y > 2100:
                        continue
                    else:
                        assumed_year = False
                dt = date(y, mo, d)
            except (ValueError, IndexError, TypeError):
                continue
            iso = dt.isoformat()
            if iso not in dates:
                dates.append(iso)
            if assumed_year:
                flags.append(
                    f"Date '{m.group(0).strip()}' has no year — assumed "
                    f"{iso}; please confirm the year is right."
                )
    # weekday mentions without an attached date can't be resolved reliably
    weekdays = {m.group(0).capitalize() for m in _DATE_RES[2].finditer(text or "")}
    if weekdays and not dates:
        flags.append(
            f"Found weekday mention(s) {sorted(weekdays)} but no calendar "
            "date — please confirm the actual date."
        )
    return dates, flags


def _extract_times(text: str) -> list[str]:
    found: list[str] = []
    for m in _TIME_RE.finditer(text or ""):
        raw = m.group(0).strip()
        if raw not in found:
            found.append(raw)
    if not found:
        for m in _TIME24_RE.finditer(text or ""):
            raw = m.group(0).strip()
            if raw not in found:
                found.append(raw)
    return found


def _extract_timezones(text: str) -> list[str]:
    found: list[str] = []
    for rx in (_TZ_ABBR_RE, _TZ_NAME_RE, _TZ_IANA_RE):
        for m in rx.finditer(text or ""):
            raw = m.group(0).strip()
            if raw not in found:
                found.append(raw)
    return found


def _extract_links(text: str) -> list[str]:
    found: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,;")
        if url not in found:
            found.append(url)
    video = [u for u in found if any(h in u for h in _VIDEO_HOSTS)]
    return video


def _extract_interviewers(text: str) -> list[str]:
    found: list[str] = []
    for m in _NAME_RE.finditer(text or ""):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .,;")
        parts = name.split()
        if len(parts) >= 2 and name not in found:
            found.append(name)
    return found


def _extract_duration(text: str) -> int | None:
    m = _DURATION_RE.search(text or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if n > 480:  # not a plausible interview length; likely a phone number
        return None
    return n * 60 if unit.startswith("h") else n


def parse_invite(text: str, *, today: date | None = None) -> dict:
    """Parse pasted invite text into structured fields.

    Returns a dict with keys: dates, times, timezones, interviewers,
    video_links, duration_minutes, needs_confirm (list of strings).

    Anything the text doesn't pin down shows up in ``needs_confirm``
    instead of being guessed.
    """
    if not (text or "").strip():
        raise SchedulingError(
            "No invite text to parse. Paste the invite, pass --file, or pipe "
            "it in.\nNext: run `python -m candid schedule parse --help`."
        )
    today = today or date.today()
    dates, date_flags = _extract_dates(text, today)
    times = _extract_times(text)
    timezones = _extract_timezones(text)
    interviewers = _extract_interviewers(text)
    links = _extract_links(text)
    duration = _extract_duration(text)

    needs_confirm: list[str] = []
    needs_confirm.extend(date_flags)
    if not dates:
        needs_confirm.append("No calendar date found — please confirm the date.")
    if not times:
        needs_confirm.append("No time found — please confirm the time.")
    elif len(times) > 2:
        needs_confirm.append(
            f"Found several times {times}; the invite may list options — "
            "please confirm which one applies."
        )
    if not timezones:
        needs_confirm.append(
            "No timezone found — please confirm the timezone before you accept."
        )
    if not interviewers:
        needs_confirm.append(
            "No interviewer name found — please confirm who you're meeting."
        )
    elif len(interviewers) > 3:
        needs_confirm.append(
            f"Found {len(interviewers)} possible names; only the ones that "
            "look like interviewers are kept — please confirm the panel."
        )
    if not links and re.search(r"(?i)\b(video|virtual|remote|zoom|meet|teams)\b", text):
        needs_confirm.append(
            "The invite mentions a virtual meeting but no video link was "
            "found — please confirm the link."
        )
    if duration is None:
        needs_confirm.append(
            "No duration found — please confirm how long the interview runs."
        )

    return {
        "dates": dates,
        "times": times,
        "timezones": timezones,
        "interviewers": interviewers,
        "video_links": links,
        "duration_minutes": duration,
        "needs_confirm": needs_confirm,
    }


def render_parse(parsed: dict) -> str:
    """Human-readable view of parse_invite() output."""
    def line(label: str, value) -> str:
        return f"{label}: {value if value not in ([], None, '') else '(not found)'}"

    dur = parsed.get("duration_minutes")
    lines = [
        "📅 Parsed interview invite:",
        line("  dates", ", ".join(parsed.get("dates", []))),
        line("  times", ", ".join(parsed.get("times", []))),
        line("  timezones", ", ".join(parsed.get("timezones", []))),
        line("  interviewers", ", ".join(parsed.get("interviewers", []))),
        line("  video_links", ", ".join(parsed.get("video_links", []))),
        line("  duration_minutes", dur if dur is not None else ""),
        "",
    ]
    flags = parsed.get("needs_confirm", [])
    if flags:
        lines.append("⚠️  Please confirm:")
        lines.extend(f"  • {f}" for f in flags)
    else:
        lines.append("✅ Everything resolved — no ambiguities.")
    return "\n".join(lines)


def reply_draft(name: str, *, interviewer: str = "", role: str = "",
                company: str = "", slots: list[str] | None = None,
                parsed: dict | None = None, greeting: str = "Hi") -> str:
    """Draft a reply proposing 2–3 time slots you supply.

    ``slots`` are free-form strings like "Tue 2–4pm ET". The draft
    echoes back what the invite said (if ``parsed`` is given) so the
    recruiter can spot a mismatch.
    """
    slots = slots or []
    if not slots:
        raise SchedulingError(
            "No time slots given: pass at least one with --slots. "
            "Next: run `python -m candid schedule reply --help`."
        )
    if len(slots) > 3:
        raise SchedulingError(
            f"Got {len(slots)} slots — keep it to 3 at most. "
            "Next: run `python -m candid schedule reply --help`."
        )
    who = interviewer or "there"
    subject_bits = [p for p in (role, company) if p]
    subject = "Re: Interview scheduling" + (
        f" — {' @ '.join(subject_bits)}" if subject_bits else "")

    echo = ""
    if parsed:
        bits = []
        if parsed.get("dates"):
            bits.append("date: " + ", ".join(parsed["dates"]))
        if parsed.get("times"):
            bits.append("time: " + ", ".join(parsed["times"]))
        if parsed.get("timezones"):
            bits.append("timezone: " + ", ".join(parsed["timezones"]))
        if bits:
            echo = ("Just to confirm I read your invite right — " +
                    "; ".join(bits) + ". ")

    slot_lines = "\n".join(f"  • {s}" for s in slots)
    return (
        f"Subject: {subject}\n\n"
        f"{greeting} {who},\n\n"
        f"Thanks for the invite! {echo}Here are some times that work for me:\n\n"
        f"{slot_lines}\n\n"
        "If none of these work, I'm happy to find another time.\n\n"
        f"Best,\n{name}"
    )


def read_source(source: str | None = None, file: str | None = None,
                stdin_text: str | None = None) -> str:
    """Resolve invite text: ``source`` may be a file path, literal text, or
    empty (fall back to stdin_text). Raises SchedulingError with guidance."""
    if file:
        try:
            return open(file, encoding="utf-8").read()
        except OSError as exc:
            raise SchedulingError(
                f"Could not read file '{file}': {exc}. "
                "Next: run `python -m candid schedule parse --help`."
            ) from exc
    if source:
        try:
            if len(source) < 1024 and "\n" not in source.strip():
                import os as _os
                if _os.path.exists(source):
                    return open(source, encoding="utf-8").read()
        except OSError:
            pass
        return source
    if stdin_text and stdin_text.strip():
        return stdin_text
    raise SchedulingError(
        "No invite text to parse. Paste the invite, pass --file, or pipe "
        "it in.\nNext: run `python -m candid schedule parse --help`."
    )


__all__ = ["parse_invite", "render_parse", "reply_draft", "read_source",
           "SchedulingError"]
