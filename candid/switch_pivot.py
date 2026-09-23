"""Pivot resume template for career switchers.

Builds a functional/hybrid one-page-style resume (markdown text) that leads
with a "Relevant capabilities" section - experience grouped by competency
rather than by chronology - followed by a condensed work history, skills, and
education.

  build_pivot_resume(profile, target_role)
      The main entry point. Everything comes strictly from the profile dict:
      name, contact fields, headline, seniority, years of experience, skills,
      experience entries (titles, companies, dates, bullets), and education.
      Nothing is invented.

  pivot_cover_header(profile, target_role)
      A short positioning statement for the top of the resume (or the top of
      a cover letter): who the person is, what they bring, where they're
      headed.

Bullet-to-competency grouping reuses the competency model from
``candid.switch_narrative`` so the two modules speak the same language.

Everything is deterministic and local - no network, no paid APIs, no LLM.
"""

from __future__ import annotations

import re

from candid.switch_narrative import competency_of, _COMPETENCIES, _FALLBACK_COMPETENCY


class PivotResumeError(Exception):
    """Raised for invalid profile input to the pivot resume builder."""


_MAX_BULLETS_PER_COMPETENCY = 6
_MAX_TOTAL_BULLETS = 18


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().rstrip(".")


def _contact_line(profile: dict) -> str:
    bits = [profile[k] for k in ("location", "email", "phone", "linkedin", "website")
            if profile.get(k)]
    return " | ".join(str(b) for b in bits)


def pivot_cover_header(profile: dict, target_role: str) -> str:
    """Short positioning statement: who they are, what they bring, where headed."""
    if not isinstance(profile, dict):
        raise PivotResumeError("profile must be a dict.")
    if not isinstance(target_role, str) or not target_role.strip():
        raise PivotResumeError("target_role must be a non-empty string.")
    target_role = target_role.strip()
    headline = _clean(profile.get("headline", "") or "")
    years = profile.get("years_experience")
    seniority = _clean(profile.get("seniority", "") or "")

    who = headline or seniority or "Experienced professional"
    if years not in (None, ""):
        try:
            yrs = float(years)
            yrs_text = f"{yrs:g} years"
        except (TypeError, ValueError):
            yrs_text = f"{years} years"
        who = f"{who} with {yrs_text} of experience"
    return (f"{who} pivoting into {target_role} - bringing a track record of "
            f"transferable strengths built across prior roles.")


def _group_bullets(experience: list[dict]) -> dict[str, list[dict]]:
    """Group every bullet by competency; each bullet listed once, with provenance."""
    order = [label for label, _ in _COMPETENCIES] + [_FALLBACK_COMPETENCY]
    groups: dict[str, list[dict]] = {label: [] for label in order}
    seen: set[str] = set()
    for entry in experience:
        title = _clean(entry.get("title", "") or "Role")
        company = _clean(entry.get("company", "") or "")
        for b in (entry.get("bullets") or []):
            if not isinstance(b, str) or not b.strip():
                continue
            bullet = _clean(b)
            if bullet in seen:
                continue
            seen.add(bullet)
            groups[competency_of(b)].append({"bullet": bullet,
                                             "provenance": f"{title} at {company}" if company else title})
    return groups


def _condensed_history(experience: list[dict]) -> list[str]:
    lines = []
    for entry in experience:
        title = _clean(entry.get("title", "") or "Role")
        company = _clean(entry.get("company", "") or "")
        dates = _clean(entry.get("dates", "") or "")
        line = title
        if company:
            line += f", {company}"
        if dates:
            line += f" ({dates})"
        lines.append(line)
    return lines


def build_pivot_resume(profile: dict, target_role: str) -> str:
    """Generate the pivot resume markdown from the profile dict."""
    if not isinstance(profile, dict):
        raise PivotResumeError("profile must be a dict.")
    if not isinstance(target_role, str) or not target_role.strip():
        raise PivotResumeError("target_role must be a non-empty string.")
    target_role = target_role.strip()
    experience = profile.get("experience")
    if not isinstance(experience, list) or not experience:
        raise PivotResumeError("profile needs a non-empty 'experience' list to pivot from.")

    lines: list[str] = []
    name = _clean(profile.get("name", "") or "Candidate")
    lines.append(f"# {name} - pivot to {target_role}")
    contact = _contact_line(profile)
    if contact:
        lines.append(contact)
    lines.append("")
    lines.append(pivot_cover_header(profile, target_role))
    lines.append("")

    # Relevant capabilities, strongest-evidence competency first.
    lines.append("## Relevant capabilities")
    groups = _group_bullets(experience)
    ranked = sorted(
        ((label, items) for label, items in groups.items() if items),
        key=lambda kv: len(kv[1]), reverse=True,
    )
    total = 0
    for label, items in ranked:
        lines.append("")
        lines.append(f"### {label}")
        for item in items[:_MAX_BULLETS_PER_COMPETENCY]:
            if total >= _MAX_TOTAL_BULLETS:
                break
            lines.append(f"- {item['bullet']}. ({item['provenance']})")
            total += 1
        if total >= _MAX_TOTAL_BULLETS:
            break

    lines.append("")
    lines.append("## Work history (condensed)")
    for line in _condensed_history(experience):
        lines.append(f"- {line}")

    skills = [s for s in (profile.get("skills") or []) if isinstance(s, str) and s.strip()]
    if skills:
        lines.append("")
        lines.append("## Skills")
        lines.append(", ".join(skills))

    education = profile.get("education") or []
    if education:
        lines.append("")
        lines.append("## Education")
        for ed in education:
            if isinstance(ed, dict):
                deg = _clean(ed.get("degree", "") or "")
                inst = _clean(ed.get("institution", "") or "")
                lines.append(f"- {deg}, {inst}".rstrip(", "))
            elif isinstance(ed, str) and ed.strip():
                lines.append(f"- {_clean(ed)}")

    return "\n".join(lines).rstrip() + "\n"
