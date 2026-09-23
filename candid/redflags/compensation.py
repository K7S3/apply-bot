"""Compensation red flags for job postings (category ``"compensation"``).

Flags missing pay transparency (``comp.no_salary``, ``comp.vague_comp``) and
suspicious pay structures (``comp.equity_only``, ``comp.commission_only``,
``comp.lowball_hint``). All checks are offline regex scans of the raw posting
text, case-insensitive, and return ``[]`` for empty/None input.
"""

from __future__ import annotations

import re

from .core import Flag, register


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _snippets(text: str, matches, window: int = 55, limit: int = 4) -> list[str]:
    """Short (~120-char) context windows around regex matches."""
    out: list[str] = []
    for m in list(matches)[:limit]:
        start = max(0, m.start() - window)
        end = min(len(text), m.end() + window)
        snippet = " ".join(text[start:end].split())
        if len(snippet) > 125:
            snippet = snippet[:122].rstrip() + "..."
        out.append(snippet)
    return out


# ---------------------------------------------------------------------------
# comp.no_salary
# ---------------------------------------------------------------------------

_COMP_MENTION = re.compile(
    r"\$|salary|salaries|compensation|pay\s+range|\bote\b|\bhourly\b|\bannual\b",
    re.IGNORECASE,
)


def check_no_salary(text: str) -> list[Flag]:
    """Flag postings that mention pay nowhere at all."""
    if not _COMP_MENTION.search(text):
        return [Flag(
            flag_id="comp.no_salary",
            title="No salary or compensation mentioned",
            severity="medium",
            category="compensation",
            explanation=(
                "The posting never mentions pay at all: no salary range, hourly "
                "rate, or compensation details. Employers who hide pay often use "
                "the interview process to anchor candidates low, and you can "
                "spend weeks interviewing for a role that can't meet your floor."
            ),
            evidence=[],
            suggestion=(
                "Ask the recruiter for the base salary range before investing "
                "time in interviews, and check candid's salary benchmark for "
                "the role to set your walk-away number."
            ),
        )]
    return []


# ---------------------------------------------------------------------------
# comp.vague_comp
# ---------------------------------------------------------------------------

_WEASEL_PHRASES = [
    re.compile(r"competitive\s+(salary|pay|compensation|comp|benefits)", re.IGNORECASE),
    re.compile(r"(?<!john\s)\bdoe\b", re.IGNORECASE),  # "DOE", not John Doe
    re.compile(r"depend(?:s|ent)?\s+(?:up\s+)?on\s+experience", re.IGNORECASE),
    re.compile(r"market[\s-]?rate", re.IGNORECASE),
]

# A real number next to pay language: "$150k", "$80,000", "150k-185k".
_NUMERIC_COMP = re.compile(r"\$\s*\d|\b\d{2,6}\s?[kK]\b", re.IGNORECASE)


def check_vague_comp(text: str) -> list[Flag]:
    """Flag weasel phrases ('competitive salary', 'DOE') with no numbers."""
    if _NUMERIC_COMP.search(text):
        return []
    hits = [m for pat in _WEASEL_PHRASES for m in pat.finditer(text)]
    if not hits:
        return []
    return [Flag(
        flag_id="comp.vague_comp",
        title="Vague pay language, no numbers",
        severity="medium",
        category="compensation",
        explanation=(
            "The posting uses weasel phrases like 'competitive salary' or 'DOE' "
            "but gives no numeric range. 'Competitive' is unverifiable marketing "
            "language, and 'depends on experience' usually means the offer will "
            "be anchored to whatever you reveal first, not to the market."
        ),
        evidence=_snippets(text, hits),
        suggestion=(
            "Reply asking for the budgeted range for the role, and never share "
            "your current salary first: quote your target range from market data."
        ),
    )]


# ---------------------------------------------------------------------------
# comp.equity_only
# ---------------------------------------------------------------------------

_EQUITY_ONLY = [
    re.compile(r"equity\s+only", re.IGNORECASE),
    re.compile(r"\bunpaid\b", re.IGNORECASE),
    re.compile(r"\bvolunteer\b", re.IGNORECASE),
    re.compile(r"for\s+exposure", re.IGNORECASE),
    re.compile(r"deferred\s+compensation", re.IGNORECASE),
]


