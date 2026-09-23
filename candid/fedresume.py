"""Federal (USAJOBS) resume notes generator + announcement scoring.

Federal resumes differ from private-sector ones: they are longer (often
4-6+ pages), list duties in detail with hours/week and supervisor info per
role, use month/year dates, and must mirror the announcement's
specialized-experience language. This module turns the user's profile into
an actionable checklist (never inventing experience) and scores a federal
announcement in the same 0-100 spirit as ``candid.match.score_match``.

Series keywords and the GS grade-band translator come from
``candid.federal`` when it is importable, with a defensive keyword fallback
otherwise. Everything is offline and stdlib-only.
"""

from __future__ import annotations

import re

from candid import config as C

try:
    from candid import match as _match  # reuse JD skill extraction helpers
    _extract_jd = _match._extract_jd
except Exception:  # pragma: no cover - defensive; match.py is stdlib-only
    _match = None
    _extract_jd = None


# ---------------------------------------------------------------------------
# Series keywords (fallback when no candid.federal module is installed)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Series keywords: prefer candid.federal's bundled SERIES table; fall back to
# the small keyword map below only if the module cannot be imported.
# ---------------------------------------------------------------------------

def _keywords_for_series(series: str) -> set[str] | None:
    """Series keywords from candid.federal; None if the module is missing."""
    try:
        from candid import federal as _fed
        for s in _fed.SERIES:
            if s.get("code") == series:
                return set(s.get("keywords", []))
        return set()  # unknown series code -> neutral scoring
    except Exception:
        return None


def _series_keywords(series: str) -> set[str] | None:
    # Backwards-compatible alias used by older callers/tests.
    return _keywords_for_series(series)


_SERIES_KEYWORDS: dict[str, set[str]] = {
    "1550": {"software", "algorithm", "machine learning", "computer science",
             "research", "data", "python", "programming"},
    "2210": {"information technology", "systems", "network", "cybersecurity",
             "cloud", "software", "database", "it"},
    "0855": {"electronics", "hardware", "circuit", "embedded", "rf"},
    "0830": {"mechanical", "design", "cad", "thermodynamics"},
    "0861": {"aerospace", "aerodynamics", "propulsion"},
    "0343": {"analysis", "program", "policy", "evaluation", "management"},
    "0301": {"administration", "operations", "management", "program"},
    "0501": {"finance", "accounting", "audit", "financial"},
    "0560": {"budget", "forecast", "financial", "analysis"},
    "1102": {"contract", "procurement", "acquisition", "solicitation"},
    "0201": {"human resources", "staffing", "recruitment", "hr"},
    "0404": {"biology", "laboratory", "research", "science"},
    "0401": {"natural resources", "environmental", "science"},
}

_SERIES_RE = re.compile(r"\b(?:series\s*)?(\d{4})\b", re.I)


