"""Smart questions to ASK each interviewer (reverse interview questions).

Keyed by interviewer role from ``candid.interviewers.InterviewerRole``.
Unknown roles fall back to the generic list.
"""

from __future__ import annotations


REVERSE_QUESTIONS: dict[str, list[str]] = {
    "hiring_manager": [
        "What does success look like in the first 90 days?",
        "What is the biggest challenge the team is facing right now?",
        "How do you measure the impact of this team?",
        "What does the growth path for this role look like over two years?",
        "How do you run one-on-ones and give feedback?",
        "What kind of person thrives on this team, and who struggles?",
        "If I joined tomorrow, what would you want me to pick up first?",
    ],
    "peer_engineer": [
        "What is the on-call load like?",
        "How does the team handle code review and design docs?",
        "What part of the codebase would you rewrite if you had a free month?",
        "How much time goes to new features versus maintenance?",
        "What is the testing and deploy story like?",
        "What did the last big technical disagreement on the team look like?",
    ],
    "bar_raiser": [
        "What separates a good engineer from a great one at this company?",
        "Can you tell me about a recent hire who raised the bar for the team?",
        "How does the company handle disagreement about a hiring decision?",
        "What is one principle the company would not compromise on?",
        "How is engineering excellence recognized here beyond promotions?",
    ],
    "recruiter": [
        "What is the interview timeline from here?",
        "What are the next steps after this round?",
        "How does the compensation band for this level work?",
        "Is the role remote, hybrid, or on-site, and how firm is that?",
        "What should I prepare that candidates usually overlook?",
    ],
    "skip_level": [
        "Where is the org headed in the next 18 months?",
        "What keeps you up at night about the business?",
        "How do priorities get set across teams?",
        "What does the company do to keep senior engineers growing?",
        "How would you describe the culture in one sentence to a friend?",
    ],
    "domain_specialist": [
        "What is the hardest technical problem in this domain right now?",
        "How do you evaluate trade-offs between model quality and latency here?",
        "What does the experimentation and measurement loop look like?",
        "Which parts of the stack are build versus buy, and why?",
        "What is a recent bet in this area that did not pay off, and what did you learn?",
    ],
    "generic": [
        "What do you enjoy most about working here?",
        "What surprised you when you joined?",
        "What does a typical week look like in this role?",
        "How would you describe the team culture?",
        "What is one thing you would change about the team if you could?",
    ],
}


def _normalize_role(role: str | None) -> str:
    return (role or "").strip().lower()


def questions_for_role(role: str | None, *, n: int = 5) -> list[str]:
    """Return up to ``n`` questions to ask an interviewer of this role.

    Unknown roles fall back to the generic list.
    """
    key = _normalize_role(role)
    questions = REVERSE_QUESTIONS.get(key, REVERSE_QUESTIONS["generic"])
    return list(questions[: max(n, 0)])


def questions_for_panel(roles: list[str]) -> dict[str, list[str]]:
    """Map each role to its questions, deduplicated across the panel.

    If two roles share a question, it appears only under the first role.
    Unknown roles fall back to the generic list under their own key.
    """
    seen: set[str] = set()
    out: dict[str, list[str]] = {}
    for role in roles or []:
        key = _normalize_role(role)
        picked: list[str] = []
        for q in REVERSE_QUESTIONS.get(key, REVERSE_QUESTIONS["generic"]):
            norm = q.strip().lower()
            if norm not in seen:
                seen.add(norm)
                picked.append(q)
        out[key or "generic"] = picked
    return out
