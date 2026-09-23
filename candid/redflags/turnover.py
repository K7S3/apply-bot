"""Culture / turnover red flags for job postings (category ``"culture"``).

Flags language that correlates with understaffing, burnout, and revolving-door
hiring (``turnover.churn_language``, ``turnover.family_cliche``,
``turnover.overtime_signal``, ``turnover.rockstar``,
``turnover.revolving_door``). All checks are offline regex scans of the raw
posting text, case-insensitive, and return ``[]`` for empty/None input.
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
# turnover.churn_language
# ---------------------------------------------------------------------------

_CHURN_PHRASES = [
    re.compile(r"fast[\s-]?paced(\s+environment)?", re.IGNORECASE),
    re.compile(r"wear many hats", re.IGNORECASE),
    re.compile(r"do more with less", re.IGNORECASE),
    re.compile(r"self[\s-]?starter", re.IGNORECASE),
]

_AUTONOMY_PHRASES = [
    re.compile(r"minimal supervision", re.IGNORECASE),
    re.compile(r"hit the ground running", re.IGNORECASE),
]


def check_churn_language(text: str) -> list[Flag]:
    """Flag churn phrasing repeated 3+ times plus 'sink or swim' autonomy."""
    churn_hits = [m for pat in _CHURN_PHRASES for m in pat.finditer(text)]
    autonomy_hit = any(pat.search(text) for pat in _AUTONOMY_PHRASES)
    if len(churn_hits) < 3 or not autonomy_hit:
        return []
    return [Flag(
        flag_id="turnover.churn_language",
        title="Churn language: understaffing and burnout signals",
        severity="medium",
        category="culture",
        explanation=(
            "The posting leans on churn cliches ('fast-paced environment', "
            "'wear many hats', 'do more with less') three or more times and "
            "pairs them with 'minimal supervision' or 'hit the ground running'. "
            "In practice this combination correlates with understaffed teams, "
            "no onboarding, and burnout: they need someone to absorb chaos, "
            "not to grow into a supported role."
        ),
        evidence=_snippets(text, churn_hits),
        suggestion=(
            "Ask the hiring manager about team size, attrition in the last "
            "year, and what onboarding actually looks like in the first 30 days."
        ),
    )]


# ---------------------------------------------------------------------------
# turnover.family_cliche
# ---------------------------------------------------------------------------

_FAMILY_CLICHE = [
    re.compile(r"\b(we'?re|we are)\s+(like\s+)?a\s+family\b", re.IGNORECASE),
    re.compile(r"\blike a family\b", re.IGNORECASE),
    re.compile(r"work hard[,\s]+play hard", re.IGNORECASE),
]


def check_family_cliche(text: str) -> list[Flag]:
    """Flag 'we are a family' / 'work hard play hard' cliches."""
    hits = [m for pat in _FAMILY_CLICHE for m in pat.finditer(text)]
    if not hits:
        return []
    return [Flag(
        flag_id="turnover.family_cliche",
        title="'We are a family' culture cliche",
        severity="low",
        category="culture",
        explanation=(
            "The posting calls the team a family or promises 'work hard play "
            "hard'. 'Family' language is often used to demand loyalty and "
            "unpaid extra effort while offering none of a family's "
            "unconditional support: layoffs still happen. It is a yellow flag, "
            "not a dealbreaker on its own."
        ),
        evidence=_snippets(text, hits),
        suggestion=(
            "Ask how the team handles mistakes and layoffs: the answer tells "
            "you whether 'family' means support or just loyalty."
        ),
    )]


# ---------------------------------------------------------------------------
# turnover.overtime_signal
# ---------------------------------------------------------------------------

_OVERTIME = [
    re.compile(r"nights and weekends", re.IGNORECASE),
    re.compile(r"\b24\s*/\s*7\b", re.IGNORECASE),
    re.compile(r"\balways[\s-]?on\b", re.IGNORECASE),
    re.compile(r"\blong hours\b", re.IGNORECASE),
]


def check_overtime_signal(text: str) -> list[Flag]:
    """Flag overtime framed as normal or positive."""
    hits = [m for pat in _OVERTIME for m in pat.finditer(text)]
    if not hits:
        return []
    return [Flag(
        flag_id="turnover.overtime_signal",
        title="Overtime presented as normal",
        severity="high",
        category="culture",
        explanation=(
            "The posting normalizes nights, weekends, 'always on' availability, "
            "or long hours. When crunch is advertised as the culture instead of "
            "an occasional exception, it means the workload is structurally "
            "bigger than the team: expect burnout, not a phase."
        ),
        evidence=_snippets(text, hits),
        suggestion=(
            "Ask for the team's actual average weekly hours and on-call load, "
            "and talk to a current team member before accepting."
        ),
    )]


# ---------------------------------------------------------------------------
# turnover.rockstar
# ---------------------------------------------------------------------------

_ROCKSTAR = re.compile(
    r"\brockstars?\b|\bninjas?\b|\bgurus?\b|\bwizards?\b|\bsuperstars?\b",
    re.IGNORECASE,
)


def check_rockstar(text: str) -> list[Flag]:
    """Flag 'rockstar' / 'ninja' hero-culture language in requirements."""
    hits = list(_ROCKSTAR.finditer(text))
    if not hits:
        return []
    return [Flag(
        flag_id="turnover.rockstar",
        title="'Rockstar' hero-culture language",
        severity="low",
        category="culture",
        explanation=(
            "The requirements ask for a 'rockstar', 'ninja', 'guru', 'wizard', "
            "or 'superstar'. This hero-culture framing correlates with teams "
            "that reward individual heroics over sustainable process, and it "
            "often pairs with poor work-life balance and vague expectations."
        ),
        evidence=_snippets(text, hits),
        suggestion=(
            "Ask how success is measured for the role: concrete goals beat "
            "'be a rockstar' every time."
        ),
    )]


# ---------------------------------------------------------------------------
# turnover.revolving_door
# ---------------------------------------------------------------------------

_URGENT_HIRE = [
    re.compile(r"immediate start", re.IGNORECASE),
    re.compile(r"urgent(?:ly)?\s+hir\w+", re.IGNORECASE),
    re.compile(r"\bbackfill\b", re.IGNORECASE),
]

_FAST_PACED = re.compile(r"fast[\s-]?paced", re.IGNORECASE)


def check_revolving_door(text: str) -> list[Flag]:
    """Flag urgent-hire language combined with 'fast-paced'."""
    urgent_hits = [m for pat in _URGENT_HIRE for m in pat.finditer(text)]
    if not urgent_hits or not _FAST_PACED.search(text):
        return []
    return [Flag(
        flag_id="turnover.revolving_door",
        title="Revolving-door hiring signals",
        severity="medium",
        category="culture",
        explanation=(
            "The posting demands an immediate start or urgent hire (sometimes "
            "an outright backfill) while also selling a 'fast-paced' culture. "
            "That combination often means someone just quit or burned out and "
            "the team is desperate: you would be inheriting their workload, "
            "not joining a stable team."
        ),
        evidence=_snippets(text, urgent_hits),
        suggestion=(
            "Ask why the role is open and how long the last person stayed. "
            "A backfill after a short tenure is the clearest warning sign."
        ),
    )]


# ---------------------------------------------------------------------------
# registered detector
# ---------------------------------------------------------------------------

@register
def detect(text: str) -> list[Flag]:
    """Run all culture/turnover checks over the posting text."""
    text = text or ""
    if not text.strip():
        return []
    flags: list[Flag] = []
    flags.extend(check_churn_language(text))
    flags.extend(check_family_cliche(text))
    flags.extend(check_overtime_signal(text))
    flags.extend(check_rockstar(text))
    flags.extend(check_revolving_door(text))
    return flags
