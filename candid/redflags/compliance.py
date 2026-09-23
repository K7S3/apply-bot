"""Compliance detectors for the JD red-flag engine.

Flags language that can signal discriminatory hiring practices, requests for
protected personal information, worker misclassification, and equipment
shifting. These are heuristics worth a closer look, not legal advice: none
of these detectors determines whether a posting violates any law.
"""

from __future__ import annotations

import re

from .core import Flag, register

CATEGORY = "compliance"

_HEURISTIC_NOTE = (
    "This is an automated heuristic worth a closer look, not legal advice. "
)


def _blank(text) -> bool:
    return not isinstance(text, str) or not text.strip()


def _snippets(text: str, matches, radius: int = 55, limit: int = 3) -> list[str]:
    """Short (~120 char) quoted context windows around regex matches."""
    out: list[str] = []
    for m in list(matches)[:limit]:
        start = max(0, m.start() - radius)
        end = min(len(text), m.end() + radius)
        snip = " ".join(text[start:end].split())
        if len(snip) > 120:
            snip = snip[:117].rstrip() + "..."
        out.append(snip)
    return out


# ---------------------------------------------------------------------------
# 1. compliance.age_hints (medium)
# ---------------------------------------------------------------------------

# Words that suggest the matched phrase describes a person (the candidate),
# used to avoid flagging things like "young company" or "energetic culture".
_PERSON_WORDS = re.compile(
    r"\b(candidate|applicant|person|individual|professional|hire|talent|"
    r"employee|teammate|you're|you are|seeking|looking for|ideal|join us)\b",
    re.IGNORECASE,
)

# Phrases that are inherently about the applicant's age or generation.
_AGE_DIRECT = [
    ("recent graduate", re.compile(r"\brecent graduates?\b", re.IGNORECASE)),
    ("digital native", re.compile(r"\bdigital natives?\b", re.IGNORECASE)),
]

# Phrases only flagged when they describe a person.
_AGE_PERSONAL = [
    ("young", re.compile(r"\byoung\b", re.IGNORECASE)),
    ("energetic", re.compile(r"\benergetic\b", re.IGNORECASE)),
]

# "overqualified" is only a signal when used dismissively.
_OVERQUALIFIED = re.compile(r"\boverqualified\b", re.IGNORECASE)
_DISMISSIVE = re.compile(
    r"will not be considered|won't be considered|need not apply|"
    r"do not apply|don't apply|discouraged|not a fit|rejected",
    re.IGNORECASE,
)


def _person_nearby(text: str, match, window: int = 70) -> bool:
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    return _PERSON_WORDS.search(text[start:end]) is not None


def _dismissive_nearby(text: str, match, window: int = 80) -> bool:
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    return _DISMISSIVE.search(text[start:end]) is not None


def detect_age_hints(text: str) -> Flag | None:
    """Age-coded language: young/energetic (as person descriptors),
    recent graduate, digital native, dismissive use of overqualified."""
    if _blank(text):
        return None
    hits: list[tuple[str, object]] = []
    for label, pat in _AGE_DIRECT:
        for m in pat.finditer(text):
            hits.append((label, m))
    for label, pat in _AGE_PERSONAL:
        for m in pat.finditer(text):
            if _person_nearby(text, m):
                hits.append((label, m))
    for m in _OVERQUALIFIED.finditer(text):
        if _dismissive_nearby(text, m):
            hits.append(("overqualified (dismissive)", m))
    if not hits:
        return None
    labels = ", ".join(sorted({label for label, _ in hits}))
    return Flag(
        flag_id="compliance.age_hints",
        title="Age-coded language in the posting",
        severity="medium",
        category=CATEGORY,
        explanation=(
            "The posting uses age-coded phrasing "
            f"({labels}). Language like this can signal a preference for "
            "younger applicants and may discourage qualified older "
            "candidates from applying, which is why age discrimination is "
            "restricted in hiring in many places. " + _HEURISTIC_NOTE +
            "Context matters: a graduate program that says 'recent "
            "graduate' may be legitimate, so read the full posting before "
            "drawing conclusions."
        ),
        evidence=_snippets(text, [m for _, m in hits]),
        suggestion="Note the phrasing and compare it against how the role is actually described; if you apply, focus your materials on the listed skills and experience.",
    )


# ---------------------------------------------------------------------------
# 2. compliance.gendered_language (low)
# ---------------------------------------------------------------------------

_MASCULINE_CODED = [
    ("dominant", re.compile(r"\bdominant\b", re.IGNORECASE)),
    ("aggressive", re.compile(r"\baggressive\b", re.IGNORECASE)),
    ("alpha", re.compile(r"\balpha\b", re.IGNORECASE)),
    ("manpower", re.compile(r"\bmanpower\b", re.IGNORECASE)),
    # "competitive" alone is fine; it only counts toward a cluster.
    ("competitive", re.compile(r"\bcompetitive\b", re.IGNORECASE)),
]

