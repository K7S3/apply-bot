"""USAJOBS / federal hiring helpers: GS-level translation, occupation-series
matching, and an eligibility checklist.

Everything here is local, offline, and stdlib-only. All numbers are
public-domain *rules of thumb* for self-assessment only — OPM and the
hiring agency's HR office make the official qualification determination
for every posting. Never treat these estimates as official.
"""

from __future__ import annotations

import re

from candid import config as C

# Must appear in every translate_to_gs / translate_from_gs output.
ESTIMATE_CAVEAT = (
    "This is a rough estimate for self-assessment only, not an official "
    "determination. OPM and the hiring agency's HR office make the official "
    "grade/qualification call for each posting."
)

# ---------------------------------------------------------------------------
# 1. GS-level translator (private sector -> federal)
# ---------------------------------------------------------------------------

# Rule of thumb: years of specialized experience -> GS grade, using the
# OPM pattern where each grade from GS-5 up through GS-12 is roughly one
# year of progressively higher-level (specialized) experience beyond the
# bachelor's degree. GS-13/14/15 require increasingly senior, supervisory
# or expert-level experience.
#
# grade: minimum typical years of specialized experience
_EXPERIENCE_TO_GRADE = [
    (0, 5),
    (1, 7),
    (2, 9),
    (3, 11),
    (4, 12),
    (5, 13),
    (8, 14),
    (12, 15),
]

# Title keywords -> seniority rank (reuses the shared mapping in config.py).
# grade band per rank: entry/inter-ish -> GS-5..7, mid -> GS-9..11,
# senior -> GS-11..12, lead -> GS-12..13, staff -> GS-13..14,
# principal -> GS-14..15, director+ -> GS-14..15.
_RANK_TO_GRADE_BAND: dict[int, tuple[int, int]] = {
    0: (5, 7),    # intern / new grad
    1: (7, 9),    # junior
    2: (9, 11),   # associate / mid
    3: (11, 12),  # senior
    4: (12, 13),  # lead
    5: (13, 14),  # staff
    6: (14, 15),  # principal
    7: (14, 15),  # director
    8: (15, 15),  # vp+
}


def _grade_for_experience(years: float) -> int:
    """Lowest typical GS grade for the given years of specialized experience."""
    grade = 5
    for min_years, g in _EXPERIENCE_TO_GRADE:
        if years >= min_years:
            grade = g
    return grade


def _title_rank(title: str) -> int | None:
    t = (title or "").lower()
    best: int | None = None
    for kw, rank in C.SENIORITY_KEYWORDS.items():
        if kw in t:
            best = rank if best is None else max(best, rank)
    return best


def _has_phd(title: str) -> bool:
    return bool(re.search(r"\b(ph\.?d\.?|doctorate|dr\.?)\b", (title or "").lower()))


def translate_to_gs(title: str, years_experience: float,
                    current_salary: float | None = None) -> dict:
    """Estimate a GS grade band from a private-sector title + experience.

    Returns {grade_low, grade_high, rationale, caveats}. Every output
    carries the "rough estimate" caveat in ``caveats``.
    """
    if years_experience is None or years_experience < 0:
        raise ValueError("years_experience must be a non-negative number.")

    rationale: list[str] = []
    caveats: list[str] = [ESTIMATE_CAVEAT]

    exp_grade = _grade_for_experience(years_experience)
    rationale.append(
        f"~{years_experience:g} year(s) of specialized experience maps to "
        f"roughly GS-{exp_grade} under the OPM 'one year per grade' pattern "
        f"(GS-5 through GS-12), with senior grades needing supervisory or "
        f"expert-level work."
    )

    rank = _title_rank(title or "")
    if rank is not None:
        band = _RANK_TO_GRADE_BAND[rank]
        label = C.SENIORITY_LABELS.get(rank, "")
        rationale.append(
            f"Title '{title}' reads as {label} level, typically seen in the "
            f"GS-{band[0]} to GS-{band[1]} range for comparable federal roles."
        )
    else:
        # No seniority signal in the title: fall back to a mid-range guess
        # centered on the experience-based grade.
        band = (max(5, exp_grade - 1), min(15, exp_grade + 1))
        rationale.append(
            f"No seniority keyword found in '{title}'; centering the band on "
            f"the experience-based grade."
        )

    grade_low = min(exp_grade, band[0])
    grade_high = max(exp_grade, band[1])

    # PhD floors roughly at GS-11 per OPM qualification standards.
    if _has_phd(title or ""):
        rationale.append(
            "A doctorate (PhD) typically qualifies for GS-11 even with little "
            "additional experience."
        )
        grade_low = max(grade_low, 11)
        grade_high = max(grade_high, 11)

    grade_low = max(5, min(15, grade_low))
    grade_high = max(grade_low, min(15, grade_high))

    if current_salary:
        rationale.append(
            f"Current salary ${current_salary:,.0f}/yr doesn't map directly "
            f"to a grade: federal pay includes locality adjustments and steps, "
            f"so use it only to sanity-check which locality tables to compare."
        )

    caveats.append(
        "Grade also depends on degree field, specialized-experience match to "
        "the specific posting, and (for GS-13+) supervisory or expert "
        "credentials — all judged by HR against the vacancy announcement."
    )
    caveats.append(
        "Many postings are capped (e.g. 'GS-11/12/13 ladder' or 'GS-13 only'); "
        "the announcement's listed grades are what you can actually apply to."
    )

    return {
        "grade_low": grade_low,
        "grade_high": grade_high,
        "rationale": rationale,
        "caveats": caveats,
    }


