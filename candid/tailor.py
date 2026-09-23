"""Tailored resume + cover letter generation.

Reads the user profile and a job description, then produces:
  - a tailored resume (reorders bullets, emphasizes JD keywords, rewrites the
    summary around the single strongest proof bullet) - it NEVER invents
    employers, degrees, skills, or achievements; everything comes from the
    profile. Appends an ATS keyword check (covered vs missing JD keywords)
    and a what-changed summary (which bullets were promoted/trimmed).
  - a cover letter in the requested tone.

Tones: concise | confident | formal | warm
Lengths: one-page (condensed) | detailed
"""

from __future__ import annotations

import re
from datetime import date

from candid import config as C
from candid.contexts import ctx_value
from candid.match import _jd_skills, _extract_jd  # internal reuse

TONES = ["concise", "confident", "formal", "warm"]
LENGTHS = ["one-page", "detailed"]

_TONE_SUMMARY = {
    "concise": "Results-driven {seniority} professional with {years} years across {domains}. Standout: {proof}.",
    "confident": "{seniority_cap} professional with a track record of shipping {domains} work that moves business metrics - {years} years turning ambiguous problems into production systems. Standout: {proof}.",
    "formal": "{seniority_cap} professional offering {years} years of experience in {domains}, with demonstrated success delivering measurable outcomes in production environments. Most relevant: {proof}.",
    "warm": "I'm a {seniority} {family} specialist ({years} yrs) who loves turning messy, real-world data into {domains} products people actually use. A recent highlight: {proof}.",
}


def _role_family_label(profile: dict) -> str:
    from candid.match import _profile_role_family
    return _profile_role_family(profile).replace("_", " ")


def _top_domains(profile: dict, jd: str) -> str:
    must, nice = _jd_skills(jd)
    matched = [s for s in (must | nice) if s in set(profile.get("skills", []))]
    return ", ".join(matched[:4]) or "data"


def _bullet_score(bullet: str, jd_skills: set[str]) -> int:
    low = bullet.lower()
    return sum(1 for s in jd_skills if s in low) + (2 if re.search(r"\d", bullet) else 0)


def _tailor_bullets(experience: list[dict], jd_skills: set[str], detailed: bool) -> list[dict]:
    out = []
    for e in experience:
        scored = sorted(
            (( _bullet_score(b, jd_skills), b) for b in e.get("bullets", [])),
            reverse=True,
        )
        keep = len(scored) if detailed else min(len(scored), 4)
        out.append({
            "title": e.get("title", ""),
            "company": e.get("company", ""),
            "dates": e.get("dates", ""),
            "bullets": [b for _, b in scored[:keep]],
        })
    return out


def _short(text: str, n: int = 64) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[:n - 3] + "..."


def _ats_keyword_check(resume_text: str, jd: str) -> str:
    """Which JD keywords/skills appear in the tailored resume, which don't."""
    ex = _extract_jd(jd)
    low = resume_text.lower()
    covered, missing = [], []
    for name in sorted(ex["items"]):
        info = ex["items"][name]
        if info["aliases"] is not None:
            hit = any(C.skill_regex(a).search(low) for a in info["aliases"])
        else:
            hit = re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])",
                            low) is not None
        (covered if hit else missing).append(name)
    total = len(ex["items"])
    lines = [f"Covered ({len(covered)}/{total}): " + (", ".join(covered) if covered else "none")]
    lines.append(f"Missing from this resume ({len(missing)}): " +
                 (", ".join(missing) if missing else "none - good coverage"))
    return "\n".join(lines)


