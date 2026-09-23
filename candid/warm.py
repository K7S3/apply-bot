"""Warm-intro job ranking: rank jobs by the strength of your network there.

The LinkedIn data export contains ONLY 1st-degree connections
(Connections.csv). candid never claims 2nd-degree visibility, mutual
connections, or anything beyond "you are directly connected to this person".
intro_path() strings describe a one-hop path: You -> Connection.

Everything here is offline: the export ZIP never leaves your machine, and
email addresses from the export are deliberately NOT imported.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

from candid import config as C


class WarmError(Exception):
    """Raised for warm-intro engine problems (bad export, bad status, ...)."""


# --- connection loading -------------------------------------------------------

#: Outreach statuses tracked per company (see warm.json).
WARM_STATUSES = ("none", "asked", "introduced", "applied")


def _row_get(row: dict, *names: str) -> str:
    """Fetch a value from a CSV row, case-insensitive on column names."""
    lower = {str(k).lower().strip(): v for k, v in row.items()}
    for n in names:
        hit = lower.get(n.lower())
        if hit is not None and str(hit).strip():
            return str(hit).strip()
    return ""


_DATE_FORMATS = ("%d %b %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y")


def _parse_connected_on(raw: str) -> date | None:
    """Parse LinkedIn's 'Connected On' into a date; None if unparseable."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            from datetime import datetime
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def load_connections(export_zip: str | Path) -> list[dict]:
    """Parse Connections.csv from a LinkedIn data-export ZIP.

    Returns one dict per 1st-degree connection:
    {"first_name", "last_name", "full_name", "company", "position",
     "connected_on" (datetime.date | None), "degree": 1}.

    Email addresses from the export are never imported.
    """
    p = Path(export_zip)
    if not p.exists():
        raise WarmError(f"File not found: {p}")
    if not zipfile.is_zipfile(p):
        raise WarmError(f"Not a ZIP file: {p}")
    target = None
    with zipfile.ZipFile(p) as zf:
        for name in zf.namelist():
            if Path(name).name.lower() == "connections.csv":
                target = name
                break
        if target is None:
            raise WarmError(
                f"No Connections.csv found in {p}. Request the full archive: "
                "LinkedIn -> Settings & Privacy -> Data privacy -> "
                "Get a copy of your data.")
        try:
            raw = zf.read(target).decode("utf-8-sig", errors="replace")
        except Exception as exc:
            raise WarmError(f"Could not read Connections.csv in {p}: {exc}") from exc
    reader = csv.DictReader(io.StringIO(raw))
    conns = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue  # blank row
        first = _row_get(row, "First Name")
        last = _row_get(row, "Last Name")
        full = f"{first} {last}".strip()
        company = _row_get(row, "Company")
        position = _row_get(row, "Position")
        if not full and not company:
            continue  # nothing identifying; skip like a blank row
        conns.append({
            "first_name": first,
            "last_name": last,
            "full_name": full,
            "company": company,
            "position": position,
            "connected_on": _parse_connected_on(
                _row_get(row, "Connected On", "ConnectedOn", "Connected Date")),
            "degree": 1,
        })
    return conns


# --- company normalization ----------------------------------------------------

_SUFFIXES = ("inc", "incorporated", "llc", "ltd", "limited", "corp",
             "corporation", "co", "company", "gmbh", "plc", "llp")


def _norm_company(name: str | None) -> str:
    """Normalize a company name for matching.

    Lowercases, strips legal-entity suffixes (Inc/LLC/Ltd/Corp/Co/GmbH/...),
    removes trailing dots, and collapses whitespace. "Acme Inc." and
    "ACME LLC" both become "acme".
    """
    s = re.sub(r"\s+", " ", (name or "").strip().lower().rstrip("."))
    prev = None
    while prev != s:
        prev = s
        for suf in _SUFFIXES:
            s = re.sub(rf"\s+{suf}$", "", s)
        s = s.rstrip(".")
    return s.strip()


# --- warmth scoring -------------------------------------------------------------

# Weights for warmth_score(): recency 40%, title signal 60%.
_RECENCY_WEIGHT = 0.4
_SENIORITY_WEIGHT = 0.6