# ---------------------------------------------------------------------------
# 1b. GS -> private sector (reverse translator)
# ---------------------------------------------------------------------------

# Approximate *base pay* bands (no locality), rounded to 2025-26 dollars.
# Wide and clearly approximate — actual pay tables are published by OPM.
_GS_PROFILE: dict[int, dict] = {
    5:  {"base_low": 35_000, "base_high": 46_000,
         "private_titles": ["Junior / Associate", "entry-level analyst"]},
    6:  {"base_low": 39_000, "base_high": 51_000,
         "private_titles": ["Associate", "early-career analyst"]},
    7:  {"base_low": 43_000, "base_high": 56_000,
         "private_titles": ["Associate", "early-career engineer/scientist"]},
    8:  {"base_low": 48_000, "base_high": 62_000,
         "private_titles": ["Mid-level associate", "engineer I/II"]},
    9:  {"base_low": 52_000, "base_high": 68_000,
         "private_titles": ["Mid-level engineer/scientist", "analyst II"]},
    10: {"base_low": 58_000, "base_high": 75_000,
         "private_titles": ["Mid-level engineer/scientist", "senior analyst"]},
    11: {"base_low": 63_000, "base_high": 82_000,
         "private_titles": ["Senior engineer/scientist/analyst", "team lead (non-manager)"]},
    12: {"base_low": 75_000, "base_high": 98_000,
         "private_titles": ["Senior engineer/scientist", "tech lead"]},
    13: {"base_low": 89_000, "base_high": 116_000,
         "private_titles": ["Staff-level IC", "engineering manager (small team)"]},
    14: {"base_low": 106_000, "base_high": 138_000,
         "private_titles": ["Senior staff / principal IC", "senior manager", "director (small org)"]},
    15: {"base_low": 125_000, "base_high": 159_000,
         "private_titles": ["Principal / distinguished IC", "director", "senior director"]},
}


def translate_from_gs(grade: str | int, step: int | None = None) -> dict:
    """Approximate private-sector equivalent for a GS grade (+ optional step).

    ``grade`` may be like "GS-12", "gs12", or 12. Steps 1-10 within a grade
    run low->high across the band. Returns {grade, step, base_pay_band,
    private_sector_titles, caveats}.
    """
    raw = str(grade).strip().upper().replace("GS", "").replace("-", "").strip()
    try:
        g = int(raw)
    except ValueError:
        raise ValueError(f"Cannot parse GS grade from {grade!r}.")
    if g not in _GS_PROFILE:
        raise ValueError(f"GS grade must be 5-15, got GS-{g}.")

    prof = _GS_PROFILE[g]
    low, high = prof["base_low"], prof["base_high"]
    note = None
    if step is not None:
        if not 1 <= step <= 10:
            raise ValueError(f"GS step must be 1-10, got {step}.")
        # interpolate within the band
        frac = (step - 1) / 9
        point = low + (high - low) * frac
        note = (f"Step {step}/10 sits roughly ${point:,.0f}/yr within the "
                f"GS-{g} base band.")
    else:
        note = f"Full GS-{g} base band shown; steps 1-10 run low to high."

    return {
        "grade": f"GS-{g}",
        "step": step,
        "base_pay_band": {"low": low, "high": high, "currency": "USD"},
        "base_pay_note": note,
        "private_sector_titles": list(prof["private_titles"]),
        "caveats": [
            ESTIMATE_CAVEAT,
            "Bands are approximate *base* pay (2025-26 dollars, rounded). "
            "Actual federal pay adds locality adjustments (often 20-40%+) "
            "and step increases — check OPM's published tables for exact figures.",
            "Private-sector total comp (equity, bonuses) usually runs well "
            "above these base bands; this is an order-of-magnitude "
            "comparison, not a salary prediction.",
        ],
    }


