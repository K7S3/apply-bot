"""Freelance / remote job sources for candid.

Three free, no-key, no-login, no-scraping adapters returning the same
normalized job dicts as ``candid.jobs``:

    {source, source_id, title, company, location, url, description,
     salary_text, remote (bool), posted_at}

Adapters:
    remotive       — Remotive JSON API (https://remotive.com/api/remote-jobs).
                     Remote-only board; listings are a mix of full-time,
                     contract and freelance roles. Shape verified live
                     2026-09-22 (fields: id, title, company_name, url,
                     description (HTML), salary, publication_date (ISO),
                     candidate_required_location, category, job_type, tags).
    weworkremotely — WeWorkRemotely public RSS
                     (https://weworkremotely.com/remote-jobs.rss), parsed
                     with xml.etree.ElementTree. Item titles are
                     "Company: Title"; region gives the location hint.
    workingnomads  — SUBSTITUTION (2026-09-22): the Working Nomads RSS
                     (https://www.workingnomads.com/jobs.rss) and its API
                     variants (/api/v1/jobs, /jobs.json) all return 404 and
                     the site no longer advertises a feed, so this slot is
                     served by the Jobspresso public RSS
                     (https://jobspresso.co/feed/) — also free, no-key,
                     remote-only. The feed currently validates but serves an
                     empty channel, so the adapter legitimately returns []
                     until Jobspresso publishes items again.

Each adapter degrades gracefully: any fetch or parse failure raises
``FreelanceError``. Registration into ``candid.jobs.ADAPTERS`` happens at
final merge by the coordinator; this module is intentionally standalone.
Fetched listings are treated as *data* — never executed as code.
"""

from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

USER_AGENT = "candid/0.1 (personal job curation; contact: user-local)"
FETCH_TIMEOUT = 20
MAX_PER_SOURCE = 100
DESC_LIMIT = 4000


class FreelanceError(Exception):
    """Raised when a freelance feed is unreachable or unparsable."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _get_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _get_xml(url: str) -> ET.Element:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return ET.fromstring(resp.read())


def _strip_html(s: str) -> str:
    text = re.sub(r"<[^>]+>", " ", s or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _child_text(item: ET.Element, *names: str) -> str:
    """First non-empty child text whose local tag name matches.

    Names are tried in priority order: all children are scanned for the
    first name before falling back to the next (e.g. prefer
    ``content:encoded`` over ``description``)."""
    for name in names:
        for child in item:
            if child.tag.split("}")[-1] == name and child.text \
                    and child.text.strip():
                return child.text.strip()
    return ""


def _norm_posted_at(value: object) -> str:
    """Normalize a date string to ISO 8601; pass through if unparsable."""
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # RFC 2822 (RSS pubDate)
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        pass
    # ISO 8601 (Remotive publication_date)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        pass
    return s


def _norm_job(source: str, source_id: str, title: str, company: str,
              location: str, url: str, description: str,
              salary_text: str, remote: bool, posted_at: object) -> dict:
    return {
        "source": source,
        "source_id": source_id,
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "url": url or "",
        "description": _strip_html(description)[:DESC_LIMIT],
        "salary_text": (salary_text or "").strip(),
        "remote": bool(remote),
        "posted_at": _norm_posted_at(posted_at),
    }


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------

_REMOTIVE_URL = "https://remotive.com/api/remote-jobs?limit=100"


def _adapt_remotive() -> list[dict]:
    """Remotive JSON API — free, no key, remote-only board."""
    try:
        payload = _get_json(_REMOTIVE_URL)
    except Exception as exc:
        raise FreelanceError(f"remotive unreachable: {exc}") from exc
    items = payload.get("jobs", []) if isinstance(payload, dict) else []
    out = []
    for j in items[:MAX_PER_SOURCE]:
        if not isinstance(j, dict):
            continue
        loc = j.get("candidate_required_location") or "Remote"
        out.append(_norm_job(
            source="remotive",
            source_id=f"remotive:{j.get('id')}",
            title=j.get("title") or "",
            company=j.get("company_name") or "",
            location=loc,
            url=j.get("url") or "",
            description=j.get("description") or "",
            salary_text=j.get("salary") or "",
            remote=True,
            posted_at=j.get("publication_date"),
        ))
    return out


_WWR_URL = "https://weworkremotely.com/remote-jobs.rss"


def _wwr_company_title(raw: str) -> tuple[str, str]:
    """WWR titles are 'Company: Title'. Split on the first ': '."""
    raw = (raw or "").strip()
    company, sep, title = raw.partition(": ")
    if sep and title.strip():
        return company.strip(), title.strip()
    return "", raw


def _adapt_weworkremotely() -> list[dict]:
    """WeWorkRemotely public RSS — free, no key, remote-only board."""
    try:
        root = _get_xml(_WWR_URL)
    except Exception as exc:
        raise FreelanceError(f"weworkremotely unreachable: {exc}") from exc
    out = []
    for item in root.findall(".//item")[:MAX_PER_SOURCE]:
        guid = _child_text(item, "guid", "link")
        slug = guid.rstrip("/").split("/")[-1] if guid else ""
        company, title = _wwr_company_title(_child_text(item, "title"))
        region = _child_text(item, "region")
        out.append(_norm_job(
            source="weworkremotely",
            source_id=f"weworkremotely:{slug or guid or title}",
            title=title,
            company=company,
            location=region or "Remote",
            url=_child_text(item, "link") or guid,
            description=_child_text(item, "description"),
            salary_text="",
            remote=True,
            posted_at=_child_text(item, "pubDate"),
        ))
    return out


# SUBSTITUTION: Working Nomads' own feed is dead (404 on /jobs.rss and all
# API variants as of 2026-09-22). Serving this slot with the Jobspresso
# public RSS instead — free, no-key, remote-only. Currently validates but
# publishes an empty channel, so expect [] until items return.
_WORKINGNOMADS_SUBSTITUTE_URL = "https://jobspresso.co/feed/"


def _adapt_workingnomads() -> list[dict]:
    """Working Nomads slot — substituted with the Jobspresso public RSS
    (Working Nomads' feed is dead; see module docstring)."""
    try:
        root = _get_xml(_WORKINGNOMADS_SUBSTITUTE_URL)
    except Exception as exc:
        raise FreelanceError(f"workingnomads unreachable: {exc}") from exc
    out = []
    for item in root.findall(".//item")[:MAX_PER_SOURCE]:
        link = _child_text(item, "link")
        guid = _child_text(item, "guid")
        sid = guid.rstrip("/").split("/")[-1] if guid else link
        out.append(_norm_job(
            source="workingnomads",
            source_id=f"workingnomads:{sid or _child_text(item, 'title')}",
            title=_child_text(item, "title"),
            company="",  # Jobspresso item titles carry no structured company field
            location="Remote",
            url=link or guid,
            description=_child_text(item, "encoded", "description"),
            salary_text="",
            remote=True,
            posted_at=_child_text(item, "pubDate"),
        ))
    return out


# ---------------------------------------------------------------------------
# contract — source name -> adapter callable (registration into
# candid.jobs.ADAPTERS happens at final merge by the coordinator)
# ---------------------------------------------------------------------------

CONTRACT_SOURCES: dict[str, callable] = {
    "remotive": _adapt_remotive,
    "weworkremotely": _adapt_weworkremotely,
    "workingnomads": _adapt_workingnomads,
}

FREELANCE_SOURCE_NAMES = ["remotive", "weworkremotely", "workingnomads"]