# Title regex -> warmth score (0-100), first match wins.
_TITLE_RULES: list[tuple[str, float]] = [
    (r"\b(vice president|vp|svp|evp)\b", 95),
    (r"\b(ceo|cto|coo|cfo|founder|co-?founder|president)\b", 90),
    (r"\bdirector\b", 90),
    (r"\bhead\b", 85),
    # Recruiters/HR score well: they are the fastest path to an intro.
    (r"\b(recruiter|recruiting|talent|sourcing|hr|people)\b", 85),
    (r"\bmanager\b", 80),
    (r"\blead\b", 75),
    (r"\b(staff|principal|senior)\b", 65),
    (r"\bintern\b", 35),
]
_TITLE_DEFAULT = 50.0  # plain IC / unknown title


def _recency_component(connected_on: date | None,
                       today: date | None = None) -> float:
    """Recent connections are slightly warmer.

    100 for a connection made today, decaying linearly to a floor of 20 at
    10 years; an unknown connection date is neutral (50).
    """
    if connected_on is None:
        return 50.0
    today = today or date.today()
    days = max(0, (today - connected_on).days)
    return max(20.0, 100.0 - 80.0 * days / 3650.0)


def _seniority_component(position: str | None) -> float:
    """Title-based warmth: senior folks and recruiters score higher."""
    title = (position or "").lower()
    for pattern, score in _TITLE_RULES:
        if re.search(pattern, title):
            return score
    return _TITLE_DEFAULT


def warmth_score(conn: dict) -> float:
    """Warmth of a single connection, 0-100.

    Formula: 0.4 * recency_component + 0.6 * seniority_component.

    - recency: 100 at day 0 decaying to 20 at 10 years; unknown date = 50.
    - seniority: vp 95, director 95/90, head/recruiter 85, manager 80,
      lead 75, senior/staff/principal 65, plain IC 50, intern 35.
    """
    rec = _recency_component(conn.get("connected_on"))
    sen = _seniority_component(conn.get("position"))
    return round(_RECENCY_WEIGHT * rec + _SENIORITY_WEIGHT * sen, 1)


def connection_strength(conns: list[dict]) -> float:
    """Aggregate strength of a list of connections at one company, 0-100.

    The strongest connection counts fully; each additional connection
    contributes half as much as the previous one (diminishing returns),
    and the total is capped at 100.
    """
    if not conns:
        return 0.0
    scores = sorted((warmth_score(c) for c in conns), reverse=True)
    total, weight = 0.0, 1.0
    for s in scores:
        total += s * weight
        weight /= 2.0
    return round(min(100.0, total), 1)


# --- intro paths and insider map ------------------------------------------------

def intro_path(conn: dict) -> str:
    """One-hop intro path, e.g. "You -> Jane Doe (Engineering Manager @ Acme)".

    When the export recorded a connection date it is included
    ("connected Mar 2021"). Always 1st-degree: never implies a mutual or
    2nd-degree hop.
    """
    name = conn.get("full_name") or "?"
    role = conn.get("position") or ""
    company = conn.get("company") or ""
    label = f"{role} @ {company}".strip(" @") or "connection"
    d = conn.get("connected_on")
    when = f", connected {d.strftime('%b %Y')}" if isinstance(d, date) else ""
    return f"You -> {name} ({label}{when})"


def _bucket(position: str | None) -> str:
    """Sort a title into hiring / recruiting / engineering / other."""
    title = (position or "").lower()
    if re.search(r"\b(recruiter|recruiting|talent|sourcing|hr|people)\b", title):
        return "recruiting"
    if re.search(r"\b(vice president|vp|svp|evp|ceo|cto|coo|cfo|founder|"
                 r"co-?founder|president|director|head|manager|lead)\b", title):
        return "hiring"
    if re.search(r"\b(engineer|developer|software|swe|data|scientist|"
                 r"researcher|analyst|designer)\b", title):
        return "engineering"
    return "other"


def insider_map(company: str, connections: list[dict]) -> dict:
    """Group 1st-degree connections at one company by likely usefulness.

    Returns {"hiring": [...], "recruiting": [...], "engineering": [...],
    "other": [...]}; each list holds connection dicts sorted by
    warmth_score descending. Company matched via _norm_company.
    """
    want = _norm_company(company)
    buckets = {"hiring": [], "recruiting": [], "engineering": [], "other": []}
    for conn in connections:
        if _norm_company(conn.get("company")) != want:
            continue
        buckets[_bucket(conn.get("position"))].append(conn)
    for key in buckets:
        buckets[key].sort(key=warmth_score, reverse=True)
    return buckets


# --- job ranking ---------------------------------------------------------------

