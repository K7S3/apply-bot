"""Unrealistic-requirements detector for job postings.

Flags postings whose stated requirements do not add up:

- ``req.years_impossible``: asks for more years of experience with a
  technology than could plausibly exist given its public release date.
- ``req.junior_senior_mismatch``: junior-level title with senior-level
  years required, or senior-level title with ~1 year required.
- ``req.laundry_list``: demands "expert"-level skill in 6+ technologies,
  or lists 12+ must-have requirement bullets.
- ``req.degree_inflation``: PhD required for a non-research role, or MBA
  required for an individual-contributor engineering role.
- ``req.contradiction``: "entry level"/"no experience necessary" alongside
  "5+ years"/"senior" in the same posting.

All checks are offline, case-insensitive, and degrade gracefully on
empty or malformed input (they return ``[]``).
"""

from __future__ import annotations

import re

from .core import Flag, register

#: Reference year for "years of experience" plausibility math.
CURRENT_YEAR = 2026

#: Approximate first public release year for common tools/frameworks.
#: Values are approximate on purpose; the +1 year slack in the flag
#: condition keeps the check conservative.
TECH_RELEASE = {
    "rust": 2015,
    "kubernetes": 2014,
    "k8s": 2014,
    "go": 2009,
    "golang": 2009,
    "typescript": 2012,
    "react": 2013,
    "terraform": 2014,
    "snowflake": 2014,
    "dbt": 2016,
    "docker": 2013,
    "svelte": 2016,
    "pytorch": 2016,
    "kafka": 2011,
    "airflow": 2015,
    "helm": 2015,
    "next.js": 2016,
}

_YEARS_RE = re.compile(r"\b(\d{1,2})\s*\+?\s*years?\b", re.IGNORECASE)

_JUNIOR_RE = re.compile(
    r"\b(junior|entry[\s-]?level|associate|graduate|grad|intern(?:ship)?)\b",
    re.IGNORECASE,
)
_SENIOR_RE = re.compile(
    r"\b(senior|staff|principal|lead|head of)\b", re.IGNORECASE
)

_EXPERT_RE = re.compile(
    r"\b(?:expert(?:ise)? in|mastery of|deep knowledge of)\s+"
    r"([A-Za-z][\w.+#]*(?:[\s,]+[A-Za-z][\w.+#]*){0,5})",
    re.IGNORECASE,
)

_REQ_HEADING_RE = re.compile(
    r"(?im)^\s*(requirements?|qualifications?|must[\s-]?haves?|"
    r"what you(?:'ll|\u2019ll)? bring|you(?:'ll|\u2019ll) (?:have|need)|"
    r"basic qualifications)\b[^\n]*$"
)
_BULLET_RE = re.compile(r"^\s*(?:[-*\u2022]|\d{1,2}[.)])\s+(\S.*)$")
_GENERIC_HEADING_RE = re.compile(r"^\s*[A-Z][A-Za-z ,&/-]{2,40}:\s*$")

_TITLE_FIELD_RE = re.compile(r"(?im)^\s*(?:job\s+)?title\s*:\s*(.+)$")
_RESEARCH_RE = re.compile(r"\b(research|scientist)\b", re.IGNORECASE)
_PHD_RE = re.compile(r"\b(Ph\.?\s?D\.?|doctorate|doctoral degree)\b", re.IGNORECASE)
_REQ_WORD_RE = re.compile(
    r"\b(required|requirement|must have|mandatory|a must)\b", re.IGNORECASE
)
_MBA_REQ_RE = re.compile(
    r"\bMBA\b.{0,60}?\brequired\b|\brequired\b.{0,60}?\bMBA\b",
    re.IGNORECASE,
)
_ENG_TITLE_RE = re.compile(
    r"\b(engineer|developer|engineering)\b", re.IGNORECASE
)
_MGR_TITLE_RE = re.compile(
    r"\b(manager|director|\bvp\b|vice president|head|chief)\b", re.IGNORECASE
)