def _announcement_series(text: str, announcement: dict) -> str:
    if announcement.get("series"):
        m = _SERIES_RE.search(str(announcement["series"]))
        if m:
            return m.group(1)
    m = _SERIES_RE.search(text or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# 1. Federal resume notes
# ---------------------------------------------------------------------------

_MONTH_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _date_quality(dates: str) -> str:
    """Classify a date range string: 'month_year', 'year_only', or 'missing'."""
    d = dates or ""
    if not _YEAR_RE.search(d):
        return "missing"
    if _MONTH_RE.search(d):
        return "month_year"
    return "year_only"


def federal_resume_notes(profile: dict) -> dict:
    """Build a structured federal-resume checklist from the profile.

    Everything references only what the profile contains. Missing pieces
    become prompts, never invented content.
    """
    exp = profile.get("experience", []) or []
    skills = profile.get("skills", []) or []
    edu = profile.get("education", []) or []

    has = lambda v: bool((v or "").strip()) if isinstance(v, str) else bool(v)

    blocks = [
        {"block": "Contact info (name, phone, email, city/state)",
         "present": has(profile.get("name")) and has(profile.get("location")),
         "note": "Include phone and email at the top. Add a citizenship "
                 "line (e.g. 'U.S. Citizen') - federal postings ask for it."},
        {"block": "Citizenship / eligibility statement",
         "present": False,
         "note": "State citizenship explicitly; add veterans' preference "
                 "and federal-employment status only if they apply to you."},
        {"block": "Work experience with full detail per role",
         "present": bool(exp),
         "note": "Each role needs: title, employer, location, start/end in "
                 "MM/YYYY format, hours per week, supervisor name + "
                 "'may we contact' permission, and a duties paragraph."},
        {"block": "Education (school, degree, dates)",
         "present": bool(edu),
         "note": "List degrees with school and completion date. Include "
                 "relevant coursework only if it supports the series."},
        {"block": "Skills / certifications",
         "present": bool(skills),
         "note": "Keep the skills list but expand duties to *show* the "
                 "top 5-8 in context; the assessment questionnaire will "
                 "ask for experience levels per skill."},
        {"block": "Honors, awards, publications (optional)",
         "present": False,
         "note": "Optional for most announcements; add when the posting "
                 "mentions publications, patents, or awards."},
        {"block": "References",
         "present": False,
         "note": "USAJOBS resumes often list references with contact info. "
                 "'References available upon request' is acceptable for "
                 "early drafts, but some announcements require names."},
    ]

    per_role = []
    for e in exp:
        title = e.get("title", "")
        company = e.get("company", "")
        bullets = e.get("bullets", []) or []
        dq = _date_quality(e.get("dates", ""))
        total_words = sum(len(b.split()) for b in bullets)
        prompts: list[str] = []
        if dq == "missing":
            prompts.append("Add employment dates (even approximate).")
        elif dq == "year_only":
            prompts.append("Expand dates to MM/YYYY - MM/YYYY (e.g. "
                           "'June 2021 - Present').")
        prompts.append("Add hours per week (e.g. '40 hrs/week').")
        prompts.append("Add supervisor name and whether they may be contacted.")
        if len(bullets) < 4 or total_words < 120:
            prompts.append(
                "Expand duties: federal resumes run 4-8+ detailed bullets per "
                "role. Use CCAR (context, challenge, action, result) and "
                "mirror the announcement's specialized-experience language.")
        else:
            prompts.append(
                "Review bullets against the announcement's specialized-"
                "experience paragraph; echo its key phrases verbatim where "
                "true.")
        prompts.append("End with a results line per major duty (scope, "
                       "savings, users, scale).")
        per_role.append({"title": title, "company": company,
                         "dates": e.get("dates", ""), "prompts": prompts})

    formatting_rules = [
        "Dates in MM/YYYY - MM/YYYY for every role and degree.",
        "Hours per week on every work entry; full-time vs part-time matters "
        "for experience credit.",
        "No photo, no graphics, no salary history (USAJOBS does not ask).",
        "Length is fine at 3-6 pages: completeness beats brevity for "
        "federal HR review.",
        "Mirror the announcement's wording for duties and specialized "
        "experience - HR specialists screen on keyword match.",
        "Save/export as plain text or the USAJOBS builder format; fancy "
        "templates break the parser.",
    ]

    notes = {
        "required_blocks": blocks,
        "per_role": per_role,
        "formatting_rules": formatting_rules,
        "veterans": {
            "guidance": "If you are a veteran, the USAJOBS builder asks for "
                        "branch, service dates, discharge type, and any "
                        "preference claim (with supporting documents like "
                        "DD-214/SF-15). Add these yourself in the builder; "
                        "candid never infers veteran status from your resume.",
            "user_provided": False,
        },
        "groundedness": "All prompts reference your actual profile entries; "
                        "nothing here invents experience. Anything you cannot "
                        "verify belongs in the builder, not on the resume.",
    }
    return notes


def render_notes(notes: dict) -> str:
    """Render the structured notes as a human-readable text report."""
    lines = ["FEDERAL RESUME CHECKLIST", "=" * 24, ""]
    lines.append("Required blocks:")
    for b in notes.get("required_blocks", []):
        mark = "[x]" if b.get("present") else "[ ]"
        lines.append(f"  {mark} {b['block']}")
        lines.append(f"      -> {b['note']}")
    lines.append("")
    per_role = notes.get("per_role", [])
    if per_role:
        lines.append("Per-role prompts:")
        for r in per_role:
            hdr = f"  {r.get('title') or '(untitled role)'}"
            if r.get("company"):
                hdr += f" - {r['company']}"
            if r.get("dates"):
                hdr += f" ({r['dates']})"
            lines.append(hdr)
            for p in r.get("prompts", []):
                lines.append(f"    * {p}")
        lines.append("")
    lines.append("Formatting rules:")
    for f in notes.get("formatting_rules", []):
        lines.append(f"  - {f}")
    lines.append("")
    v = notes.get("veterans", {})
    lines.append("Veterans / preference:")
    lines.append(f"  {v.get('guidance', '')}")
    lines.append("")
    lines.append(notes.get("groundedness", ""))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. KSA / assessment-questionnaire hints
# ---------------------------------------------------------------------------

_KSA_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("skill", re.compile(r"\bskill\s+in\s+([^.:\n]{4,90})", re.I)),
    ("ability", re.compile(r"\babilit(?:y|ies)\s+to\s+([^.:\n]{4,90})", re.I)),
    ("knowledge", re.compile(r"\bknowledge\s+of\s+([^.:\n]{4,90})", re.I)),
    ("experience", re.compile(
        r"\bexperience\s+(?:in|with)\s+([^.:\n]{4,90})", re.I)),
    ("competency", re.compile(
        r"\bcompetenc(?:y|ies)\s+(?:in|with)\s+([^.:\n]{4,90})", re.I)),
    ("proficiency", re.compile(r"\bproficien(?:cy|t)\s+in\s+([^.:\n]{4,90})",
                               re.I)),
    ("specialized", re.compile(
        r"\bspecialized\s+experience\s*(?:includes?|:)?\s*([^.:\n]{4,160})",
        re.I)),
]


