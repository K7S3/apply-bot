"""Bait-and-switch detectors for the JD red-flag engine.

Flags postings where the advertised title, location, or role does not match
what the body actually describes: senior titles on junior work (and the
reverse), tech titles hiding sales/support work, keyword-stuffed title spam,
and "remote" postings that quietly require onsite presence.

All detectors are heuristic, offline, case-insensitive, and return [] for
empty/None input.
"""

from __future__ import annotations

import re

from .core import Flag, register

CATEGORY = "bait-and-switch"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _blank(text) -> bool:
    return not isinstance(text, str) or not text.strip()


def _title(text: str) -> str:
    """First non-empty line of the posting, treated as the job title line."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return ""


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
# 1. bait.title_level_mismatch (high)
# ---------------------------------------------------------------------------

_SENIOR_TITLE = re.compile(
    r"\b(senior|staff|principal|leads?|leader|director|vp|vice\s+president)\b",
    re.IGNORECASE,
)
_JUNIOR_TITLE = re.compile(
    r"\b(junior|associate|intern(?:ship)?|entry[\s-]?level|trainee|apprentice)\b",
    re.IGNORECASE,
)

# Body language that describes junior-level work.
_JUNIOR_BODY = [
    re.compile(r"entry[\s-]?level", re.IGNORECASE),
    re.compile(r"\b[01]\s?[-–—]\s?2\s*years?\b", re.IGNORECASE),
    re.compile(r"\b[01]\s+to\s+2\s*years?\b", re.IGNORECASE),
    re.compile(r"training provided", re.IGNORECASE),
    re.compile(r"under supervision", re.IGNORECASE),
    re.compile(r"no experience (?:required|necessary|needed)", re.IGNORECASE),
    re.compile(r"(?:we )?will train you", re.IGNORECASE),
]

# Body language that describes senior-level duties.
_SENIOR_DUTIES = [
    re.compile(r"lead a team", re.IGNORECASE),
    re.compile(r"manage a team", re.IGNORECASE),
    re.compile(r"own the roadmap", re.IGNORECASE),
    re.compile(r"architect(?:ing)?\s+(?:the|our|a|an|new)\b", re.IGNORECASE),
    re.compile(r"\b(?:[89]|10)\s*\+\s*years?\b", re.IGNORECASE),
    re.compile(r"years of (?:leadership|management) experience", re.IGNORECASE),
    re.compile(r"mentor (?:a team|engineers?|junior)", re.IGNORECASE),
    re.compile(r"set (?:the )?strategy", re.IGNORECASE),
]


def detect_title_level_mismatch(text: str) -> Flag | None:
    """Senior title on junior work, or junior title on senior duties."""
    if _blank(text):
        return None
    title = _title(text)
    senior = _SENIOR_TITLE.search(title)
    junior = _JUNIOR_TITLE.search(title)

    if senior and not junior:
        hits = [p for p in _JUNIOR_BODY if p.search(text)]
        if not hits:
            return None
        return Flag(
            flag_id="bait.title_level_mismatch",
            title="Senior title, junior-level work described",
            severity="high",
            category=CATEGORY,
            explanation=(
                f"The posting advertises a '{senior.group(0)}' title, but the "
                "description reads like a junior role: it mentions "
                "entry-level work, minimal experience, or training and "
                "supervision. This often means the senior title is used to "
                "attract applicants for lower-paid work, or the posting was "
                "copied from a different listing. It is worth confirming "
                "which level the role is actually budgeted at before you "
                "invest time in interviews."
            ),
            evidence=_snippets(text, [p.search(text) for p in _JUNIOR_BODY if p.search(text)]),
            suggestion="Ask the recruiter for the official level and pay band, and confirm the title matches the offer letter.",
        )

    if junior and not senior:
        hits = [p for p in _SENIOR_DUTIES if p.search(text)]
        if not hits:
            return None
        return Flag(
            flag_id="bait.title_level_mismatch",
            title="Junior title, senior-level duties described",
            severity="high",
            category=CATEGORY,
            explanation=(
                f"The posting is titled as a junior role ('{junior.group(0)}'), "
                "but the responsibilities describe senior-level work such as "
                "leading a team, owning a roadmap, or many years of "
                "experience. That can mean doing senior work for junior pay, "
                "or an employer that has not decided what level it needs. "
                "Either way, the mismatch is worth pinning down early."
            ),
            evidence=_snippets(text, [p.search(text) for p in _SENIOR_DUTIES if p.search(text)]),
            suggestion="Ask how the level and compensation were set, and get the scope of the role confirmed in writing.",
        )
    return None


# ---------------------------------------------------------------------------
# 2. bait.role_mismatch (high)
# ---------------------------------------------------------------------------

_TECH_TITLE = re.compile(
    r"\b(engineer|developer|data\s+(?:scientist|analyst|engineer)|devops|sre|"
    r"machine\s+learning|software\s+engineer)\b",
    re.IGNORECASE,
)
# Titles that are honestly sales/support/recruiting are excluded.
_NONTECH_TITLE = re.compile(
    r"\b(sales|support|customer|success|account\s+(?:executive|manager)|"
    r"\bsdr\b|\bbdr\b|recruit|staffing|business\s+development)\b",
    re.IGNORECASE,
)

# (label, pattern) pairs for sales/support/recruiting duty language.
_DUTY_VERBS = [
    ("cold calls", re.compile(r"cold[\s-]?calls?", re.IGNORECASE)),
    ("prospecting", re.compile(r"\bprospect(?:ing|ed|s)?\b", re.IGNORECASE)),
    ("closing deals", re.compile(r"clos(?:e|ing) deals", re.IGNORECASE)),
    ("handling tickets", re.compile(
        r"(?:handle|handling|resolve|resolving|answer|answering)\s+"
        r"(?:support\s+)?tickets?", re.IGNORECASE)),
    ("answering phones", re.compile(r"answer(?:ing)?\s+(?:phones|calls)", re.IGNORECASE)),
    ("upselling", re.compile(r"\bupsell(?:ing|ed|s)?\b", re.IGNORECASE)),
    ("outbound calls", re.compile(r"outbound calls?", re.IGNORECASE)),
    ("call quotas", re.compile(r"calls?\s+(?:a|per)\s+day", re.IGNORECASE)),
    ("recruiting", re.compile(r"\brecruit(?:ing|er|ers|ment)?\b", re.IGNORECASE)),
    ("sourcing candidates", re.compile(r"source candidates", re.IGNORECASE)),
    ("screening resumes", re.compile(r"screen(?:ing)? resumes", re.IGNORECASE)),
    ("sales quotas", re.compile(
        r"(?:sales|call)\s+quota|hit (?:your )?quota|meet (?:your )?quota",
        re.IGNORECASE)),
]

# At least this many distinct non-tech duty signals counts as "dominated".
_ROLE_MISMATCH_THRESHOLD = 3


def detect_role_mismatch(text: str) -> Flag | None:
    """Tech title whose body is dominated by sales/support/recruiting duties."""
    if _blank(text):
        return None
    title = _title(text)
    if not _TECH_TITLE.search(title) or _NONTECH_TITLE.search(title):
        return None
    matched = [(label, pat.search(text)) for label, pat in _DUTY_VERBS]
    matched = [(label, m) for label, m in matched if m]
    if len(matched) < _ROLE_MISMATCH_THRESHOLD:
        return None
    labels = ", ".join(label for label, _ in matched)
    return Flag(
        flag_id="bait.role_mismatch",
        title="Tech title, sales/support duties in the body",
        severity="high",
        category=CATEGORY,
        explanation=(
            "The title advertises an engineering or data role, but the body "
            f"is dominated by a different job: {labels}. When the actual "
            "day-to-day differs this much from the advertised title, the "
            "posting may be mislabeled to attract technical applicants, or "
            "the role may have been repurposed after posting. Either way, "
            "what you would actually be hired to do is unclear."
        ),
        evidence=_snippets(text, [m for _, m in matched]),
        suggestion="Ask for a typical week in the role and what share of time goes to engineering versus sales or support work.",
    )


# ---------------------------------------------------------------------------
# 3. bait.keyword_stuffing (medium)
# ---------------------------------------------------------------------------

# (label, pattern) pairs for recognizable job titles.
_JOB_TITLES = [
    ("java developer", re.compile(r"\bjava developer\b", re.IGNORECASE)),
    ("python developer", re.compile(r"\bpython developer\b", re.IGNORECASE)),
    ("c++ developer", re.compile(r"c\+\+\s+developer", re.IGNORECASE)),
    ("frontend developer", re.compile(r"\bfront[\s-]?end developer\b", re.IGNORECASE)),
    ("backend developer", re.compile(r"\bback[\s-]?end developer\b", re.IGNORECASE)),
    ("full stack developer", re.compile(r"\bfull[\s-]?stack developer\b", re.IGNORECASE)),
    ("mobile developer", re.compile(r"\bmobile developer\b", re.IGNORECASE)),
    ("ios developer", re.compile(r"\bios developer\b", re.IGNORECASE)),
    ("android developer", re.compile(r"\bandroid developer\b", re.IGNORECASE)),
    (".net developer", re.compile(r"\.net developer", re.IGNORECASE)),
    ("web developer", re.compile(r"\bweb developer\b", re.IGNORECASE)),
    ("devops engineer", re.compile(r"\bdevops engineer\b", re.IGNORECASE)),
    ("data analyst", re.compile(r"\bdata analyst\b", re.IGNORECASE)),
    ("data engineer", re.compile(r"\bdata engineer\b", re.IGNORECASE)),
    ("data scientist", re.compile(r"\bdata scientist\b", re.IGNORECASE)),
    ("ml engineer", re.compile(r"\bmachine learning engineer\b", re.IGNORECASE)),
    ("qa engineer", re.compile(r"\bqa engineer\b", re.IGNORECASE)),
    ("test engineer", re.compile(r"\btest engineer\b", re.IGNORECASE)),
    ("systems administrator", re.compile(r"\bsystems? administrator\b", re.IGNORECASE)),
    ("network engineer", re.compile(r"\bnetwork engineer\b", re.IGNORECASE)),
    ("security engineer", re.compile(r"\bsecurity engineer\b", re.IGNORECASE)),
    ("project manager", re.compile(r"\bproject manager\b", re.IGNORECASE)),
    ("product manager", re.compile(r"\bproduct manager\b", re.IGNORECASE)),
    ("scrum master", re.compile(r"\bscrum master\b", re.IGNORECASE)),
    ("business analyst", re.compile(r"\bbusiness analyst\b", re.IGNORECASE)),
    ("ui designer", re.compile(r"\bui designer\b", re.IGNORECASE)),
    ("ux designer", re.compile(r"\bux designer\b", re.IGNORECASE)),
    ("ui/ux designer", re.compile(r"\bui/?ux designer\b", re.IGNORECASE)),
]

# Phrases that signal a stuffed "also hiring" title list.
_STUFFING_MARKER = re.compile(
    r"also hiring|similar (?:jobs|titles|roles)|related (?:titles|searches|jobs)|"
    r"\bkeywords\s*:|\btags\s*:|other (?:job )?titles|we are hiring.{0,40}:",
    re.IGNORECASE,
)


def detect_keyword_stuffing(text: str) -> Flag | None:
    """SEO-style spam: many distinct job titles crammed into one posting."""
    if _blank(text):
        return None
    matched = [(label, pat.search(text)) for label, pat in _JOB_TITLES]
    matched = [(label, m) for label, m in matched if m]
    marker = _STUFFING_MARKER.search(text)
    threshold = 4 if marker else 6
    if len(matched) < threshold:
        return None
    labels = ", ".join(label for label, _ in matched[:8])
    return Flag(
        flag_id="bait.keyword_stuffing",
        title="Keyword-stuffed job titles",
        severity="medium",
        category=CATEGORY,
        explanation=(
            f"This posting names {len(matched)} distinct job titles "
            f"({labels}), which looks like keyword stuffing to catch search "
            "traffic rather than a description of one real role. Stuffed "
            "postings are often recycled across many openings or posted by "
            "aggregators, so the actual job behind the listing is unclear. "
            "Treat the stated title and requirements with extra skepticism."
        ),
        evidence=_snippets(text, [m for _, m in matched]),
        suggestion="Verify the role exists on the company's own careers page, and confirm the exact title with the recruiter.",
    )


# ---------------------------------------------------------------------------
# 4. bait.remote_bait (medium)
# ---------------------------------------------------------------------------

_REMOTE_AD = re.compile(
    r"\b(remote|wfh|work from home|fully remote|remote[\s-]?first)\b",
    re.IGNORECASE,
)
_REMOTE_CONTRADICTIONS = [
    ("must relocate", re.compile(r"must relocate", re.IGNORECASE)),
    ("relocation required", re.compile(r"relocation (?:is )?required", re.IGNORECASE)),
    ("onsite 5 days", re.compile(r"on[\s-]?site\s+5\s+days?", re.IGNORECASE)),
    ("5 days in office", re.compile(
        r"5\s+days?\s+(?:a week\s+)?in (?:the )?office", re.IGNORECASE)),
    ("hybrid", re.compile(r"\bhybrid\b", re.IGNORECASE)),
    ("remote within miles", re.compile(
        r"remote\s*\([^)]*within\s+\d+\s*(?:miles|mi)\b", re.IGNORECASE)),
]


def detect_remote_bait(text: str) -> Flag | None:
    """'Remote' advertised prominently but contradicted in the body."""
    if _blank(text):
        return None
    prominent = _title(text) + "\n" + text[:200]
    ad = _REMOTE_AD.search(prominent)
    if not ad:
        return None
    hits = [(label, pat.search(text)) for label, pat in _REMOTE_CONTRADICTIONS]
    hits = [(label, m) for label, m in hits if m]
    if not hits:
        return None
    labels = ", ".join(label for label, _ in hits)
    return Flag(
        flag_id="bait.remote_bait",
        title="Remote advertised, onsite required in the body",
        severity="medium",
        category=CATEGORY,
        explanation=(
            "The posting advertises remote work prominently, but the body "
            f"walks it back ({labels}). This is a common bait pattern: the "
            "remote label pulls in applicants who would never have applied "
            "to an onsite or hybrid role. The real location expectation may "
            "be stricter than the headline suggests."
        ),
        evidence=_snippets(text, [ad] + [m for _, m in hits]),
        suggestion="Ask how many days per week are actually expected in the office, and get the remote arrangement in the offer letter.",
    )


# ---------------------------------------------------------------------------
# registered detector
# ---------------------------------------------------------------------------

@register
def detect(text: str) -> list[Flag]:
    """Run all bait-and-switch sub-detectors over the posting text."""
    if _blank(text):
        return []
    flags: list[Flag] = []
    for fn in (
        detect_title_level_mismatch,
        detect_role_mismatch,
        detect_keyword_stuffing,
        detect_remote_bait,
    ):
        try:
            flag = fn(text)
        except Exception:
            continue
        if flag is not None:
            flags.append(flag)
    return flags
