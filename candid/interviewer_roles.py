"""Interviewer role profiles for interview-prep briefs.

Each profile describes what an interviewer in a given role typically
evaluates, which question categories they lean on, the concrete angles
they tend to probe, how to prepare for them, and the observable tells
that reveal what they are really scoring.

Role keys come from ``candid.interviewers.ROLES`` when that module is
present. If it is not importable yet (it may be built by a sibling
worker in the same batch), we fall back to the six canonical keys and
stay in sync automatically once the module lands.
"""

from __future__ import annotations

try:  # candid.interviewers may be added by a sibling worker in this batch
    from candid.interviewers import ROLES
except ImportError:  # pragma: no cover - fallback until the module exists
    ROLES = [
        "hiring_manager",
        "peer_engineer",
        "bar_raiser",
        "recruiter",
        "skip_level",
        "domain_specialist",
    ]

_GENERIC_PROFILE = {
    "label": "Interviewer",
    "description": (
        "An interviewer whose specific role is unknown. Prepare a balanced "
        "mix across question categories and adapt to whatever they probe."
    ),
    "evaluates": ["general role fit", "technical depth", "communication clarity"],
    "angle_categories": ["behavioral", "case", "ml", "stats", "sql", "system_design", "coding"],
    "likely_angles": [
        "walk me through your background",
        "a technical deep-dive on one project",
        "a time you handled conflict or ambiguity",
        "why this role and this company",
        "questions you have for the interviewer",
    ],
    "prep_tips": [
        "bring one strong end-to-end project story",
        "balance technical depth with clear communication",
        "prepare genuine questions for them",
        "quantify impact wherever you can",
    ],
    "tells": [
        "adapts to whatever topic you offer",
        "asks for specifics when an answer stays vague",
    ],
}