def _ksa_snippet(text: str, start: int, end: int, radius: int = 40) -> str:
    s = max(0, start - radius)
    e = min(len(text), end + radius)
    frag = re.sub(r"\s+", " ", text[s:e]).strip()
    return ("..." if s > 0 else "") + frag + ("..." if e < len(text) else "")


def ksa_hints(announcement_text: str, limit: int = 12) -> list[dict]:
    """Extract likely KSA / assessment-questionnaire themes from an
    announcement. Returns [{kind, phrase, snippet, prep_pointer}]."""
    text = announcement_text or ""
    seen: set[str] = set()
    hints: list[dict] = []
    for kind, pat in _KSA_PATTERNS:
        for m in pat.finditer(text):
            phrase = re.sub(r"\s+", " ", m.group(1)).strip(" .;,-")
            if len(phrase) < 4:
                continue
            key = phrase.lower()
            if key in seen:
                continue
            seen.add(key)
            hints.append({
                "kind": kind,
                "phrase": phrase,
                "snippet": _ksa_snippet(text, m.start(), m.end()),
                "prep_pointer": (
                    f"Expect an assessment question on '{phrase}'. In your "
                    "resume and questionnaire answers, cite a concrete "
                    "example (what you did, scale, outcome) - 'expert' "
                    "ratings need evidence."),
            })
            if len(hints) >= limit:
                return hints
    return hints


# ---------------------------------------------------------------------------
# 3. Federal announcement scoring
# ---------------------------------------------------------------------------

def _profile_text(profile: dict) -> str:
    return _match.json_text(profile).lower() if _match else str(profile).lower()


def _profile_skill_set(profile: dict) -> set[str]:
    return set(profile.get("skills", []) or [])


