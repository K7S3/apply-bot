"""Remote-job curation filters for the job curation pipeline.

Pure functions only: no network, no filesystem, no side effects. They sit
beside the normalization + ``_filter_rank`` helpers in ``candid/jobs.py``
(which stays untouched) and give the curator a stricter remote-only view
plus remote-friendliness signals for ranking.

Bucket vocabulary from :func:`normalize_remote_location`:
``anywhere`` / ``us-only`` / ``americas`` / ``emea`` / ``europe`` /
``apac`` / ``hybrid`` / ``onsite`` / ``unknown``.
"""

from __future__ import annotations

import re

__all__ = [
    "normalize_remote_location",
    "remote_only_filter",
    "remote_keyword_boost",
    "remote_rank_adjust",
]


# ---------------------------------------------------------------------------
# remote location normalization
# ---------------------------------------------------------------------------

def _word(pattern: str) -> re.Pattern[str]:
    """Compile a case-insensitive word-boundary regex."""
    return re.compile(r"\b" + pattern + r"\b", re.IGNORECASE)


# Checked in order; first bucket with any matching pattern wins. Hybrid and
# onsite come first because a location string like "Remote / hybrid" or
# "New York (On-site)" must not land in a remote bucket.
_BUCKET_RULES: list[tuple[str, tuple[re.Pattern[str], ...]]] = [
    ("hybrid", (
        _word(r"hybrid"),
    )),
    ("onsite", (
        _word(r"on-?site"),
        _word(r"in[- ]office"),
        _word(r"office[- ]based"),
        _word(r"in[- ]person"),
        _word(r"work[- ]from[- ]office"),
        _word(r"must be in the office"),
    )),
    ("anywhere", (
        _word(r"worldwide"),
        _word(r"anywhere"),
        _word(r"global"),
        _word(r"remotely"),
        _word(r"work from anywhere"),
        _word(r"fully remote"),
        _word(r"100% remote"),
        _word(r"remote[-\s]?first"),
        _word(r"remote[-\s]?friendly"),
        _word(r"location[- ]independent"),
        _word(r"no[-\s]?location"),
    )),
    ("us-only", (
        _word(r"remote[- ]?(in|within|for|from)?[- ]?(the[-\s]?)?u\.?s\.?"),
        _word(r"u\.?s\.?[-\s]?remote"),
        _word(r"u\.?s\.?[- ]?only"),
        _word(r"united states( of america)?( only)?"),
        _word(r"u\.?s\.?(a\.?)?"),
        _word(r"usa"),
        _word(r"\bus\b"),
        _word(r"us[-\s]?based"),
        _word(r"american"),
    )),
    ("americas", (
        _word(r"americas"),
        _word(r"north america"),
        _word(r"south america"),
        _word(r"latin america"),
        _word(r"latam"),
        _word(r"the americas"),
    )),
    ("emea", (
        _word(r"emea"),
    )),
    ("europe", (
        _word(r"europe"),
        _word(r"european( union)?"),
        _word(r"\beu\b"),
        _word(r"eu[-\s]?only"),
        _word(r"eu[-\s]?based"),
        _word(r"united kingdom"),
        _word(r"\buk\b"),
    )),
    ("apac", (
        _word(r"apac"),
        _word(r"asia[- ]?pacific"),
        _word(r"\basia\b"),
        _word(r"australia"),
        _word(r"anz"),
    )),
]

_BARE_REMOTE = _word(r"remote")
# Pure-remote qualifiers that may accompany a bare "remote" without adding a
# city or region (e.g. "Remote only"). Anything else alongside "remote"
# (like "New York (Remote)") means a residency requirement we cannot infer.
_BARE_REMOTE_QUALIFIERS = re.compile(
    r"\b(only|first|friendly|fully|100%?|workforce|position|role|job|jobs)\b",
    re.IGNORECASE)


