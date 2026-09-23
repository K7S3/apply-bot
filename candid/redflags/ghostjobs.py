"""Posting-integrity detectors (category ``posting-integrity``).

Flags postings that may not represent a real job: evergreen / talent-pool
postings with no open headcount, multi-level-marketing schemes, and
too-good-to-be-true offers. Also provides :func:`find_reposts`, a plain
(offline, unregistered) helper that groups likely reposted listings.

All detectors are offline, case-insensitive, and return ``[]`` for
empty/``None`` input.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .core import Flag, register

CATEGORY = "posting-integrity"

_SNIPPET_CHARS = 120


def _text(value: str | None) -> str:
    """Normalize detector input; ``None`` becomes the empty string."""
    return value or ""


def _snippet(text: str, match: re.Match, radius: int = 60) -> str:
    """Quoted evidence around a regex match, trimmed to ~120 chars."""
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    if len(snippet) > _SNIPPET_CHARS:
        snippet = snippet[: _SNIPPET_CHARS - 1].rstrip() + "…"
    return "…" + snippet + "…" if start > 0 or end < len(text) else snippet


def _flag(flag_id, title, severity, explanation, evidence, suggestion) -> Flag:
    return Flag(
        flag_id=flag_id,
        title=title,
        severity=severity,
        category=CATEGORY,
        explanation=explanation,
        evidence=evidence,
        suggestion=suggestion,
    )


# ---------------------------------------------------------------------------
# ghost.evergreen
# ---------------------------------------------------------------------------

_EVERGREEN_PATTERNS = (
    "always accepting applications",
    "accepting applications on an ongoing basis",
    "join our talent pool",
    "talent community",
    "we are always looking",
    "always on the lookout",
    "pipeline candidates",
    "future pipeline",
    "talent pipeline",
    "bench",
    "evergreen",
    "ongoing recruitment",
    "continuous recruitment",
)

_EVERGREEN_RE = re.compile(
    r"(?i)\b(?:"
    + "|".join(re.escape(p) for p in sorted(_EVERGREEN_PATTERNS, key=len, reverse=True))
    + r")\b"
)


@register
def detect_evergreen(text: str | None) -> list[Flag]:
    """Flag evergreen / talent-pool postings with no real open headcount."""
    text = _text(text)
    if not text.strip():
        return []
    match = _EVERGREEN_RE.search(text)
    if not match:
        return []
    return [
        _flag(
            flag_id="ghost.evergreen",
            title="Evergreen posting, likely no open headcount",
            severity="high",
            explanation=(
                "This posting reads like an evergreen requisition: the company is "
                "collecting resumes for a talent pool or pipeline rather than "
                "hiring for a specific open role. Applications to these postings "
                "are rarely reviewed promptly, and many sit open for months or "
                "years with no actual headcount behind them."
            ),
            evidence=[_snippet(text, match)],
            suggestion=(
                "Ask the recruiter directly whether this is an active requisition "
                "with approved headcount and a target start date. If not, skip it "
                "or apply only if you are happy being in a pipeline."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# ghost.mlm
# ---------------------------------------------------------------------------

_MLM_PATTERNS = (
    "be your own boss",
    "unlimited earning potential",
    "financial freedom",
    "residual income",
    "downline",
    "upline",
    "starter kit",
    "registration fee",
    "sign-up fee",
    "signup fee",
    "enrollment fee",
    "joining fee",
    "multi-level marketing",
    "network marketing",
    "ground floor opportunity",
)

_MLM_RE = re.compile(
    r"(?i)\b(?:"
    + "|".join(re.escape(p) for p in sorted(_MLM_PATTERNS, key=len, reverse=True))
    + r")\b"
)


@register
def detect_mlm(text: str | None) -> list[Flag]:
    """Flag multi-level-marketing schemes disguised as job postings."""
    text = _text(text)
    if not text.strip():
        return []
    match = _MLM_RE.search(text)
    if not match:
        return []
    return [
        _flag(
            flag_id="ghost.mlm",
            title="Possible multi-level-marketing scheme",
            severity="critical",
            explanation=(
                "This posting uses classic multi-level-marketing language: promises "
                "of unlimited earnings or financial freedom, talk of downlines or "
                "residual income, or upfront fees like a starter kit or registration "
                "fee. Legitimate employers pay you; they do not charge you to work "
                "or make your income depend on recruiting others."
            ),
            evidence=[_snippet(text, match)],
            suggestion=(
                "Do not pay any fee to apply or start. Treat this as a scam risk: "
                "walk away unless the company can show a real salaried role with "
                "a written offer and no upfront costs."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# ghost.too_good
# ---------------------------------------------------------------------------

_NO_EXPERIENCE_RE = re.compile(r"(?i)\bno experience (?:necessary|required|needed)\b")

# "earn $X per hour/week/month/year", with optional k/thousand suffix.
_EARN_RE = re.compile(
    r"(?i)\bearn\s+(?:up to\s+)?\$?\s*([\d,]+(?:\.\d+)?)\s*"
    r"(k|thousand)?\s*(?:per|/|a|an)?\s*(hour|hr|week|wk|month|mo|year|yr|annum)?\b"
)

_PERIOD_TO_ANNUAL = {
    "hour": 2080, "hr": 2080,
    "week": 52, "wk": 52,
    "month": 12, "mo": 12,
    "year": 1, "yr": 1, "annum": 1,
}

# Annual pay above this for a no-experience role is implausible.
_IMPLAUSIBLE_ANNUAL = 150_000

_NO_INTERVIEW_RE = re.compile(r"(?i)\bno interview (?:required|necessary|needed)\b")
_WFH_RE = re.compile(r"(?i)\bwork from home\b")


def _earn_to_annual(match: re.Match) -> float | None:
    try:
        amount = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    if match.group(2):  # "k" / "thousand"
        amount *= 1000
    period = (match.group(3) or "year").lower()
    return amount * _PERIOD_TO_ANNUAL.get(period, 1)


@register
def detect_too_good(text: str | None) -> list[Flag]:
    """Flag too-good-to-be-true offers: no experience + implausible pay, etc."""
    text = _text(text)
    if not text.strip():
        return []
    match = None
    detail = ""
    if _NO_EXPERIENCE_RE.search(text):
        for earn in _EARN_RE.finditer(text):
            annual = _earn_to_annual(earn)
            if annual is not None and annual >= _IMPLAUSIBLE_ANNUAL:
                match = earn
                detail = (
                    f"promises no experience needed while advertising pay around "
                    f"${annual:,.0f}/year"
                )
                break
    if match is None and _WFH_RE.search(text) and _NO_INTERVIEW_RE.search(text):
        match = _NO_INTERVIEW_RE.search(text)
        detail = "advertises work from home with no interview required"
    if match is None:
        return []
    return [
        _flag(
            flag_id="ghost.too_good",
            title="Too-good-to-be-true offer",
            severity="high",
            explanation=(
                f"This posting {detail}. Real employers do not offer very high pay "
                "with no experience required, and they do not hire remote workers "
                "without any interview. Combinations like this are hallmarks of "
                "job scams, including fake-check and equipment-purchase fraud."
            ),
            evidence=[_snippet(text, match)],
            suggestion=(
                "Do not share bank details, buy equipment, or cash checks for this "
                "'employer'. Verify the company independently through its official "
                "site before engaging further."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# find_reposts (plain helper, NOT a registered detector)
# ---------------------------------------------------------------------------

_REPOST_WINDOW_DAYS = 90
_TEXT_SIMILARITY_THRESHOLD = 0.85


def _normalize(value: str | None) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _token_set_similarity(a: str, b: str) -> float:
    """Jaccard similarity over token sets (0.0-1.0)."""
    set_a = set(_normalize(a).split())
    set_b = set(_normalize(b).split())
    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _as_date(value) -> date | None:
    """Best-effort parse of a posting date; ``None`` when unknown."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d %b %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value.strip()).date()
        except ValueError:
            return None
    return None