def _specialized_section(text: str) -> str:
    """Pull the 'Specialized Experience' paragraph(s) from an announcement."""
    m = re.search(r"specialized\s+experience[:\s]*(.+?)(?:\n\s*\n|\Z)",
                  text, re.I | re.S)
    return m.group(1).strip() if m else ""


def _spec_terms(text: str) -> dict[str, dict]:
    """Specialized-experience terms: match.py extraction or a plain fallback."""
    if _extract_jd is not None:
        try:
            return _extract_jd(text)["items"]
        except Exception:
            pass
    # fallback: lexicon hits + quoted phrases
    items: dict[str, dict] = {}
    low = text.lower()
    for canonical, aliases in C.SKILL_LEXICON.items():
        for a in aliases:
            mm = C.skill_regex(a).search(low)
            if mm:
                items[canonical] = {"tier": "must", "weight": 1.0,
                                    "evidence": "", "aliases": list(aliases)}
                break
    for qm in re.finditer(r'"([^"\n]{2,60})"', text):
        items.setdefault(qm.group(1).lower(),
                         {"tier": "must", "weight": 1.0,
                          "evidence": "", "aliases": None})
    return items


def _score_specialized(profile: dict, text: str) -> tuple[float, dict]:
    """0-35 based on specialized-experience language present in the profile."""
    spec = _specialized_section(text) or text[:4000]
    items = _spec_terms(spec)
    if not items:
        return 17.5, {"note": "No specialized-experience signals found - "
                              "scored neutrally.", "matched": [], "missing": []}
    pskills = _profile_skill_set(profile)
    prof_text = _profile_text(profile)

    def _hit(name: str, info: dict) -> bool:
        if info.get("aliases") is not None:
            return name in pskills
        return re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])",
                         prof_text) is not None

    matched = [n for n, i in items.items() if _hit(n, i)]
    denom = sum(i["weight"] for i in items.values())
    numer = sum(i["weight"] for n, i in items.items() if n in matched)
    score = round(35 * numer / denom, 1) if denom else 17.5
    return score, {"matched": sorted(matched),
                   "missing": sorted(set(items) - set(matched)),
                   "note": f"{len(matched)}/{len(items)} specialized-experience "
                           f"terms present in your profile."}


def _series_fit_score(profile: dict, text: str,
                      announcement: dict) -> tuple[float, dict]:
    """0-25 based on occupational series fit."""
    series = _announcement_series(text, announcement)
    kws = _keywords_for_series(series)
    if kws is None:
        kws = _SERIES_KEYWORDS.get(series, set())
    prof_text = _profile_text(profile)
    pskills = _profile_skill_set(profile)
    domains = set(profile.get("domains", []) or [])
    if not kws:
        return 12.5, {"note": "No series identified - scored neutrally. "
                              "Check the series fits your background.",
                      "series": series or "unknown"}
    hits = {k for k in kws
            if k in prof_text or k in pskills or k in " ".join(domains)}
    score = round(25 * len(hits) / len(kws), 1)
    detail = {"series": series, "series_keywords": sorted(kws),
              "hits": sorted(hits),
              "note": f"Series {series}: {len(hits)}/{len(kws)} keyword hits."}
    return score, detail


_GRADE_RE = re.compile(
    r"\bGS[-\s]?(\d{1,2})(?:\s*(?:/|-|to)\s*(?:GS[-\s]?)?(\d{1,2}))?", re.I)


def _parse_grade_band(text: str, announcement: dict) -> tuple[int, int] | None:
    src = str(announcement.get("grade", "") or "") + " " + (text or "")[:2000]
    m = _GRADE_RE.search(src)
    if not m:
        return None
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) else lo
    if not (1 <= lo <= 15 and 1 <= hi <= 15):
        return None
    return (min(lo, hi), max(lo, hi))


