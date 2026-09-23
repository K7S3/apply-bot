"""Green-flag detectors: positive signals in a job posting.

These are the optimistic counterpart to the red-flag detectors. Each one
spots a sign that the posting is transparent, candidate-friendly, or
well-run. All green flags use severity ``info`` (they never raise the risk
score on their own); :func:`green_adjustment` converts the green count into
a downward score adjustment applied by the report layer.
"""

from __future__ import annotations

import re

from candid.redflags.core import Flag, register

#: Target width for evidence snippets (~120 chars of context).
_EVIDENCE_WIDTH = 120


def _snippets(text: str, patterns: list[str],
              width: int = _EVIDENCE_WIDTH) -> list[str]:
    """Collect ~120-char context windows around each pattern match."""
    seen: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            half = max(0, (width - (m.end() - m.start()))) // 2
            start = max(0, m.start() - half)
            end = min(len(text), start + width)
            snippet = " ".join(text[start:end].split())
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."
            if snippet and snippet not in seen:
                seen.append(snippet)
    return seen


def _green(flag_id: str, title: str, explanation: str, suggestion: str,
           snippets: list[str]) -> list[Flag]:
    if not snippets:
        return []
    return [Flag(
        flag_id=flag_id,
        title=title,
        severity="info",
        category="green",
        explanation=explanation,
        evidence=snippets,
        suggestion=suggestion,
    )]


@register
def detect_salary_range(text: str) -> list[Flag]:
    """Explicit pay range present."""
    if not text:
        return []
    patterns = [
        r"\$\s*\d[\d,]*\.?\d*\s*[kK]?\s*(?:-|–|—|to)\s*\$?\s*\d[\d,]*\.?\d*\s*[kK]?",
        r"\bpay range\b",
        r"\bsalary range\b",
        r"\bcompensation range\b",
    ]
    return _green(
        "green.salary_range",
        "Salary range listed",
        ("The posting states an explicit pay range up front. That is a strong "
         "transparency signal: you know the budget before investing time in "
         "interviews. Ranges also make it harder for the company to lowball "
         "individual candidates."),
        ("Confirm the range maps to your level and location in the first "
         "recruiter call, and ask where you would land inside it."),
        _snippets(text, patterns),
    )


@register
def detect_growth_path(text: str) -> list[Flag]:
    """Career growth / mentorship / learning signals."""
    if not text:
        return []
    patterns = [
        r"\bcareer growth\b",
        r"\bpromotions?\b",
        r"\bmentorship\b",
        r"\blearning budget\b",
        r"\bconferences?\b",
    ]
    return _green(
        "green.growth_path",
        "Growth and learning signals",
        ("The posting mentions career growth, mentorship, or learning support. "
         "Employers who spell this out tend to invest in leveling people up "
         "rather than hiring and forgetting. It also gives you concrete "
         "things to ask about in interviews."),
        ("Ask for examples: how often do people get promoted, and what does "
         "the mentorship actually look like week to week?"),
        _snippets(text, patterns),
    )


@register
def detect_work_life(text: str) -> list[Flag]:
    """Work-life balance signals."""
    if not text:
        return []
    patterns = [
        r"\bwork[\s-]?life balance\b",
        r"\bflexible hours\b",
        r"\bunlimited pto\b",
        r"\bgenerous pto\b",
        r"\bparental leave\b",
    ]
    return _green(
        "green.work_life",
        "Work-life balance signals",
        ("The posting calls out flexible hours, generous time off, or "
         "parental leave. Companies that advertise this are usually "
         "comfortable being held to it. It is still worth validating with "
         "future teammates."),
        ("Ask the team how often people actually take PTO and what a "
         "typical week looks like."),
        _snippets(text, patterns),
    )


@register
def detect_process_transparency(text: str) -> list[Flag]:
    """Interview steps listed (hiring process transparency)."""
    if not text:
        return []
    patterns = [
        r"\bonsite\b",
        r"\btake-home\b",
        r"\btake[\s-]?home\s+(?:assignment|exercise|challenge|test|project)\b",
        r"\b\d+\s+rounds?\b",
        r"\binterview process\b",
    ]
    return _green(
        "green.process_transparency",
        "Transparent hiring process",
        ("The posting describes the interview steps, such as the number of "
         "rounds, an onsite, or a take-home. Knowing the process up front "
         "lets you prepare properly and spot scope creep later. It also "
         "suggests the hiring team is organized."),
        "Ask for the timeline and who you will meet at each stage.",
        _snippets(text, patterns),
    )


@register
def detect_equal_opportunity(text: str) -> list[Flag]:
    """EEO statement present."""
    if not text:
        return []
    patterns = [
        r"\bequal opportunity\b",
        r"\bequal employment opportunity\b",
        r"\beeo\b",
        r"\baffirmative action\b",
        r"\bdo(?:es)?\s+not\s+discriminate\b",
    ]
    return _green(
        "green.equal_opportunity",
        "Equal opportunity statement",
        ("The posting includes an EEO or non-discrimination statement. This "
         "is standard at larger employers and a basic compliance signal. It "
         "does not guarantee an inclusive culture, but its absence is worth "
         "noticing."),
        ("Ask about the team's actual diversity and inclusion practices, "
         "not just the statement."),
        _snippets(text, patterns),
    )


#: Benefit keywords; 3+ distinct hits trigger the benefits flag.
_BENEFIT_PATTERNS = [
    (r"\bhealth(?:care)?\b", "health"),
    (r"\bdental\b", "dental"),
    (r"\bvision\b", "vision"),
    (r"\b401\s?\(?k\)?", "401k"),
    (r"\bequity\b", "equity"),
    (r"\brsus?\b", "rsu"),
    (r"\brestricted stock\b", "rsu"),
]


@register
def detect_benefits_listed(text: str) -> list[Flag]:
    """3+ of: health, dental, vision, 401k, equity/RSU."""
    if not text:
        return []
    matched: list[str] = []
    snippets: list[str] = []
    for pat, label in _BENEFIT_PATTERNS:
        hits = _snippets(text, [pat])
        if hits and label not in matched:
            matched.append(label)
            snippets.extend(s for s in hits if s not in snippets)
    if len(matched) < 3:
        return []
    return _green(
        "green.benefits_listed",
        "Benefits spelled out",
        (f"The posting lists concrete benefits ({', '.join(sorted(matched))}). "
         "Detailed benefits usually mean the total compensation is "
         "competitive and the offer stage will have fewer surprises. Plan "
         "quality varies a lot, so compare the fine print."),
        ("Ask for the benefits summary early so you can value the full "
         "package, not just the base salary."),
        snippets,
    )


def green_adjustment(green_count: int) -> int:
    """Score reduction for green flags: -3 per flag, capped at -15.

    Returns a non-positive int. The report layer adds this to the raw
    risk score (floored at 0) so transparent postings score lower.
    """
    count = max(0, int(green_count))
    return max(-15, -3 * count)
