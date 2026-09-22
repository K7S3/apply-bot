"""LinkedIn import via LinkedIn's OFFICIAL data export.

Why there's no login-based scraping here: automated scraping of LinkedIn
violates LinkedIn's Terms of Service and can get your account restricted or
banned. The official export (Settings → Get a copy of your data) is the
safe, supported path — and it contains everything candid needs: positions,
skills, education, and your headline.

How to get it (takes under 2 minutes to request):
  1. LinkedIn → Me → Settings & Privacy → Data privacy → "Get a copy of your data"
  2. Check "Download larger data archive" (or pick the fast option) → Request archive
  3. LinkedIn emails you a download link (usually within minutes, up to 24h)
  4. Unzip it, then run:  python -m candid linkedin import --zip <the-export>.zip

Fully offline: the ZIP never leaves your machine. Email addresses in the
export are deliberately NOT imported.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from candid import config as C


class LinkedInError(Exception):
    """Raised for LinkedIn import problems."""


EXPORT_GUIDE = """\
Get your LinkedIn data export in under 2 minutes:

  1. Open LinkedIn → click "Me" (top right) → "Settings & Privacy"
  2. Go to "Data privacy" → "Get a copy of your data"
  3. Select "Download larger data archive" (has positions, skills, education)
     — or "Want something in particular?" and pick the fast option
  4. Click "Request archive" → LinkedIn emails you the download link
     (usually within minutes; can take up to 24 hours)
  5. Download + unzip, then:
         python -m candid linkedin import --zip ~/Downloads/LinkedIn*.zip

