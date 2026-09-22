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


def _parse_experience(lines: list[str]) -> list[dict]:
    """Parse experience bullets into {title, company, dates, bullets} entries.

    Heuristic: a line containing a date range starts a new entry; the text
    before the date range is split into title/company on '—', '-', '@', '|'.
    """
    entries: list[dict] = []
    current: dict | None = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = _DATE_RE.search(line)
        if m and len(line) < 160:
            head = line[: m.start()].strip(" –—-|,@")
            parts = re.split(r"\s+[—–|@]\s+|\s+-\s+", head)
            parts = [p.strip() for p in parts if p.strip()]
            title = parts[0] if parts else head
            company = parts[1].split(",")[0].strip() if len(parts) > 1 else ""
            current = {
                "title": title,
                "company": company,
                "dates": m.group(0).strip(),
                "bullets": [],
            }
            entries.append(current)
        elif current is not None and len(line) > 10:
            current["bullets"].append(line.strip(" •·-*").strip())
        elif current is None and len(line) > 10 and len(entries) == 0:
            # bullet before any dated header — stash for the head summary
            pass
    return entries


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

    experience = _parse_experience(exp_lines)
    education = _parse_education(edu_lines)
    skills = _extract_skills(" ".join(skill_lines) or combined)
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
        "source_files": source_files or [],
    }


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
    dest = Path(out_path) if out_path else C.PROFILE_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return profile


def load_profile(path: str | Path | None = None) -> dict:
    """Load the stored profile; raise a friendly error if onboarding is needed."""
    p = Path(path) if path else C.PROFILE_PATH
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
