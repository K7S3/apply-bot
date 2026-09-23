"""Interview-ready STAR stories built from career-ledger wins.

Builds on candid.wins: each ledger win carries a ``star`` dict
({situation, task, action, result}), a competencies list, and optional
impact metrics. This module turns those records into:

- QUESTION_BANK: "Tell me about a time when..." prompts per competency
- win_to_star: a clean STAR dict for one win
- answer_kit: interview Q&A pairings of questions with matching stories
- bullet_drafts: resume bullets grounded strictly in recorded facts
- story_bank_entry: a story-bank-shaped dict for one win

Grounding rule: nothing here invents numbers, employers, dates, or
details. Quantified claims come only from win impacts; gaps are left
as empty strings.
"""
from __future__ import annotations

import re
from typing import Any, Optional

try:  # candid.wins is built by a sibling worker; use it when present
    from candid.wins import load_wins, get_win, list_wins, COMPETENCIES
except ImportError:  # pragma: no cover - wins module not landed yet
    load_wins = None  # type: ignore[assignment]
    get_win = None  # type: ignore[assignment]
    list_wins = None  # type: ignore[assignment]
    COMPETENCIES = (
        "leadership",
        "ownership",
        "communication",
        "system-design",
        "coding",
        "debugging",
        "data-analysis",
        "experimentation",
        "ml-modeling",
        "product-sense",
        "stakeholder-management",
        "mentoring",
        "project-management",
        "incident-response",
        "technical-writing",
        "collaboration",
        "strategic-thinking",
        "customer-focus",
    )

__all__ = [
    "QUESTION_BANK",
    "StarError",
    "win_to_star",
    "answer_kit",
    "bullet_drafts",
    "story_bank_entry",
]


class StarError(Exception):
    """Raised for STAR-kit usage errors."""


# --- question bank ------------------------------------------------------------
# Every seeded competency maps to 2-3 "Tell me about a time when..." prompts.
QUESTION_BANK: dict[str, list[str]] = {
    "leadership": [
        "Tell me about a time when you led a project or team through a difficult challenge.",
        "Tell me about a time when you had to influence people who did not report to you.",
        "Tell me about a time when you set a vision and got others to follow it.",
    ],
    "ownership": [
        "Tell me about a time when you took ownership of a problem outside your job description.",
        "Tell me about a time when you were accountable for a result and things went wrong.",
        "Tell me about a time when you drove something to completion with minimal guidance.",
    ],
    "communication": [
        "Tell me about a time when you had to explain a complex technical topic to a non-technical audience.",
        "Tell me about a time when clear communication prevented or resolved a conflict.",
    ],
    "system-design": [
        "Tell me about a time when you designed a system that had to scale.",
        "Tell me about a time when you made a key architectural tradeoff. What did you choose and why?",
    ],
    "coding": [
        "Tell me about a time when you wrote code you are especially proud of.",
        "Tell me about a time when you refactored a messy codebase.",
    ],
    "debugging": [
        "Tell me about a time when you tracked down a particularly tricky bug.",
        "Tell me about a time when a production issue had you stumped and how you cracked it.",
    ],
    "data-analysis": [
        "Tell me about a time when data changed your mind or a key decision.",
        "Tell me about a time when your analysis uncovered something surprising.",
    ],
    "experimentation": [
        "Tell me about a time when you ran an experiment that failed. What did you learn?",
        "Tell me about a time when an A/B test result surprised you.",
    ],
    "ml-modeling": [
        "Tell me about a time when you built a machine learning model that shipped to production.",
        "Tell me about a time when a model did not perform as expected and how you fixed it.",
    ],
    "product-sense": [
        "Tell me about a time when you shaped a product decision with user insight.",
        "Tell me about a time when you said no to a feature request and why.",
    ],
    "stakeholder-management": [
        "Tell me about a time when you managed competing stakeholder priorities.",
        "Tell me about a time when you had to deliver bad news to a stakeholder.",
    ],
    "mentoring": [
        "Tell me about a time when you mentored someone and saw them grow.",
        "Tell me about a time when you gave difficult feedback to a colleague.",
    ],
    "project-management": [
        "Tell me about a time when you delivered a project under a tight deadline.",
        "Tell me about a time when a project slipped and how you got it back on track.",
    ],
    "incident-response": [
        "Tell me about a time when you responded to a production incident.",
        "Tell me about a time when you led a postmortem after an outage.",
    ],
    "technical-writing": [
        "Tell me about a time when you wrote documentation that others relied on.",
        "Tell me about a time when a design doc you wrote changed a technical decision.",
    ],
    "collaboration": [
        "Tell me about a time when you worked effectively with a difficult team.",
        "Tell me about a time when cross-team collaboration was key to your success.",
    ],
    "strategic-thinking": [
        "Tell me about a time when you shaped a long-term technical strategy.",
        "Tell me about a time when you chose short-term pain for long-term gain.",
    ],
    "customer-focus": [
        "Tell me about a time when you went above and beyond for a customer.",
        "Tell me about a time when customer feedback changed what you built.",
    ],
}

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def _fallback_star(description: str) -> dict[str, str]:
    """Best-effort STAR from free text: first sentence to situation,
    second to task, third to action, the rest to result. Gaps stay ""."""
    sents = _sentences(description)
    parts = {"situation": "", "task": "", "action": "", "result": ""}
    if not sents:
        return parts
    parts["situation"] = sents[0]
    if len(sents) > 1:
        parts["task"] = sents[1]
    if len(sents) > 2:
        parts["action"] = sents[2]
    if len(sents) > 3:
        parts["result"] = " ".join(sents[3:])
    return parts


