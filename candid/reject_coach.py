"""Rejection coach: classify rejections and turn them into next actions.

Given a rejection record (a plain dict like ``{"app_id": 3, "company": "Acme",
"role": "MLE", "stage": "technical", "reason_notes": "...", "feedback": "..."}``),
this module figures out *why* it likely happened and tells you what to do
next. It stays deliberately dependency-free: the keyword classifier below is
self-contained so it works without any ML stack.

Nothing here sugar-coats anything. The advice is concrete: do this, then
that, because the data says so.
"""

from __future__ import annotations

import re
from collections import Counter

__all__ = [
    "CATEGORY_KEYWORDS",
    "UNSTATED",
    "RejectCoachError",
    "categorize",
    "next_actions",
    "pattern_advice",
    "morale_summary",
    "render_actions",
    "render_advice",
    "render_morale",
]


class RejectCoachError(Exception):
    """Raised when a rejection record is malformed."""


# Checked in dict order; the first category with any keyword hit wins.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "experience_gap": [
        "years of experience",
        "not enough experience",
        "experience gap",
        "more experienced",
        "level mismatch",
        "underqualified",
        "depth of experience",
        "looking for someone senior",
        "stronger background",
        "background does not match",
    ],
    "ghosted": [
        "ghosted",
        "never heard back",
        "no response",
        "no reply",
        "unresponsive",
        "went dark",
        "stopped responding",
        "radio silence",
    ],
    "location": [
        "relocation",
        "location",
        "remote",
        "hybrid",
        "return to office",
        "time zone",
        "visa",
        "sponsorship",
    ],
    "compensation": [
        "compensation",
        "salary",
        "pay band",
        "below band",
        "band",
        "total comp",
        "equity",
        "offer too low",
        "could not meet",
    ],
    "headcount_freeze": [
        "headcount",
        "hiring freeze",
        "freeze",
        "budget",
        "req frozen",
        "hiring pause",
    ],
    "culture_fit": [
        "culture fit",
        "cultural fit",
        "team fit",
        "not a fit",
        "values",
        "working style",
    ],
    "role_closed": [
        "role closed",
        "position closed",
        "requisition closed",
        "req closed",
        "position filled",
        "role filled",
        "already filled",
        "hired internally",
        "internal candidate",
        "pulled the req",
        "cancelled the role",
        "canceled the role",
        "role cancelled",
        "role canceled",
    ],
}

UNSTATED = "unstated"


def _keyword_regexes() -> list[tuple[str, "re.Pattern[str]"]]:
    pairs = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            pairs.append((category, re.compile(r"\b" + re.escape(kw) + r"\b")))
    return pairs


_KEYWORD_PAIRS = _keyword_regexes()


def categorize(notes: str) -> str:
    """Classify free-text rejection notes into a reason category.

    Returns the first matching category (checked in ``CATEGORY_KEYWORDS``
    order) or ``"unstated"`` when the notes are empty or match nothing.
    """
    text = (notes or "").lower()
    if not text.strip():
        return UNSTATED
    for category, pattern in _KEYWORD_PAIRS:
        if pattern.search(text):
            return category
    return UNSTATED