def _what_changed(original: list[dict], tailored: list[dict]) -> list[str]:
    """One line per role describing bullet promotion/trimming vs original order."""
    notes = []
    for orig, new in zip(original, tailored):
        ob = orig.get("bullets", [])
        nb = new["bullets"]
        if not ob:
            continue
        label = new["company"] or new["title"] or "Role"
        promoted = [b for b in nb[:3] if b in ob and ob.index(b) >= 3]
        trimmed = [b for b in ob if b not in nb]
        bits = []
        if promoted:
            bits.append("promoted %d to top: %s" % (
                len(promoted), "; ".join('"%s"' % _short(b) for b in promoted[:2])))
        if trimmed:
            bits.append("trimmed %d lower-relevance: %s" % (
                len(trimmed), "; ".join('"%s"' % _short(b) for b in trimmed[:2])))
        if bits:
            notes.append("%s: %s" % (label, ", ".join(bits)))
    return notes or ["No reordering needed - bullets already in JD-relevance order."]


def build_resume(profile: dict, jd: str, company: str = "", role: str = "",
                 tone: str | None = None, length: str | None = None) -> str:
    """Build a tailored plain-text resume. Never invents experience.

    ``tone``/``length`` default to the active context (tailor.tone /
    tailor.length), honoring per-company overrides for the target company;
    with no active context they fall back to "confident" / "one-page".
    Explicitly passed values always win.
    """
    if tone is None:
        tone = ctx_value("tailor.tone", "confident", company=company or None)
    if length is None:
        length = ctx_value("tailor.length", "one-page", company=company or None)
    if tone not in TONES:
        raise ValueError(f"Unknown tone '{tone}'. Choose from {TONES}.")
    if length not in LENGTHS:
        raise ValueError(f"Unknown length '{length}'. Choose from {LENGTHS}.")

    must, nice = _jd_skills(jd)
    jd_skills = must | nice
    detailed = length == "detailed"
    seniority = profile.get("seniority", "mid")
    years = profile.get("years_experience", 0)
    family = _role_family_label(profile)
    domains = _top_domains(profile, jd)

    # summary leads with the single strongest proof bullet (from the profile)
    proof = _proof_bullet(profile, jd).rstrip(".")
    proof_txt = _short(proof, 160) if proof else "production data work end to end"
    summary_tpl = _TONE_SUMMARY[tone]
    summary = summary_tpl.format(
        seniority=seniority, seniority_cap=seniority.capitalize(),
        years=years, domains=domains, family=family, proof=proof_txt,
    )

    name = profile.get("name") or "Your Name"
    lines = [name.upper()]
    contact_bits = [b for b in [profile.get("location"), profile.get("headline")] if b]
    if contact_bits:
        lines.append(" | ".join(contact_bits))
    lines += ["", "SUMMARY", summary, "", "EXPERIENCE", ""]

    experience = profile.get("experience", [])
    tailored = _tailor_bullets(experience, jd_skills, detailed)
    for e in tailored:
        header = " - ".join(b for b in [e["title"], e["company"]] if b)
        if e["dates"]:
            header += f" | {e['dates']}"
        lines.append(header)
        for b in e["bullets"]:
            lines.append(f"• {b}")
        lines.append("")

    if profile.get("education"):
        lines.append("EDUCATION")
        for ed in profile["education"]:
            ed_line = " - ".join(b for b in [ed.get("school"), ed.get("degree")] if b)
            if ed.get("dates"):
                ed_line += f" | {ed['dates']}"
            lines.append(ed_line)
        lines.append("")

    matched_skills = sorted(set(profile.get("skills", [])) & jd_skills)
    other_skills = sorted(set(profile.get("skills", [])) - jd_skills)
    lines.append("SKILLS")
    if matched_skills:
        lines.append("Most relevant to this role: " + ", ".join(matched_skills))
    lines.append("Also: " + ", ".join(other_skills[:20]))

    lines += ["", "ATS KEYWORD CHECK", _ats_keyword_check("\n".join(lines), jd), "",
              "WHAT CHANGED"] + _what_changed(experience, tailored) + [""]

    if role or company:
        lines += [f"- Tailored for {role} @ {company} on {date.today().isoformat()} -"]
    return "\n".join(lines).strip() + "\n"


