"""Career-switcher interview prep: classic switcher questions with answer frameworks.

A career switcher (a candidate changing roles or industries) faces a small
set of recurring interview questions that candidates on a linear track do
not. This module ships:

- ``switcher_questions(target_role)``: the classic switcher questions
  ("Why are you switching?", "Why this role/industry?", "How will you ramp
  up?", "Aren't you overqualified/underqualified?"), each with a structured
  answer framework built on the hook-bridge-proof-close pattern, plus do/don't
  guidance.
- ``build_answer(question, user_facts)``: assemble a draft answer from the
  supplied facts only. Nothing is invented: any fact that is needed by the
  framework but missing from ``user_facts`` becomes an explicit
  ``[PLACEHOLDER]`` marker the candidate can fill in later.

Everything here is deterministic and offline. The frameworks are generic
interview strategy, not advice about any specific company or role.
"""

from __future__ import annotations

__all__ = [
    "SwitcherQuestionError",
    "FRAMEWORK_STEPS",
    "QUESTIONS",
    "switcher_questions",
    "build_answer",
]


class SwitcherQuestionError(Exception):
    """Raised when a switcher-interview request is invalid."""


# ---------------------------------------------------------------------------
# The hook-bridge-proof-close framework used for every switcher question.
# ---------------------------------------------------------------------------

FRAMEWORK_STEPS = (
    "hook",
    "bridge",
    "proof",
    "close",
)

FRAMEWORK_DESCRIPTIONS: dict[str, str] = {
    "hook": "Open with a short, genuine statement of what draws you to this "
    "move (30 seconds max). Personal but professional.",
    "bridge": "Connect your past experience to the target role: name the "
    "transferable skills and patterns that carry over.",
    "proof": "Ground the bridge with one concrete example: what you did, "
    "the context, and the measurable outcome.",
    "close": "End by looking forward: what you want to learn in the first "
    "90 days and why you are excited about this team.",
}


def _framework() -> dict[str, str]:
    """Return the hook-bridge-proof-close framework description."""
    return {
        step: FRAMEWORK_DESCRIPTIONS[step]
        for step in FRAMEWORK_STEPS
    }


# ---------------------------------------------------------------------------
# The classic switcher question bank.
# ---------------------------------------------------------------------------

_QUESTION_DEFS: tuple[dict, ...] = (
    {
        "id": "why_switching",
        "question": "Why are you switching careers?",
        "why_asked": "The interviewer is screening for red flags (fleeing "
        "vs. pursuing) and for whether the motivation will last.",
        "framework": _framework(),
        "do": [
            "Frame the switch as moving *toward* something, not away from "
            "something.",
            "Name one specific thing you discovered about yourself or the "
            "target field that made the switch feel right.",
            "Keep it short: a 60-90 second answer beats a life story.",
        ],
        "dont": [
            "Don't badmouth your current/previous field, team, or employer.",
            "Don't sound like you are experimenting ('I thought I'd try "
            "something new').",
            "Don't imply the switch was forced and you have no plan.",
        ],
        "needed_facts": ["motivating_experience", "current_role", "target_role"],
    },
    {
        "id": "why_role_industry",
        "question": "Why this role / industry specifically?",
        "why_asked": "Tests whether you have done your homework and whether "
        "your interest is specific enough to stick.",
        "framework": _framework(),
        "do": [
            "Reference something specific about the company or industry, "
            "not just the role title.",
            "Tie your answer to an experience where you touched this domain "
            "or adjacent skills.",
            "Show curiosity: name a trend or problem in the space you want "
            "to work on.",
        ],
        "dont": [
            "Don't give an answer that would fit any company ('I love the "
            "mission').",
            "Don't over-claim domain expertise you don't have.",
            "Don't confuse the interviewer with three different target "
            "directions.",
        ],
        "needed_facts": ["why_this_company", "target_role", "relevant_experience"],
    },
    {
        "id": "ramp_up",
        "question": "How will you ramp up? You don't have direct experience.",
        "why_asked": "The interviewer is pricing the risk: how long before "
        "you are productive, and who pays for the learning curve.",
        "framework": _framework(),
        "do": [
            "Give a concrete 30/60/90-day ramp plan, not just 'I'm a fast "
            "learner'.",
            "Name what you have already done to learn (course, project, "
            "side work).",
            "Show how your existing skills shorten the curve in the new "
            "role.",
        ],
        "dont": [
            "Don't say 'I'm a quick learner' without evidence.",
            "Don't pretend there is no learning curve.",
            "Don't dump all the learning on the team's mentoring capacity.",
        ],
        "needed_facts": ["learning_done", "ramp_plan", "transferable_skill"],
    },
    {
        "id": "over_under_qualified",
        "question": "Aren't you overqualified / underqualified for this role?",
        "why_asked": "Overqualified: fear you will leave or get bored. "
        "Underqualified: fear you cannot do the job. Answer the specific "
        "worry behind the question.",
        "framework": _framework(),
        "do": [
            "Address the real concern (flight risk or capability risk), not "
            "just the label.",
            "If 'overqualified': explain why this level/role is a deliberate "
            "choice, and what you still want to learn.",
            "If 'underqualified': name the gaps honestly and show how you "
            "have closed similar gaps before.",
        ],
        "dont": [
            "Don't get defensive or argue with the premise.",
            "Don't inflate your old title to sound senior; it raises the "
            "flight-risk worry.",
            "Don't promise to be 'fine with less' if you will not be.",
        ],
        "needed_facts": ["seniority_context", "what_you_learn", "gap_closure_example"],
    },
)