Why the export instead of scraping? LinkedIn's Terms of Service prohibit
automated login/scraping, and they actively detect and restrict accounts
that do it. The export is official, complete, and risk-free.
"""


def _read_csvs(zf: zipfile.ZipFile) -> dict[str, list[dict]]:
    """Read every CSV in the archive into {basename: rows}."""
    out: dict[str, list[dict]] = {}
    for name in zf.namelist():
        if not name.lower().endswith(".csv"):
            continue
        base = Path(name).name
        try:
            raw = zf.read(name).decode("utf-8-sig", errors="replace")
        except Exception:
            continue
        reader = csv.DictReader(io.StringIO(raw))
        out[base] = [dict(r) for r in reader if any((v or "").strip() for v in r.values())]
    return out


def _get(row: dict, *names: str) -> str:
    for n in names:
        if n in row and (row[n] or "").strip():
            return row[n].strip()
    # case-insensitive fallback
    low = {k.lower(): v for k, v in row.items()}
    for n in names:
        if n.lower() in low and (low[n.lower()] or "").strip():
            return low[n.lower()].strip()
    return ""


def _parse_positions(rows: list[dict]) -> list[dict]:
    entries = []
    for r in rows:
        title = _get(r, "Title")
        company = _get(r, "Company Name", "Company")
        if not title and not company:
            continue
        started = _get(r, "Started On", "Start Date")
        finished = _get(r, "Finished On", "End Date")
        dates = " – ".join(x for x in (started, finished) if x)
        desc = _get(r, "Description")
        bullets = [b.strip(" •·-*") for b in desc.splitlines() if b.strip()] if desc else []
        entries.append({
            "title": title,
            "company": company,
            "dates": dates,
            "bullets": bullets[:12],
        })
    return entries


def _parse_education(rows: list[dict]) -> list[dict]:
    entries = []
    for r in rows:
        school = _get(r, "School Name", "School")
        if not school:
            continue
        entries.append({
            "school": school,
            "degree": _get(r, "Degree Name", "Degree"),
            "dates": " – ".join(x for x in (_get(r, "Start Date"), _get(r, "End Date")) if x).strip(" –"),
        })
    return entries[:6]


def parse_export(zip_path: str | Path) -> dict:
    """Parse a LinkedIn data-export ZIP into candid-profile-shaped data."""
    p = Path(zip_path)
    if not p.exists():
        raise LinkedInError(f"File not found: {p}")
    if not zipfile.is_zipfile(p):
        raise LinkedInError(f"Not a ZIP file: {p}. Download your export from "
                            "LinkedIn Settings → Data privacy → Get a copy of your data.")
    with zipfile.ZipFile(p) as zf:
        csvs = _read_csvs(zf)
    if not csvs:
        raise LinkedInError(f"No CSVs found in {p} — is this a LinkedIn data export?")

    prof_rows = csvs.get("Profile.csv", [])
    prof = prof_rows[0] if prof_rows else {}
    first = _get(prof, "First Name")
    last = _get(prof, "Last Name")
    parsed = {
        "name": f"{first} {last}".strip(),
        "headline": _get(prof, "Headline"),
        "location": _get(prof, "Location", "Geo Location"),
        "summary": _get(prof, "Summary")[:600],
        "skills_raw": [_get(r, "Name") for r in csvs.get("Skills.csv", []) if _get(r, "Name")],
        "experience": _parse_positions(csvs.get("Positions.csv", [])),
        "education": _parse_education(csvs.get("Education.csv", [])),
        "files_found": sorted(csvs.keys()),
    }
    if not parsed["experience"] and not parsed["skills_raw"] and not parsed["name"]:
        raise LinkedInError(
            f"Couldn't recognize {p} as a LinkedIn export. "
            f"Found CSVs: {', '.join(parsed['files_found'])}. "
            "Request the full archive: LinkedIn → Settings & Privacy → "
            "Data privacy → Get a copy of your data.")
    return parsed


def to_profile(parsed: dict) -> dict:
    """Convert parsed export data into the candid profile schema."""
    from candid import profile as P
    skills = P._extract_skills(" ".join(parsed.get("skills_raw", [])))
    experience = parsed.get("experience", [])
    years = P._years_from_dates(experience)
    return {
        "name": parsed.get("name", ""),
        "headline": parsed.get("headline", ""),
        "location": parsed.get("location", ""),
        "summary": parsed.get("summary", ""),
        "skills": skills,
        "linkedin_skills_raw": parsed.get("skills_raw", []),
        "experience": experience,
        "education": parsed.get("education", []),
        "years_experience": years,
        "seniority": P._seniority_for(years, [e["title"] for e in experience]),
        "source_files": ["linkedin_export"],
    }


def _merge_profiles(base: dict, new: dict) -> dict:
    """Merge LinkedIn data into an existing profile (dedupe by title+company)."""
    merged = dict(base)
    seen = {(e.get("title", "").lower(), e.get("company", "").lower())
            for e in merged.get("experience", [])}
    for e in new.get("experience", []):
        key = (e.get("title", "").lower(), e.get("company", "").lower())
        if key not in seen:
            merged.setdefault("experience", []).append(e)
            seen.add(key)
    for edu in new.get("education", []):
        if edu["school"].lower() not in {x.get("school", "").lower()
                                         for x in merged.get("education", [])}:
            merged.setdefault("education", []).append(edu)
    skills = list(dict.fromkeys(merged.get("skills", []) + new.get("skills", [])))
    merged["skills"] = sorted(skills)
    for field in ("name", "headline", "location", "summary"):
        if not merged.get(field) and new.get(field):
            merged[field] = new[field]
    if new.get("linkedin_skills_raw"):
        merged["linkedin_skills_raw"] = new["linkedin_skills_raw"]
    from candid import profile as P
    merged["years_experience"] = P._years_from_dates(merged.get("experience", []))
    merged["seniority"] = P._seniority_for(
        merged["years_experience"],
        [e["title"] for e in merged.get("experience", [])])
    srcs = merged.get("source_files", [])
    if "linkedin_export" not in srcs:
        merged["source_files"] = srcs + ["linkedin_export"]
    return merged


def import_zip(zip_path: str | Path, mode: str = "merge",
               out_path: str | Path | None = None) -> dict:
    """Import a LinkedIn export ZIP.

    mode="merge" (default): fold into the existing profile, deduping.
    mode="replace": overwrite the profile with the LinkedIn data.
    """
    import json
    from candid import profile as P
    if mode not in ("merge", "replace"):
        raise LinkedInError("mode must be 'merge' or 'replace'.")
    parsed = parse_export(zip_path)
    new_profile = to_profile(parsed)
    if mode == "merge":
        try:
            base = P.load_profile()
        except P.OnboardError:
            base = None
        profile = _merge_profiles(base, new_profile) if base else new_profile
    else:
        profile = new_profile
    C.ensure_data_dirs()
    dest = Path(out_path) if out_path else C.PROFILE_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return {
        "profile": profile,
        "positions": len(new_profile["experience"]),
        "skills": len(new_profile["skills"]),
        "education": len(new_profile["education"]),
        "mode": mode,
    }
