"""30-60-90 ramp plan generator for career switchers starting a new role.

- ``build_ramp_plan(target_role, company, known_gaps=None)``: three phases,
  each with ``goals``, ``questions`` (key questions to ask), ``relationships``
  (relationships to build), and ``metrics`` (success metrics):

      * Learn (Days 0-30): understand the team, stack, and norms.
      * Contribute (Days 30-60): ship real work with lighter supervision.
      * Own (Days 60-90): own a workstream and be ramp-ready.

  The user's ``known_gaps`` are inserted as explicit learning goals in the
  Learn phase, and the surrounding questions and relationships point at
  closing them.
- ``ramp_markdown(plan)``: render a plan dict as Markdown.

Deterministic and offline: no network, no paid APIs, no LLMs. Content is
template-driven from the supplied role, company, and gaps; nothing is
invented beyond fixed boilerplate.
"""

from __future__ import annotations

__all__ = [
    "SwitchRampError",
    "PHASES",
    "build_ramp_plan",
    "ramp_markdown",
]


class SwitchRampError(Exception):
    """Raised when a ramp plan cannot be built or rendered (bad input)."""


PHASES: tuple[tuple[str, str], ...] = (
    ("Learn", "0-30"),
    ("Contribute", "30-60"),
    ("Own", "60-90"),
)

_SECTION_KEYS: tuple[str, ...] = ("goals", "questions", "relationships", "metrics")

_SECTION_LABELS: dict[str, str] = {
    "goals": "Goals",
    "questions": "Key questions to ask",
    "relationships": "Relationships to build",
    "metrics": "Success metrics",
}


# ---------------------------------------------------------------------------
# Phase content templates (boilerplate only; role/company/gaps personalize).
# ---------------------------------------------------------------------------

def _learn_goals(role: str, gaps: list[str]) -> list[str]:
    goals = [
        f"Shadow teammates through a full {role} workflow end to end.",
        "Map the stack: tooling, codebases, docs, and where answers live.",
        "Learn the team's norms: how work is prioritized, reviewed, and shipped.",
        "Close your known gaps with a focused learning sprint: "
        "docs, a course, and paired sessions on each gap.",
    ]
    goals.extend(f"Close gap: {gap} - finish a focused learning sprint "
                 f"and demo it in a ramp task." for gap in gaps)
    return goals


def _learn_questions(role: str, gaps: list[str]) -> list[str]:
    questions = [
        f"What does a great {role} look like here in the first 90 days?",
        "How is work prioritized, and who makes the final call?",
        "What does 'done' look like for a typical task?",
        "Where do I go for help when I am stuck, and when should I ask?",
        "What mistakes do new joiners usually make?",
    ]
    if gaps:
        questions.insert(3, "Who is the best person to pair with on: "
                            + ", ".join(gaps[:3])
                            + ("?" if len(gaps) <= 3 else ", and the rest?"))
    return questions


def _learn_relationships() -> list[str]:
    return [
        "Manager: align on 30-60-90 expectations and a weekly check-in cadence.",
        "Onboarding buddy: your daily unblock contact and culture guide.",
        "Closest collaborators: the teammates you will review and ship with.",
        "Cross-functional partners: stakeholders whose work you will touch.",
    ]


def _learn_metrics() -> list[str]:
    return [
        "Ramp tasks completed without rework from misunderstandings.",
        "Can demo the core workflow end to end to your manager.",
        "Known gaps each have a learning plan and a scheduled demo.",
    ]


def _contribute_goals(role: str) -> list[str]:
    return [
        "Own small, well-scoped tasks end to end.",
        f"Ship your first real {role} change and document what you learned.",
        "Cut buddy-dependence: debug independently, ask targeted questions.",
        "Start closing open loops from your learning sprint with real tasks.",
    ]


def _contribute_questions() -> list[str]:
    return [
        "What are the team's biggest pain points right now?",
        "How do you evaluate quality on this team?",
        "What should I keep doing, and what should I change?",
        "Which part of the codebase or process most needs a fresh pair of eyes?",
    ]


def _contribute_relationships() -> list[str]:
    return [
        "Stakeholders or customers of your work: learn what 'good' means to them.",
        "Adjacent team leads: know whose decisions affect your tasks.",
        "Skip-level manager: make yourself visible and understood.",
    ]


def _contribute_metrics() -> list[str]:
    return [
        "Tasks shipped per week trending up with review comments trending down.",
        "First unprompted positive review feedback from a teammate.",
        "No repeat questions on topics already covered in the learning sprint.",
    ]


