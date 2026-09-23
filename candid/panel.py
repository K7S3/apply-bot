"""Panel planning: give every interviewer a distinct angle for the loop.

Takes the interviewer roster for one application and produces a per-round
game plan: who should hear which of your stories, which angles to avoid
repeating, and a few panel-level strategy notes.

Angle data comes from Worker B's ``candid.interviewer_roles.get_role_profile``.
Each role profile exposes an ordered ``angle_categories`` list whose first
entry is that role's primary angle.
"""

from __future__ import annotations

from candid.interviewer_roles import get_role_profile


# Tie-break order when two interviewers want the same primary angle.
# Earlier entries claim their preferred angle first.
ROLE_PRIORITY = [
    "hiring_manager",
    "bar_raiser",
    "peer_engineer",
    "domain_specialist",
    "skip_level",
    "recruiter",
]


def _priority_index(role: str) -> int:
    """Position of a role in ROLE_PRIORITY; unknown roles sort last."""
    try:
        return ROLE_PRIORITY.index((role or "").strip().lower())
    except ValueError:
        return len(ROLE_PRIORITY)


def _role_label(role: str) -> str:
    """Display label for a role, from its profile or a humanized key."""
    profile = get_role_profile(role) or {}
    label = profile.get("label")
    if label:
        return str(label)
    return (role or "interviewer").replace("_", " ").title()


def _strategy_notes(roles: list[str]) -> list[str]:
    """3-5 panel-level tips, with role-specific advice appended."""
    notes = [
        "Open each round by asking what the interviewer most wants to cover, then tailor your depth to their answer.",
        "Do not repeat the same example twice in one loop; interviewers compare notes afterward.",
        "End every round with: is there anything about my background I can clarify for you?",
    ]
    if "bar_raiser" in roles:
        notes.append(
            "Save your strongest ownership story for the bar raiser; "
            "they carry the most weight on the hiring bar."
        )
    if "hiring_manager" in roles:
        notes.append(
            "With the hiring manager, lean into outcomes and team impact, "
            "not just technical detail."
        )
    if "recruiter" in roles:
        notes.append(
            "Keep the recruiter round to logistics, timeline, and compensation; "
            "save technical depth for the engineers."
        )
    if "peer_engineer" in roles:
        notes.append(
            "Peer engineers want code-level specifics; bring one deep "
            "technical story with numbers."
        )
    if "skip_level" in roles:
        notes.append(
            "The skip level cares about trajectory and judgment; talk about "
            "where you want to grow, not just what you shipped."
        )
    return notes[:5]


def plan_panel(interviewers: list[dict], *, profile_bullets: list[str] | None = None) -> dict:
    """Assign each interviewer a distinct primary angle.

    Args:
        interviewers: roster dicts with at least ``name`` and ``role`` keys
            (see ``candid.interviewers``).
        profile_bullets: your resume/story bullets to distribute across the
            panel. Assigned round-robin so no bullet repeats.

    Returns:
        ``{"assignments": [...], "strategy_notes": [...]}`` where each
        assignment has ``interviewer``, ``role``, ``role_label``,
        ``focus_categories``, ``talking_points``, and ``avoid`` keys.
    """
    ordered = sorted(
        list(interviewers or []),
        key=lambda iv: _priority_index(str(iv.get("role", ""))),
    )
    roles = [(iv.get("role") or "").strip().lower() for iv in ordered]

    taken: list[str] = []
    assignments: list[dict] = []
    bullets = [b for b in (profile_bullets or []) if b]

    for idx, iv in enumerate(ordered):
        role = (iv.get("role") or "").strip().lower()
        profile = get_role_profile(role) or {}
        angles = [str(a) for a in (profile.get("angle_categories") or []) if a]

        primary: str | None = None
        for angle in angles:
            if angle not in taken:
                primary = angle
                break
        if primary is None and angles:
            # Every angle is claimed; fall back to the role's own primary.
            primary = angles[0]
        if primary is not None:
            taken.append(primary)

        focus = [primary] if primary else []
        focus += [a for a in angles if a != primary][:2]

        if ordered:
            talking_points = [b for j, b in enumerate(bullets) if j % len(ordered) == idx]
        else:
            talking_points = []

        avoid = [f"don't repeat your {cat} story" for cat in taken[:-1]]

        assignments.append(
            {
                "interviewer": iv.get("name", ""),
                "role": role,
                "role_label": _role_label(role),
                "focus_categories": focus,
                "talking_points": talking_points,
                "avoid": avoid,
            }
        )

    return {"assignments": assignments, "strategy_notes": _strategy_notes(roles)}
