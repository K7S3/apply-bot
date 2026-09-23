"""Career narrative builder: "tell me about yourself" scripts.

Everything is grounded strictly in the profile's experience entries.
Transitions between roles use neutral phrasing and never invent reasons
for leaving — a "to focus on X" clause appears only when X is evidenced
by the next role's own bullets/title (e.g. a skill named there).

Missing information becomes explicit ``[fill in]`` placeholders, never
fabricated detail.
"""

from __future__ import annotations

import re


class NarrativeError(Exception):
    """Raised when a profile has no usable experience to narrate."""


LENGTHS = ("60s", "2min")
AUDIENCES = ("recruiter", "hiring-manager", "networking")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _experience(profile: dict) -> list[dict]:
    """Experience entries, most recent first, stripped of empties."""
    return [
        e for e in (profile.get("experience") or [])
        if e.get("title") or e.get("company")
    ]


def _require_experience(profile: dict) -> list[dict]:
    exp = _experience(profile)
    if not exp:
        raise NarrativeError(
            "No experience entries in the profile — run onboarding first "
            "with a resume so there is a career to narrate."
        )
    return exp


def _role_line(e: dict) -> str:
    """'Senior Data Scientist at Acme Corp' — never invents missing parts."""
    title = (e.get("title") or "[fill in: title]").strip()
    company = (e.get("company") or "[fill in: company]").strip()
    if title.startswith("[fill in") and company.startswith("[fill in"):
        return "[fill in: role and company]"
    if company.startswith("[fill in"):
        return title
    if title.startswith("[fill in"):
        return f"at {company}"
    return f"{title} at {company}"


def _best_bullet(e: dict, skills: set[str]) -> str:
    """The single most representative bullet of a role (grounded)."""
    bullets = [b for b in (e.get("bullets") or []) if str(b).strip()]
    if not bullets:
        return ""
    scored = sorted(
        bullets,
        key=lambda b: (sum(1 for s in skills if s in b.lower()),
                       bool(re.search(r"\d", b)), len(b)),
        reverse=True,
    )
    return str(scored[0]).strip()


def _focus_skill(next_role: dict, skills: set[str]) -> str:
    """A skill evidenced in the next role's bullets/title, or ''.

    Only ever returns a skill name that literally appears in the next
    role's own content — this is what makes 'to focus on X' grounded.
    """
    text = " ".join(
        [next_role.get("title", "")]
        + [str(b) for b in (next_role.get("bullets") or [])]
    ).lower()
    for skill in sorted(skills, key=len, reverse=True):
        if skill in text:
            return skill
    return ""


def _transition(prev: dict, nxt: dict, skills: set[str]) -> str:
    """Neutral, grounded transition between two consecutive roles.

    'prev' is the older role, 'nxt' the newer one. No invented reasons
    for leaving: the only causal clause allowed is 'to focus on X' when
    X is evidenced by the newer role's content.
    """
    focus = _focus_skill(nxt, skills)
    if focus:
        return (f"I then moved to {_role_line(nxt)} to focus on {focus}.")
    return f"I then moved to {_role_line(nxt)}."


# ---------------------------------------------------------------------------
# narrative script
# ---------------------------------------------------------------------------

def build_narrative(profile: dict, length: str = "60s") -> str:
    """Spoken-style 'tell me about yourself' script.

    Structure: present (current role + focus) -> past (arc across roles,
    one line each, neutral transitions) -> future (what you are looking
    for, from target roles / skills). ``length`` is "60s" (~130 words)
    or "2min" (~300 words).
    """
    if length not in LENGTHS:
        raise NarrativeError(
            f"Unknown length '{length}'. Choose from {list(LENGTHS)}."
        )
    exp = _require_experience(profile)
    name = (profile.get("name") or "").strip()
    skills = {s.lower() for s in (profile.get("skills") or [])}
    current = exp[0]
    opener = f"I'm {name}. " if name else ""

    # --- present ---------------------------------------------------------
    present = f"{opener}I'm currently {_role_line(current)}."
    focus_bullet = _best_bullet(current, skills)
    if focus_bullet:
        present += f" Day to day, my focus is on: {focus_bullet}"

    # --- past: oldest to newest, one line per role -----------------------
    chronological = exp[::-1]
    past_lines: list[str] = []
    for i, role in enumerate(chronological):
        if i == 0:
            first = role
            bullets = [b for b in (first.get("bullets") or []) if str(b).strip()]
            if len(chronological) == 1:
                # no separate past for a single-role career
                break
            line = f"I started my career as {_role_line(first)}"
            if bullets:
                line += f", where {_best_bullet(first, skills)}" \
                    if _best_bullet(first, skills) else ""
            line += "."
            past_lines.append(line)
        else:
            prev = chronological[i - 1]
            trans = _transition(prev, role, skills)
            if length == "60s":
                past_lines.append(trans)
            else:
                bullet = _best_bullet(role, skills)
                past_lines.append(trans + (f" There, {bullet}" if bullet else ""))

    # --- future ----------------------------------------------------------
    future_parts: list[str] = []
    targets = [t for t in (profile.get("target_roles") or []) if str(t).strip()]
    if targets:
        future_parts.append(
            "Going forward, I'm looking for roles like "
            + ", ".join(str(t) for t in targets[:3]) + "."
        )
    else:
        future_parts.append(
            "Going forward, I'm looking for a role where I can keep "
            "doing more of this kind of work [fill in: what specifically "
            "you're looking for next]."
        )
    if skills:
        top = sorted(skills)[:5]
        future_parts.append(
            "My strongest tools for it are " + ", ".join(top) + "."
        )

    sections = ["Present", "Past", "Future"] if length == "2min" else None
    if sections:
        text = (
            f"## Present\n\n{present}\n\n"
            f"## Past\n\n{' '.join(past_lines)}\n\n"
            f"## Future\n\n{' '.join(future_parts)}"
        )
    else:
        arc = " ".join(past_lines[:2])  # 60s: keep the arc tight
        text = f"{present} {arc} {' '.join(future_parts)}".strip()

    # roughly enforce the word budgets
    words = text.split()
    budget = {"60s": 160, "2min": 330}[length]
    if len(words) > budget:
        text = " ".join(words[:budget]).rstrip(".,;:") + "."
    return text.strip()