# ---------------------------------------------------------------------------
# 2. Occupation series matcher
# ---------------------------------------------------------------------------

# Bundled table of federal occupation series relevant to knowledge workers.
# Each entry: OPM series code, title, typical degree/experience bar, keywords.
SERIES: list[dict] = [
    {
        "code": "2210",
        "title": "Information Technology Management",
        "requirements": (
            "Bachelor's (often IT/CS) or equivalent experience; hands-on "
            "experience in systems administration, networking, cybersecurity, "
            "software development, or IT project management."
        ),
        "keywords": [
            "software", "python", "java", "javascript", "typescript", "react",
            "devops", "cloud", "aws", "azure", "gcp", "kubernetes", "docker",
            "cybersecurity", "network", "linux", "database", "sql",
            "it support", "system administration", "agile", "scrum",
            "product management", "data engineering",
        ],
    },
    {
        "code": "1550",
        "title": "Computer Science",
        "requirements": (
            "Bachelor's in computer science (or 30 semester hours of CS/math "
            "coursework) typical; professional software development, "
            "algorithms, or research experience."
        ),
        "keywords": [
            "computer science", "algorithms", "software development",
            "machine learning", "deep learning", "artificial intelligence",
            "python", "java", "c++", "research", "data structures",
            "distributed systems", "operating systems",
        ],
        # slightly more education-weighted series
        "keyword_weight": 1.0,
    },
    {
        "code": "0801",
        "title": "General Engineering",
        "requirements": (
            "Bachelor's in engineering (ABET-accredited) or equivalent "
            "professional engineering experience; PE license a plus."
        ),
        "keywords": [
            "engineering", "design", "systems engineering", "mechanical",
            "electrical", "civil", "testing", "prototyping", "cad",
            "requirements", "validation", "matlab",
        ],
    },
    {
        "code": "0854",
        "title": "Computer Engineering",
        "requirements": (
            "Bachelor's in computer/electrical engineering or equivalent; "
            "hardware-software integration, embedded systems experience."
        ),
        "keywords": [
            "computer engineering", "embedded", "firmware", "fpga",
            "hardware", "verilog", "vhdl", "microcontroller", "c",
            "electronics", "robotics", "iot",
        ],
    },
    {
        "code": "0861",
        "title": "Aerospace Engineering",
        "requirements": (
            "Bachelor's in aerospace/mechanical engineering or equivalent; "
            "flight systems, propulsion, aerodynamics experience."
        ),
        "keywords": [
            "aerospace", "aerodynamics", "propulsion", "flight",
            "satellite", "spacecraft", "avionics", "orbital", "rockets",
            "cfd", "structures",
        ],
    },
    {
        "code": "1515",
        "title": "Operations Research",
        "requirements": (
            "Bachelor's in operations research, math, CS, or a related "
            "quantitative field (often 24+ semester hours of math/stats); "
            "modeling, optimization, simulation experience."
        ),
        "keywords": [
            "operations research", "optimization", "linear programming",
            "simulation", "modeling", "decision science", "analytics",
            "supply chain", "logistics", "scheduling", "stochastic",
        ],
    },
    {
        "code": "1529",
        "title": "Mathematical Statistics",
        "requirements": (
            "Bachelor's in math/statistics (often 24+ semester hours of "
            "math/statistics including calculus); statistical analysis, "
            "experimental design, survey sampling experience."
        ),
        "keywords": [
            "statistics", "statistical", "hypothesis testing", "regression",
            "bayesian", "experimental design", "a/b testing", "sampling",
            "econometrics", "biostatistics", "r programming",
        ],
    },
    {
        "code": "0343",
        "title": "Management and Program Analysis",
        "requirements": (
            "Bachelor's in any field (business/public admin common) plus "
            "analytical experience; program evaluation, process improvement, "
            "policy analysis background."
        ),
        "keywords": [
            "program management", "policy analysis", "process improvement",
            "business analysis", "stakeholder", "strategic planning",
            "evaluation", "metrics", "kpi", "operations", "budget",
            "consulting", "change management",
        ],
    },
    {
        "code": "1102",
        "title": "Contracting",
        "requirements": (
            "Bachelor's (business/law common) plus 24 semester hours in "
            "business disciplines typical; procurement, negotiation, "
            "contract administration experience."
        ),
        "keywords": [
            "procurement", "contracts", "contracting", "negotiation",
            "vendor", "acquisition", "far", "sourcing", "rfp", "compliance",
            "supplier",
        ],
    },
    {
        "code": "0301",
        "title": "Miscellaneous Administration and Program",
        "requirements": (
            "Bachelor's in any field plus administrative/program experience; "
            "generalist series used when no specialized series fits."
        ),
        "keywords": [
            "administration", "program support", "coordination", "outreach",
            "communications", "writing", "project coordination", "hr",
            "training", "grants",
        ],
    },
]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+ ]", " ", (s or "").lower())


