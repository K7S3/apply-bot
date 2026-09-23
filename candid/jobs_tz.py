"""Timezone overlap analysis for remote job postings.

Pure functions (stdlib only: ``re``, ``os``, ``datetime``, ``zoneinfo``)
that infer a posting's required timezone overlap window from its text and
measure how many working hours that window shares with the user's home
timezone.

Conventions follow the rest of the candid package: module docstring,
``from __future__ import annotations``, typed signatures, and small
single-purpose functions. No network, no config writes — only
``home_tz_from_config`` reads user settings, and it never raises.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# inference: text -> required overlap window
# ---------------------------------------------------------------------------

#: Window dict shape: {"label", "utc_offsets", "confidence"}.
#: ``utc_offsets`` is a (lo, hi) tuple of whole/fractional UTC offsets, or
#: None when the text says nothing usable.

_CITY_OFFSETS: dict[str, float] = {
    # UTC+0
    "london": 0, "dublin": 0, "lisbon": 0, "reykjavik": 0,
    # UTC+1
    "berlin": 1, "paris": 1, "amsterdam": 1, "madrid": 1, "rome": 1,
    "zurich": 1, "stockholm": 1, "oslo": 1, "copenhagen": 1, "brussels": 1,
    # US / Canada
    "new york": -5, "nyc": -5, "boston": -5, "toronto": -5, "miami": -5,
    "atlanta": -5, "washington": -5, "philadelphia": -5,
    "chicago": -6, "austin": -6, "dallas": -6, "houston": -6,
    "mexico city": -6,
    "denver": -7, "phoenix": -7, "salt lake city": -7,
    "los angeles": -8, "san francisco": -8, "seattle": -8,
    "vancouver": -8, "portland": -8, "las vegas": -8, "san diego": -8,
    "anchorage": -9, "honolulu": -10,
    # Asia-Pacific
    "singapore": 8, "hong kong": 8, "beijing": 8, "shanghai": 8,
    "perth": 8, "taipei": 8, "kuala lumpur": 8, "manila": 8,
    "tokyo": 9, "seoul": 9, "osaka": 9,
    "sydney": 11, "melbourne": 11, "brisbane": 10,
    "auckland": 13,
    # South Asia / Middle East
    "mumbai": 5.5, "bangalore": 5.5, "bengaluru": 5.5, "delhi": 5.5,
    "chennai": 5.5, "hyderabad": 5.5, "pune": 5.5, "kolkata": 5.5,
    "dubai": 4, "abu dhabi": 4,
}

# (pattern, (lo, hi), label, confidence) — checked in order after the
# GMT-literal and overlap-with-city rules below.
_REGION_PATTERNS: list[tuple[str, tuple[float, float], str, str]] = [
    (r"pst\s*[-–/]\s*est", (-8, -4), "US timezones (UTC-8 to UTC-4)", "high"),
    (r"\bpt\s*(?:to|[-–/])\s*et\b", (-8, -4), "US timezones (UTC-8 to UTC-4)", "high"),
    (r"pacific\s*(?:to|[-–/])\s*eastern", (-8, -4), "US timezones (UTC-8 to UTC-4)", "high"),
    (r"\bus\b[\w\s,.'-]{0,40}\btime\s*zones?\b", (-8, -4), "US timezones (UTC-8 to UTC-4)", "high"),
    (r"\bus\s+(?:business\s+)?hours\b", (-8, -4), "US hours (UTC-8 to UTC-4)", "medium"),
    (r"\bamericas\b", (-8, -4), "Americas (UTC-8 to UTC-4)", "medium"),
    (r"\bemea\b", (0, 4), "EMEA (UTC+0 to UTC+4)", "medium"),
    (r"\bcet\b", (0, 4), "CET region (UTC+0 to UTC+4)", "medium"),
    (r"\beurope\b", (0, 4), "Europe (UTC+0 to UTC+4)", "medium"),
    (r"\bapac\b", (8, 12), "APAC (UTC+8 to UTC+12)", "medium"),
    (r"\banywhere\b", (-12, 14), "remote, anywhere (UTC-12 to UTC+14)", "medium"),
    (r"\bworldwide\b", (-12, 14), "remote, anywhere (UTC-12 to UTC+14)", "medium"),
    (r"\basync(?:hronous)?\b", (-12, 14), "remote, async (UTC-12 to UTC+14)", "medium"),
]

_GMT_RANGE_RE = re.compile(
    r"\b(?:gmt|utc)\s*([+-]\s*\d+(?:\.\d+)?)\s*(?:to|-|–|/|until)\s*"
    r"(?:(?:gmt|utc)\s*)?([+-]\s*\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_GMT_SINGLE_RE = re.compile(
    r"\b(?:gmt|utc)\s*([+-]\s*\d+(?:\.\d+)?)\b", re.IGNORECASE
)
_OVERLAP_CITY_RE = re.compile(
    r"\boverlap\b[^.\n]{0,80}?\bwith\s+([a-zA-Z][a-zA-Z .'\-]{1,40})",
    re.IGNORECASE,
)


def _num(tok: str) -> float:
    return float(tok.replace(" ", ""))


def _unknown() -> dict:
    return {"label": "unknown", "utc_offsets": None, "confidence": "low"}


def infer_tz_window(location: str, description: str = "") -> dict:
    """Infer the required timezone overlap from posting text.

    Returns ``{"label", "utc_offsets", "confidence"}`` where ``utc_offsets``
    is a ``(lo, hi)`` tuple of UTC offsets (or None when nothing usable is
    found) and confidence is one of "high"/"medium"/"low".
    """
    text = f"{location or ''} {description or ''}".lower()

    # 1. Explicit GMT/UTC literals, e.g. "GMT-5 to GMT+3", "UTC+8".
    m = _GMT_RANGE_RE.search(text)
    if m:
        lo, hi = sorted((_num(m.group(1)), _num(m.group(2))))
        return {"label": f"UTC{lo:g} to UTC{hi:g}",
                "utc_offsets": (lo, hi), "confidence": "high"}
    m = _GMT_SINGLE_RE.search(text)
    if m:
        off = _num(m.group(1))
        return {"label": f"UTC{off:g}", "utc_offsets": (off, off),
                "confidence": "high"}

    # 2. "overlap with <city>" against a small city -> offset table.
    m = _OVERLAP_CITY_RE.search(text)
    if m:
        mention = m.group(1).lower()
        for city, off in _CITY_OFFSETS.items():
            if city in mention:
                pretty = city.title()
                return {"label": f"overlap with {pretty} (UTC{off:g})",
                        "utc_offsets": (off, off), "confidence": "high"}

    # 3. Region shorthands.
    for pattern, offsets, label, confidence in _REGION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {"label": label, "utc_offsets": offsets,
                    "confidence": confidence}

    return _unknown()


# ---------------------------------------------------------------------------
# overlap math
# ---------------------------------------------------------------------------

#: Reference date used to resolve a home timezone's UTC offset. Fixed so
#: results are deterministic regardless of when the analysis runs.
_REF_DATE = date(2026, 1, 15)

_WORK_START = 9.0   # local working day starts at 9:00
_WORK_END = 17.0    # ... and ends at 17:00


def _home_offset_hours(home_tz: str) -> float:
    """UTC offset in hours of ``home_tz`` on the reference date.

    Raises ValueError for an unknown/invalid timezone name.
    """
    if ZoneInfo is None:  # pragma: no cover
        raise ValueError(f"zoneinfo is unavailable on this Python; "
                         f"cannot resolve timezone {home_tz!r}")
    try:
        tz = ZoneInfo(home_tz)
    except Exception as exc:
        raise ValueError(f"Unknown timezone {home_tz!r}: {exc}") from exc
    noon = datetime(_REF_DATE.year, _REF_DATE.month, _REF_DATE.day, 12,
                    tzinfo=tz)
    off = noon.utcoffset()
    if off is None:
        raise ValueError(f"Timezone {home_tz!r} has no UTC offset")
    return off.total_seconds() / 3600.0


def working_overlap_hours(home_tz: str, window: dict) -> int:
    """Working hours shared between ``home_tz`` and the required window.

    Both sides are assumed to work 9:00-17:00 local. The required window
    is approximated as the UTC interval ``[9 + lo, 17 + hi)`` and the home
    working day as ``[9 + home_offset, 17 + home_offset)``; the overlap of
    the two intervals is the shared working time. Returns an int 0..8.

    Raises ValueError for an invalid ``home_tz`` or a window with no
    usable UTC offsets.
    """
    offsets = window.get("utc_offsets") if isinstance(window, dict) else None
    if not offsets:
        raise ValueError("tz window has no usable UTC offsets")
    lo, hi = float(offsets[0]), float(offsets[1])
    if lo > hi:
        lo, hi = hi, lo

    oh = _home_offset_hours(home_tz)
    home_start, home_end = _WORK_START + oh, _WORK_END + oh
    win_start, win_end = _WORK_START + lo, _WORK_END + hi
    overlap = min(home_end, win_end) - max(home_start, win_start)
    hours = int(round(max(0.0, overlap)))
    return max(0, min(8, hours))


def overlap_verdict(hours: int) -> str:
    """Qualitative verdict for an overlap-hours count."""
    if hours >= 5:
        return "strong"
    if hours >= 3:
        return "workable"
    if hours >= 1:
        return "tight"
    return "none"


# ---------------------------------------------------------------------------
# job enrichment + home timezone resolution
# ---------------------------------------------------------------------------

def enrich_with_tz(job: dict, home_tz: str) -> dict:
    """Return a copy of ``job`` with tz-window fields added.

    Adds ``tz_window`` (the infer_tz_window dict), ``tz_overlap_hours``
    (int) and ``tz_verdict`` (str). The input dict is never mutated. Jobs
    whose window cannot be inferred get 0 hours and a "none" verdict.
    """
    enriched = dict(job)
    window = infer_tz_window(job.get("location", "") or "",
                             job.get("description", "") or "")
    enriched["tz_window"] = window
    if window["utc_offsets"] is None:
        enriched["tz_overlap_hours"] = 0
        enriched["tz_verdict"] = "none"
    else:
        hours = working_overlap_hours(home_tz, window)
        enriched["tz_overlap_hours"] = hours
        enriched["tz_verdict"] = overlap_verdict(hours)
    return enriched


def home_tz_from_config() -> str:
    """Resolve the user's home timezone.

    Order: ``home_timezone`` key in the candid config, then the ``TZ``
    environment variable, then ``America/New_York``. Never raises — a
    missing or unreadable config simply falls through to the next source.
    """
    try:
        from candid import config as C
        cfg = C.load_config() or {}
        val = cfg.get("home_timezone")
        if val:
            return str(val)
    except Exception:
        pass
    env_tz = os.environ.get("TZ")
    if env_tz:
        return env_tz
    return "America/New_York"