_ENTRY_RE = re.compile(
    r"\bentry[\s-]?level\b|no experience (?:necessary|required)",
    re.IGNORECASE,
)
_SENIORISH_RE = re.compile(
    r"\b(?:[5-9]|[1-9]\d)\s*\+\s*years\b|\bsenior\b", re.IGNORECASE
)


def _clean(text) -> str:
    """Return stripped text, or "" for None/non-string input."""
    if not isinstance(text, str):
        return ""
    return text.strip()


def _snippet(text: str, start: int, end: int, width: int = 120) -> str:
    """Quote the match with a little context, trimmed to ~width chars."""
    pad = max(0, (width - (end - start)) // 2)
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    snip = re.sub(r"\s+", " ", text[lo:hi]).strip()
    if len(snip) > width:
        snip = snip[: width - 3].rstrip() + "..."
    if lo > 0:
        snip = "..." + snip
    if hi < len(text):
        snip = snip + "..."
    return snip


def _years_near(text: str, t_start: int, t_end: int, window: int = 80):
    """Find the years-of-experience figure nearest a tech mention.

    Returns ``(years, match_start, match_end)`` or ``None``.
    """
    lo = max(0, t_start - window)
    hi = min(len(text), t_end + window)
    best = None
    for m in _YEARS_RE.finditer(text, lo, hi):
        dist = min(abs(m.start() - t_start), abs(m.end() - t_end))
        if best is None or dist < best[0]:
            best = (dist, int(m.group(1)), m.start(), m.end())
    return None if best is None else best[1:]


def _posting_title(text: str) -> str:
    """Best-effort job title: a Title:/Job Title: field, else first line."""
    m = _TITLE_FIELD_RE.search(text)
    if m:
        return m.group(1).strip()
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _requirement_bullets(text: str) -> list[str]:
    """Bullet items under a Requirements/Qualifications-style heading."""
    m = _REQ_HEADING_RE.search(text)
    if not m:
        return []
    bullets: list[str] = []
    for line in text[m.end() :].splitlines()[:80]:
        if _REQ_HEADING_RE.match(line) or _GENERIC_HEADING_RE.match(line):
            break
        bm = _BULLET_RE.match(line)
        if bm:
            bullets.append(bm.group(1).strip())
    seen: set[str] = set()
    unique: list[str] = []
    for b in bullets:
        key = b.lower()
        if key not in seen:
            seen.add(key)
            unique.append(b)
    return unique


@register
def detect_years_impossible(text: str) -> list[Flag]:
    """Flag experience asks that exceed a technology's public lifetime."""
    text = _clean(text)
    if not text:
        return []
    flags: list[Flag] = []
    for tech, release in TECH_RELEASE.items():
        max_plausible = (CURRENT_YEAR - release) + 1
        pattern = re.compile(r"\b" + re.escape(tech) + r"\b", re.IGNORECASE)
        best_years = 0
        best_span: tuple[int, int] | None = None
        for m in pattern.finditer(text):
            found = _years_near(text, m.start(), m.end())
            if found and found[0] > best_years:
                best_years = found[0]
                best_span = (
                    min(m.start(), found[1]),
                    max(m.end(), found[2]),
                )
        if best_years > max_plausible and best_span is not None:
            gap = best_years - max_plausible
            name = tech.title()
            flags.append(
                Flag(
                    flag_id="req.years_impossible",
                    title=f"Impossible experience ask: {best_years} years of {name}",
                    severity="high" if gap >= 5 else "medium",
                    category="requirements",
                    explanation=(
                        f"{name} was first publicly released around {release}, "
                        f"so even the earliest adopters have at most about "
                        f"{max_plausible} years with it. A posting that demands "
                        f"{best_years} years is asking for something impossible, "
                        "which usually means the requirement was copied without "
                        "thought or the role is poorly defined. It matters "
                        "because you could be screened out by a bar nobody can "
                        "clear."
                    ),
                    evidence=[_snippet(text, *best_span)],
                    suggestion=(
                        f"Ask the recruiter what level of {name} fluency the team "
                        "actually needs day to day, and confirm the posting's "
                        "years figure will not be used as a hard screen."
                    ),
                )
            )
    return flags


@register
def detect_junior_senior_mismatch(text: str) -> list[Flag]:
    """Flag junior titles with senior years (and vice versa)."""
    text = _clean(text)
    if not text:
        return []
    title = _posting_title(text)
    years = [int(n) for n in _YEARS_RE.findall(text)]
    title_span = (0, len(title))
    idx = text.find(title)
    if idx >= 0 and title:
        title_span = (idx, idx + len(title))
    if _JUNIOR_RE.search(title) and years and max(years) >= 4:
        top = max(years)
        return [
            Flag(
                flag_id="req.junior_senior_mismatch",
                title="Junior title, senior-level experience ask",
                severity="medium",
                category="requirements",
                explanation=(
                    f"The title ({title[:60]}) reads junior or entry-level, but "
                    f"the posting asks for {top}+ years of experience. That "
                    "usually means the company wants senior-level output at a "
                    "junior-level salary, or the posting was assembled from "
                    "mismatched templates. Either way, the real level and pay "
                    "band are unclear, so clarify them before you invest time."
                ),
                evidence=[
                    _snippet(text, *title_span),
                    _snippet(text, *_YEARS_RE.search(text).span()),
                ],
                suggestion=(
                    "Ask what level this role is actually budgeted at, what the "
                    "salary band is, and how much mentorship versus independent "
                    "ownership is expected."
                ),
            )
        ]
    if _SENIOR_RE.search(title) and years and max(years) <= 1:
        top = max(years)
        return [
            Flag(
                flag_id="req.junior_senior_mismatch",
                title="Senior title, minimal experience ask",
                severity="medium",
                category="requirements",
                explanation=(
                    f"The title ({title[:60]}) reads senior or staff-level, but "
                    f"the posting asks for at most {top} year(s) of experience. "
                    "Senior titles usually come with ownership, mentorship, and "
                    "pay that reflect several years of practice. This mismatch "
                    "can mean the title is inflated, the pay band is low, or "
                    "the requirements were written carelessly."
                ),
                evidence=[
                    _snippet(text, *title_span),
                    _snippet(text, *_YEARS_RE.search(text).span()),
                ],
                suggestion=(
                    "Ask what scope, ownership, and compensation actually come "
                    "with this title, and why the experience bar is set so low."
                ),
            )
        ]
    return []


@register
def detect_laundry_list(text: str) -> list[Flag]:
    """Flag postings demanding expert skill in everything at once."""
    text = _clean(text)
    if not text:
        return []
    flags: list[Flag] = []
    techs: set[str] = set()
    expert_snips: list[str] = []
    for m in _EXPERT_RE.finditer(text):
        phrase = m.group(1)
        for part in re.split(r",|\band\b|\bor\b|/|&", phrase, flags=re.IGNORECASE):
            part = re.sub(r"^(the|a|an)\s+", "", part.strip().lower())
            part = part.strip(".,;:!?")
            if part and len(part) <= 40:
                techs.add(part)
        if len(expert_snips) < 4:
            expert_snips.append(_snippet(text, *m.span()))
    if len(techs) >= 6:
        flags.append(
            Flag(
                flag_id="req.laundry_list",
                title=f"Laundry list: expert-level skill demanded in {len(techs)} areas",
                severity="medium",
                category="requirements",
                explanation=(
                    f"The posting demands expert-level skill in {len(techs)} "
                    "different technologies. Very few roles genuinely need deep "
                    "expertise in that many tools at once; this usually signals "
                    "an unfocused wishlist or a team that has not decided what "
                    "the job really is. You risk being judged against an "
                    "impossible standard instead of the work you would actually "
                    "do."
                ),
                evidence=expert_snips,
                suggestion=(
                    "Ask the recruiter which 2-3 of these are actually day-one "
                    "critical, and which ones are just nice-to-have."
                ),
            )
        )
    bullets = _requirement_bullets(text)
    if len(bullets) >= 12:
        flags.append(
            Flag(
                flag_id="req.laundry_list",
                title=f"Laundry list: {len(bullets)} separate must-have requirements",
                severity="medium",
                category="requirements",
                explanation=(
                    f"The requirements section lists {len(bullets)} separate "
                    "must-have items. When everything is a must-have, nothing "
                    "is, and it becomes hard to tell what the job really "
                    "involves. Long must-have lists also give hiring teams easy "
                    "excuses to reject strong candidates on trivia."
                ),
                evidence=[b[:120] for b in bullets[:4]],
                suggestion=(
                    "Ask which 2-3 of these are actually day-one critical, and "
                    "treat the rest as flexible until they say otherwise."
                ),
            )
        )
    return flags


@register
def detect_degree_inflation(text: str) -> list[Flag]:
    """Flag PhD/MBA requirements that look like copy-paste boilerplate."""
    text = _clean(text)
    if not text:
        return []
    title = _posting_title(text)
    flags: list[Flag] = []
    for m in _PHD_RE.finditer(text):
        lo = max(0, m.start() - 60)
        hi = min(len(text), m.end() + 60)
        if _REQ_WORD_RE.search(text, lo, hi) and not _RESEARCH_RE.search(title):
            flags.append(
                Flag(
                    flag_id="req.degree_inflation",
                    title="PhD required for a non-research role",
                    severity="low",
                    category="requirements",
                    explanation=(
                        f"The posting requires a PhD or doctorate, but the role "
                        f"({title[:60]}) shows no research focus. For most "
                        "industry engineering roles a doctorate is not needed to "
                        "do the work well, so this often looks like lazy "
                        "boilerplate copied from another posting. It matters "
                        "because an unnecessary degree bar can screen out "
                        "strong candidates, including you."
                    ),
                    evidence=[_snippet(text, *m.span())],
                    suggestion=(
                        "Ask whether the PhD is a hard requirement or a "
                        "nice-to-have, and what parts of the job supposedly "
                        "need it."
                    ),
                )
            )
            break
    if _MBA_REQ_RE.search(text) and _ENG_TITLE_RE.search(title) \
            and not _MGR_TITLE_RE.search(title):
        m = _MBA_REQ_RE.search(text)
        flags.append(
            Flag(
                flag_id="req.degree_inflation",
                title="MBA required for an individual-contributor engineering role",
                severity="low",
                category="requirements",
                explanation=(
                    f"The posting requires an MBA for what looks like an "
                    f"individual-contributor engineering role ({title[:60]}). An "
                    "MBA rarely changes how well someone writes code or "
                    "designs systems, so this usually signals boilerplate or a "
                    "hiring manager chasing credentials over skill. It may just "
                    "be lazy copy-paste, but treat it as a yellow flag about "
                    "how the role is evaluated."
                ),
                evidence=[_snippet(text, *m.span())],
                suggestion=(
                    "Ask whether the MBA is truly required or just preferred, "
                    "and what business responsibilities the role actually has."
                ),
            )
        )
    return flags


@register
def detect_contradiction(text: str) -> list[Flag]:
    """Flag postings that are entry-level and senior-level at once."""
    text = _clean(text)
    if not text:
        return []
    entry = _ENTRY_RE.search(text)
    seniorish = _SENIORISH_RE.search(text)
    if entry and seniorish:
        return [
            Flag(
                flag_id="req.contradiction",
                title="Posting contradicts itself on seniority",
                severity="medium",
                category="requirements",
                explanation=(
                    "The same posting calls the role entry level (or says no "
                    "experience is necessary) while also asking for 5+ years or "
                    "senior-level experience. Those two cannot both be true, "
                    "which means the posting was written carelessly or the "
                    "real expectations are hidden. Apply only after you learn "
                    "which version is real."
                ),
                evidence=[
                    _snippet(text, *entry.span()),
                    _snippet(text, *seniorish.span()),
                ],
                suggestion=(
                    "Ask the recruiter directly: is this an entry-level role "
                    "with entry-level pay, or a senior role? Get the level and "
                    "salary band confirmed before interviewing."
                ),
            )
        ]
    return []