def find_reposts(postings: list[dict]) -> list[list[dict]]:
    """Group likely reposts of the same job listing.

    Two postings are grouped when they share the same normalized
    company + title within 90 days of each other, OR when their texts are
    near-duplicates (token-set similarity >= 0.85).

    Args:
        postings: dicts with ``company``, ``title``, ``text``, ``date_posted``.

    Returns:
        A list of groups (each a list of the input dicts, in original order),
        largest groups first. Groups always contain at least 2 postings.
    """
    postings = list(postings or [])
    n = len(postings)
    if n < 2:
        return []

    norm_company = [_normalize(p.get("company")) for p in postings]
    norm_title = [_normalize(p.get("title")) for p in postings]
    texts = [p.get("text") or "" for p in postings]
    dates = [_as_date(p.get("date_posted")) for p in postings]

    # Union-find over posting indices.
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    def same_listing_company_title(i: int, j: int) -> bool:
        if not norm_company[i] or not norm_title[i]:
            return False
        if norm_company[i] != norm_company[j] or norm_title[i] != norm_title[j]:
            return False
        if dates[i] is None or dates[j] is None:
            return False
        return abs((dates[i] - dates[j]).days) <= _REPOST_WINDOW_DAYS

    for i in range(n):
        for j in range(i + 1, n):
            if same_listing_company_title(i, j):
                union(i, j)
            elif _token_set_similarity(texts[i], texts[j]) >= _TEXT_SIMILARITY_THRESHOLD:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    result = [
        [postings[i] for i in sorted(idxs)]
        for idxs in groups.values()
        if len(idxs) >= 2
    ]
    result.sort(key=len, reverse=True)
    return result