QUESTIONS: dict[str, dict] = {q["id"]: q for q in _QUESTION_DEFS}


def switcher_questions(target_role: str) -> list[dict]:
    """Return the classic switcher questions, tailored to ``target_role``.

    Each entry carries ``id``, ``question``, ``why_asked``, ``framework``
    (the hook-bridge-proof-close steps), ``do`` and ``dont`` guidance.
    ``target_role`` is substituted into the question text where relevant;
    a blank role raises :class:`SwitcherQuestionError`.
    """
    if not target_role or not target_role.strip():
        raise SwitcherQuestionError("target_role must be a non-empty string.")
    role = target_role.strip()
    out = []
    for qdef in _QUESTION_DEFS:
        entry = {
            "id": qdef["id"],
            "question": qdef["question"],
            "why_asked": qdef["why_asked"],
            "framework": dict(qdef["framework"]),
            "do": list(qdef["do"]),
            "dont": list(qdef["dont"]),
        }
        if qdef["id"] == "why_role_industry":
            entry["question"] = f"Why this role ({role}) / industry specifically?"
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Answer assembly: grounded, with [PLACEHOLDER] for missing facts.
# ---------------------------------------------------------------------------

_PLACEHOLDER = "[PLACEHOLDER: {}]"


def _fact_or_placeholder(user_facts: dict, key: str) -> str:
    value = user_facts.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return _PLACEHOLDER.format(key)
    return str(value).strip()


def build_answer(question_id: str, user_facts: dict) -> dict:
    """Assemble a draft answer for a switcher question from supplied facts.

    ``question_id`` must be one of the ids from ``QUESTIONS``
    (e.g. "why_switching"). ``user_facts`` maps fact keys to user-supplied
    strings; only those strings are used verbatim in the draft. Any needed
    fact that is absent becomes an explicit ``[PLACEHOLDER: <key>]`` marker,
    so nothing is invented.

    Returns a dict with ``question_id``, ``draft`` (the assembled text),
    ``framework_steps`` (the hook/bridge/proof/close skeleton with the
    facts slotted in), and ``missing_facts`` (the placeholder keys).
    """
    if question_id not in QUESTIONS:
        raise SwitcherQuestionError(
            f"Unknown switcher question id: {question_id!r}. "
            f"Valid ids: {sorted(QUESTIONS)}."
        )
    if not isinstance(user_facts, dict):
        raise SwitcherQuestionError("user_facts must be a dict of fact key -> value.")

    qdef = QUESTIONS[question_id]
    facts: dict[str, str] = {}
    missing: list[str] = []
    for key in qdef["needed_facts"]:
        facts[key] = _fact_or_placeholder(user_facts, key)
        if facts[key].startswith("[PLACEHOLDER"):
            missing.append(key)

    target_role = _fact_or_placeholder(user_facts, "target_role")

    # Map needed facts onto the framework in order:
    # hook -> first fact, bridge -> second fact, proof -> last fact.
    first, second, last = (
        qdef["needed_facts"][0],
        qdef["needed_facts"][1],
        qdef["needed_facts"][-1],
    )
    framework_steps = {
        "hook": f"What draws me to this move: {facts[first]}.",
        "bridge": f"What carries over from my background: {facts[second]}.",
        "proof": f"One concrete example: {facts[last]}.",
        "close": f"In the first 90 days as a {target_role}, I plan to learn "
        f"fast and contribute where my background gives me an edge.",
    }
    lines = [f"Question: {qdef['question']}", ""]
    for step in FRAMEWORK_STEPS:
        lines.append(f"[{step.upper()}] {framework_steps[step]}")
    return {
        "question_id": question_id,
        "draft": "\n".join(lines),
        "framework_steps": framework_steps,
        "missing_facts": missing,
    }
