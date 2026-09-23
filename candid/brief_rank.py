"""Rank prep questions for an interviewer role and generate topic probes.

``rank_questions`` scores question dicts (the same shape as in
``candid.prep_questions.QUESTIONS_DB``: ``q``, ``category``, optional
``source``) against an interviewer role profile from
``candid.interviewer_roles`` plus optional job-description text.

``topic_deep_dives`` builds probing questions from topic names using
deterministic templates. Its output is GENERATED, not verified: it was
never reported as asked by any company, and every dict it returns
carries ``"generated": True``. Treat it as general preparation, never
as evidence of what a specific company asks.
"""

from __future__ import annotations

import re

from candid.interviewer_roles import get_role_profile

_STOPWORDS = frozenset(
    """
    the a an and or of to in on for with is are was were be been being by at
    as from that this these those it its you your we our us i my me mine he
    him his she her they them their do does did done how what why when where
    which who whom would will shall can could should have has had having if
    into about not but so such than then there here all any both each few
    more most other some no nor only own same too very just also per via
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set:
    """Lowercase word tokens with stopwords and single characters removed."""
    if not isinstance(text, str):
        return set()
    return {
        tok
        for tok in _TOKEN_RE.findall(text.lower())
        if len(tok) > 1 and tok not in _STOPWORDS
    }


def rank_questions(questions: list, *, role: str, jd_text: str = "") -> list:
    """Rank questions for the given interviewer role key.

    Scoring, all deterministic:
      * +2 base when the question's category is one of the role's
        ``angle_categories``; categories listed earlier in the profile
        weigh more (up to +1 extra for the top category).
      * +1 per distinct JD keyword that also appears in the question text
        (simple token overlap, stopwords removed).
      * +0.5 bonus for company-verified questions (those with a ``source``).

    Returns a list of ``(question_dict, score, rationale)`` tuples sorted
    by score, highest first. Ties keep the input order (stable sort).
    ``rationale`` is a short human-readable explanation and is never empty.
    """
    profile = get_role_profile(role)
    angle_cats = [c.lower() for c in profile.get("angle_categories", [])]
    role_slug = str(role).strip().lower().replace("_", "-") if isinstance(role, str) else "interviewer"
    jd_tokens = _tokenize(jd_text)

    ranked = []
    for question in questions:
        score = 0.0
        parts = []

        category = str(question.get("category", "") or "").lower()
        if category in angle_cats:
            idx = angle_cats.index(category)
            bonus = 2.0 + 0.5 * (len(angle_cats) - 1 - idx)
            score += bonus
            parts.append(f"matches {role_slug} angle: {category} (+{bonus:.1f})")
        else:
            parts.append(f"no {role_slug} angle match")

        hits = sorted(jd_tokens & _tokenize(question.get("q", "")))
        score += len(hits)
        if hits:
            shown = ", ".join(hits[:3])
            suffix = ", ..." if len(hits) > 3 else ""
            parts.append(f"{len(hits)} JD keyword hit{'s' if len(hits) != 1 else ''}: {shown}{suffix}")
        else:
            parts.append("no JD keyword overlap")

        if question.get("source"):
            score += 0.5
            parts.append("company-verified question (+0.5)")

        rationale = "; ".join(parts) or "no role-angle or JD-keyword match"
        ranked.append((question, score, rationale))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


_TOPIC_TEMPLATES = [
    ("Walk me through the hardest technical decision you made while working on {topic}.", "decision deep-dive"),
    ("What are the most common failure modes of {topic}, and how have you handled one?", "failure modes"),
    ("Explain {topic} as if I were a strong engineer new to the area. Where do people usually go wrong?", "foundations"),
    ("If you had to rebuild your {topic} work from scratch today, what would you change and why?", "redesign with hindsight"),
    ("How do you validate that your {topic} work is correct, robust, and actually working in practice?", "validation"),
    ("What assumptions does {topic} rely on, and how do you check whether they hold?", "assumptions"),
    ("Compare {topic} to its main alternative. When would you pick each?", "tradeoffs"),
    ("Tell me about a time {topic} did not behave as expected. How did you debug it?", "debugging story"),
]


def topic_deep_dives(topics: list, *, role: str = "domain_specialist", n: int = 5) -> list:
    """Generate probing questions for each topic using fixed templates.

    Deterministic: the same topics, role, and n always produce the same
    output. Each returned dict is ``{"topic", "question", "angle",
    "generated": True}``. These questions are GENERATED, not verified:
    they were invented from templates for general preparation and were
    never reported as asked by any company.
    """
    role_slug = str(role).strip().lower().replace("_", "-") if isinstance(role, str) else "interviewer"
    dives = []
    for topic in topics:
        for i in range(max(0, n)):
            template, angle = _TOPIC_TEMPLATES[i % len(_TOPIC_TEMPLATES)]
            dives.append(
                {
                    "topic": topic,
                    "question": template.format(topic=topic),
                    "angle": f"{role_slug} probe: {angle}",
                    "generated": True,
                }
            )
    return dives
