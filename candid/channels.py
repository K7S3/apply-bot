"""Direct-apply vs portal guidance.

For every posting, candid answers the practical question: *what is the best
way to apply?* This module classifies the application channels a posting
offers, identifies the ATS portal (if any) with per-ATS notes, detects
referral paths from your LinkedIn export, and produces ranked,
per-posting advice.

Pipeline:
    classify_channels(job) -> recommend_channels(job, referral=...) ->
    guide(job, ...) -> printable per-posting report.

Pure stdlib, no network: ATS identification works off the posting URL and
job text you already have (curated jobs carry ``url`` and ``description``).
Email extraction it only finds addresses the employer published in the job text
finds addresses already published in the job text (e.g. "send your resume
to jobs@example.com"), never invents or looks up private addresses.

Channel vocabulary (also used by candid.tracker as the ``channel`` field):
    referral, direct_email, ats_portal, company_site,
    linkedin_easy_apply, aggregator
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

CHANNELS = [
    "referral",
    "direct_email",
    "ats_portal",
    "company_site",
    "linkedin_easy_apply",
    "aggregator",
]

CHANNEL_LABELS = {
    "referral": "Referral",
    "direct_email": "Direct email",
    "ats_portal": "ATS portal",
    "company_site": "Company careers page",
    "linkedin_easy_apply": "LinkedIn Easy Apply",
    "aggregator": "Job aggregator",
}


class ChannelError(Exception):
    """Raised for direct-apply guidance problems."""


# ---------------------------------------------------------------------------
# ATS identification
# ---------------------------------------------------------------------------

# Host fragment -> ATS name. Checked as substring of the lowercased netloc.
_ATS_HOSTS = {
    "greenhouse.io": "Greenhouse",
    "boards.greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "ashbyhq.com": "Ashby",
    "myworkdayjobs.com": "Workday",
    "workday.com": "Workday",
    "icims.com": "iCIMS",
    "taleo.net": "Taleo",
    "smartrecruiters.com": "SmartRecruiters",
    "bamboohr.com": "BambooHR",
    "workable.com": "Workable",
    "jobvite.com": "Jobvite",
    "jazzhr.com": "JazzHR",
    "jazz.co": "JazzHR",
    "breezy.hr": "Breezy HR",
    "rippling-ats.com": "Rippling",
    "jobs.rippling.com": "Rippling",
    "successfactors": "SAP SuccessFactors",
    "eightfold.ai": "Eightfold",
    "pinpointhq.com": "Pinpoint",
    "ukg": "UKG",
    "oraclecloud.com": "Oracle HCM",
    "brassring.com": "BrassRing",
    "phenompeople.com": "Phenom",
    "myjobs.adp.com": "ADP",
    "workforcenow.adp.com": "ADP",
    "applytojob.com": "ApplyToJob",
    "recruitee.com": "Recruitee",
    "teamtailor.com": "Teamtailor",
    "personio": "Personio",
    "zoho": "Zoho Recruit",
    "freshteam": "Freshteam",
    "zoho.com": "Zoho Recruit",
    "wellfound.com": "Wellfound",
    "angel.co": "Wellfound",
}

# Text hints (lowercased) -> ATS, used when the URL does not identify one.
_ATS_TEXT_HINTS = {
    "greenhouse": "Greenhouse",
    "boards.greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "ashbyhq.com": "Ashby",
    "myworkdayjobs.com": "Workday",
    "workday": "Workday",
    "icims": "iCIMS",
    "taleo": "Taleo",
    "smartrecruiters": "SmartRecruiters",
    "bamboohr": "BambooHR",
    "workable": "Workable",
    "jobvite": "Jobvite",
    "jazzhr": "JazzHR",
    "breezy.hr": "Breezy HR",
    "successfactors": "SAP SuccessFactors",
    "eightfold": "Eightfold",
    "pinpoint": "Pinpoint",
    "brassring": "BrassRing",
    "phenom": "Phenom",
}


def _host(url: str) -> str:
    try:
        return urlparse(url or "").netloc.lower()
    except Exception:
        return ""


def identify_ats(url: str, text: str = "") -> str | None:
    """Identify the ATS behind a posting URL (and/or its job text).

    Returns the ATS name (e.g. "Greenhouse") or None when unidentified.
    Host matching runs first; job-text hints are a fallback for postings
    whose URL is a company careers page that names the ATS in the text.
    """
    host = _host(url)
    if host:
        for frag, name in _ATS_HOSTS.items():
            if frag in host:
                return name
    low = (text or "").lower()
    if low:
        for hint, name in _ATS_TEXT_HINTS.items():
            if hint in low:
                return name
    return None


# ---------------------------------------------------------------------------
# ATS portal notes
# ---------------------------------------------------------------------------

ATS_NOTES: dict[str, dict] = {
    "Greenhouse": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": [
            "Usually no account needed; apply with a simple form.",
            "Parses PDF resumes well; keep standard section headers.",
        ],
        "tips": [
            "Use the 'upload resume' autofill, then fix any mis-parsed fields.",
            "Cover letter is optional on most boards; attach one only if it adds signal.",
        ],
    },
    "Lever": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": [
            "No account needed; one-page apply form.",
            "Some postings link out to an external form (Typeform/Google Form).",
        ],
        "tips": [
            "Lever parses LinkedIn profiles decently; still upload the tailored PDF.",
        ],
    },
    "Ashby": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": [
            "Modern, fast form; often includes short screening questions.",
        ],
        "tips": [
            "Answer the custom questions concretely; they are read by the hiring team.",
        ],
    },
    "Workday": {
        "account_required": True,
        "parsing_quality": "fair",
        "time_minutes": "20-30",
        "quirks": [
            "Requires a Workday account per company; credentials are NOT shared across companies.",
            "Session timeouts are aggressive; save drafts often.",
            "Often asks you to re-enter work history field by field even after resume upload.",
        ],
        "tips": [
            "Use candid tailor first so your resume upload parses cleanly; budget extra time.",
            "If a referral is available, use it: it can skip the Workday gauntlet entirely.",
            "Disable aggressive autofill; Workday forms sometimes reject pasted dates.",
        ],
    },
    "iCIMS": {
        "account_required": True,
        "parsing_quality": "fair",
        "time_minutes": "15-25",
        "quirks": [
            "Usually requires a profile/account.",
            "Multi-page application with pre-screening questions.",
        ],
        "tips": [
            "Complete in one sitting; partial saves can be flaky.",
        ],
    },
    "Taleo": {
        "account_required": True,
        "parsing_quality": "poor",
        "time_minutes": "20-40",
        "quirks": [
            "Legacy system; resume parsing is weak and the UI times out.",
            "Often requires re-typing your entire work history.",
        ],
        "tips": [
            "Prefer a referral or direct email for Taleo postings when possible.",
            "Keep answers short; long text fields sometimes truncate silently.",
        ],
    },
    "SmartRecruiters": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-15",
        "quirks": [
            "Often supports LinkedIn-profile import; account optional on many sites.",
        ],
        "tips": [
            "The LinkedIn import is a decent shortcut, but review every field.",
        ],
    },
    "BambooHR": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": ["Simple form; common at startups and small companies."],
        "tips": ["Fast portal; apply quickly while the posting is fresh."],
    },
    "Workable": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": ["Clean form; social-profile import available."],
        "tips": ["Upload the tailored resume PDF rather than relying on profile import."],
    },
    "Jobvite": {
        "account_required": True,
        "parsing_quality": "fair",
        "time_minutes": "10-20",
        "quirks": ["Often routes through a candidate profile; social apply supported."],
        "tips": ["Social-profile apply saves time but double-check the parsed resume."],
    },
    "JazzHR": {
        "account_required": False,
        "parsing_quality": "fair",
        "time_minutes": "5-10",
        "quirks": ["Simple form, common with small businesses."],
        "tips": ["Straightforward; attach the tailored PDF and go."],
    },
    "Breezy HR": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": ["Candidate-friendly; sometimes includes video screening questions."],
        "tips": ["If a video intro is requested, keep it under 60 seconds."],
    },
    "Rippling": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": ["Modern form; often has knockout questions."],
        "tips": ["Answer knockout questions carefully; they auto-filter."],
    },
    "SAP SuccessFactors": {
        "account_required": True,
        "parsing_quality": "fair",
        "time_minutes": "15-25",
        "quirks": [
            "Enterprise portal; account required and multi-step.",
            "Common at large enterprises.",
        ],
        "tips": ["A referral is worth extra effort here; the portal is slow."],
    },
    "Eightfold": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": ["AI-matching portal; profile completeness affects matching."],
        "tips": ["Fill skills thoroughly; Eightfold matches on them."],
    },
    "Pinpoint": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": ["Clean modern form."],
        "tips": ["Quick apply; prioritize speed."],
    },
    "UKG": {
        "account_required": True,
        "parsing_quality": "fair",
        "time_minutes": "15-25",
        "quirks": ["Enterprise portal; account usually required."],
        "tips": ["Budget time; save progress between sections."],
    },
    "Oracle HCM": {
        "account_required": True,
        "parsing_quality": "fair",
        "time_minutes": "15-30",
        "quirks": ["Enterprise portal with lengthy questionnaires."],
        "tips": ["Referral strongly preferred; portal is heavyweight."],
    },
    "BrassRing": {
        "account_required": True,
        "parsing_quality": "poor",
        "time_minutes": "20-40",
        "quirks": [
            "Legacy enterprise system; parsing is weak, sessions time out.",
        ],
        "tips": [
            "Prefer a referral or direct email when the company offers one.",
        ],
    },
    "Phenom": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-15",
        "quirks": ["Chatbot-assisted apply on some sites."],
        "tips": ["The chatbot is quick; keep answers concise."],
    },
    "ADP": {
        "account_required": True,
        "parsing_quality": "fair",
        "time_minutes": "15-25",
        "quirks": ["Account required on most ADP career sites."],
        "tips": ["Complete in one session to avoid timeouts."],
    },
    "Recruitee": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": ["Simple European ATS; GDPR notices are common."],
        "tips": ["Fast apply; GDPR consent is standard."],
    },
    "Teamtailor": {
        "account_required": False,
        "parsing_quality": "good",
        "time_minutes": "5-10",
        "quirks": ["Modern form; common in EU startups."],
        "tips": ["Quick apply; attach the tailored PDF."],
    },
    "Personio": {
        "account_required": False,
        "parsing_quality": "fair",
        "time_minutes": "5-15",
        "quirks": ["Common at EU SMBs; straightforward form."],
        "tips": ["Straightforward; attach the tailored PDF and go."],
    },
    "Zoho Recruit": {
        "account_required": False,
        "parsing_quality": "fair",
        "time_minutes": "5-15",
        "quirks": ["Simple form."],
        "tips": ["Attach the tailored PDF and go."],
    },
    "Freshteam": {
        "account_required": False,
        "parsing_quality": "fair",
        "time_minutes": "5-15",
        "quirks": ["Simple form."],
        "tips": ["Attach the tailored PDF and go."],
    },
    "Wellfound": {
        "account_required": True,
        "parsing_quality": "good",
        "time_minutes": "10-20",
        "quirks": [
            "Requires a Wellfound profile; startups review your profile, not just the application.",
            "One profile serves all applications.",
        ],
        "tips": [
            "Keep your Wellfound profile sharp (it is your resume here); add a one-line intro note per application.",
        ],
    },
    "ApplyToJob": {
        "account_required": False,
        "parsing_quality": "fair",
        "time_minutes": "5-10",
        "quirks": ["Simple hosted apply form."],
        "tips": ["Attach the tailored PDF and go."],
    },
}


def ats_notes(ats: str | None) -> dict:
    """Portal guidance for an ATS name (None/unknown -> generic notes)."""
    if ats and ats in ATS_NOTES:
        n = ATS_NOTES[ats]
        return {"ats": ats, **n}
    return {
        "ats": ats or "unknown",
        "account_required": None,
        "parsing_quality": "unknown",
        "time_minutes": "10-20",
        "quirks": ["Unidentified portal; treat like a standard ATS form."],
        "tips": [
            "Upload a clean PDF (candid tailor) rather than pasting text.",
            "If an account is required, use a password manager entry.",
        ],
    }


# ---------------------------------------------------------------------------
# Aggregators
# ---------------------------------------------------------------------------

_AGGREGATORS = {
    "indeed.com": "Indeed",
    "glassdoor.com": "Glassdoor",
    "ziprecruiter.com": "ZipRecruiter",
    "simplyhired.com": "SimplyHired",
    "monster.com": "Monster",
    "careerbuilder.com": "CareerBuilder",
    "dice.com": "Dice",
    "linkedin.com": "LinkedIn Jobs",
    "themuse.com": "The Muse",
    "adzuna.com": "Adzuna",
    "snagajob.com": "Snagajob",
    "ladders.com": "Ladders",
    "nexxt.com": "Nexxt",
    "jobcase.com": "Jobcase",
}


def aggregator_info(url: str) -> dict | None:
    """Detect job aggregators. Returns {aggregator, warning} or None.

    Aggregators re-list postings: always prefer the company's own posting.
    """
    host = _host(url)
    if not host:
        return None
    for frag, name in _AGGREGATORS.items():
        if frag in host:
            return {
                "aggregator": name,
                "warning": (
                    f"This is a {name} listing, not the employer's own posting. "
                    "Aggregator listings can be stale, duplicated, or scraped. "
                    "Find the posting on the company's careers page and apply there."
                ),
            }
    return None


# ---------------------------------------------------------------------------
# Direct-email detection
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Apply context must appear BEFORE the address ("was emailed by x@" is not
# an apply instruction). Word boundaries keep "emailed" from matching.
_APPLY_HINT_RE = re.compile(r"\b(apply|send|submit|forward|resume|cv)\b", re.I)

# Domains that are almost never a direct employer apply address.
_NOISE_DOMAINS = (
    "example.com", "test.com", "sentry.io", "schema.org",
)


def extract_apply_emails(text: str) -> list[dict]:
    """Find employer email addresses published in the job text.

    Returns [{email, context}] for addresses that appear near apply/send/
    resume wording. Noise (example.com, noreply, do-not-reply) is dropped.
    Only finds addresses the employer published; nothing is looked up.
    """
    out: list[dict] = []
    seen: set[str] = set()
    text = text or ""
    for m in _EMAIL_RE.finditer(text):
        email = m.group(0)
        key = email.lower()
        if key in seen:
            continue
        local, _, domain = key.partition("@")
        if any(nd in domain for nd in _NOISE_DOMAINS):
            continue
        if local.startswith(("noreply", "no-reply", "donotreply", "do-not-reply",
                              "bounce", "mailer-daemon", "postmaster")):
            continue
        window = text[max(0, m.start() - 80):m.end() + 40]
        before = text[max(0, m.start() - 120):m.start()]
        if not _APPLY_HINT_RE.search(before) and "careers" not in key:
            # No apply context: keep only obvious hiring inboxes.
            if not any(k in local for k in ("job", "career", "hire", "hiring",
                                            "talent", "recruit", "apply", "resume")):
                continue
        snippet = re.sub(r"\s+", " ", window).strip()
        out.append({"email": email,
                    "context": snippet[:140] + ("..." if len(snippet) > 140 else "")})
        seen.add(key)
    return out


# ---------------------------------------------------------------------------
# Channel classification
# ---------------------------------------------------------------------------

def classify_channels(job: dict) -> dict[str, dict]:
    """Classify the application channels a posting offers.

    Returns {channel: {available: bool, detail: str}}. ``job`` uses the
    curated-job shape (title, company, url, description, source).
    """
    job = job or {}
    url = job.get("url") or ""
    text = job.get("description") or ""
    source = (job.get("source") or "").lower()

    ats = identify_ats(url, text)
    agg = aggregator_info(url)
    emails = extract_apply_emails(text)

    out: dict[str, dict] = {}

    # Referral availability is computed at guide time (needs connections);
    # here we mark it as "check", letting recommend_channels upgrade it.
    out["referral"] = {
        "available": False,
        "detail": "Run `candid guide referral --company ...` with your LinkedIn export to check.",
    }

    if emails:
        out["direct_email"] = {
            "available": True,
            "detail": f"Employer lists {emails[0]['email']} for applications.",
        }
    else:
        out["direct_email"] = {
            "available": False,
            "detail": "No apply email published in the posting.",
        }

    if ats:
        out["ats_portal"] = {
            "available": True,
            "detail": f"Apply through the {ats} portal at the posting URL.",
        }
    else:
        out["ats_portal"] = {
            "available": False,
            "detail": "No recognized ATS portal in the posting URL.",
        }

    if agg:
        out["aggregator"] = {
            "available": True,
            "detail": agg["warning"],
        }
        out["company_site"] = {
            "available": False,
            "detail": "Company careers-page link not visible from this listing; search the company site.",
        }
    elif ats:
        out["aggregator"] = {"available": False,
                             "detail": "Posting is on the employer's own ATS link."}
        out["company_site"] = {
            "available": True,
            "detail": "The ATS link is hosted for the employer; the company careers page usually links here too.",
        }
    elif url:
        out["aggregator"] = {"available": False,
                             "detail": "Not an aggregator listing."}
        out["company_site"] = {
            "available": True,
            "detail": "Posting appears to be on the employer's own site.",
        }
    else:
        out["aggregator"] = {"available": False, "detail": "No URL to check."}
        out["company_site"] = {"available": False, "detail": "No URL to check."}

    host = _host(url)
    if "linkedin.com" in host and "easy" in (text or "").lower()[:2000]:
        out["linkedin_easy_apply"] = {
            "available": True,
            "detail": "Easy Apply detected: one-click apply with your LinkedIn profile.",
        }
    elif source in ("linkedin",) or "linkedin.com/jobs" in (url or "").lower():
        out["linkedin_easy_apply"] = {
            "available": False,
            "detail": "LinkedIn listing, but Easy Apply not confirmed; it may redirect to the company site.",
        }
    else:
        out["linkedin_easy_apply"] = {
            "available": False,
            "detail": "Not a LinkedIn posting.",
        }
    return out


# ---------------------------------------------------------------------------
# Referral path
# ---------------------------------------------------------------------------
#
# Data source: your LinkedIn data export (Settings → Get a copy of your
# data). ``Connections.csv`` inside the export lists 1st-degree connections
# with First Name, Last Name, Company, Position, Connected On. Email
# addresses are deliberately NOT imported (same privacy rule as the
# LinkedIn importer: the export has no 2nd-degree data, so candid never
# claims to see it).
#
# Pipeline: load_connections() -> referral_path(company, connections) ->
# draft_referral_request(name, company, role).

import csv
import io
import zipfile


def _norm_company(name: str) -> str:
    """Normalize a company name for matching."""
    n = (name or "").lower().strip()
    n = re.sub(r"\s+(inc|llc|ltd|corp|corporation|co|gmbh|pvt)\.?$", "", n)
    return re.sub(r"\s+", " ", n).strip()


def _read_connections_csv(text: str) -> list[dict]:
    """Parse Connections.csv text into connection dicts.

    Defensive CSV handling: utf-8-sig, case-insensitive column lookup,
    blank rows skipped, email deliberately not imported.
    """
    rows = csv.DictReader(io.StringIO(text))
    out: list[dict] = []
    for r in rows:
        if not r or not any((v or "").strip() for v in r.values()):
            continue
        low = {k.lower().strip(): (v or "").strip()
               for k, v in r.items() if k}
        first = low.get("first name", "")
        last = low.get("last name", "")
        name = f"{first} {last}".strip()
        if not name:
            continue
        out.append({
            "name": name,
            "company": low.get("company", ""),
            "position": low.get("position", ""),
            "connected_on": low.get("connected on", ""),
        })
    return out


def load_connections(source: str | Path | None = None) -> list[dict]:
    """Load 1st-degree connections from a LinkedIn export.

    ``source`` is the export ``.zip`` (reads ``Connections.csv`` from it)
    or a bare ``Connections.csv`` file. Raises ChannelError with the
    export instructions when no source is configured.
    """
    if source is None:
        raise ChannelError(
            "No LinkedIn export configured. Pass --connections <LinkedIn-export.zip "
            "or Connections.csv>. Get it: LinkedIn → Settings & Privacy → "
            "Data privacy → Get a copy of your data.")
    p = Path(source).expanduser()
    if not p.exists():
        raise ChannelError(f"File not found: {p}")
    if p.suffix.lower() == ".zip":
        if not zipfile.is_zipfile(p):
            raise ChannelError(f"Not a ZIP file: {p}")
        with zipfile.ZipFile(p) as zf:
            csv_names = [n for n in zf.namelist()
                         if n.lower().endswith("connections.csv")]
            if not csv_names:
                raise ChannelError(
                    f"No Connections.csv in {p}. Request the larger data "
                    "archive: LinkedIn → Settings & Privacy → Data privacy "
                    "→ Get a copy of your data.")
            text = zf.read(csv_names[0]).decode("utf-8-sig", errors="replace")
    elif p.suffix.lower() == ".csv":
        text = p.read_text(encoding="utf-8-sig", errors="replace")
    else:
        raise ChannelError(f"Expected a .zip or .csv file, got: {p}")
    return _read_connections_csv(text)


_CONNECTED_ON_FORMATS = ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%m/%d/%Y",
                          "%d-%b-%Y", "%b %d, %Y", "%B %d, %Y")


def _connected_date(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _CONNECTED_ON_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


_SENIORITY_KEYWORDS = {
    "intern": 1, "junior": 1, "associate": 1,
    "engineer": 2, "analyst": 2, "designer": 2, "scientist": 2,
    "senior": 3, "sr.": 3, "sr ": 3, "lead": 3, "staff": 4,
    "principal": 4, "architect": 4, "manager": 3, "director": 5,
    "vp": 5, "vice president": 5, "head": 5, "chief": 6,
    "cto": 6, "ceo": 6, "founder": 6,
}


def _seniority_of(title: str) -> int:
    low = (title or "").lower()
    rank = 0
    for kw, lvl in _SENIORITY_KEYWORDS.items():
        if kw in low and lvl > rank:
            rank = lvl
    return rank


def _match_tier(target_norm: str, conn_norm: str) -> int:
    """0 = no match, 1 = partial/fuzzy, 2 = exact normalized match."""
    if not target_norm or not conn_norm:
        return 0
    if target_norm == conn_norm:
        return 2
    if target_norm in conn_norm or conn_norm in target_norm:
        return 1
    return 0


def _rank_key(target: str, conn: dict) -> tuple:
    """Sort key: best referral first.

    Exact company match outranks fuzzy; within a tier, senior titles first,
    then recently connected, then name for stability.
    """
    t = _norm_company(target)
    tier = _match_tier(t, _norm_company(conn.get("company", "")))
    sen = _seniority_of(conn.get("position", ""))
    d = _connected_date(conn.get("connected_on", ""))
    recency = d.toordinal() if d else 0
    return (-tier, -sen, -recency, conn.get("name", "").lower())


def _rank_reason(target: str, conn: dict) -> str:
    parts = []
    if _match_tier(_norm_company(target),
                    _norm_company(conn.get("company", ""))) > 0:
        parts.append(f"works at {conn.get('company', '').strip() or target} now")
    if _seniority_of(conn.get("position", "")) >= 4:
        parts.append("staff/principal-level title")
    elif _seniority_of(conn.get("position", "")) >= 3:
        parts.append("senior-level title")
    d = _connected_date(conn.get("connected_on", ""))
    if d:
        from datetime import date
        days = (date.today() - d).days
        if days <= 365:
            parts.append("connected recently")
        elif days <= 365 * 3:
            parts.append(f"connected {days // 365}y ago")
    if not parts:
        parts.append("1st-degree connection")
    return "; ".join(parts)


def referral_path(company: str,
                  connections: list[dict] | None = None) -> dict:
    """Detect referral paths for a company from your LinkedIn connections.

    Returns {company, candidates: [{name, position, connected_on,
    rank_reason}], best, count}. ``connections`` is the load_connections()
    shape; when None, load_connections() is attempted and a ChannelError
    raised with the export instructions when no source is configured.
    """
    if not (company or "").strip():
        raise ChannelError("Pass a company name to check for referral paths.")
    if connections is None:
        connections = load_connections()
    t = _norm_company(company)
    hits = [c for c in (connections or []) if c.get("name")
            and _match_tier(t, _norm_company(c.get("company", ""))) > 0]
    scored = sorted(((_rank_key(company, c), c) for c in hits),
                    key=lambda s: s[0])
    cands = [{
        "name": c["name"],
        "position": c.get("position", ""),
        "connected_on": c.get("connected_on", ""),
        "rank_reason": _rank_reason(company, c),
    } for _, c in scored]
    return {
        "company": company,
        "candidates": cands,
        "best": cands[0] if cands else None,
        "count": len(cands),
    }


def draft_referral_request(name: str, company: str, role: str) -> str:
    """Draft a short, warm LinkedIn message asking for a referral.

    Placeholders are marked [LIKE THIS] for the user to fill in.
    """
    name = (name or "").strip() or "[Name]"
    company = (company or "").strip() or "[Company]"
    role = (role or "").strip() or "[Role]"
    first = name.split()[0]
    return (
        f"Hi {first},\n\n"
        f"I hope you're doing well! I saw you're at {company} and I'm "
        f"exploring {role} roles there. Would you be open to a quick chat "
        "about your experience on the team? And if it seems like a fit, "
        "I'd really appreciate a referral.\n\n"
        "A quick bit about me: [Your Name], [one line on your background, "
        "e.g. ML engineer, 4 years in ads ranking].\n\n"
        "Totally fine if the timing isn't right, no pressure at all. "
        "Thanks for considering!\n\n"
        "Best,\n"
        "[Your Name]"
    )


# ---------------------------------------------------------------------------
# Posting freshness
# ---------------------------------------------------------------------------

_RELATIVE_RE = re.compile(
    r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago", re.I)
_UNIT_DAYS = {"second": 1 / 86400, "minute": 1 / 1440, "hour": 1 / 24,
              "day": 1, "week": 7, "month": 30, "year": 365}


def posting_age_days(job: dict, now: datetime | None = None) -> int | None:
    """Age of a posting in days from its ``posted_at`` field. None if unknown."""
    now = now or datetime.now()
    raw = (job.get("posted_at") or "").strip()
    if not raw:
        return None
    m = _RELATIVE_RE.search(raw)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        return int(n * _UNIT_DAYS.get(unit, 1))
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%m/%d/%Y", "%d %b %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return max(0, (now - datetime.strptime(raw, fmt)).days)
        except ValueError:
            continue
    # dateutil-style ISO with timezone or fractional seconds
    try:
        dt = datetime.fromisoformat(raw)
        return max(0, (now - dt.replace(tzinfo=None)).days)
    except ValueError:
        return None


def freshness_note(job: dict, now: datetime | None = None) -> dict:
    """Freshness advice for a posting. Returns {age_days, verdict, advice}."""
    age = posting_age_days(job, now)
    if age is None:
        return {"age_days": None, "verdict": "unknown",
                "advice": "Posting date unknown; apply soon anyway, and verify the role is still open."}
    if age <= 2:
        verdict, advice = ("fresh",
                            "Posted within the last 48 hours. Apply today: early applicants are read first.")
    elif age <= 7:
        verdict, advice = ("recent", "Posted within the last week. Apply this week; still prime time.")
    elif age <= 30:
        verdict, advice = ("aging",
                            "Posted up to a month ago. Still worth applying, but tailor harder and consider a referral to stand out.")
    else:
        verdict, advice = ("stale",
                            f"Posted {age} days ago. Verify the role is still open before investing effort; prioritize fresher postings.")
    return {"age_days": age, "verdict": verdict, "advice": advice}


# ---------------------------------------------------------------------------
# Recommendation + full guide
# ---------------------------------------------------------------------------

# Channel preference order when multiple are available (lower = better).
_CHANNEL_RANK = {
    "referral": 0,
    "direct_email": 1,
    "ats_portal": 2,
    "company_site": 2,
    "linkedin_easy_apply": 3,
    "aggregator": 4,
}


def recommend_channels(job: dict,
                       referral: dict | None = None) -> list[dict]:
    """Rank the application channels for a posting.

    Returns [{channel, label, rank, why, next_step}] best first. When
    ``referral`` (referral_path() output) has candidates, referral ranks
    first with the best contact named.
    """
    classified = classify_channels(job)
    recs: list[dict] = []

    ref_cands = (referral or {}).get("candidates") or []
    if ref_cands:
        best = ref_cands[0]
        recs.append({
            "channel": "referral",
            "label": CHANNEL_LABELS["referral"],
            "rank": 0,
            "why": (f"{best['name']} ({best.get('position') or 'role unknown'}) "
                    f"can refer you: {best.get('rank_reason') or '1st-degree connection'}."),
            "next_step": (f"Ask {best['name'].split()[0]} for a referral "
                          f"(`candid guide referral --company \"{job.get('company', '')}\"` shows the draft)."),
        })

    emails = extract_apply_emails(job.get("description") or "")
    if emails:
        recs.append({
            "channel": "direct_email",
            "label": CHANNEL_LABELS["direct_email"],
            "rank": 1,
            "why": f"Employer accepts applications at {emails[0]['email']}.",
            "next_step": "Send the tailored resume + a short cover email directly; skip the portal queue.",
        })

    ats = identify_ats(job.get("url") or "", job.get("description") or "")
    if ats:
        notes = ats_notes(ats)
        acct = "account required" if notes["account_required"] else "no account needed"
        recs.append({
            "channel": "ats_portal",
            "label": CHANNEL_LABELS["ats_portal"],
            "rank": 2,
            "why": f"{ats} portal ({acct}, ~{notes['time_minutes']} min).",
            "next_step": f"`candid guide ats --name {ats}` for portal notes, then apply at the posting URL.",
        })
    elif (job.get("url") or "") and not aggregator_info(job.get("url") or ""):
        recs.append({
            "channel": "company_site",
            "label": CHANNEL_LABELS["company_site"],
            "rank": 2,
            "why": "Posting is on the employer's own site.",
            "next_step": "Apply directly on the company careers page.",
        })

    host = _host(job.get("url") or "")
    if "linkedin.com" in host:
        recs.append({
            "channel": "linkedin_easy_apply",
            "label": CHANNEL_LABELS["linkedin_easy_apply"],
            "rank": 3,
            "why": "LinkedIn listing: Easy Apply is fast but your profile, not your tailored resume, is the application.",
            "next_step": "Use Easy Apply only for stretch roles; for top targets, find the company posting instead.",
        })

    agg = aggregator_info(job.get("url") or "")
    if agg:
        recs.append({
            "channel": "aggregator",
            "label": CHANNEL_LABELS["aggregator"],
            "rank": 4,
            "why": agg["warning"],
            "next_step": f"Search \"{job.get('company', '')} careers {job.get('title', '')}\" and apply on the company site.",
        })

    recs.sort(key=lambda r: r["rank"])
    return recs


def draft_direct_apply_email(name: str, company: str, role: str,
                             to_email: str = "") -> str:
    """Draft a short cold-application email for the direct-email channel.

    Placeholders are marked [LIKE THIS].
    """
    name = (name or "").strip() or "[Name]"
    company = (company or "").strip() or "[Company]"
    role = (role or "").strip() or "[Role]"
    to_email = (to_email or "").strip()
    header = f"To: {to_email}\n" if to_email else ""
    return (
        f"{header}Subject: Application for {role} - {name}\n\n"
        f"Hi {company} hiring team,\n\n"
        f"I'm applying for the {role} role. I'm {name}, "
        "[one line: e.g. ML engineer with 4 years in ads ranking].\n\n"
        "A couple of highlights relevant to this role:\n"
        "- [Achievement 1, quantified]\n"
        "- [Achievement 2, quantified]\n\n"
        "My resume is attached. I'd welcome a conversation about the role.\n\n"
        "Best,\n"
        f"{name}\n"
        "[Phone] | [LinkedIn URL]"
    )


def guide(job: dict, connections: list[dict] | None = None,
          connections_error: str | None = None,
          now: datetime | None = None) -> dict:
    """Full per-posting direct-apply guidance.

    Returns a dict with: job summary, ats, ats_notes, channels (ranked),
    referral (referral_path output or {"error": ...}), emails, freshness,
    aggregator warning, and a one-line ``headline`` recommendation.
    ``connections_error`` lets callers pre-resolve connection loading and
    pass the failure message through instead of raising.
    """
    job = job or {}
    title = job.get("title") or job.get("role") or "(unknown role)"
    company = job.get("company") or "(unknown company)"
    url = job.get("url") or job.get("jd_link") or ""

    ats = identify_ats(url, job.get("description") or job.get("jd_text") or "")
    emails = extract_apply_emails(job.get("description") or job.get("jd_text") or "")
    agg = aggregator_info(url)
    fresh = freshness_note(job, now)

    referral: dict
    if connections_error:
        referral = {"company": company, "candidates": [], "best": None,
                    "count": 0, "error": connections_error}
    else:
        try:
            referral = referral_path(company, connections)
        except ChannelError as e:
            referral = {"company": company, "candidates": [], "best": None,
                        "count": 0, "error": str(e)}

    recs = recommend_channels({**job, "url": url}, referral)
    headline = (f"Best channel: {recs[0]['label']} - {recs[0]['why']}"
                if recs else "No application channel identified.")

    return {
        "title": title,
        "company": company,
        "url": url,
        "ats": ats,
        "ats_notes": ats_notes(ats),
        "emails": emails,
        "aggregator": agg,
        "freshness": fresh,
        "referral": referral,
        "channels": recs,
        "headline": headline,
    }


def render_guide(g: dict) -> str:
    """Render a guide() dict as human-readable text."""
    lines = [
        f"Apply guide: {g['title']} @ {g['company']}",
        f"URL: {g['url'] or '(none)'}",
        "",
        f"HEADLINE: {g['headline']}",
        "",
        "Ranked channels:",
    ]
    for i, r in enumerate(g["channels"], 1):
        lines.append(f"  {i}. {r['label']}: {r['why']}")
        lines.append(f"     Next: {r['next_step']}")
    if not g["channels"]:
        lines.append("  (none identified)")
    lines.append("")
    if g["ats"]:
        n = g["ats_notes"]
        acct = ("account required" if n["account_required"]
                else "no account needed" if n["account_required"] is False
                else "account requirement unknown")
        lines.append(f"ATS portal: {g['ats']} ({acct}, ~{n['time_minutes']} min, parsing: {n['parsing_quality']})")
        for q in n["quirks"]:
            lines.append(f"  - {q}")
        for t in n["tips"]:
            lines.append(f"  Tip: {t}")
        lines.append("")
    if g["emails"]:
        lines.append("Direct apply emails found in posting:")
        for e in g["emails"]:
            lines.append(f"  - {e['email']}")
            if e["context"]:
                lines.append(f"    ...{e['context']}")
        lines.append("")
    ref = g["referral"]
    if ref.get("error"):
        lines.append(f"Referral check: {ref['error']}")
    elif ref["count"]:
        lines.append(f"Referral path: {ref['count']} connection(s) at {ref['company']}; best: "
                     f"{ref['best']['name']} ({ref['best'].get('position') or 'role unknown'}) - "
                     f"{ref['best'].get('rank_reason') or ''}")
    else:
        lines.append("Referral path: no 1st-degree connections at this company in your export.")
    lines.append("")
    f = g["freshness"]
    age = f"{f['age_days']}d" if f["age_days"] is not None else "unknown"
    lines.append(f"Freshness: {age} ({f['verdict']}). {f['advice']}")
    if g["aggregator"]:
        lines.append("")
        lines.append(f"WARNING: {g['aggregator']['warning']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Channel stats from the tracker
# ---------------------------------------------------------------------------

_RESPONSE = {"selected_for_interview", "rejected", "offer"}
_INTERVIEW = {"selected_for_interview", "offer"}


def channel_stats(path=None) -> dict[str, dict]:
    """Application-channel success stats from tracker records.

    Returns {channel: {applied, interviews, offers, rejections,
    response_rate, interview_rate}} where ``applied`` counts records with a
    channel set and status past "saved". Records without a channel are
    grouped under "unlogged".
    """
    from candid import tracker as T

    out: dict[str, dict] = {}
    for app in T.list_apps(path=path):
        ch = (app.get("channel") or "").strip() or "unlogged"
        s = out.setdefault(ch, {"applied": 0, "interviews": 0, "offers": 0,
                                "rejections": 0, "responses": 0})
        if app.get("status") in _RESPONSE or app.get("status") == "applied":
            s["applied"] += 1
        if app.get("status") in _INTERVIEW:
            s["interviews"] += 1
        if app.get("status") == "offer":
            s["offers"] += 1
        if app.get("status") == "rejected":
            s["rejections"] += 1
        if app.get("status") in _RESPONSE:
            s["responses"] += 1
    for s in out.values():
        a = s["applied"]
        s["response_rate"] = round(s["responses"] / a, 3) if a else 0.0
        s["interview_rate"] = round(s["interviews"] / a, 3) if a else 0.0
    return out


def render_channel_stats(stats: dict[str, dict]) -> str:
    """Render channel_stats() as a text table."""
    if not stats:
        return "No tracked applications yet. Log channels with `candid guide log --app-id N --channel X`."
    rows = sorted(stats.items(), key=lambda kv: (-kv[1]["applied"], kv[0]))
    lines = [f"{'channel':<22}{'applied':>8}{'resp%':>7}{'iv%':>6}{'offers':>7}",
             "-" * 50]
    for ch, s in rows:
        lines.append(f"{ch:<22}{s['applied']:>8}"
                     f"{s['response_rate'] * 100:>6.0f}%"
                     f"{s['interview_rate'] * 100:>5.0f}%"
                     f"{s['offers']:>7}")
    return "\n".join(lines)