_COVER_TEMPLATES = {
    "concise": (
        "Dear Hiring Manager,\n\n"
        "I'm applying for the {role} role at {company}. As a {seniority} {family} "
        "specialist with {years} years of experience, my recent work includes {proof_short}. "
        "What excites me about this role is {hook}.\n\n"
        "I'd welcome the chance to discuss how I can contribute. Thank you for your consideration.\n\n"
        "Best regards,\n{name}"
    ),
    "confident": (
        "Dear {company} Hiring Team,\n\n"
        "The {role} role caught my eye because it sits exactly at the intersection "
        "of what I do best: {domains}. Over the last {years} years as a {seniority} {family} "
        "specialist, {proof_sentence}\n\n"
        "{hook_sentence}\n\n"
        "I'd love to bring that same impact to {company}. Happy to walk through the details anytime.\n\n"
        "Best,\n{name}"
    ),
    "formal": (
        "Dear Hiring Manager,\n\n"
        "Please accept my application for the position of {role} at {company}. "
        "With {years} years of experience as a {seniority} {family} specialist, I offer "
        "{domains} expertise demonstrated through {proof}. "
        "I am particularly drawn to this opportunity because {hook}.\n\n"
        "I would appreciate the opportunity to discuss my qualifications further. "
        "Thank you for your time and consideration.\n\n"
        "Sincerely,\n{name}"
    ),
    "warm": (
        "Hi {company} team,\n\n"
        "I'm {name}, a {seniority} {family} specialist ({years} yrs), and I couldn't not "
        "apply for the {role} role - {hook}. "
        "Recently, {proof_sentence}\n\n"
        "Would love to chat about what you're building.\n\n"
        "Warmly,\n{name}"
    ),
}


def _proof_bullet(profile: dict, jd: str) -> str:
    """Pick the highest-JD-relevance bullet as the proof point (raw text)."""
    must, nice = _jd_skills(jd)
    jd_skills = must | nice
    best, best_score = "", -1
    for e in profile.get("experience", []):
        for b in e.get("bullets", []):
            s = _bullet_score(b, jd_skills)
            if s > best_score:
                best, best_score = b, s
    return best or "Delivered production data work end to end"


def _proof_sentence(profile: dict, jd: str) -> str:
    b = _proof_bullet(profile, jd).rstrip(".")
    return f"I {b[0].lower() + b[1:]}." if b else "I've delivered production data work end to end."


def build_cover_letter(profile: dict, jd: str, company: str, role: str,
                       tone: str | None = None, hook: str = "") -> str:
    """Build a cover letter. `hook` = why this company/role (one line, optional).

    ``tone`` defaults to the active context (tailor.tone), honoring a
    per-company override for the target company; with no active context it
    falls back to "confident". An explicitly passed tone wins.
    """
    if tone is None:
        tone = ctx_value("tailor.tone", "confident", company=company or None)
    if tone not in TONES:
        raise ValueError(f"Unknown tone '{tone}'. Choose from {TONES}.")
    if not company or not role:
        raise ValueError("Cover letters need both --company and --role.")
    tpl = _COVER_TEMPLATES[tone]
    seniority = profile.get("seniority", "mid")
    years = profile.get("years_experience", 0)
    family = _role_family_label(profile)
    domains = _top_domains(profile, jd)
    proof = _proof_sentence(profile, jd)
    proof_bullet = _proof_bullet(profile, jd)
    proof_short = proof_bullet[0].lower() + proof_bullet[1:] if proof_bullet else proof_bullet
    hook = hook or "the problems you're solving are exactly the ones I've spent my career on"
    return tpl.format(
        company=company, role=role, seniority=seniority, years=years,
        family=family, domains=domains, proof=proof,
        proof_sentence=proof[0].upper() + proof[1:] if proof else proof,
        proof_short=proof_short,
        hook=hook, hook_sentence=f"What draws me to {company} is {hook}.",
        name=profile.get("name") or "Your Name",
    )