def _estimate_gs_band(profile: dict) -> tuple[int, int]:
    """Heuristic GS band for the user's experience level.

    Uses candid.federal's ``translate_to_gs`` (title + years -> grade band)
    when available; falls back to a years/seniority heuristic otherwise.
    Always a rough estimate for self-assessment, never an HR determination.
    """
    exp = profile.get("experience") or []
    title = (exp[0].get("title", "") if exp else "") or profile.get("headline", "")
    years = float(profile.get("years_experience") or 0)
    try:
        from candid import federal as _fed
        r = _fed.translate_to_gs(title, years)
        return (int(r["grade_low"]), int(r["grade_high"]))
    except Exception:
        pass
    seniority = (profile.get("seniority") or "mid").lower()
    boost = {"senior": 1, "lead": 2, "staff": 3, "principal": 3}.get(seniority, 0)
    if years < 1:
        base = 5
    elif years < 3:
        base = 7
    elif years < 5:
        base = 9
    elif years < 8:
        base = 11
    elif years < 13:
        base = 12
    else:
        base = 13
    base = min(14, base + boost)
    return (base, min(15, base + 1))


def _grade_fit_score(profile: dict, text: str,
                     announcement: dict) -> tuple[float, dict]:
    """0-25: does the announcement's grade band meet the user's band?"""
    band = _parse_grade_band(text, announcement)
    mine = _estimate_gs_band(profile)
    if band is None:
        return 12.5, {"note": "No GS grade found in the announcement - "
                              "scored neutrally.", "your_band": mine,
                      "announcement_band": None}
    lo, hi = band
    mlo, mhi = mine
    if hi >= mlo and lo <= mhi:
        score, note = 25.0, (f"Grade band GS-{lo}/GS-{hi} overlaps your "
                             f"estimated GS-{mlo}/GS-{mhi}.")
    else:
        gap = mlo - hi if hi < mlo else lo - mhi
        if gap <= 0:
            score, note = 25.0, "Grade band overlaps."
        elif gap == 1:
            score, note = 15.0, (f"GS-{lo}/GS-{hi} is one grade off your "
                                 f"estimated GS-{mlo}/GS-{mhi} - adjacent, "
                                 "worth a look.")
        elif gap == 2:
            score, note = 8.0, (f"GS-{lo}/GS-{hi} is two grades from your "
                                f"estimated GS-{mlo}/GS-{mhi}.")
        else:
            score, note = 4.0, (f"GS-{lo}/GS-{hi} is well outside your "
                                f"estimated GS-{mlo}/GS-{mhi}.")
    return score, {"announcement_band": band, "your_band": mine, "note": note,
                   "estimate_caveat": "Your band is a heuristic from years + "
                                      "seniority, not an HR qualification "
                                      "determination."}


def _location_fit_score(profile: dict, text: str,
                        announcement: dict) -> tuple[float, dict]:
    """0-15 on location / remote fit."""
    remote = bool(announcement.get("remote")) or bool(
        re.search(r"\bremote\b|\btelework\b|\bvirtual\b", (text or "")[:1500], re.I))
    loc = (announcement.get("location") or "").strip()
    prof_loc = (profile.get("location") or "").strip()
    if remote:
        return 15.0, {"note": "Announcement is remote/telework eligible.",
                      "announcement_location": loc or "remote",
                      "your_location": prof_loc or "unknown"}
    if not loc:
        return 7.5, {"note": "No location in the announcement - scored "
                             "neutrally.", "your_location": prof_loc or "unknown"}
    if not prof_loc:
        return 7.5, {"note": f"Announcement is in {loc}; your location is "
                             "unknown - scored neutrally."}
    # city/state token overlap
    def toks(s: str) -> set[str]:
        return {t for t in re.sub(r"[^a-z ]", " ", s.lower()).split()
                if len(t) > 2}
    if toks(loc) & toks(prof_loc):
        return 15.0, {"note": f"Location match: {loc}.",
                      "announcement_location": loc,
                      "your_location": prof_loc}
    return 8.0, {"note": f"Announcement is in {loc}; you are in {prof_loc} - "
                         "relocation or commuting would be needed.",
                 "announcement_location": loc, "your_location": prof_loc}