# ---------------------------------------------------------------------------
# story arc + elevator pitches
# ---------------------------------------------------------------------------

def story_arc(profile: dict) -> str:
    """One-paragraph career thesis: the through-line across roles."""
    exp = _require_experience(profile)
    name = (profile.get("name") or "This candidate").strip() or "This candidate"
    skills = [s for s in (profile.get("skills") or []) if s]
    domains = [d for d in (profile.get("domains") or []) if d]
    seniority = (profile.get("seniority") or "").strip()
    years = profile.get("years_experience")

    trajectory = " to ".join(
        (e.get("title") or "a role").strip() for e in exp[::-1]
    )

    parts = [
        f"{name}'s career arc runs {trajectory} — "
        f"{len(exp)} role{'s' if len(exp) != 1 else ''}"
    ]
    if years:
        parts[-1] += f" over about {years} years"
    parts[-1] += "."
    if domains:
        parts.append(f"The through-line is work in {', '.join(domains[:3])}.")
    if skills:
        parts.append(
            f"The recurring technical thread is {', '.join(skills[:4])}, "
            "which shows up across multiple roles."
        )
    if seniority:
        parts.append(f"The trajectory tracks a {seniority}-level profile.")
    return " ".join(parts)


def elevator_pitch(profile: dict, audience: str = "recruiter") -> str:
    """Short pitch tailored to an audience.

    ``audience``: "recruiter" (skills fit), "hiring-manager" (outcomes),
    or "networking" (conversational, with an ask placeholder).
    """
    if audience not in AUDIENCES:
        raise NarrativeError(
            f"Unknown audience '{audience}'. Choose from {list(AUDIENCES)}."
        )
    exp = _require_experience(profile)
    name = (profile.get("name") or "").strip()
    skills = {s.lower() for s in (profile.get("skills") or [])}
    current = exp[0]
    who = f"I'm {name}, " if name else "I'm "
    role = _role_line(current)
    focus = _best_bullet(current, skills)

    if audience == "recruiter":
        skill_str = ", ".join(sorted(skills)[:5]) or "[fill in: key skills]"
        pitch = (
            f"{who}a {_role_line(current)}. I work with {skill_str}"
        )
        if len(exp) > 1:
            pitch += f"; previously {_role_line(exp[1])}."
        else:
            pitch += "."
        if focus:
            pitch += f" Recently: {focus}"
        return pitch

    if audience == "hiring-manager":
        pitch = f"{who}currently {role}. "
        if focus:
            pitch += f"My biggest impact there: {focus} "
        pitch += "I bring " + ", ".join(sorted(skills)[:4] or
                                        ["[fill in: strengths]"]) + \
            ", and I'm looking for a team where those move the needle " \
            "[fill in: on what]."
        return pitch

    # networking
    domain_str = ", ".join((profile.get("domains") or [])[:2])
    pitch = f"{who}a {role.split(' at ')[0] if ' at ' in role else role}"
    if domain_str:
        pitch += f" working in {domain_str}"
    pitch += ". I'm exploring what's next"
    targets = [t for t in (profile.get("target_roles") or []) if str(t).strip()]
    if targets:
        pitch += f" — especially roles like {', '.join(str(t) for t in targets[:2])}"
    pitch += " — and I'd love to hear how your team thinks about " \
        "[fill in: a topic you'd genuinely like to discuss]."
    return pitch