def warm_score(strength: float, match: float | None) -> float:
    """Blend connection strength with profile/job match into 0-100.

    Formula: (strength + match) / 2 when a match score is given; when
    match is None, strength alone (clamped to 0-100). Ranks jobs with
    warm intros against jobs that are merely a good fit.
    """
    s = max(0.0, min(100.0, float(strength or 0.0)))
    if match is None:
        return round(s, 1)
    return round((s + float(match)) / 2.0, 1)


def rank_jobs(jobs: list[dict], connections: list[dict],
              match_scores: list | dict | None = None) -> list[dict]:
    """Rank jobs by warm-intro strength, blended with match scores.

    Jobs are dicts with at least "title" and "company" (may also carry
    "url", "source", ...). Connections attach to a job when their company
    normalizes to the same key via _norm_company ("Acme Inc." matches
    "ACME"). match_scores is a parallel list aligned with jobs, or a dict
    keyed by job index; unmatched jobs get match=None.

    Returns items sorted by warm_score desc:
    {"job", "company", "connections", "strength", "paths", "match",
     "warm_score"}. Jobs with no connections are included (at the bottom).
    """
    by_company: dict[str, list[dict]] = {}
    for conn in connections:
        key = _norm_company(conn.get("company"))
        if key:
            by_company.setdefault(key, []).append(conn)

    def _match_for(i: int) -> float | None:
        if match_scores is None:
            return None
        if isinstance(match_scores, dict):
            m = match_scores.get(i, match_scores.get(str(i)))
        else:
            m = match_scores[i] if i < len(match_scores) else None
        return float(m) if m is not None else None

    ranked = []
    for i, job in enumerate(jobs):
        company = job.get("company") or ""
        conns = sorted(by_company.get(_norm_company(company), []),
                       key=warmth_score, reverse=True)
        strength = connection_strength(conns)
        match = _match_for(i)
        ranked.append({
            "job": job,
            "company": company,
            "connections": conns,
            "strength": strength,
            "paths": [intro_path(c) for c in conns],
            "match": match,
            "warm_score": warm_score(strength, match),
        })
    ranked.sort(key=lambda r: r["warm_score"], reverse=True)
    return ranked


# --- intro drafts ----------------------------------------------------------------

def draft_intro(conn: dict, job: dict, user_name: str) -> str:
    """Short personalized intro/referral request draft. Plain text, not sent.

    Names the connection's role and the job title/company; asks for a
    referral or an intro to the hiring manager.
    """
    first = (conn.get("first_name") or conn.get("full_name") or "there").split()[0]
    role = conn.get("position") or "your team"
    title = job.get("title") or "the role"
    company = job.get("company") or "the company"
    return (
        f"Hi {first},\n\n"
        f"I'm {user_name}, and I'm applying for the {title} role at {company}. "
        f"I saw you're connected there as {role}, so I wanted to ask: "
        "would you be open to a quick chat about the team? If it looks like "
        "a fit, I'd really appreciate a referral or an intro to the hiring "
        "manager.\n\n"
        f"Thanks,\n{user_name}"
    )


# --- warm.json: per-company outreach tracking --------------------------------------

def _warm_file() -> Path:
    return C.WARM_PATH


def load_warm() -> dict:
    """Load warm-intro outreach state: {company_norm: {"contact", "status", "asked_on"}}."""
    p = _warm_file()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WarmError(f"Warm file {p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WarmError(f"Warm file {p} should contain a JSON object.")
    return data


def save_warm(state: dict) -> Path:
    """Persist warm-intro outreach state."""
    p = _warm_file()
    C.ensure_data_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return p


def get_status(company: str) -> dict:
    """Outreach status for a company (matched via _norm_company)."""
    return load_warm().get(_norm_company(company), {
        "contact": None, "status": "none", "asked_on": None})


def set_status(company: str, status: str, contact: str | None = None) -> dict:
    """Record outreach status for a company.

    status must be one of: none, asked, introduced, applied. asked_on is
    set to today whenever status is anything but "none". A provided
    contact name is stored; otherwise the previous contact is kept.
    """
    if status not in WARM_STATUSES:
        raise WarmError(
            f"Unknown status '{status}'. Choose from: {', '.join(WARM_STATUSES)}")
    key = _norm_company(company)
    if not key:
        raise WarmError("A company name is required to set a warm status.")
    state = load_warm()
    prev = state.get(key, {})
    rec = {
        "contact": contact if contact is not None else prev.get("contact"),
        "status": status,
        "asked_on": (date.today().isoformat() if status != "none" else None),
    }
    state[key] = rec
    save_warm(state)
    return rec
