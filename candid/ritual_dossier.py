"""One-page confidence sheet: "why I'm a strong candidate".

``python -m candid ritual dossier --company X --role Y`` (CLI wired by a
separate worker via lazy imports) produces plain text meant to be read
30 minutes before the interview:

  - headline from the profile (name, seniority, years)
  - top strengths drawn ONLY from candid_data/profile.json
  - best match highlights from the last real match run, if stored
  - top 3 resume bullets (metric-bearing bullets preferred)

Groundedness is the whole point: nothing here is invented. Every line
traces back to the profile or the tracker. If no profile exists, the
dossier says so and suggests running onboard first.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

from candid import config as C


def _data_dir() -> Path:
    """User data dir, honoring CANDID_DATA_DIR even if set after import."""
    override = os.environ.get("CANDID_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return C.DATA_DIR


def _profile_path() -> Path:
    return _data_dir() / "profile.json"


def load_profile() -> dict | None:
    """Load candid_data/profile.json, or None if missing/unreadable."""
    p = _profile_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _last_match_result(company: str, role: str) -> dict | None:
    """Best stored match run for company+role, or None.

    Only real stored data is used: a JSON list at
    candid_data/matches.json (or match_history.json), where each entry
    may carry company, role, score, strengths, and date. Nothing is
    computed or guessed here.
    """
    for fname in ("matches.json", "match_history.json"):
        p = _data_dir() / fname
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data = data.get("runs", data.get("matches", []))
        if not isinstance(data, list):
            continue
        cl, rl = company.strip().lower(), role.strip().lower()
        scored = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if (str(entry.get("company", "")).strip().lower() == cl
                    and str(entry.get("role", "")).strip().lower() == rl):
                scored.append(entry)
        if scored:
            scored.sort(key=lambda e: str(e.get("date", "")))
            return scored[-1]
    return None


def _metric_weight(bullet: str) -> int:
    """Rank bullets: quantified impact first, then length."""
    return (2 if re.search(r"\d", bullet) else 0) + (1 if len(bullet) > 60 else 0)


def top_resume_bullets(profile: dict, limit: int = 3) -> list[tuple[str, str]]:
    """Top bullets as (header, bullet) pairs. Metric bullets preferred.

    Header is "Title at Company" so every bullet stays attributed.
    """
    scored = []
    for exp in profile.get("experience", []) or []:
        title = str(exp.get("title", "") or "").strip()
        comp = str(exp.get("company", "") or "").strip()
        header = f"{title} at {comp}".strip(" at")
        for b in exp.get("bullets", []) or []:
            b = str(b).strip()
            if b:
                scored.append((_metric_weight(b), header, b))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [(h, b) for _, h, b in scored[:limit]]


def _strength_lines(profile: dict) -> list[str]:
    """Strength statements, all derived from the profile."""
    lines = []
    name = str(profile.get("name", "") or "").strip()
    seniority = str(profile.get("seniority", "") or "").strip()
    years = profile.get("years_experience")
    headline = str(profile.get("headline", "") or "").strip()
    if name:
        who = name
        if seniority:
            who += f" - {seniority} professional"
        if isinstance(years, (int, float)) and years:
            who += f" with {years:g} years of experience"
        lines.append(who)
    if headline:
        lines.append(headline)
    skills = [str(s) for s in (profile.get("skills") or []) if str(s).strip()]
    if skills:
        lines.append("Core skills: " + ", ".join(skills[:10]))
    summary = str(profile.get("summary", "") or "").strip()
    if summary:
        lines.append(summary[:280] + ("..." if len(summary) > 280 else ""))
    edu = profile.get("education") or []
    if edu and isinstance(edu[0], dict):
        school = str(edu[0].get("school", "") or "").strip()
        degree = str(edu[0].get("degree", "") or "").strip()
        if school or degree:
            lines.append("Education: " + ", ".join(x for x in (degree, school) if x))
    return lines


def _match_lines(match: dict | None) -> list[str]:
    """Highlight lines from a stored match run; empty if none."""
    if not match:
        return []
    lines = []
    score = match.get("score")
    if isinstance(score, (int, float)):
        lines.append(f"Last match score for this role: {score:g}/100 "
                     f"(run {match.get('date', 'on file')})")
    for s in (match.get("strengths") or [])[:4]:
        s = str(s).strip()
        if s:
            lines.append(s)
    return lines


def build_dossier(company: str, role: str) -> str:
    """Build the one-page confidence sheet as plain printable text."""
    company = (company or "").strip()
    role = (role or "").strip()

    width = 72
    bar = "-" * width
    lines = [
        bar,
        "WHY YOU ARE A STRONG CANDIDATE",
        f"{role} @ {company}".strip(" @"),
        f"Read 30 minutes before the interview - {date.today().isoformat()}",
        bar,
        "",
    ]

    profile = load_profile()
    if not profile:
        lines.append("No profile found yet.")
        lines.append("")
        lines.append("Run onboarding first so this sheet is built from your")
        lines.append("real background, not guesswork:")
        lines.append("")
        lines.append("  python -m candid onboard --resume your_resume.pdf")
        lines.append("")
        lines.append(bar)
        return "\n".join(lines)

    lines.append("YOUR STRENGTHS (from your profile)")
    lines.append("")
    for s in _strength_lines(profile):
        lines.append(f"  * {s}")
    lines.append("")

    match = _last_match_result(company, role)
    mlines = _match_lines(match)
    if mlines:
        lines.append("MATCH HIGHLIGHTS (last stored match run)")
        lines.append("")
        for s in mlines:
            lines.append(f"  * {s}")
        lines.append("")
    else:
        lines.append("No stored match run for this role - run:")
        lines.append("")
        lines.append("  python -m candid match --jd jd.txt "
                     f"--company \"{company}\" --role \"{role}\"")
        lines.append("")

    lines.append("TOP 3 RESUME BULLETS (say these out loud)")
    lines.append("")
    bullets = top_resume_bullets(profile, limit=3)
    if bullets:
        for i, (header, b) in enumerate(bullets, 1):
            lines.append(f"  {i}. [{header}]")
            lines.append(f"     {b}")
    else:
        lines.append("  No bullets in your profile yet - add experience during")
        lines.append("  onboarding so this section has real proof points.")
    lines.append("")
    lines.append("Remember: every line above comes from your own profile.")
    lines.append("Walk in with the receipts.")
    lines.append(bar)
    return "\n".join(lines)