def _own_goals(role: str) -> list[str]:
    return [
        f"Own a full {role} workstream: plan it, ship it, report on it.",
        "Propose one improvement to a process, doc, or tool you struggled with.",
        "Be the onboarding answer for the next new joiner on your area.",
    ]


def _own_questions() -> list[str]:
    return [
        "What does leveling up look like from here?",
        "Where should I invest my learning time next quarter?",
        "What is the riskiest assumption in our current plan?",
    ]


def _own_relationships() -> list[str]:
    return [
        "Wider org peers: build the network you will need next quarter.",
        "External community: a meetup, forum, or peer group in the field.",
    ]


def _own_metrics() -> list[str]:
    return [
        "Workstream milestone delivered on the agreed timeline.",
        "Peer feedback shows trust in your judgment, not just output.",
        "Personal scorecard: gaps closed, learning goals met, next goals set.",
    ]


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------

def _clean_gaps(known_gaps) -> list[str]:
    if known_gaps is None:
        return []
    if isinstance(known_gaps, str):
        known_gaps = [known_gaps]
    if not isinstance(known_gaps, (list, tuple)):
        raise SwitchRampError("known_gaps must be a list of strings.")
    gaps = []
    for gap in known_gaps:
        if not isinstance(gap, str):
            raise SwitchRampError("known_gaps entries must be strings.")
        gap = gap.strip()
        if gap:
            gaps.append(gap)
    return gaps


def build_ramp_plan(target_role: str, company: str,
                    known_gaps=None) -> dict:
    """Build a 30-60-90 ramp plan dict for the new role.

    Returns ``{"target_role", "company", "known_gaps", "phases"}`` where each
    phase is ``{"name", "days", "goals", "questions", "relationships",
    "metrics"}``. ``known_gaps`` appear as explicit learning goals (and a
    pairing question) in the Learn phase.
    """
    target_role = (target_role or "").strip()
    company = (company or "").strip()
    if not target_role:
        raise SwitchRampError("target_role is required.")
    if not company:
        raise SwitchRampError("company is required.")
    gaps = _clean_gaps(known_gaps)

    phases = [
        {
            "name": "Learn",
            "days": "0-30",
            "goals": _learn_goals(target_role, gaps),
            "questions": _learn_questions(target_role, gaps),
            "relationships": _learn_relationships(),
            "metrics": _learn_metrics(),
        },
        {
            "name": "Contribute",
            "days": "30-60",
            "goals": _contribute_goals(target_role),
            "questions": _contribute_questions(),
            "relationships": _contribute_relationships(),
            "metrics": _contribute_metrics(),
        },
        {
            "name": "Own",
            "days": "60-90",
            "goals": _own_goals(target_role),
            "questions": _own_questions(),
            "relationships": _own_relationships(),
            "metrics": _own_metrics(),
        },
    ]
    return {
        "target_role": target_role,
        "company": company,
        "known_gaps": gaps,
        "phases": phases,
    }


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def _validate_plan(plan) -> None:
    if not isinstance(plan, dict):
        raise SwitchRampError("plan must be a dict from build_ramp_plan().")
    for key in ("target_role", "company", "phases"):
        if not plan.get(key):
            raise SwitchRampError(f"plan is missing '{key}'.")
    if not isinstance(plan["phases"], list) or not plan["phases"]:
        raise SwitchRampError("plan['phases'] must be a non-empty list.")
    for phase in plan["phases"]:
        if not isinstance(phase, dict):
            raise SwitchRampError("each phase must be a dict.")
        for key in ("name", "days", *_SECTION_KEYS):
            if key not in phase:
                raise SwitchRampError(f"phase is missing '{key}'.")
        for key in _SECTION_KEYS:
            items = phase[key]
            if not isinstance(items, list) or not items:
                raise SwitchRampError(f"phase '{phase.get('name')}' has empty '{key}'.")


def ramp_markdown(plan: dict) -> str:
    """Render a plan dict (from :func:`build_ramp_plan`) as Markdown."""
    _validate_plan(plan)
    lines = [
        f"# 30-60-90 Ramp Plan: {plan['target_role']} at {plan['company']}",
        "",
        "A three-phase ramp for career switchers: learn the ropes, "
        "contribute real work, then own a workstream.",
        "",
    ]
    for phase in plan["phases"]:
        lines.append(f"## {phase['name']} (Days {phase['days']})")
        lines.append("")
        for key in _SECTION_KEYS:
            lines.append(f"### {_SECTION_LABELS[key]}")
            lines.extend(f"- {item}" for item in phase[key])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
