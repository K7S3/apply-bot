"""STAR story re-framing for career switchers.

A career switcher usually has strong stories from the *old* domain that read
as irrelevant in the *new* domain. This module re-angles a STAR story toward
the competencies a target role cares about:

- ``reframe_story(story, target_role)``: take a STAR dict
  ``{situation, task, action, result}`` and re-angle it toward the
  target-role competencies. Returns ``{reframed, competencies_highlighted,
  suggested_followups}``. The reframed text only reuses words from the
  supplied story plus fixed connective phrasing; it never invents new facts.
- ``tag_competencies(story)``: tag a story with competencies drawn only from
  the fixed ``COMPETENCY_TAXONOMY`` below (keyword-based, deterministic,
  offline).

Deterministic and offline: no network, no paid APIs, no LLMs.
"""

from __future__ import annotations

__all__ = [
    "StoryError",
    "COMPETENCY_TAXONOMY",
    "tag_competencies",
    "reframe_story",
]


class StoryError(Exception):
    """Raised when a story cannot be re-framed (bad input)."""


# ---------------------------------------------------------------------------
# Fixed competency taxonomy. tag_competencies() and reframe_story() only ever
# emit tags from this tuple - never anything invented on the fly.
# ---------------------------------------------------------------------------

COMPETENCY_TAXONOMY: tuple[str, ...] = (
    "leadership",
    "communication",
    "technical depth",
    "ownership",
    "customer focus",
    "ambiguity",
)

# Keywords (lowercase) that suggest each competency. A story is tagged with a
# competency only if one of its keywords appears in the story text.
_COMPETENCY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "leadership": (
        "led", "lead", "managed", "mentored", "coached", "team of",
        "delegated", "hired", "promoted", "stakeholder",
    ),
    "communication": (
        "presented", "presentation", "explained", "wrote", "documented",
        "stakeholder", "negotiat", "persuad", "aligned", "briefed",
    ),
    "technical depth": (
        "migrat", "architect", "pipeline", "algorithm", "model",
        "refactor", "database", "system design", "performance",
        "debugg", "code",
    ),
    "ownership": (
        "owned", "end-to-end", "drove", "initiated", "championed",
        "accountable", "shipped", "launched", "delivered",
    ),
    "customer focus": (
        "customer", "client", "user", "feedback", "nps", "satisfaction",
        "retention", "support ticket", "persona",
    ),
    "ambiguity": (
        "unclear", "ambiguous", "undefined", "figured out", "explored",
        "prototype", "experiment", "no precedent", "greenfield",
    ),
}

STAR_FIELDS: tuple[str, ...] = ("situation", "task", "action", "result")


def _story_text(story: dict) -> str:
    return " ".join(
        str(story.get(field, "") or "") for field in STAR_FIELDS
    ).lower()


def tag_competencies(story: dict) -> list[str]:
    """Tag a STAR story with competencies from the fixed taxonomy.

    ``story`` is a dict with any of the ``situation``, ``task``, ``action``,
    ``result`` keys. Tags are keyword-based and deterministic; only tags from
    ``COMPETENCY_TAXONOMY`` are ever returned, in taxonomy order.
    """
    if not isinstance(story, dict):
        raise StoryError("story must be a dict with STAR fields.")
    text = _story_text(story)
    tags: list[str] = []
    for competency in COMPETENCY_TAXONOMY:
        if any(kw in text for kw in _COMPETENCY_KEYWORDS[competency]):
            tags.append(competency)
    return tags


# ---------------------------------------------------------------------------
# Re-framing toward a target role.
# ---------------------------------------------------------------------------

# Per-target-role (normalized) competency emphasis plus the connective
# phrasing used to re-angle the story. The phrasing only re-labels what the
# story already says; no new facts are introduced.
_ROLE_ANGLES: dict[str, dict] = {
    "product manager": {
        "emphasize": ("customer focus", "communication", "ambiguity", "leadership"),
        "bridge": "From a product-management lens, the transferable core here is",
        "proof_line": "the same product judgment: define the problem, align "
        "stakeholders, and ship against an unclear target.",
    },
    "software engineer": {
        "emphasize": ("technical depth", "ownership", "communication", "ambiguity"),
        "bridge": "From a software-engineering lens, the transferable core here is",
        "proof_line": "the same engineering judgment: scope the work, own the "
        "outcome end-to-end, and make the system better than you found it.",
    },
    "data scientist": {
        "emphasize": ("technical depth", "ambiguity", "communication", "ownership"),
        "bridge": "From a data-science lens, the transferable core here is",
        "proof_line": "the same analytical judgment: turn an ambiguous "
        "question into a measurable answer someone can act on.",
    },
}

_GENERIC_ANGLE = {
    "emphasize": ("ownership", "communication", "ambiguity", "leadership"),
    "bridge": "From a transferable-skills lens, the core here is",
    "proof_line": "the same underlying judgment: take ownership of an unclear "
    "problem, communicate through it, and deliver a result.",
}


def _normalize_role(target_role: str) -> str:
    return " ".join(target_role.strip().lower().split())


def reframe_story(story: dict, target_role: str) -> dict:
    """Re-angle a STAR story toward ``target_role`` competencies.

    ``story`` must be a dict with the keys ``situation``, ``task``,
    ``action``, ``result`` (all non-empty strings). The reframed text reuses
    the story's own words plus fixed connective phrasing; no new facts are
    invented.

    Returns ``{"reframed": str, "competencies_highlighted": [str],
    "suggested_followups": [str]}`` where the competencies come only from
    ``COMPETENCY_TAXONOMY`` and the follow-ups are generic prompts tied to
    the highlighted competencies.
    """
    if not isinstance(story, dict):
        raise StoryError("story must be a dict with STAR fields.")
    missing = [
        field for field in STAR_FIELDS
        if not isinstance(story.get(field), str) or not story[field].strip()
    ]
    if missing:
        raise StoryError(f"story is missing non-empty STAR fields: {missing}.")
    if not isinstance(target_role, str) or not target_role.strip():
        raise StoryError("target_role must be a non-empty string.")

    role_key = _normalize_role(target_role)
    angle = _ROLE_ANGLES.get(role_key, _GENERIC_ANGLE)

    tagged = tag_competencies(story)
    # Competencies highlighted: role-emphasized ones that the story actually
    # shows (i.e. that were tagged); fall back to the tagged set in taxonomy
    # order so the list is never empty when the story has any signal.
    emphasized = [c for c in angle["emphasize"] if c in tagged]
    highlighted = emphasized or tagged

    story_quote = (
        f"Situation: {story['situation'].strip()} "
        f"Task: {story['task'].strip()} "
        f"Action: {story['action'].strip()} "
        f"Result: {story['result'].strip()}"
    )
    reframed = (
        f"{angle['bridge']} {', '.join(highlighted) if highlighted else 'general ownership'}. "
        f"{angle['proof_line']} "
        f"The original story, in your own words: {story_quote}"
    )

    followups = [
        f"How would you apply the {comp} you showed here in this new role?"
        for comp in highlighted
    ]

    return {
        "reframed": reframed,
        "competencies_highlighted": highlighted,
        "suggested_followups": followups,
    }
