"""Application autofill kit: form-ready answers from your profile.

Generates copy-pasteable work history, skills, education, and EEO
voluntary-disclosure answers as plain text/markdown. The output FILLS
fields on an application form — it never submits anything anywhere.

EEO/voluntary-disclosure policy: safe defaults only. Every question is
answered with "I don't wish to answer" (or "Decline to self-identify" for
race/ethnicity). candid NEVER invents disability, veteran, gender, or race
answers — the profile doesn't contain those fields and this module never
guesses them.
"""

from __future__ import annotations

from candid import profile as P


class AutofillError(Exception):
    """Raised when the autofill kit can't be generated."""


HEADER = (
    "# Application Autofill Kit\n"
    "_Copy the sections into the form's fields. This kit FILLS — "
    "it never submits anything._"
)

# ---------------------------------------------------------------------------
# EEO / voluntary-disclosure safe defaults
# ---------------------------------------------------------------------------

#: The exact safe-default string used for most voluntary-disclosure questions.
DECLINE = "I don't wish to answer"
#: The exact safe-default string used for race/ethnicity self-identification.
DECLINE_RACE = "Decline to self-identify"


def eeo_answers() -> list[dict]:
    """Standard US voluntary-disclosure questions with safe defaults.

    Returns [{question, answer}] — every answer is a decline-to-answer
    option. Nothing about disability, veteran status, gender, or race is
    ever inferred from the profile.
    """
    return [
        {
            "question": "Gender",
            "answer": DECLINE,
            "note": "Standard form option: \"I don't wish to answer\".",
        },
        {
            "question": "Race / Ethnicity",
            "answer": DECLINE_RACE,
            "note": "Standard form option: \"Decline to self-identify\".",
        },
        {
            "question": "Disability status (Voluntary Self-Identification)",
            "answer": DECLINE,
            "note": "Standard form option: \"I don't wish to answer\".",
        },
        {
            "question": "Veteran status",
            "answer": DECLINE,
            "note": "Standard form option: \"I don't wish to answer\".",
        },
        {
            "question": "Are you legally authorized to work in the country of the role?",
            "answer": "(answer yourself — truthfully; work authorization is "
                      "factual, not voluntary disclosure)",
            "note": "candid won't answer this one for you; say what is true.",
        },
        {
            "question": "Will you now or in the future require sponsorship for employment visa status?",
            "answer": "(answer yourself — truthfully; candid won't answer this one for you)",
            "note": "Sponsorship questions must be answered with your actual situation.",
        },
    ]


# ---------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------

def _missing(field: str) -> str:
    return f"(not detected — run `python -m candid onboard --help` to improve)"


def render_work(profile: dict) -> str:
    """Work history in the shape application forms ask for."""
    lines = ["## Work history", ""]
    experience = profile.get("experience") or []
    if not experience:
        lines.append(f"No experience entries detected. {_missing('experience')}")
        return "\n".join(lines)
    for i, e in enumerate(experience, 1):
        title = e.get("title") or "(title not detected)"
        company = e.get("company") or "(company not detected)"
        dates = e.get("dates") or "(dates not detected)"
        lines.append(f"### Job {i}: {company}")
        lines.append("")
        lines.append(f"- **Company:** {company}")
        lines.append(f"- **Title:** {title}")
        lines.append(f"- **Dates:** {dates}")
        lines.append("- **Location:** (add if the form asks; not tracked per-role)")
        bullets = [b for b in (e.get("bullets") or []) if b]
        if bullets:
            lines.append(f"- **Key work:** {bullets[0][:160]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_skills(profile: dict) -> str:
    """Skills as a comma-separated paste line plus a bulleted list."""
    skills = profile.get("skills") or []
    lines = ["## Skills", ""]
    if not skills:
        lines.append(f"No skills detected. {_missing('skills')}")
        return "\n".join(lines)
    lines.append(", ".join(skills))
    lines.append("")
    for s in skills:
        lines.append(f"- {s}")
    return "\n".join(lines) + "\n"


def render_education(profile: dict) -> str:
    """Education in school/degree/dates form shape."""
    lines = ["## Education", ""]
    education = profile.get("education") or []
    if not education:
        lines.append("(no education entries detected)")
        return "\n".join(lines)
    for i, e in enumerate(education, 1):
        lines.append(f"### Entry {i}")
        lines.append("")
        lines.append(f"- **School:** {e.get('school') or '(not detected)'}")
        lines.append(f"- **Degree:** {e.get('degree') or '(not detected)'}")
        lines.append(f"- **Dates:** {e.get('dates') or '(not detected)'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_eeo() -> str:
    """EEO / voluntary-disclosure section with safe defaults."""
    lines = [
        "## EEO / voluntary disclosure",
        "",
        "Every answer below is a decline-to-answer option. candid never",
        "invents disability, veteran, gender, or race answers.",
        "",
    ]
    for qa in eeo_answers():
        lines.append(f"- **{qa['question']}:** {qa['answer']}")
    return "\n".join(lines) + "\n"


SECTIONS = {
    "work": render_work,
    "skills": render_skills,
    "education": render_education,
    "eeo": lambda profile: render_eeo(),
}


def render_kit(profile: dict, section: str = "all") -> str:
    """Render the autofill kit. ``section`` is one of work/skills/education/eeo/all."""
    if section not in ("all", "work", "skills", "education", "eeo"):
        raise AutofillError(
            f"Unknown section '{section}'. Choose from: work, skills, education, eeo, all."
        )
    parts = [HEADER, ""]
    names = ["work", "skills", "education", "eeo"] if section == "all" else [section]
    for name in names:
        parts.append(SECTIONS[name](profile))
    parts.append("---")
    parts.append("_This kit FILLS form fields for you to paste — it never submits anything._")
    return "\n".join(parts).rstrip() + "\n"


def autofill_kit(section: str = "all", profile_path: str | None = None) -> str:
    """Load the stored profile and render the requested autofill section(s)."""
    return render_kit(P.load_profile(profile_path), section=section)