_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def next_actions(rejection: dict) -> list[dict]:
    """Generate a prioritized action list for one rejection.

    Each item is ``{"action": str, "why": str, "priority": "high"|"medium"|"low"}``.
    Actions come from the stage reached plus the classified reason. Always
    capped at 6, highest priority first.
    """
    if not isinstance(rejection, dict):
        raise RejectCoachError("rejection must be a dict")

    stage = rejection.get("stage") or ""
    category = categorize(rejection.get("reason_notes") or "")
    actions: list[dict] = []

    def add(action: str, why: str, priority: str) -> None:
        actions.append({"action": action, "why": why, "priority": priority})

    # --- stage-driven actions ------------------------------------------------
    if stage == "recruiter_screen":
        add(
            "Tailor your resume to the JD keywords before the next application.",
            "Recruiter screens filter on keyword match first; a tailored resume gets you past them.",
            "high",
        )
        add(
            "Clarify location and remote expectations in the first recruiter call.",
            "Surprises about location or remote policy are the cheapest rejections to prevent.",
            "medium",
        )
    elif stage in ("phone_screen", "technical"):
        add(
            "Drill coding problems in the exact areas that stumped you this round.",
            "Technical rejections cluster around a few weak topics; targeted reps close them fastest.",
            "high",
        )
        add(
            "Log a debrief of what stumped you: the questions, your approach, where it broke.",
            "You cannot fix what you cannot remember; a same-day debrief is your training data.",
            "high",
        )
    elif stage in ("onsite", "final"):
        add(
            "Review your behavioral story bank and tighten two or three stories.",
            "Late-stage rejections are usually about signal, not skill; crisper stories raise the signal.",
            "high",
        )
        add(
            "Schedule system-design reps with a timer before the next onsite.",
            "Full-loop mocks are the only reps that translate to full-loop performance.",
            "medium",
        )
    elif stage == "applied":
        add(
            "Tighten the resume: one tailored pass per application, keyword coverage checked.",
            "Application-stage rejections are a top-of-funnel resume filter problem.",
            "high",
        )

    # --- reason-driven actions -----------------------------------------------
    if category == "ghosted":
        add(
            "Set a 7-day follow-up cadence on every live application instead of waiting.",
            "Ghosted rejections usually mean you fell off their radar, not that you were judged.",
            "high",
        )
    elif category == "experience_gap":
        add(
            "Target postings whose years requirement matches your actual experience.",
            "Fighting the years-of-experience filter wastes cycles you could spend where you fit.",
            "medium",
        )
        add(
            "Highlight adjacent experience on your resume for stretch roles.",
            "Adjacent experience is how you earn interviews at the next level up.",
            "medium",
        )
    elif category in ("headcount_freeze", "role_closed"):
        add(
            "Schedule a re-approach in 9 months: note the hiring manager and team.",
            "This rejection was about their budget or req, not about you; the door reopens.",
            "low",
        )
    elif category == "compensation":
        add(
            "Align on the compensation band in the recruiter screen, before investing hours.",
            "Band mismatches discovered at the offer stage waste an entire loop of effort.",
            "medium",
        )
    elif category == "location":
        add(
            "State your location and remote constraints in the very first call.",
            "Location is a binary filter; surface it early so it filters you cheaply.",
            "medium",
        )
    elif category == "culture_fit":
        add(
            "Reflect on the team-fit signals and tune your stories for culture questions.",
            "Fit rejections are soft; concrete examples of how you work raise them.",
            "medium",
        )
    elif category == UNSTATED:
        add(
            "Ask for feedback in your thank-you note to the recruiter.",
            "Unstated reasons are invisible data; one reply turns them into something actionable.",
            "medium",
        )

    # --- always appended ------------------------------------------------------
    add(
        "Write a 5-minute debrief while it is fresh.",
        "Memory of what went wrong fades in hours; five minutes now saves weeks of guessing.",
        "high",
    )

    # Dedupe on action text, then stable-sort highs first, cap at 6.
    seen: set[str] = set()
    unique = [a for a in actions if not (a["action"] in seen or seen.add(a["action"]))]
    unique.sort(key=lambda a: _PRIORITY_RANK[a["priority"]])
    return unique[:6]