def match_series(profile_skills: list[str], top_n: int = 5) -> list[dict]:
    """Rank federal occupation series by keyword overlap with profile skills.

    ``profile_skills``: list of skill strings (e.g. from candid profile).
    Returns top_n dicts {code, title, score, why, requirements}.
    """
    if not profile_skills:
        raise ValueError("profile_skills must be a non-empty list of skill strings.")
    tokens: set[str] = set()
    for skill in profile_skills:
        tokens.update(_norm(skill).split())

    scored: list[dict] = []
    for s in SERIES:
        hits: list[str] = []
        for kw in s["keywords"]:
            kw_tokens = set(_norm(kw).split())
            if kw_tokens and kw_tokens & tokens:
                hits.append(kw)
        weight = s.get("keyword_weight", 1.0)
        score = round(len(hits) * weight, 2)
        scored.append({
            "code": s["code"],
            "title": s["title"],
            "score": score,
            "why": (
                [f"Skill overlap on: {', '.join(sorted(hits))}"]
                if hits else ["No direct keyword overlap — generalist fit only."]
            ),
            "requirements": s["requirements"],
        })

    scored.sort(key=lambda x: (-x["score"], x["code"]))
    return scored[:max(1, top_n)]


def render_series_matches(matches: list[dict]) -> str:
    """Render match_series output as plain text."""
    lines = ["Federal occupation series matches (keyword overlap):"]
    for m in matches:
        lines.append(f"  • {m['code']} {m['title']} (score {m['score']})")
        for w in m["why"]:
            lines.append(f"      {w}")
    lines.append("")
    lines.append(ESTIMATE_CAVEAT)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Federal eligibility checklist
# ---------------------------------------------------------------------------

# Accepted value sets. Anything else -> treated as "unknown" -> action item.
CITIZENSHIP_VALUES = {"us_citizen", "us_national", "permanent_resident",
                      "other", "unknown"}
VETERAN_VALUES = {"veteran", "disabled_veteran", "active_duty",
                  "none", "unknown"}
CLEARANCE_VALUES = {"active", "expired", "none", "unknown"}


def _norm_fact(value, allowed: set[str]) -> str:
    v = str(value or "unknown").strip().lower()
    return v if v in allowed else "unknown"