def score_federal(profile: dict, announcement: str | dict) -> dict:
    """Score a federal announcement against the profile (0-100).

    Weights: specialized-experience language 35, series fit 25, grade-band
    fit 25, location/remote 15. Returns score, verdict, gaps, and a
    breakdown - the same shape of result as candid.match.score_match.
    """
    if isinstance(announcement, str):
        announcement = {"text": announcement}
    text = announcement.get("text", "") or ""

    spec_score, spec_d = _score_specialized(profile, text)
    series_score, series_d = _series_fit_score(profile, text, announcement)
    grade_score, grade_d = _grade_fit_score(profile, text, announcement)
    loc_score, loc_d = _location_fit_score(profile, text, announcement)

    total = round(spec_score + series_score + grade_score + loc_score, 1)
    if total >= C.SCORE_STRONG_GO:
        verdict, reason = "GO", "Strong federal fit - tailor and apply."
    elif total >= C.SCORE_CONDITIONAL_GO:
        verdict, reason = ("CONDITIONAL",
                           "Workable fit - check the grade band and close "
                           "the specialized-experience gaps.")
    else:
        verdict, reason = ("NO-GO",
                           "Weak fit - series, grade, or experience language "
                           "does not line up.")

    gaps: list[str] = []
    for term in spec_d.get("missing", [])[:8]:
        gaps.append(f"Specialized-experience term not in your profile: {term}")
    if series_d.get("series") not in (None, "", "unknown") and series_score < 12.5:
        gaps.append(f"Series {series_d['series']} keyword overlap is low - "
                    "confirm this series matches your background.")
    ab = grade_d.get("announcement_band")
    if ab and grade_score < 12.5:
        gaps.append(f"Grade band GS-{ab[0]}/GS-{ab[1]} vs your estimated "
                    f"GS-{grade_d['your_band'][0]}/GS-{grade_d['your_band'][1]}.")
    if loc_score < 12.5 and loc_d.get("announcement_location"):
        gaps.append(f"Location: {loc_d['note']}")

    return {
        "score": total,
        "verdict": verdict,
        "verdict_reason": reason,
        "breakdown": {
            "specialized_experience": spec_score,
            "series_fit": series_score,
            "grade_band_fit": grade_score,
            "location": loc_score,
        },
        "specialized_experience_detail": spec_d,
        "series_detail": series_d,
        "grade_detail": grade_d,
        "location_detail": loc_d,
        "ksa_hints": ksa_hints(text),
        "gaps": gaps,
    }


def render_federal_report(result: dict) -> str:
    """Human-readable federal announcement score report."""
    b = result["breakdown"]
    gd = result.get("grade_detail", {})
    lines = [
        f"Federal match score: {result['score']}/100 - {result['verdict']}",
        result["verdict_reason"],
        "",
        f"  Specialized exp  {b['specialized_experience']:>5}/35",
        f"  Series fit       {b['series_fit']:>5}/25   "
        f"{result.get('series_detail', {}).get('note', '')}",
        f"  Grade band       {b['grade_band_fit']:>5}/25   "
        f"{gd.get('note', '')}",
        f"  Location         {b['location']:>5}/15   "
        f"{result.get('location_detail', {}).get('note', '')}",
        "",
    ]
    spec_d = result.get("specialized_experience_detail", {})
    if spec_d.get("matched"):
        lines.append("Specialized-experience terms you cover: "
                     + ", ".join(spec_d["matched"][:10]))
    if result.get("ksa_hints"):
        lines += ["", "Likely assessment (KSA) themes:"]
        for h in result["ksa_hints"][:6]:
            lines.append(f"  - [{h['kind']}] {h['phrase']}")
    if result["gaps"]:
        lines += ["", "Gaps to close:"] + [f"  * {g}" for g in result["gaps"]]
    lines.append("")
    lines.append(gd.get("estimate_caveat", ""))
    return "\n".join(lines)