_STAGE_ADVICE = {
    "recruiter_screen": (
        "Multiple rejections at the recruiter screen: tighten resume keywords to the JD "
        "and confirm fit, location, and comp band in the first call. The filter is thin; "
        "small wording changes move you through it."
    ),
    "phone_screen": (
        "Multiple rejections in early rounds: drill the coding patterns that stumped you "
        "and write a debrief the same day. Early-round failures are usually fixable reps, "
        "not talent verdicts."
    ),
    "technical": (
        "Multiple rejections in early rounds: drill the coding patterns that stumped you "
        "and write a debrief the same day. Early-round failures are usually fixable reps, "
        "not talent verdicts."
    ),
    "onsite": (
        "Multiple rejections at the onsite or final stage: invest in behavioral story-bank "
        "reps and timed full-loop mocks. You are close; the gap is polish and stamina, "
        "not fundamentals."
    ),
    "final": (
        "Multiple rejections at the onsite or final stage: invest in behavioral story-bank "
        "reps and timed full-loop mocks. You are close; the gap is polish and stamina, "
        "not fundamentals."
    ),
    "applied": (
        "Multiple rejections at the application stage: the top-of-funnel filter is your "
        "resume. Tailor it per JD and verify keyword coverage before each submission."
    ),
    "offer": (
        "Rejections at the offer stage are rare and usually about band or timing. Clarify "
        "expectations in the recruiter screen so the loop does not end in a mismatch."
    ),
}


def pattern_advice(rejections: list[dict]) -> list[str]:
    """Advice from clustering rejections by stage and reason category.

    Honest and concrete: it says what the data shows, not what feels good.
    """
    if not rejections:
        return ["No rejections logged yet - advice appears once there is data."]

    advice: list[str] = []
    stage_counts = Counter(r.get("stage") or UNSTATED for r in rejections)
    category_counts = Counter(
        categorize(r.get("reason_notes") or "") for r in rejections
    )

    for stage, count in stage_counts.most_common():
        if count >= 2 and stage in _STAGE_ADVICE:
            advice.append(_STAGE_ADVICE[stage])

    top_category, top_count = category_counts.most_common(1)[0]
    if top_category == "ghosted":
        advice.append(
            f"Ghosting is your most common outcome ({top_count} of {len(rejections)}): "
            "run a 7-day follow-up cadence on every live application. Do not sit and "
            "wait; silence is usually disorganization, not a verdict."
        )

    if len(rejections) >= 3 and not any((r.get("feedback") or "").strip() for r in rejections):
        advice.append(
            "None of these rejections came with feedback. Start asking for it in every "
            "thank-you note to the recruiter; without feedback you are guessing in the dark."
        )

    return advice


def morale_summary(apps: list[dict], rejections: list[dict]) -> dict:
    """Honest pipeline numbers derived only from the user's own data.

    Returns ``{"applications", "rejections", "interviews", "active", "line"}``.
    The line never cites benchmarks; it only restates the user's numbers.
    """
    apps = apps or []
    rejections = rejections or []
    interviews = sum(1 for a in apps if a.get("status") == "selected_for_interview")
    active = sum(
        1 for a in apps if a.get("status") not in ("rejected", "withdrawn", "offer")
    )

    if not apps:
        line = "No applications tracked yet - the pipeline starts with the first one."
    else:
        line = (
            f"{active} applications in flight, {interviews} interviews so far - "
            "the pipeline is moving."
        )
        if not rejections:
            line += " No rejections yet."
        elif len(rejections) >= 3 and interviews == 0:
            line += " Rejections are piling up without interviews; revisit the top of the funnel."

    return {
        "applications": len(apps),
        "rejections": len(rejections),
        "interviews": interviews,
        "active": active,
        "line": line,
    }


def render_actions(actions: list[dict]) -> str:
    """Render a prioritized action list as numbered text."""
    if not actions:
        return "No actions."
    lines = ["Next actions:"]
    for i, action in enumerate(actions, 1):
        lines.append(f"{i}. [{action['priority']}] {action['action']}")
        lines.append(f"   Why: {action['why']}")
    return "\n".join(lines)


def render_advice(lines: list[str]) -> str:
    """Render pattern advice as a bulleted list."""
    if not lines:
        return "No advice yet."
    return "\n".join(f"- {line}" for line in lines)


def render_morale(summary: dict) -> str:
    """Render the morale summary: the line first, then the raw counts."""
    return (
        f"{summary['line']}\n"
        f"Applications: {summary['applications']} | "
        f"Rejections: {summary['rejections']} | "
        f"Interviews: {summary['interviews']} | "
        f"Active: {summary['active']}"
    )