ROLE_PROFILES: dict[str, dict] = {
    "hiring_manager": {
        "label": "Hiring Manager",
        "description": (
            "The person who would be your manager. They own the hiring "
            "decision and care about team fit, scope of ownership, and "
            "whether you can deliver on their roadmap."
        ),
        "evaluates": [
            "team fit and collaboration style",
            "scope of past ownership and impact",
            "ability to ramp up quickly",
            "judgment under ambiguity",
        ],
        "angle_categories": ["behavioral", "case", "product", "ml", "stats", "sql"],
        "likely_angles": [
            "team-fit and scope questions",
            "your biggest project end-to-end",
            "how you handle disagreement and ambiguity",
            "what you would do in your first 90 days",
            "a failure story and what it changed",
            "why this team and this role specifically",
        ],
        "prep_tips": [
            "bring one big end-to-end project story with clear metrics",
            "show you can scope work and unblock yourself",
            "ask about the team's biggest current challenge",
            "be specific about your role versus the team's role",
            "frame the tradeoffs you made and why",
        ],
        "tells": [
            "asks 'what did you do' rather than 'what did we do'",
            "probes for metrics and before-versus-after impact",
        ],
    },
    "peer_engineer": {
        "label": "Peer Engineer",
        "description": (
            "A future teammate at or near your level. They test whether you "
            "can do the day-to-day work well and whether they would enjoy "
            "solving hard problems with you."
        ),
        "evaluates": [
            "day-to-day engineering craft",
            "debugging and design instincts",
            "code and system quality bar",
            "how easy you are to work with on hard problems",
        ],
        "angle_categories": ["coding", "system_design", "ml", "sql", "python", "process"],
        "likely_angles": [
            "live coding or whiteboard problem",
            "walk through a system you built",
            "debugging a production failure",
            "tradeoffs between two technical approaches",
            "how you review code or give feedback",
            "a technical decision you would redo",
        ],
        "prep_tips": [
            "talk out loud while solving, narrate your tradeoffs",
            "know your past systems cold, be ready to whiteboard them",
            "practice debugging stories with a clear, repeatable method",
            "ask what stack and tooling the team actually uses",
            "show curiosity about their engineering culture",
        ],
        "tells": [
            "wants concrete details, not abstractions",
            "skips ahead when an answer stays vague",
        ],
    },
    "bar_raiser": {
        "label": "Bar Raiser",
        "description": (
            "An interviewer from outside the hiring team whose job is to "
            "protect the hiring bar. They dig far deeper than anyone else "
            "and test judgment, ownership, and principles."
        ),
        "evaluates": [
            "raises-the-bar judgment across roles",
            "ownership and bias for action",
            "deep problem solving under pressure",
            "alignment with company principles",
        ],
        "angle_categories": ["behavioral", "case", "system_design", "ml", "stats"],
        "likely_angles": [
            "digs 3 levels deep on one story",
            "the hardest problem you have solved",
            "a time you disagreed and committed anyway",
            "how you decide when data is incomplete",
            "what you would do differently with hindsight",
            "principles-in-action scenarios",
        ],
        "prep_tips": [
            "pick your two strongest stories and know every detail",
            "use structured answers: situation, action, result",
            "quantify impact wherever possible",
            "expect follow-ups like 'why' three times in a row",
            "stay calm and specific under pressure",
        ],
        "tells": [
            "digs 3 levels deep on one story",
            "repeats the same question to test consistency",
        ],
    },
    "recruiter": {
        "label": "Recruiter",
        "description": (
            "The hiring-team screener and process owner. They check "
            "motivation, logistics, and communication, and they sell you "
            "on the role while screening you out of the wrong one."
        ),
        "evaluates": [
            "motivation and role fit",
            "compensation and logistics alignment",
            "communication clarity",
            "genuine interest in the company",
        ],
        "angle_categories": ["behavioral", "case", "product"],
        "likely_angles": [
            "walk me through your background",
            "why this company and this role",
            "compensation expectations and timeline",
            "work authorization and logistics",
            "what you are looking for next",
        ],
        "prep_tips": [
            "have a crisp 2-minute background story",
            "know the job description well enough to cite it",
            "be honest about compensation range and start date",
            "ask about the interview process and timeline",
            "show real enthusiasm for the team, not just the title",
        ],
        "tells": [
            "takes notes on your answers about motivation",
            "wraps up with next steps and timeline",
        ],
    },
    "skip_level": {
        "label": "Skip-Level Manager",
        "description": (
            "Your would-be manager's manager. They think in terms of org "
            "impact, strategy, and leadership potential rather than "
            "implementation details."
        ),
        "evaluates": [
            "strategic thinking and business sense",
            "influence beyond your immediate team",
            "leadership potential and mentorship",
            "alignment with org-level goals",
        ],
        "angle_categories": ["case", "product", "behavioral", "system_design", "stats"],
        "likely_angles": [
            "how your work connected to business goals",
            "influence without authority",
            "a cross-team project you drove",
            "where the industry is heading",
            "how you mentor or grow others",
        ],
        "prep_tips": [
            "connect every story to business impact",
            "show you think about the org, not just your tasks",
            "prepare one thoughtful question about strategy",
            "demonstrate learning from senior leaders",
            "be candid about what energizes you",
        ],
        "tells": [
            "zooms out from details to business impact",
            "asks who else was involved and how you influenced them",
        ],
    },
    "domain_specialist": {
        "label": "Domain Specialist",
        "description": (
            "A deep expert in the role's domain (ML, stats, data). They "
            "test rigor: methods, assumptions, failure modes, and whether "
            "your knowledge is current."
        ),
        "evaluates": [
            "depth in the specific domain (ML, stats, data)",
            "rigor of methods and assumptions",
            "awareness of failure modes",
            "staying current with the field",
        ],
        "angle_categories": ["ml", "stats", "probability", "sql", "case", "system_design"],
        "likely_angles": [
            "foundations of a key method",
            "assumptions behind a technique",
            "how you validate results",
            "edge cases and failure modes",
            "tradeoffs between methods",
            "recent developments in the field",
        ],
        "prep_tips": [
            "revisit fundamentals, they will test them",
            "be ready to derive, not just describe",
            "know the limits of your favorite methods",
            "bring examples where a method failed",
            "ask about their hardest domain problems",
        ],
        "tells": [
            "asks 'why does that work' after every answer",
            "probes assumptions, not conclusions",
        ],
    },
}

# Keep in sync with candid.interviewers.ROLES: any role key that module
# adds later gets a generic-but-labeled profile automatically.
for _role_key in ROLES:
    if _role_key not in ROLE_PROFILES:
        _synced = {k: (list(v) if isinstance(v, list) else v) for k, v in _GENERIC_PROFILE.items()}
        _synced["label"] = _role_key.replace("_", " ").title()
        ROLE_PROFILES[_role_key] = _synced
del _role_key
try:
    del _synced
except NameError:
    pass


def _copy_profile(profile: dict) -> dict:
    """Return a defensive copy so callers cannot mutate the shared registry."""
    return {k: (list(v) if isinstance(v, list) else v) for k, v in profile.items()}


def get_role_profile(role: str) -> dict:
    """Return the profile dict for an interviewer role key.

    Lookup is case-insensitive. Unknown roles fall back to a generic
    profile instead of raising KeyError, so brief generation never
    crashes on unexpected input.
    """
    key = role.strip().lower() if isinstance(role, str) else ""
    return _copy_profile(ROLE_PROFILES.get(key, _GENERIC_PROFILE))


def list_roles() -> list:
    """Return the known interviewer role keys, in canonical order."""
    return list(ROLES)