# Generic masculine pronouns referring to the candidate ("he will...", "his team...").
_GENERIC_PRONOUN = [
    ("generic 'he'", re.compile(
        r"\bhe\s+(?:will|is|must|should|needs|has|would|could|works)\b",
        re.IGNORECASE)),
    ("generic 'his'", re.compile(
        r"\bhis\s+(?:team|role|work|responsibilities|job|duties|manager|own)\b",
        re.IGNORECASE)),
]


def detect_gendered_language(text: str) -> Flag | None:
    """Masculine-coded wording or generic he/his for the candidate."""
    if _blank(text):
        return None
    coded = [(label, m) for label, pat in _MASCULINE_CODED for m in pat.finditer(text)]
    pronouns = [(label, m) for label, pat in _GENERIC_PRONOUN for m in pat.finditer(text)]
    # "competitive" only counts inside a cluster of 2+ masculine-coded words.
    strong_coded = [(l, m) for l, m in coded if l != "competitive"]
    cluster = len(strong_coded) + (1 if any(l == "competitive" for l, _ in coded) else 0) >= 2
    if not pronouns and not cluster:
        return None
    hits = pronouns + coded
    labels = ", ".join(sorted({label for label, _ in hits}))
    return Flag(
        flag_id="compliance.gendered_language",
        title="Masculine-coded language",
        severity="low",
        category=CATEGORY,
        explanation=(
            "The posting leans on masculine-coded wording "
            f"({labels}). Research consistently shows this kind of language "
            "can deter qualified applicants who do not identify with it, "
            "even when the employer did not intend any bias. "
            + _HEURISTIC_NOTE +
            "One strong word in isolation is usually just style; the "
            "pattern matters more than any single term."
        ),
        evidence=_snippets(text, [m for _, m in hits]),
        suggestion="If you are qualified, do not self-select out over wording; if you are the employer, neutral phrasing widens the applicant pool.",
    )


# ---------------------------------------------------------------------------
# 3. compliance.protected_info (high)
# ---------------------------------------------------------------------------

_PROTECTED = [
    ("headshot", re.compile(r"\bheadshot\b", re.IGNORECASE)),
    ("photo of yourself", re.compile(r"\bphoto(?:graph)? of yourself\b", re.IGNORECASE)),
    ("attach a photo", re.compile(
        r"(?:attach|include|send|submit|provide|upload)\s+(?:a\s+|your\s+)?"
        r"(?:recent\s+)?photo", re.IGNORECASE)),
    ("date of birth", re.compile(
        r"date of birth|birth\s*date|\bbirthdate\b|\bdob\b", re.IGNORECASE)),
    ("age", re.compile(
        r"(?:state|provide|include|enter|disclose|list)\s+(?:your\s+)?age\b|"
        r"\byour age\b|\bage\s*:", re.IGNORECASE)),
    ("marital status", re.compile(r"marital status", re.IGNORECASE)),
    ("maiden name", re.compile(r"maiden name", re.IGNORECASE)),
    ("social security number", re.compile(
        r"social security(?: number)?|\bssn\b", re.IGNORECASE)),
]

# Asking about citizenship is only flagged when it goes beyond confirming
# legal work authorization.
_CITIZENSHIP = re.compile(r"\bcitizenship\b|\bcitizen\b", re.IGNORECASE)
_WORK_AUTH = re.compile(
    r"work authorization|authorized to work|legally authorized|"
    r"eligible to work|employment authorization|visa sponsorship",
    re.IGNORECASE,
)


def detect_protected_info(text: str) -> Flag | None:
    """Requests for photos, DOB/age, marital status, SSN, or citizenship
    beyond work-authorization confirmation."""
    if _blank(text):
        return None
    hits: list[tuple[str, object]] = []
    for label, pat in _PROTECTED:
        for m in pat.finditer(text):
            hits.append((label, m))
    for m in _CITIZENSHIP.finditer(text):
        window = text[max(0, m.start() - 100):m.end() + 100]
        if _WORK_AUTH.search(window):
            continue  # legitimate work-authorization phrasing
        hits.append(("citizenship status", m))
    if not hits:
        return None
    labels = ", ".join(sorted({label for label, _ in hits}))
    return Flag(
        flag_id="compliance.protected_info",
        title="Posting asks for protected personal information",
        severity="high",
        category=CATEGORY,
        explanation=(
            "The posting requests personal details employers generally "
            f"should not need at the application stage ({labels}). Photos, "
            "birth dates, marital status, and similar details can enable "
            "discrimination and create identity-theft risk, and they are "
            "irrelevant to whether you can do the job. " + _HEURISTIC_NOTE +
            "Confirming legal work authorization is normal; asking for "
            "citizenship status, a headshot, or a birth date is not."
        ),
        evidence=_snippets(text, [m for _, m in hits]),
        suggestion="Do not provide this information up front; ask why it is needed and whether you can apply without it.",
    )


# ---------------------------------------------------------------------------
# 4. compliance.misclassification (high)
# ---------------------------------------------------------------------------

