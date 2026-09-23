"""Career-switcher readiness score for a target role.

Combines three deterministic, locally computed signals into a 0-100 score:

  * transferable coverage (50 pts) -- share of JD requirements covered by
    the profile's skills, with partial (adjacent/foundational) matches
    earning half credit (from candid.switch_skills);
  * gap control (30 pts) -- starts at 30, loses 7.5 points per missing
    requirement (so four or more hard gaps zero it out);
  * adjacent experience (20 pts) -- years of experience the user reported:
    >=5y -> 20, >=3y -> 15, >=1y -> 8, >0y -> 4, else 0.

readiness_score() returns:
    {"score", "grade", "breakdown", "top_gaps", "quick_wins", "target_role"}

grade: A >= 85, B >= 70, C >= 55, D >= 40, else F.
top_gaps: up to 3 missing requirements, in JD order.
quick_wins: for each partially-covered requirement, a concrete reframing
    suggestion built only from the matched skill names and the requirement
    text -- never invented experience.

Pure functions, deterministic, no disk, no network.
"""

from __future__ import annotations

from candid import switch_skills as SS


class ReadinessError(Exception):
    """Raised for bad input to the readiness scoring."""


_COVERAGE_MAX = 50.0
_GAP_MAX = 30.0
_GAP_PENALTY_PER_MISSING = 7.5
_EXPERIENCE_MAX = 20.0
_GRADE_CUTS = ((85, "A"), (70, "B"), (55, "C"), (40, "D"))


def grade_for(score: float) -> str:
    """Letter grade for a 0-100 readiness score."""
    for cutoff, letter in _GRADE_CUTS:
        if score >= cutoff:
            return letter
    return "F"


def experience_points(years_experience: float) -> int:
    """Deterministic 0-20 points from reported years of adjacent experience."""
    if not isinstance(years_experience, (int, float)) or isinstance(years_experience, bool):
        raise ReadinessError("years_experience must be a number")
    if years_experience < 0:
        raise ReadinessError("years_experience must be >= 0")
    if years_experience >= 5:
        return 20
    if years_experience >= 3:
        return 15
    if years_experience >= 1:
        return 8
    if years_experience > 0:
        return 4
    return 0


def readiness_score(profile_skills: list[dict], requirements: list[str], *,
                    years_experience: float = 0.0,
                    target_role: str = "") -> dict:
    """Score 0-100 readiness of a career switcher for a target role."""
    if not isinstance(target_role, str):
        raise ReadinessError("target_role must be a string")
    try:
        summary = SS.skill_gap_summary(profile_skills, requirements)
    except SS.SwitchSkillsError as exc:
        raise ReadinessError(str(exc)) from exc

    total = len(summary["covered"]) + len(summary["partial"]) + len(summary["missing"])
    covered_n = len(summary["covered"])
    partial_n = len(summary["partial"])
    missing_n = len(summary["missing"])

    coverage = (covered_n + 0.5 * partial_n) / total * _COVERAGE_MAX if total else 0.0
    gap_control = max(0.0, _GAP_MAX - _GAP_PENALTY_PER_MISSING * missing_n)
    experience = float(experience_points(years_experience))

    score = int(round(min(100.0, coverage + gap_control + experience)))
    grade = grade_for(score)

    breakdown = {
        "coverage": round(coverage, 1),            # out of 50
        "gap_control": round(gap_control, 1),     # out of 30
        "adjacent_experience": round(experience, 1),  # out of 20
    }

    top_gaps = [req for req in summary["missing"][:3]]

    quick_wins = []
    for entry in summary["partial"][:3]:
        skills = ", ".join(sorted({h["skill"] for h in entry["matched_skills"]}))
        quick_wins.append(
            f"Close '{entry['requirement']}' by reframing {skills} "
            f"({entry['best_strength']} match): add a resume bullet or project "
            "showing applied use."
        )

    return {
        "score": score,
        "grade": grade,
        "breakdown": breakdown,
        "top_gaps": top_gaps,
        "quick_wins": quick_wins,
        "target_role": target_role.strip(),
    }