def win_to_star(win: dict) -> dict:
    """Convert a ledger win into an interview-ready STAR dict.

    Uses win["star"] fields when filled; otherwise falls back to
    splitting the description into sentences across S/T/A/R as best
    effort. Never fabricates specifics; gaps are "".

    Returns {"win_id", "title", "situation", "task", "action",
    "result", "competencies", "role"}.
    """
    star = win.get("star") or {}
    fields = {
        key: str(star.get(key) or "").strip()
        for key in ("situation", "task", "action", "result")
    }
    if not any(fields.values()):
        fields = _fallback_star(str(win.get("description") or ""))
    return {
        "win_id": win.get("id"),
        "title": win.get("title"),
        "situation": fields["situation"],
        "task": fields["task"],
        "action": fields["action"],
        "result": fields["result"],
        "competencies": list(win.get("competencies") or []),
        "role": win.get("role"),
    }


def answer_kit(wins: Optional[list] = None, competency: Optional[str] = None) -> list[dict]:
    """Build an interview answer kit: one entry per (win x matched question).

    Each entry is {"question", "story", "win_id", "title"} where story is
    the win_to_star output. Questions come from QUESTION_BANK for the
    win's own competencies; pass competency to restrict to one. Entries
    are deduped on (win_id, question).
    """
    if wins is None:
        if list_wins is None:
            raise StarError(
                "candid.wins is not available yet; pass wins explicitly"
            )
        wins = list_wins()
    kit: list[dict] = []
    seen: set[tuple[Any, str]] = set()
    for win in wins:
        comps = [c for c in (win.get("competencies") or []) if c in QUESTION_BANK]
        if competency is not None:
            comps = [c for c in comps if c == competency]
        if not comps:
            continue
        story = win_to_star(win)
        for comp in comps:
            for question in QUESTION_BANK[comp]:
                key = (win.get("id"), question)
                if key in seen:
                    continue
                seen.add(key)
                kit.append(
                    {
                        "question": question,
                        "story": story,
                        "win_id": win.get("id"),
                        "title": win.get("title"),
                    }
                )
    return kit


def _fmt_number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


_DOWN_GOOD = ("latency", "error", "cost", "incident", "bug", "churn", "downtime", "failure", "debt")


def _impact_verb(metric: str, before: Any, after: Any) -> str:
    both_num = (
        isinstance(before, (int, float))
        and isinstance(after, (int, float))
        and not isinstance(before, bool)
        and not isinstance(after, bool)
    )
    if both_num:
        if after < before:
            return "Cut" if any(k in metric.lower() for k in _DOWN_GOOD) else "Reduced"
        if after > before:
            return "Improved"
    return "Delivered"


def _impact_bullet(impact: dict) -> str:
    """Quantified bullet from one recorded impact entry only."""
    metric = str(impact.get("metric") or "").strip()
    before = impact.get("before")
    after = impact.get("after")
    unit = str(impact.get("unit") or "").strip()
    if not metric:
        return ""
    suffix = f" {unit}" if unit and not unit.startswith(("$", "%")) else unit
    if before is not None and after is not None:
        verb = _impact_verb(metric, before, after)
        return (
            f"{verb} {metric} from {_fmt_number(before)}{suffix} "
            f"to {_fmt_number(after)}{suffix}."
        )
    if after is not None:
        return f"{_impact_verb(metric, None, after)} {metric} to {_fmt_number(after)}{suffix}."
    if before is not None:
        return f"Measured {metric} at {_fmt_number(before)}{suffix}."
    return ""


def _unquantified_bullet(win: dict) -> str:
    """Bullet from recorded facts only: the action's first sentence
    with a leading 'I' stripped so it reads verb-led, falling back to
    the title. Never adds numbers."""
    star = win.get("star") or {}
    action = str(star.get("action") or "").strip()
    text = ""
    if action:
        first = _sentences(action)[0] if _sentences(action) else ""
        core = re.sub(r"^i\s+", "", first, flags=re.IGNORECASE).strip()
        if core:
            text = core[0].upper() + core[1:]
    if not text:
        text = str(win.get("title") or "").strip()
    if not text:
        return ""
    return text if text[-1] in ".!?" else text + "."


def bullet_drafts(win: dict) -> list[str]:
    """Draft 1-3 resume bullets for a win, action-verb led.

    Quantified claims come ONLY from the win's recorded impacts (never
    invented). With no impacts, bullets stay unquantified. Bullets use
    only facts already recorded on the win.
    """
    bullets: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        text = text.strip()
        if text and text not in seen:
            seen.add(text)
            bullets.append(text)

    for impact in (win.get("impacts") or [])[:2]:
        add(_impact_bullet(impact if isinstance(impact, dict) else {}))
    add(_unquantified_bullet(win))
    return bullets[:3]


def story_bank_entry(win: dict) -> dict:
    """Return a story-bank-shaped entry for a win.

    Shape (kept import-ready for a future ``candid.story_bank`` module;
    this function does not import it)::

        {
            "win_id": str,          # ledger win id
            "title": str,           # win title
            "situation": str,       # STAR fields ("", never invented)
            "task": str,
            "action": str,
            "result": str,
            "competencies": [str],  # ledger competencies on the win
            "role": str | None,     # role the win happened under
            "source": "career-ledger",
            "tags": [str],          # ledger tags on the win
        }
    """
    entry = win_to_star(win)
    entry["source"] = "career-ledger"
    entry["tags"] = list(win.get("tags") or [])
    return entry
