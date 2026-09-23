"""Vague-role detectors (category ``clarity``).

Flags postings that don't say what the job actually is: no responsibilities
section, buzzword-heavy copy with no concrete action verbs, a catch-all
"other duties as assigned" paired with an empty responsibilities section, or
no information about the team you'd join.

All detectors are offline, case-insensitive, and return ``[]`` for
empty/``None`` input.
"""

from __future__ import annotations

import re

from .core import Flag, register

CATEGORY = "clarity"

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
# clarity.no_responsibilities
# ---------------------------------------------------------------------------

_RESPONSIBILITY_MARKERS = re.compile(
    r"(?i)"
    r"(?:responsibilit(?:y|ies)|dut(?:y|ies)|what you(?:'ll| will) do|"
    r"you will\b|day[\s-]?to[\s-]?day|key accountabilities|the role\b|"
    r"what the job (?:involves|entails)|your (?:mission|mandate))\b"
)


@register
def detect_no_responsibilities(text: str | None) -> list[Flag]:
    """Flag postings with no responsibilities/duties section at all."""
    text = _text(text)
    if not text.strip():
        return []
    match = _RESPONSIBILITY_MARKERS.search(text)
    if match:
        return []
    evidence = re.sub(r"\s+", " ", text[:_SNIPPET_CHARS]).strip()
    if len(text) > _SNIPPET_CHARS:
        evidence += "…"
    return [
        _flag(
            flag_id="clarity.no_responsibilities",
            title="No responsibilities section",
            severity="medium",
            explanation=(
                "This posting never says what the job actually involves. There is "
                "no responsibilities, duties, or 'what you'll do' section, so you "
                "cannot tell what your day-to-day work would look like. Postings "
                "like this often reflect an unscoped role or a posting written "
                "without input from the hiring team."
            ),
            evidence=[evidence] if evidence else [],
            suggestion=(
                "Before applying, ask the recruiter or hiring manager for the "
                "actual day-to-day: what you would own in the first 90 days, "
                "what success looks like, and how your time splits across tasks."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# clarity.buzzword_soup
# ---------------------------------------------------------------------------

_BUZZWORDS = (
    "synergy",
    "synergies",
    "leverage",  # as filler verb: "leverage synergies"
    "paradigm",
    "disrupt",
    "disruption",
    "disruptive",
    "thought leader",
    "thought leadership",
    "bleeding edge",
    "move fast",
    "deep dive",
    "deep-dives",
    "game changer",
    "game-changer",
    "world-class",
    "rockstar",
    "rock star",
    "ninja",
    "guru",
    "go-getter",
    "self-starter",
    "fast-paced environment",
    "dynamic environment",
    "wear many hats",
    "think outside the box",
    "move the needle",
    "circle back",
    "boil the ocean",
    "low-hanging fruit",
    "ideate",
    "ideation",
    "evangelize",
    "evangelist",
)

_ACTION_VERBS = (
    "build",
    "built",
    "builds",
    "ship",
    "shipped",
    "ships",
    "own",
    "owns",
    "owned",
    "maintain",
    "maintains",
    "debug",
    "design",
    "designs",
    "test",
    "tests",
    "deploy",
    "deploys",
    "review",
    "reviews",
    "document",
    "architect",
    "implement",
    "implements",
    "optimize",
    "optimizes",
    "mentor",
    "mentors",
    "lead",
    "leads",
    "write",
    "writes",
    "fix",
    "fixes",
    "launch",
    "launches",
    "monitor",
    "monitors",
    "refactor",
    "integrate",
    "integrates",
    "scale",
    "scales",
    "automate",
    "automates",
    "triage",
    "onboard",
    "pair",
)

_BUZZWORD_RE = re.compile(
    r"(?i)\b(?:"
    + "|".join(re.escape(b) for b in sorted(_BUZZWORDS, key=len, reverse=True))
    + r")\b"
)
_ACTION_RE = re.compile(
    r"(?i)\b(?:"
    + "|".join(sorted(set(_ACTION_VERBS), key=len, reverse=True))
    + r")\b"
)

_MIN_CHARS = 300
_MIN_BUZZWORDS = 2
# Flag when buzzwords make up at least this share of (buzzwords + action verbs).
_SOUP_RATIO = 0.5


@register
def detect_buzzword_soup(text: str | None) -> list[Flag]:
    """Flag buzzword-heavy postings with few concrete action verbs."""
    text = _text(text)
    if len(text.strip()) < _MIN_CHARS:
        return []
    buzz = _BUZZWORD_RE.findall(text)
    actions = _ACTION_RE.findall(text)
    n_buzz, n_actions = len(buzz), len(actions)
    if n_buzz < _MIN_BUZZWORDS:
        return []
    if n_actions == 0:
        soupy = n_buzz >= 3
    else:
        soupy = n_buzz / (n_buzz + n_actions) >= _SOUP_RATIO
    if not soupy:
        return []
    first = _BUZZWORD_RE.search(text)
    return [
        _flag(
            flag_id="clarity.buzzword_soup",
            title="Buzzword soup, few concrete verbs",
            severity="low",
            explanation=(
                f"This posting leans on corporate buzzwords ({n_buzz} found) while "
                f"using few concrete action verbs ({n_actions} found). Vague language "
                "like this makes it hard to tell what the role really does day to "
                "day, and it often signals a posting written by marketing rather "
                "than the team doing the work."
            ),
            evidence=[_snippet(text, first)] if first else [],
            suggestion=(
                "Ask for specifics: what would you build, own, or ship in the "
                "first 90 days, and what does a typical week look like?"
            ),
        )
    ]


# ---------------------------------------------------------------------------
# clarity.duties_assigned
# ---------------------------------------------------------------------------

_DUTIES_ASSIGNED_RE = re.compile(r"(?i)\bother duties as assigned\b")

# Headings that typically end a responsibilities section.
_SECTION_END_RE = re.compile(
    r"(?im)^\s*(?:requirements|qualifications|preferred qualifications|"
    r"nice[\s-]?to[\s-]?haves?|benefits|compensation|salary|about (?:us|the (?:company|team|role))|"
    r"what we offer|how to apply|equal opportunity|eeo)\b"
)


def _responsibilities_section(text: str) -> str:
    """Extract the responsibilities section body, or "" if none found."""
    match = _RESPONSIBILITY_MARKERS.search(text)
    if not match:
        return ""
    rest = text[match.end() :]
    end = _SECTION_END_RE.search(rest)
    return rest[: end.start()] if end else rest


@register
def detect_duties_assigned(text: str | None) -> list[Flag]:
    """Flag 'other duties as assigned' paired with a near-empty duties section."""
    text = _text(text)
    if not text.strip():
        return []
    match = _DUTIES_ASSIGNED_RE.search(text)
    if not match:
        return []
    section = _responsibilities_section(text)
    # Strip the catch-all clause itself before measuring real content.
    content = _DUTIES_ASSIGNED_RE.sub("", section)
    content = re.sub(r"\s+", " ", content).strip(" :-•\t\n")
    if len(content) >= 150:
        return []
    return [
        _flag(
            flag_id="clarity.duties_assigned",
            title="'Other duties as assigned' with no real job description",
            severity="medium",
            explanation=(
                "This posting includes the catch-all 'other duties as assigned' but "
                "the responsibilities section itself is nearly empty. That means "
                "the role is effectively undefined: the employer is asking you to "
                "do whatever comes up without saying what the core job is. It can "
                "be a sign of scope creep or a role nobody has thought through."
            ),
            evidence=[_snippet(text, match)],
            suggestion=(
                "Ask what the actual day-to-day looks like and what percentage of "
                "time goes to the listed duties versus 'other duties'. Get the "
                "core responsibilities in writing before accepting."
            ),
        )
    ]


# ---------------------------------------------------------------------------
# clarity.no_team_info
# ---------------------------------------------------------------------------

_TEAM_MARKERS = re.compile(
    r"(?i)\b(?:"
    r"your team|the team|team of|reporting to|reports to|hiring manager|"
    r"direct reports?|people manager|engineering team|product team|"
    r"data team|design team|work closely with|cross[\s-]?functional"
    r")\b"
)


@register
def detect_no_team_info(text: str | None) -> list[Flag]:
    """Flag postings that say nothing about the team, manager, or org."""
    text = _text(text)
    if not text.strip():
        return []
    if _TEAM_MARKERS.search(text):
        return []
    evidence = re.sub(r"\s+", " ", text[:_SNIPPET_CHARS]).strip()
    if len(text) > _SNIPPET_CHARS:
        evidence += "…"
    return [
        _flag(
            flag_id="clarity.no_team_info",
            title="No team or reporting-line information",
            severity="low",
            explanation=(
                "This posting never mentions the team you would join, who you "
                "would report to, or how the role fits into the organization. "
                "Your manager and teammates shape your day-to-day experience more "
                "than almost anything else, so a posting that omits them leaves a "
                "big unknown."
            ),
            evidence=[evidence] if evidence else [],
            suggestion=(
                "Ask who you would work with daily: the team size, your manager, "
                "and where this role sits in the org chart."
            ),
        )
    ]
