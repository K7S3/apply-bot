"""Recruiter relationship manager: response analytics and reply-worthiness scoring.

Read-only module. All data comes from JSON files under the candid data dir
(``CANDID_DATA_DIR`` env override or ``candid/config.py``'s ``DATA_DIR``).
Nothing here writes any files.

Expected storage formats (fictional example values only):

``recruiters.json`` - one entry per recruiter keyed by name::

    {
        "Maya Chen": {"kind": "inhouse", "company": "Fictional Corp",
                      "email": "maya@example.test"},
        "Sam Rivers": {"kind": "agency", "firm": "Fictional Staffing"}
    }

``kind`` is ``"inhouse"`` or ``"agency"``. Unknown or missing kinds are
reported as ``None`` in scorecards and are left out of the group comparison.

``recruiter_threads.json`` - logged outreach touches keyed by recruiter name::

    {
        "Maya Chen": [
            {"date": "2026-09-01", "channel": "email", "replied": true,
             "note": "Intro call booked"},
            {"date": "2026-09-12", "channel": "linkedin", "replied": false}
        ]
    }

A touch may carry ``"replied": true/false``. Touches without the flag count
as unreplied. ``date`` should be ISO ``YYYY-MM-DD`` (a full ISO datetime is
also accepted). A top-level list of touch dicts, each carrying a
``"recruiter"`` key, is accepted as well for forward compatibility.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import candid.config as C

RECRUITERS_PATH = "recruiters.json"
THREADS_PATH = "recruiter_threads.json"

# Scoring weights. Kept as module constants so the formula stays visible.
_W_RESPONSE_RATE = 50.0   # fraction of touches that got a reply, times 50
_W_RECENCY = 20.0         # recent touches score higher, linearly down to 0
_W_INHOUSE = 15.0         # flat bonus for in-house recruiters
_W_VOLUME = 15.0          # more logged history = more confidence, capped
_RECENCY_WINDOW_DAYS = 90  # touches older than this get no recency points
_VOLUME_CAP = 10           # touches beyond this add no more volume points


def _data_dir() -> Path:
    """Resolve the data dir, honoring the CANDID_DATA_DIR test override."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _load_json(name: str) -> Any:
    path = _data_dir() / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _threads_data() -> dict[str, list[dict[str, Any]]]:
    """Normalize thread storage to {recruiter: [touch, ...]}."""
    raw = _load_json(THREADS_PATH)
    if isinstance(raw, dict):
        return {str(k): list(v) for k, v in raw.items() if isinstance(v, list)}
    if isinstance(raw, list):
        grouped: dict[str, list[dict[str, Any]]] = {}
        for touch in raw:
            if isinstance(touch, dict) and touch.get("recruiter"):
                grouped.setdefault(str(touch["recruiter"]), []).append(touch)
        return grouped
    return {}


def _recruiters_data() -> dict[str, dict[str, Any]]:
    raw = _load_json(RECRUITERS_PATH)
    if isinstance(raw, dict):
        return {str(k): (v if isinstance(v, dict) else {}) for k, v in raw.items()}
    if isinstance(raw, list):
        # recruiter_contacts stores a list of profile dicts with a "name" key.
        out: dict[str, dict[str, Any]] = {}
        for rec in raw:
            if isinstance(rec, dict) and rec.get("name"):
                out[str(rec["name"])] = rec
        return out
    return {}


def _today(today: Optional[date] = None) -> date:
    return today or date.today()


def _parse_touch_date(touch: dict[str, Any]) -> Optional[date]:
    value = touch.get("date")
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def touches_for(recruiter: str) -> list[dict[str, Any]]:
    """All logged touches for a recruiter, newest first. Empty list if none."""
    touches = list(_threads_data().get(recruiter, []))
    touches.sort(
        key=lambda t: (_parse_touch_date(t) or date.min),
        reverse=True,
    )
    return touches


def recruiter_kind(recruiter: str) -> Optional[str]:
    """'inhouse' or 'agency' from recruiters.json, else None."""
    kind = _recruiters_data().get(recruiter, {}).get("kind")
    kind = str(kind).strip().lower() if kind is not None else None
    return kind if kind in ("inhouse", "agency") else None


