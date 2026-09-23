"""Generic onboarding: ingest a resume (pdf/md/txt) and/or LinkedIn export text
into a structured user profile.

The profile is plain JSON stored at candid_data/profile.json (git-ignored).
Every downstream feature (match, tailor, prep, negotiate, ...) reads from
this profile — nothing is ever hardcoded.

Profile schema:
{
  "name": str,
  "headline": str,
  "location": str,
  "summary": str,
  "skills": [str, ...],            # canonical skill names (see config.SKILL_LEXICON)
  "experience": [                  # most recent first
    {"title": str, "company": str, "dates": str, "bullets": [str, ...]}
  ],
  "education": [{"school": str, "degree": str, "dates": str}],
  "years_experience": float,
  "seniority": str,                # entry|junior|mid|senior|lead|staff|...
  "source_files": [str, ...],
}
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from candid import config as C

SECTION_HEADERS = [
    "experience", "work experience", "employment", "professional experience",
    "education", "skills", "technical skills", "core skills",
    "projects", "summary", "objective", "profile",
]


class OnboardError(Exception):
    """Raised when a resume/LinkedIn file cannot be read or parsed."""


# ---------------------------------------------------------------------------
# text extraction
# ---------------------------------------------------------------------------

def _read_txt_md(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # noqa: F401
        except ImportError as exc:
            raise OnboardError(
                "Reading PDFs needs the 'pypdf' package. Install it with:\n"
                "    pip install pypdf\n"
                "Or export your resume as .txt / .md instead."
            ) from exc
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n".join(parts).strip()
    if len(text) < 50:
        raise OnboardError(
            f"Could not extract text from {path} "
            "(it may be a scanned image PDF — export as text instead)."
        )
    return text


def read_document(path: str | Path) -> str:
    """Read a resume/LinkedIn file (.pdf, .md, .txt) into plain text."""
    p = Path(path)
    if not p.exists():
        raise OnboardError(f"File not found: {p}")
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(p)
    if suffix in (".md", ".txt", ".text", ""):
        text = _read_txt_md(p)
        if len(text.strip()) < 20:
            raise OnboardError(f"{p} looks empty — nothing to parse.")
        return text
    raise OnboardError(
        f"Unsupported file type '{suffix}' for {p}. Use .pdf, .md, or .txt."
    )


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def _split_sections(text: str) -> dict[str, list[str]]:
    """Split resume text into sections keyed by normalized header."""
    sections: dict[str, list[str]] = {"_head": []}
    current = "_head"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        # strip markdown heading marks so "## Experience" matches
        low = re.sub(r"^#+\s*", "", line).lower().strip(":")
        if low in SECTION_HEADERS and len(line) < 40:
            current = low
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(raw_line.rstrip())
    return sections


def _clean_lines(lines: list[str]) -> list[str]:
    return [l.strip(" •·-*").strip() for l in (x.strip() for x in lines) if l.strip()]


def _parse_name(head_lines: list[str]) -> str:
    for line in head_lines[:6]:
        line = line.strip()
        if not line or "@" in line or re.search(r"\d{3}[-.\s]\d{3}[-.\s]\d{4}", line):
            continue
        if len(line.split()) <= 5 and len(line) < 60:
            return line
    return ""


def _extract_skills(text: str) -> list[str]:
    found: list[str] = []
    low = text.lower()
    for canonical, aliases in C.SKILL_LEXICON.items():
        for alias in aliases:
            if C.skill_regex(alias).search(low):
                found.append(canonical)
                break
    return sorted(set(found))


_DATE_RE = re.compile(
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{4}|\d{4})\s*[–—\-to]+\s*((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{4}|\d{4}|present|current|now)",
    re.I,
)

_BULLET_MARK = re.compile(r"^[•·▪◦▪\-\*\+–—>]\s*")
_LOCATION_LINE_RE = re.compile(
    r"^[A-Z][A-Za-z .'\-]+,\s*(?:[A-Z]{2}|[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)"
    r"(?:\s*,\s*(?:United States|USA|India|Canada|UK|Remote))?$"
)
_EMPLOYMENT_TYPE_RE = re.compile(
    r"\s*[·•|]\s*(Full-time|Part-time|Contract|Contractor|Internship|"
    r"Self-employed|Freelance|Temporary)\s*$",
    re.I,
)


def _strip_location(line: str) -> str:
    """Strip location suffixes from a title/company line.

    Handles both 'Meridian Financial · New York, NY' and
    'New York, NY' location lines on their own (returns "" for those).
    """
    s = line.strip()
    if _LOCATION_LINE_RE.match(s):
        return ""
    # 'Company · City, ST' → keep the company part
    if "·" in s:
        first = s.split("·")[0].strip()
        if first:
            return first
    return s


def _clean_company_name(company: str) -> str:
    company = _EMPLOYMENT_TYPE_RE.sub("", company).strip()
    company = _strip_location(company)
    # 'Acme Corp, New York, NY' → 'Acme Corp'
    company = re.split(r",\s*(?=[A-Z][a-z])", company)[0].strip()
    return company


def _looks_like_header_line(line: str) -> bool:
    """Could this line be a title or company line (multi-line header block)?"""
    if len(line) > 90 or len(line) < 2:
        return False
    if _BULLET_MARK.match(line) or re.match(r"^\d{1,2}[.)]\s+", line):
        return False
    if "@" in line or re.search(r"\d{3}[-.\s]\d{3}[-.\s]\d{4}", line):
        return False
    if _LOCATION_LINE_RE.match(line):
        return False
    return True


def _parse_experience(lines: list[str]) -> list[dict]:
    """Parse experience bullets into {title, company, dates, bullets} entries.

    Handles three header shapes:
      1. single-line: 'Title — Company, Jan 2020 - Present'
      2. 'Title at Company, Jan 2020 - Present' (LinkedIn PDF text)
      3. multi-line (LinkedIn export style):
             Title
             Company · Full-time
             Jan 2020 - Present · 4 yrs

    Two passes: first find every date line (an entry starts there), scanning
    up to two lines back for a detached title/company block; then attribute
    the lines between entries as bullets of the preceding entry.
    """
    clean = [raw.strip() for raw in lines]
    n = len(clean)
    events: list[dict] = []

    for i, line in enumerate(clean):
        if not line:
            continue
        m = _DATE_RE.search(line)
        if not (m and len(line) < 160):
            continue
        head = line[: m.start()].strip(" –—-|,@")
        parts = [p.strip() for p in
                 re.split(r"\s+[—–|@]\s+|\s+-\s+|\s+at\s+", head, flags=re.I)
                 if p.strip()]
        title = parts[0] if parts else ""
        company = parts[1] if len(parts) > 1 else ""
        hdr_start = i  # first line belonging to this entry's header block
        if not title:
            # detached header block: up to 2 short non-bullet lines above
            hdr: list[str] = []
            j = i - 1
            while j >= 0 and len(hdr) < 2 and clean[j] and \
                    _looks_like_header_line(clean[j]) and \
                    not _DATE_RE.search(clean[j]):
                hdr.append(clean[j])
                j -= 1
            hdr.reverse()
            if hdr:
                hdr_start = i - len(hdr)
                if len(hdr) >= 2:
                    title, company = hdr[-2], hdr[-1]
                else:
                    title = hdr[-1]
                # 'Title at Company' on one detached line
                if not company:
                    parts2 = [p.strip() for p in
                              re.split(r"\s+[—–|@]\s+|\s+-\s+|\s+at\s+",
                                       title, flags=re.I) if p.strip()]
                    if len(parts2) >= 2:
                        title, company = parts2[0], parts2[1]
        events.append({
            "i": i, "hdr_start": hdr_start,
            "title": _strip_location(title),
            "company": _clean_company_name(company),
            "dates": m.group(0).strip(),
        })

    entries: list[dict] = []
    for ei, ev in enumerate(events):
        next_hdr = events[ei + 1]["hdr_start"] if ei + 1 < len(events) else n
        bullets: list[str] = []
        for line in clean[ev["i"] + 1:next_hdr]:
            if not line or _LOCATION_LINE_RE.match(line):
                continue  # blank or a leftover location line
            bullets.append(_BULLET_MARK.sub("", line).strip())
        entries.append({
            "title": ev["title"],
            "company": ev["company"],
            "dates": ev["dates"],
            "bullets": [b for b in bullets if b],
        })
    return entries


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _dedupe_experience(entries: list[dict]) -> list[dict]:
    """Merge duplicate entries (same normalized title+company).

    Happens when a resume and a LinkedIn export overlap: keep the first
    entry, union the bullets, and prefer the longer dates string.
    """
    merged: list[dict] = []
    index: dict[tuple[str, str], int] = {}
    for e in entries:
        key = (_norm_text(e.get("title", "")), _norm_text(e.get("company", "")))
        if key == ("", "") or key not in index:
            index.setdefault(key, len(merged))
            merged.append(e)
            continue
        base = merged[index[key]]
        seen = {b.lower() for b in base.get("bullets", [])}
        for b in e.get("bullets", []):
            if b and b.lower() not in seen:
                base["bullets"].append(b)
                seen.add(b.lower())
        if len(e.get("dates", "") or "") > len(base.get("dates", "") or ""):
            base["dates"] = e["dates"]
        for f in ("title", "company"):
            if not base.get(f) and e.get(f):
                base[f] = e[f]
    return merged


def _parse_education(lines: list[str]) -> list[dict]:
    entries: list[dict] = []
    for raw in lines:
        line = raw.strip()
        if len(line) < 8:
            continue
        m = _DATE_RE.search(line)
        dates = m.group(0).strip() if m else ""
        head = line[: m.start()].strip(" –—-|,") if m else line
        parts = re.split(r"\s+[—–|]\s+", head)
        school = parts[0].strip()
        degree = parts[1].strip() if len(parts) > 1 else ""
        if school:
            entries.append({"school": school, "degree": degree, "dates": dates})
    return entries[:6]


def _years_from_dates(experience: list[dict]) -> float:
    years: list[tuple[int, int]] = []
    for e in experience:
        ms = re.findall(r"(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*)?(\d{4})", e.get("dates", ""), re.I)
        if len(ms) >= 2:
            years.append((int(ms[0][1]), int(ms[1][1])))
        elif len(ms) == 1 and re.search(r"present|current|now", e.get("dates", ""), re.I):
            from datetime import date
            years.append((int(ms[0][1]), date.today().year))
    if not years:
        return 0.0
    start = min(s for s, _ in years)
    end = max(e for _, e in years)
    return round(max(0.0, end - start + 0.5), 1)


def _seniority_for(years: float, titles: list[str]) -> str:
    title_text = " ".join(titles).lower()
    for kw, rank in sorted(C.SENIORITY_KEYWORDS.items(), key=lambda kv: -kv[1]):
        if kw in title_text:
            return C.SENIORITY_LABELS[rank]
    if years < 1:
        return "entry"
    if years < 3:
        return "junior"
    if years < 6:
        return "mid"
    if years < 9:
        return "senior"
    if years < 13:
        return "lead"
    return "staff"


def build_profile(texts: list[str], source_files: list[str] | None = None) -> dict:
    """Build a structured profile from one or more resume/LinkedIn texts."""
    combined = "\n".join(texts)
    sections = _split_sections(combined)
    head = _clean_lines(sections.get("_head", []))

    name = _parse_name(head)
    headline = ""
    location = ""
    for line in head[1:7]:
        if not line or line == name:
            continue
        if "@" in line and "linkedin" not in line.lower():
            continue  # email line, not a headline
        m = re.search(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*,\s*[A-Z]{2})\b", line)
        if m:
            location = m.group(1)
            rest = line[: m.start()].strip(" |,-")
            if rest and not headline and len(rest.split()) <= 8:
                headline = rest
        elif "remote" in line.lower():
            location = "Remote"
        elif not headline and len(line.split()) <= 10 and "@" not in line:
            headline = line.strip()

    exp_lines: list[str] = []
    for key in ("experience", "work experience", "employment", "professional experience"):
        exp_lines.extend(sections.get(key, []))
    edu_lines: list[str] = []
    for key in ("education",):
        edu_lines.extend(sections.get(key, []))
    skill_lines: list[str] = []
    for key in ("skills", "technical skills", "core skills"):
        skill_lines.extend(sections.get(key, []))

    experience = _dedupe_experience(_parse_experience(exp_lines))
    education = _parse_education(edu_lines)

    # Layered skill extraction: an explicit skills section wins; when there
    # is none, mine the experience bullets/titles; last resort: whole text.
    skills = _extract_skills(" ".join(skill_lines))
    if not skills:
        exp_text = " ".join(
            [e.get("title", "") for e in experience]
            + [b for e in experience for b in e.get("bullets", [])]
        )
        skills = _extract_skills(exp_text)
    if not skills:
        skills = _extract_skills(combined)

    years = _years_from_dates(experience)
    seniority = _seniority_for(years, [e["title"] for e in experience])

    summary_lines = _clean_lines(sections.get("summary", []) + sections.get("profile", []) + sections.get("objective", []))
    summary = " ".join(summary_lines)[:600]

    return {
        "name": name,
        "headline": headline,
        "location": location,
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": education,
        "years_experience": years,
        "seniority": seniority,
        "domains": infer_domains({
            "headline": headline, "experience": experience,
        }),
        "source_files": source_files or [],
    }


# ---------------------------------------------------------------------------
# domain tags + validation (onboarding UX)
# ---------------------------------------------------------------------------

# domain tag -> match keywords (checked against titles + headline + companies)
_DOMAIN_SIGNALS: dict[str, list[str]] = {
    "data science": [r"\bdata scient", r"\bmachine learning\b", r"\bml engineer\b",
                     r"\banalytics\b", r"\bstatistic"],
    "software engineering": [r"\bsoftware engineer\b", r"\bbackend\b", r"\bfrontend\b",
                             r"\bfull[\s-]?stack\b", r"\bsde\b", r"\bdeveloper\b"],
    "ml platform / mlops": [r"\bmlops\b", r"\bml platform\b", r"\bplatform engineer\b",
                            r"\binfrastructure\b", r"\bdevops\b"],
    "ads / monetization": [r"\bads?\b", r"\badvertising\b", r"\bmonetization\b",
                           r"\branking\b"],
    "finance": [r"\bfinanc", r"\bbank\b", r"\bcapital\b", r"\btrading\b",
                r"\bfintech\b", r"\bquant\b"],
    "product": [r"\bproduct manager\b", r"\bproduct analyst\b", r"\bproduct\b"],
    "research": [r"\bresearch scientist\b", r"\bresearch\b", r"\bph\.?d\b"],
    "data engineering": [r"\bdata engineer\b", r"\betl\b", r"\bpipeline\b",
                         r"\bwarehouse\b"],
    "consulting": [r"\bconsultant\b", r"\bconsulting\b"],
}


def infer_domains(profile: dict) -> list[str]:
    """Infer domain-expertise tags from titles, companies, and headline."""
    text = " ".join(
        [e.get("title", "") + " " + e.get("company", "")
         for e in profile.get("experience", [])]
        + [profile.get("headline", "")]
    ).lower()
    return sorted(
        tag for tag, patterns in _DOMAIN_SIGNALS.items()
        if any(re.search(p, text) for p in patterns)
    )


def validate_profile(profile: dict) -> list[dict]:
    """Check a profile for onboarding problems.

    Returns a list of {field, severity, message}; empty means the profile
    is ready to use. ``error`` blocks downstream features; ``warning`` is
    advice shown during onboarding.
    """
    problems: list[dict] = []
    if not (profile.get("name") or "").strip():
        problems.append({
            "field": "name", "severity": "error",
            "message": "Name not detected — put your name on the first line of your resume.",
        })
    if not profile.get("skills"):
        problems.append({
            "field": "skills", "severity": "error",
            "message": "No skills detected — add a Skills section (or mention tools in your bullets).",
        })
    if not profile.get("experience"):
        problems.append({
            "field": "experience", "severity": "error",
            "message": "No experience entries detected — add dated role headers like 'Title — Company, 2020 - Present'.",
        })
    if not (profile.get("headline") or "").strip():
        problems.append({
            "field": "headline", "severity": "warning",
            "message": "No headline detected — a one-line role summary helps matching.",
        })
    if not (profile.get("location") or "").strip():
        problems.append({
            "field": "location", "severity": "warning",
            "message": "No location detected — location filters work better with one.",
        })
    if not profile.get("education"):
        problems.append({
            "field": "education", "severity": "warning",
            "message": "No education entries detected — optional, but some roles filter on it.",
        })
    return problems


def onboard(resume_path: str | Path | None = None,
            linkedin_path: str | Path | None = None,
            out_path: str | Path | None = None) -> dict:
    """Run onboarding: parse inputs, write profile JSON, return the profile."""
    if not resume_path and not linkedin_path:
        raise OnboardError(
            "Nothing to ingest. Provide --resume FILE and/or --linkedin FILE."
        )
    texts: list[str] = []
    sources: list[str] = []
    if resume_path:
        texts.append(read_document(resume_path))
        sources.append(str(resume_path))
    if linkedin_path:
        texts.append(read_document(linkedin_path))
        sources.append(str(linkedin_path))

    profile = build_profile(texts, sources)
    C.ensure_data_dirs()
    dest = Path(out_path) if out_path else C.profile_json_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return profile


def load_profile(path: str | Path | None = None) -> dict:
    """Load the stored profile; raise a friendly error if onboarding is needed."""
    p = Path(path) if path else C.profile_json_path()
    if not p.exists():
        raise OnboardError(
            f"No profile found at {p}.\n"
            "Run onboarding first:\n"
            "    python -m candid onboard --resume your_resume.pdf"
        )
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OnboardError(f"Profile file {p} is not valid JSON: {exc}") from exc


def profile_card(profile: dict) -> str:
    """One-screen human-readable summary of a profile."""
    lines = [
        f"Name:      {profile.get('name') or '(not detected)'}",
        f"Headline:  {profile.get('headline') or '(not detected)'}",
        f"Location:  {profile.get('location') or '(not detected)'}",
        f"Seniority: {profile.get('seniority')} (~{profile.get('years_experience')} yrs)",
        f"Skills ({len(profile.get('skills', []))}): {', '.join(profile.get('skills', [])[:18])}",
        f"Roles:     {len(profile.get('experience', []))} experience entries, "
        f"{len(profile.get('education', []))} education entries",
    ]
    return "\n".join(lines)