def normalize_remote_location(location: str) -> str:
    """Canonicalize a free-text location into a remote bucket.

    Returns one of ``anywhere`` / ``us-only`` / ``americas`` / ``emea`` /
    ``europe`` / ``apac`` / ``hybrid`` / ``onsite`` / ``unknown``.

    Matching is case-insensitive. A bare ``"Remote"`` (no qualifier) maps
    to ``"anywhere"`` since nothing constrains it; a city-anchored remote
    like ``"New York (Remote)"`` maps to ``"unknown"`` because the
    residency requirement cannot be inferred safely. ``hybrid`` and
    ``onsite`` take precedence over any remote qualifier in the same
    string.
    """
    s = (location or "").strip()
    if not s:
        return "unknown"
    for bucket, patterns in _BUCKET_RULES:
        if any(p.search(s) for p in patterns):
            return bucket
    if _BARE_REMOTE.search(s):
        # "Remote" alone is unconstrained; "New York (Remote)" names a place
        # we cannot infer a residency rule from, so it is unknown.
        cleaned = _BARE_REMOTE.sub("", s)
        cleaned = _BARE_REMOTE_QUALIFIERS.sub("", cleaned)
        cleaned = re.sub(r"[^a-z0-9]", "", cleaned, flags=re.IGNORECASE)
        return "anywhere" if not cleaned else "unknown"
    return "unknown"


# ---------------------------------------------------------------------------
# strict remote-only filter
# ---------------------------------------------------------------------------

_EXCLUDED_BUCKETS = {"onsite", "unknown"}


def remote_only_filter(jobs: list[dict]) -> list[dict]:
    """Keep only unambiguous remote jobs.

    A job survives when its ``remote`` flag is truthy AND its normalized
    location bucket is a genuine remote bucket (``anywhere``, ``us-only``,
    ``americas``, ``emea``, ``europe``, ``apac``). Hybrid/onsite/unknown
    locations are dropped even when ``remote`` is True — that is the
    strictness this filter exists for.
    """
    out = []
    for job in jobs:
        if not job.get("remote"):
            continue
        bucket = normalize_remote_location(str(job.get("location") or ""))
        if bucket in _EXCLUDED_BUCKETS:
            continue
        out.append(job)
    return out


# ---------------------------------------------------------------------------
# remote-friendliness boost
# ---------------------------------------------------------------------------

_POSITIVE_SIGNALS: tuple[tuple[re.Pattern[str], float], ...] = (
    (_word(r"work from anywhere"), 0.30),
    (_word(r"remote[-\s]?first"), 0.25),
    (_word(r"fully remote"), 0.25),
    (_word(r"distributed team"), 0.20),
    (_word(r"async(hronous)?"), 0.20),
    (_word(r"no office"), 0.15),
    (_word(r"home office stipend"), 0.15),
    (_word(r"remote stipend"), 0.15),
    (_word(r"flexible hours"), 0.10),
    (_word(r"flexible schedule"), 0.10),
)

_RED_FLAGS: tuple[tuple[re.Pattern[str], float], ...] = (
    (_word(r"must be in (the )?office"), 0.40),
    (_word(r"hybrid \d+ days?"), 0.30),
    (_word(r"return to office"), 0.30),
    (_word(r"rto"), 0.25),
    (_word(r"on[- ]site \d+ days?"), 0.30),
    (_word(r"commute to"), 0.20),
    (_word(r"in[- ]office \d+"), 0.20),
)

_MAX_BOOST = 10.0  # boost points added to a 0..100 score at full strength


def remote_keyword_boost(title: str, description: str) -> float:
    """Remote-friendliness bonus in ``0.0..1.0``.

    Each positive signal contributes its weight once (phrase presence, not
    count), so adding more remote-friendly text can only raise the boost.
    Red-flag phrases ("must be in office", "hybrid 3 days") subtract, and
    the result is clamped to ``0.0..1.0``.
    """
    text = f"{title or ''}\n{description or ''}"
    boost = 0.0
    for pattern, weight in _POSITIVE_SIGNALS:
        if pattern.search(text):
            boost += weight
    for pattern, weight in _RED_FLAGS:
        if pattern.search(text):
            boost -= weight
    return min(1.0, max(0.0, boost))


# ---------------------------------------------------------------------------
# score adjustment
# ---------------------------------------------------------------------------

def remote_rank_adjust(score: float, job: dict) -> float:
    """Combine a base ``score`` (0..100) with the remote boost.

    ``boost * _MAX_BOOST`` points are added (full strength = +10), then the
    result is clamped to ``0..100``. Jobs without remote-friendly text are
    unchanged.
    """
    boost = remote_keyword_boost(
        job.get("title", ""), job.get("description", ""))
    adjusted = float(score) + boost * _MAX_BOOST
    return min(100.0, max(0.0, adjusted))