def response_rate(recruiter: str) -> Optional[float]:
    """Fraction of logged touches that got a reply.

    A touch counts as replied only when it carries ``"replied": true``.
    Returns None when the recruiter has zero logged touches (no division
    by zero, and no fabricated rate).
    """
    touches = touches_for(recruiter)
    if not touches:
        return None
    replies = sum(1 for t in touches if t.get("replied") is True)
    return replies / len(touches)


def days_since_last_touch(recruiter: str, today: Optional[date] = None) -> Optional[int]:
    """Days between today and the recruiter's most recent dated touch.

    Returns None when there are no touches or none carry a parseable date.
    """
    day = _today(today)
    dates = [
        d for d in (_parse_touch_date(t) for t in touches_for(recruiter)) if d
    ]
    if not dates:
        return None
    return max(0, (day - max(dates)).days)


def _worth_replying(rr: Optional[float], days: Optional[int], kind: Optional[str],
                    total: int) -> float:
    """Composite 0-100 score. Weights: response rate 50%, recency 20%,
    in-house bonus 15%, volume 15% (capped at 10 touches).

    - Response rate: (replies / total_touches) * 50. No touches -> 0.
    - Recency: 20 * (1 - days_since_last_touch / 90), floored at 0, so a
      touch today scores 20 and one 90+ days old scores 0. No dated
      touch -> 0.
    - In-house bonus: +15 when kind == "inhouse", else 0.
    - Volume: 15 * min(total_touches, 10) / 10, so confidence grows with
      history but caps once 10 touches are logged.
    Deterministic: same inputs always give the same score.
    """
    rate_part = (rr or 0.0) * _W_RESPONSE_RATE
    if days is None:
        recency_part = 0.0
    else:
        recency_part = _W_RECENCY * max(0.0, 1.0 - days / _RECENCY_WINDOW_DAYS)
    inhouse_part = _W_INHOUSE if kind == "inhouse" else 0.0
    volume_part = _W_VOLUME * min(total, _VOLUME_CAP) / _VOLUME_CAP
    return round(min(100.0, max(0.0, rate_part + recency_part + inhouse_part
                                + volume_part)), 2)


def scorecard(recruiter: str, today: Optional[date] = None) -> dict[str, Any]:
    """Per-recruiter card: response rate, counts, recency, kind, and the
    composite worth_replying score (see _worth_replying docstring)."""
    touches = touches_for(recruiter)
    rr = response_rate(recruiter)
    kind = recruiter_kind(recruiter)
    days = days_since_last_touch(recruiter, today=today)
    replies = sum(1 for t in touches if t.get("replied") is True)
    return {
        "recruiter": recruiter,
        "response_rate": rr,
        "total_touches": len(touches),
        "replies": replies,
        "days_since_last_touch": days,
        "kind": kind,
        "worth_replying": _worth_replying(rr, days, kind, len(touches)),
    }


def all_recruiters() -> list[str]:
    """Every known recruiter name: union of recruiters.json and threads."""
    return sorted(set(_recruiters_data()) | set(_threads_data()))


def rank_recruiters(limit: Optional[int] = None,
                    today: Optional[date] = None) -> list[dict[str, Any]]:
    """All recruiters sorted by worth_replying desc, ties broken by name.

    limit truncates to the top N (None means all).
    """
    cards = [scorecard(name, today=today) for name in all_recruiters()]
    cards.sort(key=lambda c: (-c["worth_replying"], c["recruiter"]))
    if limit is not None:
        cards = cards[: max(0, limit)]
    return cards


def _group_stats(kind: str, today: Optional[date]) -> dict[str, Any]:
    names = [n for n in all_recruiters() if recruiter_kind(n) == kind]
    rates = [r for r in (response_rate(n) for n in names) if r is not None]
    scores = [scorecard(n, today=today)["worth_replying"] for n in names]
    return {
        "count": len(names),
        "avg_response_rate": (round(sum(rates) / len(rates), 4)
                              if rates else None),
        "avg_worth_replying": (round(sum(scores) / len(scores), 2)
                               if scores else None),
    }


def agency_vs_inhouse(today: Optional[date] = None) -> dict[str, dict[str, Any]]:
    """Aggregate comparison of agency vs in-house recruiters.

    Always returns both groups; a group with no recruiters reports count 0
    and None averages instead of raising or fabricating numbers. Recruiters
    whose kind is unknown appear in neither group.
    """
    return {
        "agency": _group_stats("agency", today),
        "inhouse": _group_stats("inhouse", today),
    }