def check_equity_only(text: str) -> list[Flag]:
    """Flag unpaid / equity-only full-time work."""
    hits = [m for pat in _EQUITY_ONLY for m in pat.finditer(text)]
    if not hits:
        return []
    return [Flag(
        flag_id="comp.equity_only",
        title="Unpaid or equity-only work",
        severity="critical",
        category="compensation",
        explanation=(
            "The posting asks for full-time work with no cash pay: equity only, "
            "unpaid, volunteer, or 'exposure'. Startup equity is usually worth "
            "zero, and unpaid full-time work for a for-profit company is often "
            "illegal. This is the single worst compensation signal a posting "
            "can carry."
        ),
        evidence=_snippets(text, hits),
        suggestion=(
            "Ask point-blank whether any cash salary is offered. If not, walk "
            "away: you cannot pay rent with lottery tickets."
        ),
    )]


# ---------------------------------------------------------------------------
# comp.commission_only
# ---------------------------------------------------------------------------

_COMMISSION_ONLY = [
    re.compile(r"commission\s+only", re.IGNORECASE),
    re.compile(r"100\s*%\s*commission", re.IGNORECASE),
    re.compile(r"uncapped\s+commission", re.IGNORECASE),
]

# Any mention of guaranteed cash means it is not really commission-only.
_BASE_MENTION = re.compile(
    r"\$|\bbase\s+(salary|pay|compensation|comp)\b|\bguaranteed\b|\bdraw\b",
    re.IGNORECASE,
)


def check_commission_only(text: str) -> list[Flag]:
    """Flag commission-only roles with no base pay mentioned."""
    hits = [m for pat in _COMMISSION_ONLY for m in pat.finditer(text)]
    if not hits or _BASE_MENTION.search(text):
        return []
    return [Flag(
        flag_id="comp.commission_only",
        title="Commission-only pay, no base mentioned",
        severity="high",
        category="compensation",
        explanation=(
            "The role pays on commission alone with no base salary, draw, or "
            "guarantee mentioned. All of the income risk sits on you: a bad "
            "territory, a bad quarter, or a bad manager means zero pay for "
            "full-time effort."
        ),
        evidence=_snippets(text, hits),
        suggestion=(
            "Ask for the base salary or guaranteed draw in writing, plus the "
            "average first-year earnings of people actually in the role."
        ),
    )]


# ---------------------------------------------------------------------------
# comp.lowball_hint
# ---------------------------------------------------------------------------

_LOWBALL = [
    re.compile(r"below[\s-]?market\s+(pay|salary|compensation|rate)", re.IGNORECASE),
    re.compile(
        r"(salary|pay|compensation)\s+is\s+(modest|below[\s-]?market|limited|tight)",
        re.IGNORECASE,
    ),
    re.compile(r"passion\s+(over|before)\s+pay", re.IGNORECASE),
    re.compile(r"can\s*'?t\s+pay\s+market", re.IGNORECASE),
    re.compile(r"\bmodest\s+(salary|pay|compensation)\b", re.IGNORECASE),
]


def check_lowball_hint(text: str) -> list[Flag]:
    """Flag language that pre-excuses below-market pay."""
    hits = [m for pat in _LOWBALL for m in pat.finditer(text)]
    if not hits:
        return []
    return [Flag(
        flag_id="comp.lowball_hint",
        title="Pre-excused below-market pay",
        severity="low",
        category="compensation",
        explanation=(
            "The posting openly warns that pay is 'below market', 'modest', or "
            "that 'passion' should matter more than pay. They are telling you "
            "up front the offer will be low, so do not expect negotiation to "
            "fix it: the budget was set before you applied."
        ),
        evidence=_snippets(text, hits),
        suggestion=(
            "Only proceed if the non-cash upside (learning, title, equity with "
            "real traction) is worth a pay cut, and get any equity terms in "
            "writing before you interview."
        ),
    )]


# ---------------------------------------------------------------------------
# registered detector
# ---------------------------------------------------------------------------

@register
def detect(text: str) -> list[Flag]:
    """Run all compensation checks over the posting text."""
    text = text or ""
    if not text.strip():
        return []
    flags: list[Flag] = []
    flags.extend(check_no_salary(text))
    flags.extend(check_vague_comp(text))
    flags.extend(check_equity_only(text))
    flags.extend(check_commission_only(text))
    flags.extend(check_lowball_hint(text))
    return flags