_CONTRACTOR_SIGNALS = [
    re.compile(r"\b1099\b"),
    re.compile(r"independent contractor", re.IGNORECASE),
    re.compile(r"\bfreelancer\b", re.IGNORECASE),
    re.compile(r"\bfreelance\b", re.IGNORECASE),
    re.compile(r"contract basis", re.IGNORECASE),
    re.compile(r"contractor (?:role|position)", re.IGNORECASE),
]

# Employee-like control signals.
_CONTROL_SIGNALS = [
    ("set hours", re.compile(r"set hours", re.IGNORECASE)),
    ("fixed schedule", re.compile(r"fixed schedule|set schedule", re.IGNORECASE)),
    ("mandatory standup", re.compile(
        r"(?:must attend|required to attend).{0,40}standup", re.IGNORECASE)),
    ("core hours", re.compile(r"core hours", re.IGNORECASE)),
    ("exclusivity", re.compile(r"\bexclusiv\w*", re.IGNORECASE)),
    ("non-compete", re.compile(r"non[\s-]?compete", re.IGNORECASE)),
]


def detect_misclassification(text: str) -> Flag | None:
    """Contractor label combined with employee-like control."""
    if _blank(text):
        return None
    contractor = [p.search(text) for p in _CONTRACTOR_SIGNALS]
    contractor = [m for m in contractor if m]
    control = [(label, p.search(text)) for label, p in _CONTROL_SIGNALS]
    control = [(label, m) for label, m in control if m]
    if not contractor or not control:
        return None
    labels = ", ".join(label for label, _ in control)
    return Flag(
        flag_id="compliance.misclassification",
        title="Contractor label with employee-like control",
        severity="high",
        category=CATEGORY,
        explanation=(
            "The posting labels the worker as a contractor (1099, freelancer, "
            "or similar) while also demanding employee-like control "
            f"({labels}). True independent contractors generally set their "
            "own hours and methods; set schedules, mandatory attendance, "
            "exclusivity, and non-competes point toward employment. "
            "Misclassification can cost you benefits, overtime, and tax "
            "protections. " + _HEURISTIC_NOTE
        ),
        evidence=_snippets(text, contractor + [m for _, m in control]),
        suggestion="Ask directly about worker classification, who sets the schedule, and what benefits (if any) are included.",
    )


# ---------------------------------------------------------------------------
# 5. compliance.own_equipment (low)
# ---------------------------------------------------------------------------

_OWN_EQUIPMENT = [
    re.compile(
        r"(?:must|need to|have to|required to)\s+(?:have\s+)?(?:your|their)\s+own\s+"
        r"(?:laptop|computer|device|vehicle|car|tools|equipment|phone)",
        re.IGNORECASE),
    re.compile(
        r"provide your own\s+"
        r"(?:laptop|computer|device|vehicle|car|tools|equipment|phone)",
        re.IGNORECASE),
    re.compile(
        r"bring your own\s+"
        r"(?:laptop|computer|device|vehicle|car|tools|equipment|phone)",
        re.IGNORECASE),
    re.compile(
        r"use your own\s+"
        r"(?:laptop|computer|device|vehicle|car|tools|equipment|phone)",
        re.IGNORECASE),
]

# If the role is honestly contract work, providing your own gear is normal.
_CONTRACTOR_CONTEXT = re.compile(
    r"\b1099\b|independent contractor|\bfreelancer\b|\bfreelance\b",
    re.IGNORECASE,
)


def detect_own_equipment(text: str) -> Flag | None:
    """Non-contract role that requires the worker's own laptop/vehicle/tools."""
    if _blank(text):
        return None
    if _CONTRACTOR_CONTEXT.search(text):
        return None
    hits = [p.search(text) for p in _OWN_EQUIPMENT]
    hits = [m for m in hits if m]
    if not hits:
        return None
    return Flag(
        flag_id="compliance.own_equipment",
        title="Must provide your own equipment",
        severity="low",
        category=CATEGORY,
        explanation=(
            "The posting requires you to supply your own laptop, vehicle, or "
            "tools for what looks like a regular employment role. Shifting "
            "equipment costs onto the worker is normal for genuine contract "
            "work but unusual for employees, and it quietly lowers your "
            "effective pay. " + _HEURISTIC_NOTE
        ),
        evidence=_snippets(text, hits),
        suggestion="Ask whether equipment is provided or reimbursed, and factor any out-of-pocket cost into the compensation.",
    )


# ---------------------------------------------------------------------------
# registered detector
# ---------------------------------------------------------------------------

@register
def detect(text: str) -> list[Flag]:
    """Run all compliance sub-detectors over the posting text."""
    if _blank(text):
        return []
    flags: list[Flag] = []
    for fn in (
        detect_age_hints,
        detect_gendered_language,
        detect_protected_info,
        detect_misclassification,
        detect_own_equipment,
    ):
        try:
            flag = fn(text)
        except Exception:
            continue
        if flag is not None:
            flags.append(flag)
    return flags