def eligibility_checklist(user_facts: dict) -> dict:
    """Build a federal-job eligibility checklist from explicitly provided facts.

    ``user_facts`` keys (all optional, no assumptions made):
        citizenship:      "us_citizen" | "us_national" | "permanent_resident"
                          | "other" | "unknown"
        veteran_status:   "veteran" | "disabled_veteran" | "active_duty"
                          | "none" | "unknown"
        clearance:        "active" | "expired" | "none" | "unknown"
        federal_employee: True | False | "unknown" (current fed employee?)
    Returns {items: [{item, status, note}]}, status in ok/info/action.
    Unknown facts always become "action: confirm" items — never assumed.
    """
    if not isinstance(user_facts, dict):
        raise ValueError("user_facts must be a dict.")

    citizenship = _norm_fact(user_facts.get("citizenship"), CITIZENSHIP_VALUES)
    veteran = _norm_fact(user_facts.get("veteran_status"), VETERAN_VALUES)
    clearance = _norm_fact(user_facts.get("clearance"), CLEARANCE_VALUES)
    fed_emp_raw = user_facts.get("federal_employee", "unknown")
    if isinstance(fed_emp_raw, bool):
        federal_employee = fed_emp_raw
    elif str(fed_emp_raw).strip().lower() in {"true", "yes"}:
        federal_employee = True
    elif str(fed_emp_raw).strip().lower() in {"false", "no"}:
        federal_employee = False
    else:
        federal_employee = "unknown"

    items: list[dict] = []

    # --- citizenship ---
    if citizenship in {"us_citizen", "us_national"}:
        items.append({
            "item": "US citizenship",
            "status": "ok",
            "note": "Meets the citizenship requirement most competitive federal "
                    "postings carry.",
        })
    elif citizenship == "permanent_resident":
        items.append({
            "item": "US citizenship",
            "status": "info",
            "note": "Many (not all) postings require citizenship or national status; "
                    "filter USAJOBS for postings open to non-citizens or check the "
                    "'Who may apply' section.",
        })
    elif citizenship == "other":
        items.append({
            "item": "US citizenship",
            "status": "action",
            "note": "Most competitive postings require US citizenship/national status. "
                    "Confirm your work authorization matches each posting's "
                    "'Requirements' section.",
        })
    else:
        items.append({
            "item": "US citizenship",
            "status": "action",
            "note": "Not provided — confirm your citizenship status; most postings "
                    "require US citizenship or national status.",
        })

    # --- veterans' preference (never assumed) ---
    if veteran in {"veteran", "disabled_veteran", "active_duty"}:
        items.append({
            "item": "Veterans' preference",
            "status": "info",
            "note": "You declared veteran status — claim preference on the "
                    "application if the posting allows it, and have your DD-214 "
                    "(and VA letter if disabled) ready to upload.",
        })
    elif veteran == "none":
        items.append({
            "item": "Veterans' preference",
            "status": "info",
            "note": "No preference claimed — noted per your input; no documents needed.",
        })
    else:
        items.append({
            "item": "Veterans' preference",
            "status": "action",
            "note": "Not provided — confirm whether you hold veterans' preference "
                    "(never assumed). If yes, prepare DD-214 / VA documentation.",
        })

    # --- clearance ---
    if clearance == "active":
        items.append({
            "item": "Security clearance",
            "status": "ok",
            "note": "Active clearance is a plus for cleared postings — keep the "
                    "level/agency handy for the application.",
        })
    elif clearance == "expired":
        items.append({
            "item": "Security clearance",
            "status": "info",
            "note": "Expired clearance: some agencies can reinstate within ~24 months; "
                    "otherwise expect a fresh investigation for cleared roles.",
        })
    elif clearance == "none":
        items.append({
            "item": "Security clearance",
            "status": "info",
            "note": "No clearance needed for most uncleared postings; cleared roles "
                    "will sponsor the investigation (takes months).",
        })
    else:
        items.append({
            "item": "Security clearance",
            "status": "action",
            "note": "Not provided — confirm whether you hold an active clearance "
                    "and its level; it only matters for cleared postings.",
        })

    # --- hiring path: open to public vs merit promotion ---
    if federal_employee is True:
        items.append({
            "item": "Hiring path",
            "status": "ok",
            "note": "As a current federal employee you may also apply to "
                    "merit-promotion (internal) announcements, not just "
                    "'open to the public' ones.",
        })
    elif federal_employee is False:
        items.append({
            "item": "Hiring path",
            "status": "info",
            "note": "Apply to announcements marked 'open to the public'. "
                    "Merit-promotion postings are for current feds only.",
        })
    else:
        items.append({
            "item": "Hiring path",
            "status": "action",
            "note": "Not provided — confirm whether you are a current federal "
                    "employee; it decides if merit-promotion announcements are open to you.",
        })

    # --- always-applicable heads-ups ---
    items.append({
        "item": "Federal resume format",
        "status": "info",
        "note": "USAJOBS expects a detailed federal resume (duties, hours/week, "
                "supervisor info, month/year dates) — a 1-page private-sector "
                "resume is usually not enough. Use the USAJOBS resume builder.",
    })
    items.append({
        "item": "Questionnaire / assessments",
        "status": "info",
        "note": "Expect an occupational questionnaire after applying; some series "
                "add proctored assessments. Answer carefully — self-ratings are "
                "scored and verified against your resume.",
    })
    items.append({
        "item": "Selective factors",
        "status": "info",
        "note": "Check each announcement's 'Qualifications' and selective/quality "
                "ranking factors — these decide referrals more than raw grade fit.",
    })

    return {"items": items}


def render_eligibility(result: dict) -> str:
    """Render eligibility_checklist output as plain text."""
    lines = ["Federal eligibility checklist:"]
    for it in result["items"]:
        lines.append(f"  [{it['status'].upper()}] {it['item']}: {it['note']}")
    return "\n".join(lines)
